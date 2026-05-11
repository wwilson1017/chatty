"""Chatty CLI — chat with your agents from the terminal."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import argparse

from cli.bootstrap import bootstrap
from cli.session import create_session, create_agent_interactive
from cli.app import run_repl
from cli.output import console


def _select_agent() -> str:
    from agents.db import list_agents

    agents = list_agents()
    if not agents:
        console.print("[dim]No agents found.[/]")
        answer = input("Create one? [Y/n] ").strip().lower()
        if answer in ("", "y", "yes"):
            agent = create_agent_interactive()
            return agent["slug"]
        raise SystemExit(0)

    if len(agents) == 1:
        slug = agents[0]["slug"]
        console.print(f"[dim]Auto-selected: {agents[0]['agent_name']} ({slug})[/]")
        return slug

    console.print("[bold]Select an agent:[/]")
    for i, a in enumerate(agents, 1):
        console.print(f"  {i}. {a['agent_name']} ({a['slug']})")
    while True:
        try:
            choice = input(f"Choice [1-{len(agents)}]: ").strip()
            idx = int(choice) - 1
            if 0 <= idx < len(agents):
                return agents[idx]["slug"]
        except (ValueError, EOFError, KeyboardInterrupt):
            raise SystemExit(0)


def _list_agents():
    from agents.db import list_agents
    from rich.table import Table

    agents = list_agents()
    if not agents:
        console.print("[dim]No agents.[/]")
        return
    table = Table(title="Agents")
    table.add_column("Name", style="cyan")
    table.add_column("Slug")
    table.add_column("Created")
    for a in agents:
        table.add_row(a.get("agent_name", ""), a.get("slug", ""), a.get("created_at", "")[:10])
    console.print(table)


def main():
    parser = argparse.ArgumentParser(
        prog="chatty",
        description="Chatty CLI — chat with your agents from the terminal",
    )
    parser.add_argument("--agent", "-a", help="Agent slug to chat with")
    parser.add_argument("--ephemeral", action="store_true",
                        help="Don't save conversation to chat.db")
    parser.add_argument("--power", action="store_true",
                        help="Power mode: skip write tool confirmations")
    parser.add_argument("--readonly", action="store_true",
                        help="Read-only tool mode (no write tools)")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Show full tool results and arguments")
    parser.add_argument("--list", "-l", action="store_true",
                        help="List all agents and exit")
    parser.add_argument("--new", action="store_true",
                        help="Create a new agent interactively")
    args = parser.parse_args()

    bootstrap()

    if args.list:
        _list_agents()
        return

    tool_mode = "read-only" if args.readonly else ("power" if args.power else "normal")

    if args.new:
        agent = create_agent_interactive()
        slug = agent["slug"]
    elif args.agent:
        slug = args.agent
    else:
        slug = _select_agent()

    session = create_session(
        slug,
        tool_mode=tool_mode,
        persist=not args.ephemeral,
        verbose=args.verbose,
    )
    asyncio.run(run_repl(session))


if __name__ == "__main__":
    main()
