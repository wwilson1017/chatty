"""Routes for agent knowledge import."""

from __future__ import annotations

import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core.auth import get_current_user

from . import db as agent_db
from .import_service.adapters.openclaw import discover_openclaw_agents
from .import_service.adapters.paste import PasteSourceAdapter
from .import_service import sessions

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agents/import", tags=["import"])

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "agents"


class StartImportRequest(BaseModel):
    agent_name: str


@router.post("/start")
async def start_import(body: StartImportRequest, user=Depends(get_current_user)):
    """Create a new agent in Import Mode and return agent + conversation IDs."""
    name = body.agent_name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="agent_name is required")

    agent = agent_db.create_agent(name)

    try:
        agent_db.update_agent(agent["id"], onboarding_complete=1)

        context_dir = DATA_DIR / agent["slug"] / "context"
        context_dir.mkdir(parents=True, exist_ok=True)
        openclaw_agents = discover_openclaw_agents()
        _seed_import_bootstrap(context_dir, name, openclaw_agents)

        from .engine import get_chat_service
        chat_svc = get_chat_service(agent["slug"])
        conv = chat_svc.create_conversation(title="Knowledge Import", mode="import")
        opener = _build_import_opener(name, openclaw_agents)
        chat_svc.save_message(
            conversation_id=conv["id"],
            msg_id=str(uuid.uuid4()),
            role="assistant",
            content=opener,
            seq=0,
        )

        placeholder = PasteSourceAdapter("(awaiting source)")
        session = sessions.create_session(
            adapter=placeholder,
            agent_id=agent["id"],
            conversation_id=conv["id"],
        )
    except Exception:
        agent_db.delete_agent(agent["id"])
        import shutil
        agent_dir = DATA_DIR / agent["slug"]
        if agent_dir.is_dir():
            shutil.rmtree(agent_dir, ignore_errors=True)
        raise

    return {
        "agent_id": agent["id"],
        "agent_slug": agent["slug"],
        "conversation_id": conv["id"],
        "session_token": session.token,
    }


@router.get("/openclaw/discover")
async def discover_openclaw(user=Depends(get_current_user)):
    """Check for a local OpenClaw installation and return discovered agents."""
    agents = discover_openclaw_agents()
    return {
        "found": len(agents) > 0,
        "agents": agents,
    }


_IMPORT_BOOTSTRAP = """\
# Import Mode

You are a new Chatty agent. Your human is importing knowledge from another AI system.

## Your job

Help them bring their knowledge files into Chatty. Start by asking where their files are,
then walk through each file one at a time, narrate what you find, and rewrite everything
into Chatty's native format.

## Step 1: Find the files

Present these options clearly in your first message:

- **Paste it** — They can copy and paste markdown content right into the chat
- **Point me at a folder** — They can give you a path like ~/Downloads/agent-files/
- **Drop a zip** — They can drag a .zip file of markdown files into the chat
{openclaw_line}

## Handling backups with multiple agents

If the scan finds a backup folder with multiple agents (subdirectories like data/jamie/,
data/connor/, databases/connor/, etc.), list the agent names you found and ask which one
to import. Once the user picks one, call scan_directory again with the specific agent's
subdirectory path (e.g. ~/Downloads/backup/data/connor/) to narrow down to just that
agent's files.

Look in BOTH data/{{name}}/ and databases/{{name}}/ — markdown knowledge files may be in
either location. The data/ folder typically has context files (soul.md, MEMORY.md, etc.)
and the databases/ folder may have additional ones.

## Step 2: Walk through files

Read files ONE AT A TIME with read_import_file. After each, narrate what you found in 2-3 sentences.

Order: soul.md first, then IDENTITY.md, SOUL.md, USER.md, TOOLS.md, MEMORY.md, daily logs.
If none of those exact names exist, read whatever .md files are available.

After reading IDENTITY.md (or the first personality file), ask:
"Do you want me to carry this identity forward (same name, vibe, personality), or start fresh —
keeping everything your old agent knew, but developing my own personality?"

Note anything surprising, outdated, or worth adjusting. Ask before making judgment calls.

## Step 3: Write Chatty files

Use write_import_context for each file. Use Chatty's style: first-person, concise, no filler.

Targets:
- soul.md — Core personality (from SOUL.md + IDENTITY.md)
- identity.md — Name, vibe, emoji (from IDENTITY.md)
- user.md — Basic human info (from USER.md)
- profile.md — Deeper context (from USER.md + MEMORY.md)
- goals.md — Current projects (from HEARTBEAT.md + MEMORY.md)
- preferences.md — Communication style (from SOUL.md + MEMORY.md)
- environment.md — Local setup notes (from TOOLS.md)
- MEMORY.md — Living fact snapshot (from MEMORY.md + consolidated old daily logs)
- daily/YYYY-MM-DD.md — Copy recent daily logs (last 30 days)

Skip: BOOTSTRAP.md, AGENTS.md, *.dev.md

## Step 4: Finalize

Ask "Anything to adjust before I wrap up?" Then call finalize_import().
"""


def _seed_import_bootstrap(context_dir: Path, agent_name: str, openclaw_agents: list[dict] | None = None) -> None:
    if openclaw_agents is None:
        openclaw_agents = discover_openclaw_agents()
    if openclaw_agents:
        names = ", ".join(f"*{a['name']}*" for a in openclaw_agents)
        openclaw_line = f"- **OpenClaw** — I found an OpenClaw installation with agents: {names}. Just tell me which one."
    else:
        openclaw_line = ""

    content = _IMPORT_BOOTSTRAP.format(openclaw_line=openclaw_line)
    (context_dir / "_import-bootstrap.md").write_text(content, encoding="utf-8")


def _build_import_opener(agent_name: str, openclaw_agents: list[dict]) -> str:
    """Build the agent's opening message for the import conversation."""
    lines = [
        f"Hey! I'm {agent_name} — a brand new agent ready to learn. "
        "Let's bring your knowledge over from another system.\n",
        "Here's how you can get your files to me:\n",
        "**Drop files** — Drag and drop `.md`, `.txt`, or `.zip` files right into the chat window.\n",
        "**Paste it** — Copy and paste markdown content directly into the chat. "
        "Works great for a quick dump.\n",
        "**Point me at a folder** — Give me a path like `~/Downloads/agent-files/` "
        "and I'll scan it for markdown files.",
    ]

    if openclaw_agents:
        names = ", ".join(f"**{a['name']}**" for a in openclaw_agents)
        lines.append(
            f"\n**OpenClaw** — I found an OpenClaw installation on this machine "
            f"with agents: {names}. Just tell me which one and I'll pull the files automatically."
        )

    lines.append("\nWhat works best for you?")

    return "\n\n".join(lines)
