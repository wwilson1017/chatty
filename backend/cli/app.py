"""Chatty CLI — Main REPL loop."""

import json

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.completion import Completer, Completion
from pathlib import Path

from cli.session import Session
from cli.output import parse_sse, StreamRenderer, print_welcome, console
from cli.commands import COMMANDS, handle_command


class SlashCommandCompleter(Completer):
    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        if not text.startswith("/"):
            return
        for cmd in COMMANDS:
            if cmd.startswith(text):
                yield Completion(cmd, start_position=-len(text),
                                 display_meta=COMMANDS[cmd])


async def send_message(session: Session, user_input: str, renderer: StreamRenderer):
    from core.agents import ai_service

    session.messages.append({"role": "user", "content": user_input})

    chat_service = session.chat_service if session.persist else None

    try:
        async for sse_line in ai_service.chat(
            config=session.config,
            provider=session.provider,
            registry=session.registry,
            ctx_manager=session.ctx_manager,
            messages=session.messages,
            conversation_id=session.conversation_id,
            chat_service=chat_service,
            anthropic_api_key=session.anthropic_api_key,
            integration_tool_defs=session.integration_tool_defs,
            tool_mode=session.tool_mode,
            integration_tool_modes=session.integration_tool_modes,
        ):
            event = parse_sse(sse_line)
            if event:
                renderer.handle(event, session)
    except KeyboardInterrupt:
        console.print("\n[dim]Response cancelled.[/]")
        renderer._flush_text()

    if renderer.accumulated_text and not renderer.pending_confirmation:
        session.messages.append({"role": "assistant", "content": renderer.accumulated_text})

    if renderer.pending_confirmation:
        await _handle_confirmation(session, renderer)

    renderer.reset()


async def _handle_confirmation(session: Session, renderer: StreamRenderer):
    from cli.session import execute_approved_tool
    from core.agents import ai_service

    conf = renderer.pending_confirmation
    tool_name = conf["tool"]
    tool_args = conf["args"]
    tool_use_id = conf["tool_use_id"]

    console.print()
    console.print(f"[bold yellow]Tool requires approval:[/] {tool_name}")
    if tool_args:
        from rich.markup import escape
        args_preview = json.dumps(tool_args, indent=2, ensure_ascii=False)
        if len(args_preview) > 500:
            args_preview = args_preview[:500] + "\n..."
        console.print(f"[dim]{escape(args_preview)}[/]")

    try:
        answer = input("Allow? [y/N] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        answer = "n"

    if answer != "y":
        console.print("[dim]Denied.[/]")
        return

    approved = await execute_approved_tool(session, tool_name, tool_args, tool_use_id)
    if "error" in approved:
        console.print(f"[red]Tool execution failed: {approved['error']}[/]")
        return

    session.messages.append({"role": "user", "content": f"[Approved] {tool_name}"})
    console.print(f"[green]✓ {tool_name} executed[/]")

    chat_service = session.chat_service if session.persist else None
    follow_up_renderer = StreamRenderer(verbose=session.verbose)

    try:
        async for sse_line in ai_service.chat(
            config=session.config,
            provider=session.provider,
            registry=session.registry,
            ctx_manager=session.ctx_manager,
            messages=session.messages,
            conversation_id=session.conversation_id,
            chat_service=chat_service,
            anthropic_api_key=session.anthropic_api_key,
            integration_tool_defs=session.integration_tool_defs,
            tool_mode=session.tool_mode,
            approved_tool=approved,
            integration_tool_modes=session.integration_tool_modes,
        ):
            event = parse_sse(sse_line)
            if event:
                follow_up_renderer.handle(event, session)
    except KeyboardInterrupt:
        console.print("\n[dim]Response cancelled.[/]")
        follow_up_renderer._flush_text()

    if follow_up_renderer.accumulated_text:
        session.messages.append({
            "role": "assistant",
            "content": follow_up_renderer.accumulated_text,
        })


async def run_repl(session: Session):
    history_dir = Path(__file__).resolve().parent.parent / "data"
    history_dir.mkdir(parents=True, exist_ok=True)
    history_path = history_dir / ".cli_history"
    if not history_path.exists():
        history_path.touch(mode=0o600)
    else:
        try:
            history_path.chmod(0o600)
        except OSError:
            pass
    prompt_session = PromptSession(
        history=FileHistory(str(history_path)),
        completer=SlashCommandCompleter(),
    )

    print_welcome(session)

    while True:
        try:
            user_input = await prompt_session.prompt_async(
                f"[{session.config.agent_name}] > ",
            )
        except (EOFError, KeyboardInterrupt):
            break

        user_input = user_input.strip()
        if not user_input:
            continue

        if user_input.startswith("/"):
            result = await handle_command(user_input, session, StreamRenderer(session.verbose))
            if result == "quit":
                break
            if isinstance(result, Session):
                session = result
                print_welcome(session)
            continue

        await send_message(session, user_input, StreamRenderer(session.verbose))

    console.print("\n[dim]Goodbye.[/]")
