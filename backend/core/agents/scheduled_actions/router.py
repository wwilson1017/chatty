"""Chatty — Scheduled actions admin REST endpoints."""

import logging
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core.auth import get_current_user
from . import service

logger = logging.getLogger(__name__)
router = APIRouter()


class UpdateActionRequest(BaseModel):
    enabled: bool | None = None
    name: str | None = None
    description: str | None = None
    prompt: str | None = None
    cron_expression: str | None = None
    interval_minutes: int | None = None
    active_hours_start: str | None = None
    active_hours_end: str | None = None
    model_override: str | None = None
    max_tool_iterations: int | None = None


@router.get("")
async def list_all_actions(user=Depends(get_current_user)):
    """List all scheduled actions across all agents."""
    actions = service.list_actions()
    return {"actions": actions}


@router.get("/{agent_slug}")
async def list_agent_actions(agent_slug: str, user=Depends(get_current_user)):
    """List scheduled actions for a specific agent."""
    actions = service.list_actions(agent=agent_slug)
    return {"actions": actions}


@router.patch("/{action_id}")
async def update_action(action_id: str, body: UpdateActionRequest, user=Depends(get_current_user)):
    """Update a scheduled action."""
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    result = service.update_action(action_id, **updates)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.delete("/{action_id}")
async def delete_action(action_id: str, user=Depends(get_current_user)):
    """Delete a scheduled action."""
    result = service.delete_action(action_id)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result
