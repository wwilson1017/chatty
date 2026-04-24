"""Routes for agent knowledge import."""

from __future__ import annotations

import logging
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

    # Seed only the import bootstrap file (not the full template set)
    context_dir = DATA_DIR / agent["slug"] / "context"
    context_dir.mkdir(parents=True, exist_ok=True)
    _seed_import_bootstrap(context_dir, name)

    # Create an import-mode conversation
    from .engine import get_chat_service
    chat_svc = get_chat_service(agent["slug"])
    conv = chat_svc.create_conversation(title="Knowledge Import", mode="import")

    # Create a placeholder session (adapter will be set by scan_directory or ingest_pasted_text)
    placeholder = PasteSourceAdapter("(awaiting source)")
    session = sessions.create_session(
        adapter=placeholder,
        agent_id=agent["id"],
        conversation_id=conv["id"],
    )

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

## Step 2: Walk through files

Read files ONE AT A TIME with read_import_file. After each, narrate what you found in 2-3 sentences.

Order: IDENTITY.md first, then SOUL.md, USER.md, TOOLS.md, MEMORY.md, daily logs.

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


def _seed_import_bootstrap(context_dir: Path, agent_name: str) -> None:
    openclaw_agents = discover_openclaw_agents()
    if openclaw_agents:
        names = ", ".join(f"*{a['name']}*" for a in openclaw_agents)
        openclaw_line = f"- **OpenClaw** — I found an OpenClaw installation with agents: {names}. Just tell me which one."
    else:
        openclaw_line = ""

    content = _IMPORT_BOOTSTRAP.format(openclaw_line=openclaw_line)
    (context_dir / "_import-bootstrap.md").write_text(content, encoding="utf-8")
