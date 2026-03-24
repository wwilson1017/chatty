"""
Webby — FastAPI router.

Provides status check and agent creation for the Webby agent.
Chat/context/conversation endpoints go through the main agents router
at /api/agents/{agent_id}/...

Phase 1: GitHub tools are stubs. Full implementation in Phase 2.
"""

from fastapi import APIRouter, Depends

from core.auth import get_current_user
from agents import db as agents_db
from webby.config import WEBBY_NAME, WEBBY_PERSONALITY, WEBBY_INSTRUCTIONS

router = APIRouter(prefix="/api/webby", tags=["webby"])

_WEBBY_SLUG = "webby"


def _get_webby() -> dict | None:
    return agents_db.get_agent_by_slug(_WEBBY_SLUG)


@router.get("/status")
async def webby_status(_: str = Depends(get_current_user)):
    """Check whether the Webby agent exists and is configured."""
    agent = _get_webby()
    if not agent:
        return {"exists": False, "agent_id": None}
    return {
        "exists": True,
        "agent_id": agent["id"],
        "onboarding_complete": bool(agent.get("onboarding_complete")),
        "phase": "stub",
        "note": "GitHub tools are stubs — full implementation in Phase 2.",
    }


@router.post("/create")
async def create_webby_agent(_: str = Depends(get_current_user)):
    """Create the Webby agent if it doesn't exist yet."""
    existing = _get_webby()
    if existing:
        return {"agent_id": existing["id"], "created": False}

    personality = f"{WEBBY_PERSONALITY}\n\n{WEBBY_INSTRUCTIONS}"
    agent = agents_db.create_agent(agent_name=WEBBY_NAME, personality=personality)
    return {"agent_id": agent["id"], "created": True}
