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

_VALID_LOG_STATUSES = {"ok", "error", "action_taken", "skipped", "running", "lease_lost"}
_VALID_EVENT_TYPES = {"scheduled_action", "chat"}


@router.get("/logs")
async def get_system_logs(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    status: str | None = None,
    event_type: str | None = None,
    agent: str | None = None,
    user=Depends(get_current_user),
):
    if status and status not in _VALID_LOG_STATUSES:
        raise HTTPException(status_code=400, detail=f"Invalid status filter: {status}")
    if event_type and event_type not in _VALID_EVENT_TYPES:
        raise HTTPException(status_code=400, detail=f"Invalid event_type: {event_type}")
    from . import history
    records = history.get_history(
        agent=agent, limit=limit, offset=offset,
        status_filter=status, event_type=event_type,
    )
    return {"logs": records}


@router.get("/logs/export")
async def export_logs(
    format: str = Query("json"),
    agent: str | None = None,
    event_type: str | None = None,
    status: str | None = None,
    days: int = Query(7, ge=1, le=90),
    user=Depends(get_current_user),
):
    """Export activity logs as JSON, CSV, or plain text."""
    import csv
    import io
    from datetime import datetime, timedelta, timezone
    from starlette.responses import Response

    if format not in ("json", "csv", "text"):
        raise HTTPException(status_code=400, detail="format must be json, csv, or text")
    if event_type and event_type not in _VALID_EVENT_TYPES:
        raise HTTPException(status_code=400, detail=f"Invalid event_type: {event_type}")
    if status and status not in _VALID_LOG_STATUSES:
        raise HTTPException(status_code=400, detail=f"Invalid status: {status}")

    from . import history
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")
    records = history.get_history(
        agent=agent, limit=10000, event_type=event_type, since=since,
        status_filter=status,
    )

    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    if format == "json":
        import json as _json
        content = _json.dumps(records, indent=2, default=str)
        return Response(
            content=content,
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="chatty-logs-{date_str}.json"'},
        )

    if format == "csv":

        def _sanitize_csv_cell(val: str) -> str:
            if val and val[0] in ("=", "+", "-", "@"):
                return "'" + val
            return val

        buf = io.StringIO()
        fieldnames = [
            "started_at", "agent", "event_type", "action_type", "source",
            "status", "result_summary", "model_used",
            "input_tokens", "output_tokens", "duration_ms", "tool_call_count",
        ]
        writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for rec in records:
            row = {k: _sanitize_csv_cell("" if rec.get(k) is None else str(rec.get(k))) for k in fieldnames}
            tc = rec.get("tool_calls")
            row["tool_call_count"] = str(len(tc) if isinstance(tc, list) else 0)
            writer.writerow(row)
        return Response(
            content=buf.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="chatty-logs-{date_str}.csv"'},
        )

    # Plain text
    lines = []
    for rec in records:
        ts = rec.get("started_at", "")
        ag = rec.get("agent", "")
        et = rec.get("event_type", rec.get("action_type", ""))
        st = rec.get("status", "")
        summary = rec.get("result_summary", "") or ""
        lines.append(f"[{ts}] {ag} | {et} | {st} | {summary}")
    return Response(
        content="\n".join(lines),
        media_type="text/plain",
        headers={"Content-Disposition": f'attachment; filename="chatty-logs-{date_str}.txt"'},
    )


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
