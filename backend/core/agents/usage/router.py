"""Chatty — Usage/cost dashboard REST endpoints."""

from fastapi import APIRouter, Depends, Query

from core.auth import get_current_user
from . import service

router = APIRouter()


@router.get("/summary")
async def get_summary(
    days: int = Query(7, ge=0, le=366),
    tz: str = Query("UTC", max_length=64),
    user=Depends(get_current_user),
):
    return service.get_usage_summary(days=days, tz=tz)
