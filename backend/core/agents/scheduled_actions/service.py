"""Chatty — Scheduled actions CRUD service and scheduling logic.

Uses the shared reminders DB for storage.
"""

import logging
import uuid
from datetime import datetime, timezone, timedelta

from croniter import croniter

from core.agents.reminders import db

logger = logging.getLogger(__name__)

MIN_INTERVAL_MINUTES = 5
MAX_INTERVAL_MINUTES = 1440
MAX_TOOL_ITERATIONS_CAP = 10
DEFAULT_INTERVAL_MINUTES = 30


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def compute_next_run(action: dict) -> str | None:
    """Compute next run time (UTC ISO string) based on schedule type."""
    schedule_type = action["schedule_type"]

    if schedule_type == "once":
        run_at = action.get("run_at")
        if not run_at:
            return None
        try:
            dt = datetime.fromisoformat(run_at.replace("Z", "+00:00"))
            if dt.tzinfo:
                dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
            if dt > datetime.now(timezone.utc).replace(tzinfo=None):
                return dt.strftime("%Y-%m-%dT%H:%M:%S")
        except ValueError:
            pass
        return None

    if schedule_type == "interval":
        interval = action.get("interval_minutes") or DEFAULT_INTERVAL_MINUTES
        last_run = action.get("last_run")
        if last_run:
            try:
                base = datetime.fromisoformat(last_run)
            except ValueError:
                base = datetime.now(timezone.utc).replace(tzinfo=None)
        else:
            base = datetime.now(timezone.utc).replace(tzinfo=None)
        next_dt = base + timedelta(minutes=interval)
        return next_dt.strftime("%Y-%m-%dT%H:%M:%S")

    if schedule_type == "cron":
        expr = action.get("cron_expression")
        if not expr:
            return None
        try:
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            cron = croniter(expr, now)
            next_dt = cron.get_next(datetime)
            return next_dt.strftime("%Y-%m-%dT%H:%M:%S")
        except (ValueError, KeyError):
            return None

    return None


def create_action(
    agent: str,
    schedule_type: str,
    *,
    name: str = "",
    description: str = "",
    cron_expression: str | None = None,
    interval_minutes: int | None = None,
    run_at: str | None = None,
    active_hours_start: str = "06:00",
    active_hours_end: str = "20:00",
    active_hours_tz: str = "America/Chicago",
    prompt: str = "",
    model_override: str | None = None,
    max_tool_iterations: int = 5,
    enabled: bool = True,
    created_by_email: str = "user",
    action_type: str = "cron",
) -> dict:
    """Create a new scheduled action."""
    if schedule_type not in ("cron", "interval", "once"):
        return {"error": "schedule_type must be 'cron', 'interval', or 'once'"}

    if schedule_type == "cron":
        if not cron_expression:
            return {"error": "cron_expression is required for schedule_type='cron'"}
        if not croniter.is_valid(cron_expression):
            return {"error": f"Invalid cron expression: {cron_expression}"}

    if schedule_type == "interval":
        interval_minutes = interval_minutes or DEFAULT_INTERVAL_MINUTES
        if interval_minutes < MIN_INTERVAL_MINUTES:
            return {"error": f"interval_minutes must be >= {MIN_INTERVAL_MINUTES}"}
        if interval_minutes > MAX_INTERVAL_MINUTES:
            return {"error": f"interval_minutes must be <= {MAX_INTERVAL_MINUTES}"}

    if schedule_type == "once":
        if not run_at:
            return {"error": "run_at is required for schedule_type='once'"}
        try:
            datetime.fromisoformat(run_at.replace("Z", "+00:00"))
        except ValueError:
            return {"error": f"run_at must be a valid ISO 8601 datetime, got: {run_at}"}

    max_tool_iterations = min(max(max_tool_iterations, 1), MAX_TOOL_ITERATIONS_CAP)

    action_id = str(uuid.uuid4())
    action_dict = {
        "id": action_id,
        "schedule_type": schedule_type,
        "cron_expression": cron_expression,
        "interval_minutes": interval_minutes,
        "run_at": run_at,
        "last_run": None,
    }
    next_run = compute_next_run(action_dict)

    conn = db.get_db()
    with db.write_lock():
        conn.execute(
            """INSERT INTO scheduled_actions
               (id, agent, created_by_email, action_type, name, description,
                schedule_type, cron_expression, interval_minutes, run_at,
                active_hours_start, active_hours_end, active_hours_tz,
                prompt, model_override, max_tool_iterations, enabled, next_run)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                action_id, agent, created_by_email, action_type, name, description,
                schedule_type, cron_expression, interval_minutes, run_at,
                active_hours_start, active_hours_end, active_hours_tz,
                prompt, model_override, max_tool_iterations,
                1 if enabled else 0, next_run,
            ),
        )
        conn.commit()

    return {
        "ok": True,
        "id": action_id,
        "agent": agent,
        "schedule_type": schedule_type,
        "next_run": next_run,
        "enabled": enabled,
    }


def list_actions(
    agent: str | None = None,
    action_type: str | None = None,
    enabled: bool | None = None,
    limit: int = 100,
) -> list[dict]:
    conn = db.get_db()
    query = "SELECT * FROM scheduled_actions WHERE 1=1"
    params: list = []

    if agent:
        query += " AND agent = ?"
        params.append(agent)
    if action_type:
        query += " AND action_type = ?"
        params.append(action_type)
    if enabled is not None:
        query += " AND enabled = ?"
        params.append(1 if enabled else 0)

    query += " ORDER BY agent, created_at LIMIT ?"
    params.append(limit)

    rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def get_action(action_id: str) -> dict | None:
    conn = db.get_db()
    row = conn.execute("SELECT * FROM scheduled_actions WHERE id = ?", (action_id,)).fetchone()
    return dict(row) if row else None


def update_action(action_id: str, **fields) -> dict:
    conn = db.get_db()

    allowed = {
        "name", "description", "schedule_type", "cron_expression",
        "interval_minutes", "run_at", "active_hours_start", "active_hours_end",
        "active_hours_tz", "prompt", "model_override", "max_tool_iterations",
        "enabled",
    }

    updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if not updates:
        return {"error": "No valid fields to update"}

    with db.write_lock():
        row = conn.execute("SELECT * FROM scheduled_actions WHERE id = ?", (action_id,)).fetchone()
        if not row:
            return {"error": f"Action {action_id} not found"}

        action = dict(row)

        if "interval_minutes" in updates:
            iv = updates["interval_minutes"]
            if iv < MIN_INTERVAL_MINUTES:
                return {"error": f"interval_minutes must be >= {MIN_INTERVAL_MINUTES}"}
            if iv > MAX_INTERVAL_MINUTES:
                return {"error": f"interval_minutes must be <= {MAX_INTERVAL_MINUTES}"}

        if "cron_expression" in updates:
            expr = updates["cron_expression"]
            if expr and not croniter.is_valid(expr):
                return {"error": f"Invalid cron expression: {expr}"}

        if "max_tool_iterations" in updates:
            updates["max_tool_iterations"] = min(max(updates["max_tool_iterations"], 1), MAX_TOOL_ITERATIONS_CAP)

        if "enabled" in updates:
            updates["enabled"] = 1 if updates["enabled"] else 0
            if updates["enabled"] == 1 and action.get("consecutive_errors", 0) >= 5:
                updates["consecutive_errors"] = 0

        updates["updated_at"] = _now_utc()

        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [action_id]
        conn.execute(f"UPDATE scheduled_actions SET {set_clause} WHERE id = ?", values)

        schedule_changed = any(k in updates for k in ("schedule_type", "cron_expression", "interval_minutes", "run_at", "enabled"))
        if schedule_changed:
            merged = {**action, **updates}
            next_run = compute_next_run(merged)
            conn.execute("UPDATE scheduled_actions SET next_run = ? WHERE id = ?", (next_run, action_id))

        conn.commit()

    return {"ok": True, "id": action_id}


def delete_action(action_id: str) -> dict:
    conn = db.get_db()
    with db.write_lock():
        row = conn.execute("SELECT * FROM scheduled_actions WHERE id = ?", (action_id,)).fetchone()
        if not row:
            return {"error": f"Action {action_id} not found"}
        conn.execute("DELETE FROM scheduled_actions WHERE id = ?", (action_id,))
        conn.commit()

    return {"ok": True, "id": action_id, "deleted": True}


def get_due_actions() -> list[dict]:
    conn = db.get_db()
    now = _now_utc()
    rows = conn.execute(
        "SELECT * FROM scheduled_actions WHERE enabled = 1 AND next_run IS NOT NULL AND next_run <= ? ORDER BY next_run ASC",
        (now,),
    ).fetchall()
    return [dict(r) for r in rows]


def mark_executed(
    action_id: str,
    status: str,
    result: str,
    duration_ms: int = 0,
    input_tokens: int = 0,
    output_tokens: int = 0,
) -> None:
    conn = db.get_db()
    now = _now_utc()

    with db.write_lock():
        row = conn.execute("SELECT * FROM scheduled_actions WHERE id = ?", (action_id,)).fetchone()
        if not row:
            return

        action = dict(row)
        action["last_run"] = now

        consecutive_errors = action.get("consecutive_errors", 0)
        if status == "error":
            consecutive_errors += 1
        else:
            consecutive_errors = 0

        next_run = compute_next_run(action)

        enabled = action["enabled"]
        if action["schedule_type"] == "once":
            enabled = 0
            next_run = None

        if consecutive_errors >= 5:
            enabled = 0
            logger.warning("Action %s auto-disabled after %d consecutive errors", action_id, consecutive_errors)

        conn.execute(
            """UPDATE scheduled_actions SET
               last_run = ?, last_status = ?, last_result = ?,
               last_duration_ms = ?, last_input_tokens = ?, last_output_tokens = ?,
               consecutive_errors = ?, total_runs = total_runs + 1,
               total_input_tokens = total_input_tokens + ?,
               total_output_tokens = total_output_tokens + ?,
               next_run = ?, enabled = ?, updated_at = ?
               WHERE id = ?""",
            (
                now, status, result[:2000],
                duration_ms, input_tokens, output_tokens,
                consecutive_errors,
                input_tokens, output_tokens,
                next_run, enabled, now,
                action_id,
            ),
        )
        conn.commit()
