"""Slash commands. repl.submit runs each one after the previous reply has finished."""

import shlex
from pathlib import Path

from . import config
from .api import ApiError
from .render import ask, console, note, safe

COMMANDS = {
    "/help": "show this help",
    "/new": "start a new conversation",
    "/agent": "switch agent",
    "/resume": "continue a recent conversation",
    "/model": "show or change this agent's model (/model auto resets it)",
    "/mode": "normal | power | read-only",
    "/attach": "attach files to your next message (/attach alone clears them)",
    "/verbose": "show tool arguments and results",
    "/quit": "exit (or Ctrl+D)",
}
MODES = ("normal", "power", "read-only")
ATTACH_TYPES = {".csv", ".xlsx", ".md", ".txt", ".pdf", ".docx"}  # what /chat/upload accepts
MAX_FILES, MAX_BYTES = 5, 10 * 1024 * 1024
TAIL = 20


async def pick(items: list, label):
    """Numbered list; returns the chosen item, or None on Enter."""
    for i, item in enumerate(items, 1):
        console.print(f"  {i}. {safe(label(item))}")
    a = await ask(f"Choose 1-{len(items)} (Enter to cancel): ")
    return items[int(a) - 1] if a.isdigit() and 1 <= int(a) <= len(items) else None


def agent_label(a: dict) -> str:
    return f"{a.get('agent_name')} ({a.get('slug')})"


async def open_conversation(session, conversation_id: str) -> None:
    """Continue a conversation: later messages go to it. Shows its last few messages."""
    conv = await session.api.conversation(session.agent["id"], conversation_id)
    session.conversation_id = conversation_id
    msgs = [m for m in conv.get("messages", [])
            if m.get("role") in ("user", "assistant") and isinstance(m.get("content"), str) and m["content"].strip()]
    note(f"Continuing \"{conv.get('title') or 'Untitled'}\"" + (f", last {TAIL} messages:" if len(msgs) > TAIL else ":"))
    for m in msgs[-TAIL:]:
        who = "you" if m["role"] == "user" else session.agent["agent_name"]
        console.print(f"[bold]{safe(who)}:[/] {safe(m['content'].strip())}")


def set_agent(session, agent: dict) -> None:
    session.agent, session.conversation_id = agent, None
    session.cfg["last_agent_id"] = agent["id"]
    config.save(session.cfg)


async def cmd_help(session, arg):
    for cmd, desc in COMMANDS.items():
        console.print(f"  [bold]{cmd:<9}[/] {desc}")
    note("Enter sends, Alt+Enter adds a line. Ctrl+C stops showing a reply (it still finishes and saves).")


async def cmd_new(session, arg):
    session.conversation_id = None
    note("New conversation.")


async def cmd_agent(session, arg):
    agents = await session.api.agents()
    agent = next((a for a in agents if a["slug"] == arg), None) if arg else await pick(agents, agent_label)
    if arg and not agent:
        note(f"No agent with slug {arg}.")
    if agent:
        set_agent(session, agent)
        note(f"Now chatting with {agent['agent_name']}, in a new conversation.")


async def cmd_resume(session, arg):
    convs = (await session.api.conversations(session.agent["id"]))[:10]
    if not convs:
        note("No conversations yet.")
        return
    c = await pick(convs, lambda c: f"{c.get('title') or 'Untitled'} · {(c.get('updated_at') or '')[:16]} UTC · "
                                    f"{c.get('message_count', 0)} messages")
    if c:
        await open_conversation(session, c["id"])


async def cmd_model(session, arg):
    agent = session.agent
    if arg == "auto":
        session.agent = await session.api.update_agent(agent["id"], provider_override="", model_override="")
        note("Model: auto.")
        return
    providers = await session.api.providers()
    if agent.get("model_override"):
        note(f"Model: {agent['model_override']} ({agent.get('provider_override') or providers.get('active_provider')})")
    else:
        note(f"Model: auto, tier {agent.get('model_tier') or 'auto'} "
             f"(default {providers.get('active_provider')} · {providers.get('active_model') or '?'})")
    options = []
    for name, profile in providers.get("profiles", {}).items():
        if profile.get("configured"):
            try:
                options += [(name, m) for m in await session.api.models(name)]
            except ApiError as e:
                note(f"{name}: {e}")
    choice = await pick(options, lambda o: f"{o[0]} · {o[1]}") if options else None
    if choice:
        session.agent = await session.api.update_agent(agent["id"], provider_override=choice[0],
                                                       model_override=choice[1])
        note(f"Model: {choice[1]} ({choice[0]}). The web uses it too.")


async def cmd_mode(session, arg):
    if arg in MODES:
        session.cfg["mode"] = arg
        config.save(session.cfg)
    note(f"Mode: {session.mode}" + ("" if arg in MODES else ". Change it with /mode normal | power | read-only"))


async def cmd_verbose(session, arg):
    session.cfg["verbose"] = not session.verbose
    config.save(session.cfg)
    note(f"Verbose: {'on' if session.verbose else 'off'}")


async def cmd_attach(session, arg):
    if not arg:
        session.staged = []
        note("No files attached.")
        return
    try:
        raw_paths = shlex.split(arg)
    except ValueError as e:
        note(str(e))
        return
    for raw in raw_paths:
        p = Path(raw).expanduser()
        problem = ("not a file" if not p.is_file() else
                   "only csv, xlsx, md, txt, pdf or docx" if p.suffix.lower() not in ATTACH_TYPES else
                   "over 10 MB" if p.stat().st_size > MAX_BYTES else
                   f"{MAX_FILES} files at most" if len(session.staged) >= MAX_FILES else None)
        if problem:
            note(f"{raw}: {problem}")
        else:
            session.staged.append(p)
    if session.staged:
        note(f"Attached to your next message: {', '.join(p.name for p in session.staged)}")


HANDLERS = {"/help": cmd_help, "/new": cmd_new, "/agent": cmd_agent, "/resume": cmd_resume, "/model": cmd_model,
            "/mode": cmd_mode, "/verbose": cmd_verbose, "/attach": cmd_attach}


async def run(session, line: str) -> bool:
    """False means quit."""
    cmd, _, arg = line.partition(" ")
    if cmd in ("/quit", "/exit"):
        return False
    if cmd not in HANDLERS:
        note(f"Unknown command {cmd}. /help lists them.")
        return True
    await HANDLERS[cmd](session, arg.strip())
    return True
