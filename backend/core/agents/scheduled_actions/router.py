"""Chatty — Scheduled actions admin REST endpoints."""

import logging
from fastapi import APIRouter, Depends, HTTPException, Query
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
    triage_enabled: bool | None = None
    notify_on_action: bool | None = None
    always_on: bool | None = None


# -- Static routes (must come before /{agent_slug} to avoid capture) ------

@router.get("/dashboard")
async def get_dashboard(user=Depends(get_current_user)):
    actions = service.list_actions()
    token_usage = service.get_token_usage_summary()
    return {"actions": actions, "token_usage": token_usage}


@router.get("/token-usage")
async def get_token_usage(user=Depends(get_current_user)):
    return service.get_token_usage_summary()


@router.get("/executor")
async def get_executor_health(user=Depends(get_current_user)):
    from .processor import get_executor_stats
    return get_executor_stats()


# -- Dynamic routes --------------------------------------------------------

@router.get("")
async def list_all_actions(user=Depends(get_current_user)):
    actions = service.list_actions()
    return {"actions": actions}


@router.get("/{agent_slug}")
async def list_agent_actions(agent_slug: str, user=Depends(get_current_user)):
    actions = service.list_actions(agent=agent_slug)
    return {"actions": actions}


@router.patch("/{action_id}")
async def update_action(action_id: str, body: UpdateActionRequest, user=Depends(get_current_user)):
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    result = service.update_action(action_id, **updates)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.delete("/{action_id}")
async def delete_action(action_id: str, user=Depends(get_current_user)):
    result = service.delete_action(action_id)
    if "error" in result:
        status = 404 if "not found" in result["error"].lower() else 409
        raise HTTPException(status_code=status, detail=result["error"])
    return result


@router.post("/{action_id}/run-now")
def run_action_now(action_id: str, user=Depends(get_current_user)):
    from .processor import run_action_now_with_tracking

    try:
        updated = run_action_now_with_tracking(action_id)
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        logger.error("Manual run of %s failed: %s", action_id, e)
        raise HTTPException(status_code=500, detail="Action execution failed — see server logs")

    if updated is None:
        raise HTTPException(status_code=404, detail="Action not found")
    return {"ok": True, "action": updated}
