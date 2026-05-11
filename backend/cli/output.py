"""Chatty CLI — SSE event parsing and terminal rendering."""

import json
import sys

from rich.console import Console
from rich.markup import escape
from rich.syntax import Syntax

console = Console()


def parse_sse(line: str) -> dict | None:
    line = line.strip()
    if not line or not line.startswith("data: "):
        return None
    try:
        return json.loads(line[6:])
    except (json.JSONDecodeError, ValueError):
        return None


class StreamRenderer:
    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.accumulated_text = ""
        self.pending_confirmation: dict | None = None
        self._in_text = False

    def reset(self):
        self.accumulated_text = ""
        self.pending_confirmation = None
        self._in_text = False

    def handle(self, event: dict, session) -> None:
        etype = event.get("type")
        if etype == "conversation_id":
            session.conversation_id = event.get("id")
        elif etype == "text":
            self._on_text(event["text"])
        elif etype == "tool_start":
            self._on_tool_start(event.get("tool", ""))
        elif etype == "tool_args":
            self._on_tool_args(event.get("tool", ""), event.get("args", {}))
        elif etype == "tool_end":
            self._on_tool_end(event.get("tool", ""), event.get("result", {}),
                              event.get("elapsed_ms", 0))
        elif etype == "confirm":
            self.pending_confirmation = {
                "tool": event.get("tool", ""),
                "args": event.get("args", {}),
                "tool_use_id": event.get("tool_use_id", ""),
            }
        elif etype == "usage":
            session.usage["input_tokens"] += event.get("input_tokens", 0)
            session.usage["output_tokens"] += event.get("output_tokens", 0)
        elif etype == "error":
            self._flush_text()
            console.print(f"[bold red]Error:[/] {escape(event.get('error', ''))}")
        elif etype == "done":
            self._flush_text()
            self._print_usage(session)

    def _on_text(self, text: str):
        self._in_text = True
        self.accumulated_text += text
        sys.stdout.write(text)
        sys.stdout.flush()

    def _flush_text(self):
        if self._in_text:
            sys.stdout.write("\n")
            sys.stdout.flush()
            self._in_text = False

    def _on_tool_start(self, tool: str):
        self._flush_text()
        console.print(f"  [dim]▸ {tool}[/]", end="")

    def _on_tool_args(self, tool: str, args: dict):
        if self.verbose and args:
            console.print()
            args_str = json.dumps(args, indent=2, ensure_ascii=False)
            console.print(Syntax(args_str, "json", theme="monokai", padding=(0, 2)))

    def _on_tool_end(self, tool: str, result: dict, elapsed_ms: int):
        elapsed_str = f"{elapsed_ms}ms" if elapsed_ms < 1000 else f"{elapsed_ms / 1000:.1f}s"
        ok = result.get("ok", result.get("status") != "error")
        icon = "[green]✓[/]" if ok else "[red]✗[/]"
        console.print(f" {icon} [dim]{elapsed_str}[/]")

        if self.verbose and result:
            result_str = json.dumps(result, indent=2, ensure_ascii=False)
            if len(result_str) > 2000:
                result_str = result_str[:2000] + "\n  ... (truncated)"
            console.print(Syntax(result_str, "json", theme="monokai", padding=(0, 2)))

    def _print_usage(self, session):
        inp = session.usage["input_tokens"]
        out = session.usage["output_tokens"]
        if inp or out:
            console.print(
                f"[dim]tokens: {inp:,} in / {out:,} out[/]"
            )


def print_welcome(session):
    console.print()
    console.print(f"[bold]Chatty CLI[/] — {session.config.agent_name}")
    provider_name = type(session.provider).__name__.replace("Provider", "")
    model = getattr(session.provider, "model", "default")
    console.print(f"[dim]Provider: {provider_name} · Model: {model}[/]")
    mode_str = session.tool_mode
    if mode_str == "read-only":
        mode_str += " (no write tools)"
    elif mode_str == "power":
        mode_str += " (no confirmations)"
    console.print(f"[dim]Mode: {mode_str} · Persistence: {'on' if session.persist else 'off'}[/]")
    console.print("[dim]Type /help for commands, Ctrl+D to exit[/]")
    console.print()
