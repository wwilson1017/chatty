"""Chatty — Reminders REST endpoints (read-only)."""

import logging

from fastapi import APIRouter, Depends, Query

from core.auth import get_current_user
from . import service

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("")
async def list_reminders(
    agent: str | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    user=Depends(get_current_user),
):
    reminders = service.list_reminders_for_api(agent=agent, status=status, limit=limit)
    return {"reminders": reminders, "count": len(reminders)}


@router.get("/series/{series_id}")
async def get_series_history(
    series_id: str,
    limit: int = Query(20, ge=1, le=100),
    user=Depends(get_current_user),
):
    history = service.get_series_history(series_id, limit=limit)
    return {"history": history, "count": len(history)}
