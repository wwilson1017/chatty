"""Chatty -- Event log API endpoints."""

from fastapi import APIRouter, Depends, Query

from core.auth import get_current_user
from core.events import db

router = APIRouter(prefix="/api/events", tags=["events"])


@router.get("")
async def list_events(
    category: str | None = Query(None),
    agent: str | None = Query(None),
    severity: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    since: str | None = Query(None),
    user=Depends(get_current_user),
):
    events = db.query_events(
        category=category,
        agent_slug=agent,
        severity=severity,
        limit=limit,
        offset=offset,
        since=since,
    )
    return {"events": events}


@router.get("/counts")
async def event_counts(
    category: str | None = Query(None),
    user=Depends(get_current_user),
):
    return db.get_event_counts(category=category)


@router.post("/{event_id}/acknowledge")
async def acknowledge_event(
    event_id: str,
    user=Depends(get_current_user),
):
    db.acknowledge_event(event_id)
    return {"ok": True}
