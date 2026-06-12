"""
Chatty — Per-agent playbook CRUD + learning-events feed routes.

Playbooks:
  GET    /api/agents/{agent_id}/playbooks                      — list (incl. archived)
  GET    /api/agents/{agent_id}/playbooks/{slug}               — full content
  PUT    /api/agents/{agent_id}/playbooks/{slug}               — create/update (partial)
  DELETE /api/agents/{agent_id}/playbooks/{slug}               — hard delete
  POST   /api/agents/{agent_id}/playbooks/{slug}/archive
  POST   /api/agents/{agent_id}/playbooks/{slug}/restore

Learning feed:
  GET    /api/agents/{agent_id}/learning-events                — what the agent learned
  POST   /api/agents/{agent_id}/learning-events/{event_id}/revert
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from core.auth import get_current_user
from core.agents.playbooks import learning_log, service

from .router import _get_agent_or_404

logger = logging.getLogger(__name__)
router = APIRouter()


class PlaybookWriteRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    content: str | None = None
    integrations: list[str] | None = None
    chip: bool | None = None


@router.get("/{agent_id}/playbooks")
async def list_playbooks(agent_id: str, user: str = Depends(get_current_user)):
    agent = _get_agent_or_404(agent_id)
    return {"playbooks": service.list_playbooks(agent["slug"], include_archived=True)}


@router.get("/{agent_id}/playbooks/{slug}")
async def get_playbook(agent_id: str, slug: str, user: str = Depends(get_current_user)):
    agent = _get_agent_or_404(agent_id)
    pb = service.read_playbook(agent["slug"], slug)
    if not pb:
        raise HTTPException(status_code=404, detail="Playbook not found")
    return pb


@router.put("/{agent_id}/playbooks/{slug}")
async def save_playbook(
    agent_id: str, slug: str, req: PlaybookWriteRequest,
    user: str = Depends(get_current_user),
):
    agent = _get_agent_or_404(agent_id)
    result = service.save_playbook(
        agent["slug"],
        name=req.name,
        description=req.description,
        content=req.content,
        integrations=req.integrations,
        chip=req.chip,
        origin="user",
        slug=slug,
    )
    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.delete("/{agent_id}/playbooks/{slug}")
async def delete_playbook(agent_id: str, slug: str, user: str = Depends(get_current_user)):
    agent = _get_agent_or_404(agent_id)
    result = service.delete_playbook(agent["slug"], slug)
    if result.get("error"):
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.post("/{agent_id}/playbooks/{slug}/archive")
async def archive_playbook(agent_id: str, slug: str, user: str = Depends(get_current_user)):
    agent = _get_agent_or_404(agent_id)
    result = service.archive_playbook(agent["slug"], slug, origin="user")
    if result.get("error"):
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.post("/{agent_id}/playbooks/{slug}/restore")
async def restore_playbook(agent_id: str, slug: str, user: str = Depends(get_current_user)):
    agent = _get_agent_or_404(agent_id)
    result = service.restore_playbook(agent["slug"], slug)
    if result.get("error"):
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.get("/{agent_id}/learning-events")
async def list_learning_events(
    agent_id: str,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: str = Depends(get_current_user),
):
    agent = _get_agent_or_404(agent_id)
    # No try/except: a DB failure should surface as a 500 (the frontend shows a
    # retryable error), not a convincing-but-wrong empty feed.
    events = learning_log.list_events(agent["slug"], limit=limit, offset=offset)
    return {"events": events}


@router.post("/{agent_id}/learning-events/{event_id}/revert")
async def revert_learning_event(
    agent_id: str, event_id: int, user: str = Depends(get_current_user),
):
    agent = _get_agent_or_404(agent_id)
    try:
        result = learning_log.revert_event(agent["slug"], event_id)
    except Exception:
        logger.warning("revert failed for %s event %s", agent["slug"], event_id, exc_info=True)
        raise HTTPException(status_code=500, detail="revert failed")
    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])
    return result
