"""The chat loop. One turn in flight at a time; Ctrl+C stops showing it, and every submit waits for it.

The server cancels a turn when its client disconnects, and saves a step only when the step completes. So
Ctrl+C never closes the stream: the turn task keeps draining it in the background until the server is done.
"""

import asyncio
import json
import signal
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import httpx
from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from rich.markup import escape

from . import commands, config
from .api import Api, ApiError
from .render import Renderer, ask, console, note


@dataclass
class Session:
    api: Api
    cfg: dict
    agent: dict
    conversation_id: str | None = None
    staged: list[Path] = field(default_factory=list)
    turn: asyncio.Task | None = None  # a muted turn still draining
    renderer: Renderer | None = None  # its renderer, for what it left behind
    on_sigint: Callable | None = None  # what Ctrl+C does right now (outside the prompt)

    @property
    def mode(self) -> str:
        return self.cfg.get("mode", "normal")

    @property
    def verbose(self) -> bool:
        return self.cfg.get("verbose", False)


def why(e: BaseException) -> str:
    return "stopped" if isinstance(e, asyncio.CancelledError) else str(e) or type(e).__name__


async def interruptible(session: Session, aw):
    """Await `aw`; Ctrl+C cancels it, raising CancelledError here."""
    task = asyncio.ensure_future(aw)
    session.on_sigint = task.cancel
    try:
        return await task
    finally:
        session.on_sigint = None


async def _drain(stream, renderer: Renderer) -> None:
    try:
        async for event in stream:
            renderer.handle(event)
    except httpx.HTTPError as e:  # never replayed: the server may have run part of the turn
        renderer.fail(f"Connection lost ({why(e)}). Not retried.")
    except ApiError as e:
        renderer.fail(str(e))
    renderer.finish()


async def send(session: Session, text: str, approved_tool: dict | None = None,
               files: list[tuple[str, bytes]] = ()) -> None:
    """Run one turn and show it. Ctrl+C mutes it and returns at once, leaving it in session.turn."""
    renderer = Renderer(session)
    stream = session.api.chat(session.agent["id"], text, session.conversation_id, session.mode, approved_tool, files)
    turn = asyncio.create_task(_drain(stream, renderer))
    released = asyncio.get_running_loop().create_future()

    def mute():
        renderer.mute()
        if not released.done():
            released.set_result(None)

    session.on_sigint = mute
    try:
        await asyncio.wait({turn, released}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        session.on_sigint = None
    if renderer.muted:
        session.turn, session.renderer = turn, renderer
        return
    turn.result()
    await approve(session, renderer)


async def settle(session: Session) -> None:
    """Wait for a muted turn before anything else runs. A second Ctrl+C abandons it."""
    turn, renderer = session.turn, session.renderer
    if turn is None:
        return
    session.turn = session.renderer = None
    if not turn.done():
        note("finishing the previous reply…")
        session.on_sigint = turn.cancel
        try:
            await turn
        except asyncio.CancelledError:
            note("Abandoned it; the server stops that reply.")
            return
        finally:
            session.on_sigint = None
    turn.result()
    for c in renderer.confirms:  # nobody saw it, so nothing is approved (like never clicking Approve on the web)
        note(f"The interrupted reply wanted to run {c.get('tool')}. Not run.")
    if renderer.error:
        note(f"The interrupted reply ended with an error: {renderer.error}")


async def approve(session: Session, renderer: Renderer) -> None:
    """y/N for each write tool the reply asked for. Yes runs it, then sends the result as the web's Approve does."""
    for i, c in enumerate(renderer.confirms):
        if session.turn:  # the reply to an earlier approval was interrupted
            for rest in renderer.confirms[i:]:
                note(f"{rest.get('tool')}: not run.")
            return
        tool, args = c.get("tool", ""), c.get("args") or {}
        console.print(f"\n[bold yellow]{escape(tool)}[/] {escape(c.get('description') or '')}")
        console.print(f"[dim]{escape(json.dumps(args, indent=2, ensure_ascii=False)[:2000])}[/]")
        if (await ask("Allow? [y/N] ")).lower() not in ("y", "yes"):
            note("Not run.")
            continue
        try:
            result = await interruptible(session, session.api.execute_tool(session.agent["id"], tool, args))
            text = f"[Approved] {tool}"
        except ApiError as e:
            result, text = {"error": str(e)}, f"[Action failed] {tool}: {e}"
        except (httpx.HTTPError, asyncio.CancelledError) as e:
            # It may have run; replaying could run it twice.
            console.print(f"[red]{escape(tool)} didn't report back ({escape(why(e))}).[/] "
                          "Not retried: check before asking again.")
            return
        await send(session, text, approved_tool={"tool": tool, "args": args, "toolUseId": c.get("tool_use_id"),
                                                 "msgId": c.get("msg_id"), "result": result})


async def submit(session: Session, line: str) -> bool:
    """Handle one input line, after the previous reply. False means quit."""
    await settle(session)
    if line.startswith("/"):
        try:
            return await interruptible(session, commands.run(session, line))
        except asyncio.CancelledError:
            note("Cancelled.")
        except (ApiError, httpx.HTTPError) as e:
            console.print(f"[red]{escape(why(e))}[/]")
        return True
    try:
        files = [(p.name, p.read_bytes()) for p in session.staged]
    except OSError as e:
        console.print(f"[red]{escape(str(e))}[/] (/attach again, or /attach alone to clear)")
        return True
    session.staged = []
    await send(session, line, files=files)
    return True


class SlashCompleter(Completer):
    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        if text.startswith("/") and " " not in text:
            for cmd, desc in commands.COMMANDS.items():
                if cmd.startswith(text):
                    yield Completion(cmd, start_position=-len(text), display_meta=desc)


def prompt_text(session: Session) -> str:
    flags = (" ⚡" if session.mode == "power" else "") + (f" 📎{len(session.staged)}" if session.staged else "")
    return f"[{session.agent['agent_name']}{flags}] > "


async def run(session: Session) -> None:
    loop = asyncio.get_running_loop()
    # At the prompt Ctrl+C is a key press (prompt_toolkit raises KeyboardInterrupt); elsewhere it's this signal.
    loop.add_signal_handler(signal.SIGINT, lambda: session.on_sigint and session.on_sigint())
    keys = KeyBindings()

    @keys.add("escape", "enter")
    def _newline(event):
        event.current_buffer.insert_text("\n")

    prompt = PromptSession(history=FileHistory(str(config.history_path())), completer=SlashCompleter(),
                           key_bindings=keys)
    try:
        while True:
            try:
                line = (await prompt.prompt_async(lambda: prompt_text(session), handle_sigint=False)).strip()
            except KeyboardInterrupt:
                continue
            except EOFError:
                line = "/quit"
            if line and not await submit(session, line):
                break
    finally:
        loop.remove_signal_handler(signal.SIGINT)
