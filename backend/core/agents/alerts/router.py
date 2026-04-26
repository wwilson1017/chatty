"""Chatty — Alerts REST endpoints."""

import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from core.auth import get_current_user
from . import service

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("")
async def list_alerts(
    agent: str | None = Query(None),
    status: Literal["active", "acknowledged", "resolved"] = Query("active"),
    user=Depends(get_current_user),
):
    alerts = service.list_alerts(agent=agent, status=status)
    return {"alerts": alerts}


@router.get("/counts")
async def get_alert_counts(user=Depends(get_current_user)):
    return {"counts": service.get_alert_counts()}


@router.post("/{alert_id}/acknowledge")
async def acknowledge_alert(alert_id: str, user=Depends(get_current_user)):
    result = service.acknowledge_alert(alert_id)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.post("/{alert_id}/resolve")
async def resolve_alert(alert_id: str, user=Depends(get_current_user)):
    result = service.resolve_alert(alert_id)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result
