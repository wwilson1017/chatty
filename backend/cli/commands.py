"""Chatty CLI — Slash command dispatcher and implementations."""

import json
import re
from datetime import date, datetime
from pathlib import Path

from rich.table import Table
from rich.markdown import Markdown
from rich.syntax import Syntax

from cli.output import console

COMMANDS = {
    "/search": "Search agent memory (FTS5)",
    "/facts": "Query temporal facts",
    "/memory": "Show MEMORY.md",
    "/context": "List context files",
    "/read": "Read a context file",
    "/daily": "Read a daily note (default: today)",
    "/history": "List conversations",
    "/dreams": "Show dreaming context scores",
    "/shared": "List shared context files",
    "/reset": "Clear conversation, start fresh",
    "/agent": "Show current agent info",
    "/agents": "List all agents",
    "/switch": "Switch to a different agent",
    "/new": "Create a new agent",
    "/usage": "Show token usage this session",
    "/mode": "Change tool mode (power/normal/readonly)",
    "/verbose": "Toggle verbose output",
    "/help": "Show this help",
    "/quit": "Exit",
    "/exit": "Exit",
}


def _safe_filename(filename: str) -> bool:
    if not filename or not filename.endswith(".md"):
        return False
    if "/" in filename or "\\" in filename or ".." in filename:
        return False
    return True


def _valid_date(s: str) -> bool:
    return bool(re.match(r"^\d{4}-\d{2}-\d{2}$", s))


async def handle_command(input_str: str, session, renderer) -> "str | Session | None":
    from cli.session import Session, reset_conversation, switch_agent, create_session, create_agent_interactive

    parts = input_str.split(maxsplit=1)
    cmd = parts[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""

    if cmd in ("/quit", "/exit"):
        return "quit"

    elif cmd == "/help":
        _cmd_help()

    elif cmd == "/search":
        await _cmd_search(arg, session)

    elif cmd == "/facts":
        _cmd_facts(arg, session)

    elif cmd == "/memory":
        _cmd_memory(session)

    elif cmd == "/context":
        _cmd_context(session)

    elif cmd == "/read":
        _cmd_read(arg, session)

    elif cmd == "/daily":
        _cmd_daily(arg, session)

    elif cmd == "/history":
        _cmd_history(arg, session)

    elif cmd == "/dreams":
        _cmd_dreams(session)

    elif cmd == "/shared":
        _cmd_shared()

    elif cmd == "/reset":
        reset_conversation(session)
        console.print("[dim]Conversation reset.[/]")

    elif cmd == "/agent":
        _cmd_agent(session)

    elif cmd == "/agents":
        _cmd_agents()

    elif cmd == "/switch":
        if not arg:
            console.print("[red]Usage: /switch <slug>[/]")
            return None
        from agents.db import get_agent_by_slug
        if not get_agent_by_slug(arg):
            console.print(f"[red]Agent not found: {arg}[/]")
            return None
        new_session = switch_agent(session, arg)
        console.print(f"[dim]Switched to {new_session.config.agent_name}[/]")
        return new_session

    elif cmd == "/new":
        agent = create_agent_interactive()
        new_session = create_session(
            agent["slug"],
            tool_mode=session.tool_mode,
            persist=session.persist,
            verbose=session.verbose,
        )
        console.print(f"[green]Created agent: {agent['agent_name']} ({agent['slug']})[/]")
        return new_session

    elif cmd == "/usage":
        _cmd_usage(session)

    elif cmd == "/mode":
        _cmd_mode(arg, session)

    elif cmd == "/verbose":
        session.verbose = not session.verbose
        renderer.verbose = session.verbose
        console.print(f"[dim]Verbose: {'on' if session.verbose else 'off'}[/]")

    else:
        console.print(f"[red]Unknown command: {cmd}. Type /help for available commands.[/]")

    return None


def _cmd_help():
    table = Table(title="Commands", show_header=False, padding=(0, 2))
    table.add_column(style="bold cyan")
    table.add_column()
    for cmd, desc in COMMANDS.items():
        if cmd == "/exit":
            continue
        table.add_row(cmd, desc)
    console.print(table)


async def _cmd_search(query: str, session):
    if not query:
        console.print("[red]Usage: /search <query>[/]")
        return
    from core.agents.memory.search_tools import search_memory_async
    result = await search_memory_async(
        str(session.ctx_manager.data_dir),
        session.config.gcs_prefix,
        query,
    )
    results = result.get("results", [])
    if not results:
        console.print("[dim]No results.[/]")
        return
    table = Table(title=f"Search: {query} ({result.get('total', 0)} results)")
    table.add_column("Source", style="cyan")
    table.add_column("Title")
    table.add_column("Snippet")
    for r in results:
        table.add_row(
            r.get("source_type", ""),
            r.get("title", ""),
            r.get("snippet", "")[:100],
        )
    console.print(table)


def _cmd_facts(arg: str, session):
    from core.agents.memory.search_tools import query_facts
    kwargs = {"data_dir": str(session.ctx_manager.data_dir),
              "gcs_prefix": session.config.gcs_prefix}
    if arg:
        kwargs["subject"] = arg
    result = query_facts(**kwargs)
    facts = result.get("facts", [])
    if not facts:
        console.print("[dim]No facts found.[/]")
        return
    table = Table(title=f"Facts ({result.get('total', 0)})")
    table.add_column("ID", style="dim")
    table.add_column("Subject", style="cyan")
    table.add_column("Predicate")
    table.add_column("Object")
    table.add_column("Confidence", justify="right")
    for f in facts:
        table.add_row(
            str(f.get("id", ""))[:8],
            f.get("subject", ""),
            f.get("predicate", ""),
            f.get("object", ""),
            f"{f.get('confidence', 1.0):.1f}",
        )
    console.print(table)


def _cmd_memory(session):
    content = session.ctx_manager.read_context("MEMORY.md")
    if not content:
        console.print("[dim]No MEMORY.md found.[/]")
        return
    console.print(Markdown(content))


def _cmd_context(session):
    files = session.ctx_manager.list_context_files()
    if not files:
        console.print("[dim]No context files.[/]")
        return
    table = Table(title="Context Files")
    table.add_column("Name", style="cyan")
    table.add_column("Size", justify="right")
    table.add_column("Modified")
    for f in files:
        size_kb = f.get("size_bytes", 0) / 1024
        mod = f.get("modified", "")
        if isinstance(mod, (int, float)):
            mod = datetime.fromtimestamp(mod).strftime("%Y-%m-%d %H:%M")
        table.add_row(f.get("name", ""), f"{size_kb:.1f}k", str(mod))
    console.print(table)


def _cmd_read(filename: str, session):
    if not filename:
        console.print("[red]Usage: /read <filename>[/]")
        return
    if not _safe_filename(filename):
        console.print("[red]Invalid filename. Must be a .md file with no path separators.[/]")
        return
    content = session.ctx_manager.read_context(filename)
    if not content:
        console.print(f"[dim]File not found: {filename}[/]")
        return
    console.print(Markdown(content))


def _cmd_daily(arg: str, session):
    target_date = arg or date.today().isoformat()
    if not _valid_date(target_date):
        console.print("[red]Invalid date format. Use YYYY-MM-DD.[/]")
        return
    content = session.ctx_manager.read_daily_note(target_date)
    if not content:
        console.print(f"[dim]No daily note for {target_date}.[/]")
        return
    console.print(Markdown(content))


def _cmd_history(arg: str, session):
    limit = 20
    if arg:
        try:
            limit = max(1, min(100, int(arg)))
        except ValueError:
            pass
    convs = session.chat_service.list_conversations(limit=limit)
    if not convs:
        console.print("[dim]No conversations.[/]")
        return
    table = Table(title=f"Conversations (last {limit})")
    table.add_column("Title")
    table.add_column("Messages", justify="right")
    table.add_column("Updated")
    for c in convs:
        table.add_row(
            c.get("title", "(untitled)")[:50],
            str(c.get("message_count", "")),
            c.get("updated_at", "")[:16],
        )
    console.print(table)


def _cmd_dreams(session):
    try:
        from core.agents.dreaming.scorer import score_context_files
        scores = score_context_files(
            session.config.agent_name,
            Path(session.config.context_dir),
        )
    except Exception as e:
        console.print(f"[red]Failed to score context: {e}[/]")
        return
    if not scores:
        console.print("[dim]No scored files.[/]")
        return
    table = Table(title="Dreaming Context Scores")
    table.add_column("File", style="cyan")
    table.add_column("Score", justify="right")
    table.add_column("Class")
    for s in scores:
        style = "green" if s.get("classification") == "active" else (
            "yellow" if s.get("classification") == "stale" else "dim"
        )
        table.add_row(
            s.get("filename", ""),
            f"{s.get('score', 0):.2f}",
            f"[{style}]{s.get('classification', '')}[/]",
        )
    console.print(table)


def _cmd_shared():
    from core.agents.shared_context.service import list_files
    files = list_files()
    if not files:
        console.print("[dim]No shared context files.[/]")
        return
    table = Table(title="Shared Context")
    table.add_column("Name", style="cyan")
    table.add_column("Headline")
    table.add_column("Size", justify="right")
    for f in files:
        size_kb = f.get("size_bytes", 0) / 1024
        table.add_row(f.get("name", ""), f.get("headline", ""), f"{size_kb:.1f}k")
    console.print(table)


def _cmd_agent(session):
    provider_name = type(session.provider).__name__.replace("Provider", "")
    model = getattr(session.provider, "model", "default")
    console.print(f"[bold]{session.config.agent_name}[/] ({session.config.slug})")
    console.print(f"  Provider: {provider_name}")
    console.print(f"  Model: {model}")
    console.print(f"  Context: {session.config.context_dir}")
    console.print(f"  Mode: {session.tool_mode}")


def _cmd_agents():
    from agents.db import list_agents
    agents = list_agents()
    if not agents:
        console.print("[dim]No agents. Use /new to create one.[/]")
        return
    table = Table(title="Agents")
    table.add_column("Name", style="cyan")
    table.add_column("Slug")
    table.add_column("Created")
    for a in agents:
        table.add_row(
            a.get("agent_name", ""),
            a.get("slug", ""),
            a.get("created_at", "")[:10],
        )
    console.print(table)


def _cmd_usage(session):
    inp = session.usage["input_tokens"]
    out = session.usage["output_tokens"]
    console.print(f"[bold]Session usage:[/] {inp:,} input / {out:,} output tokens")


def _cmd_mode(arg: str, session):
    mode_map = {
        "power": "power",
        "normal": "normal",
        "readonly": "read-only",
        "read-only": "read-only",
    }
    if not arg or arg.lower() not in mode_map:
        console.print(f"[dim]Current mode: {session.tool_mode}[/]")
        console.print("[dim]Usage: /mode <power|normal|readonly>[/]")
        return
    session.tool_mode = mode_map[arg.lower()]
    console.print(f"[dim]Tool mode: {session.tool_mode}[/]")
