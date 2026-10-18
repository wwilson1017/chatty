"""Terminal output: one turn's event stream (state always, display unless muted) and one-line prompts."""

import json
import sys
import textwrap

from prompt_toolkit import PromptSession
from rich.console import Console
from rich.markup import escape

console = Console(highlight=False)


def note(text: str) -> None:
    console.print(f"[dim]{escape(text)}[/]")


async def ask(text: str) -> str:
    """One line of input. Ctrl+C and Ctrl+D count as no answer."""
    try:
        return (await PromptSession().prompt_async(text, handle_sigint=False)).strip()
    except (KeyboardInterrupt, EOFError):
        return ""


def _json(value, limit: int = 2000) -> str:
    text = json.dumps(value, indent=2, ensure_ascii=False, default=str)
    return textwrap.indent(text[:limit] + ("\n... (truncated)" if len(text) > limit else ""), "    ")


class Renderer:
    """Renders one turn. State (conversation id, confirms, usage, error) is kept even after Ctrl+C mutes it."""

    def __init__(self, session):
        self.session = session
        self.verbose = session.verbose
        self.muted = False
        self.confirms: list[dict] = []
        self.error: str | None = None
        self.done = False
        self.tokens = [0, 0]
        self.args: dict = {}
        self._in_text = False

    def handle(self, e: dict) -> None:
        t = e.get("type")
        if t == "conversation_id":
            self.session.conversation_id = e.get("id")
        elif t == "confirm":
            self.confirms.append(e)
        elif t == "usage":
            self.tokens[0] += e.get("input_tokens") or 0
            self.tokens[1] += e.get("output_tokens") or 0
        elif t == "error":
            self.error = e.get("error") or "unknown error"  # the stream ends here, with no `done`
        elif t == "done":
            self.done = True
        if self.muted:
            return

        # simplification: plain text, no markdown rendering; upgrade: render finished blocks with rich.Markdown (#170)
        if t == "text":
            self._in_text = True
            sys.stdout.write(e.get("text", ""))
            sys.stdout.flush()
            return
        if t == "tool_args":
            self.args[e.get("tool_use_id")] = e.get("args")
            return
        self._end_text()
        if t == "tool_end":
            self._tool_line(e)
        elif t == "confirm":
            console.print(f"  [dim]▸ {escape(e.get('tool', ''))}[/] [yellow]needs your approval[/]")
        elif t == "compacted":
            note("(earlier messages were compacted)")
        elif t == "title_update":
            note(f"title: {e.get('title', '')}")
        elif t == "transcription":
            note(f"transcribing {e.get('filename', '')}: {e.get('message', '')}")
        elif t == "error":
            console.print(f"[red]Error:[/] {escape(self.error)}")
        elif t == "done":
            model = e.get("model") or "?"
            note(f"{model}{' · ' + e['tier'] if e.get('tier') else ''} · "
                 f"{self.tokens[0]:,} in / {self.tokens[1]:,} out")

    def _tool_line(self, e: dict) -> None:
        result = e.get("result") if isinstance(e.get("result"), dict) else {}
        ok = not result.get("error") and result.get("ok", result.get("status") != "error")
        ms = e.get("elapsed_ms") or 0
        took = f"{ms}ms" if ms < 1000 else f"{ms / 1000:.1f}s"
        console.print(f"  [dim]▸ {escape(e.get('tool', ''))}[/] {'[green]✓[/]' if ok else '[red]✗[/]'} [dim]{took}[/]")
        if self.verbose:
            for value in (self.args.get(e.get("tool_use_id")), result):
                if value:
                    note(_json(value))

    def _end_text(self) -> None:
        if self._in_text:
            sys.stdout.write("\n")
            sys.stdout.flush()
            self._in_text = False

    def mute(self) -> None:
        if self.muted:
            return
        self.muted = True
        self._end_text()
        note("Stopped showing the reply. It keeps saving on the server; your next message waits for it.")

    def fail(self, message: str) -> None:
        self.error = message
        if not self.muted:
            self._end_text()
            console.print(f"[red]Error:[/] {escape(message)}")

    def finish(self) -> None:
        """The stream ended."""
        if not self.done and not self.error:
            self.fail("The reply ended before it finished.")
        if not self.muted:
            self._end_text()
