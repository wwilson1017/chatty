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
_DEFAULT_LEASE_MINUTES = 15
AUTO_DISABLE_THRESHOLD = 10
_ERROR_BACKOFF_SECONDS = [30, 60, 300, 900, 3600]


def _error_backoff_seconds(consecutive_errors: int) -> int:
    if consecutive_errors <= 0:
        return 0
    idx = min(consecutive_errors - 1, len(_ERROR_BACKOFF_SECONDS) - 1)
    return _ERROR_BACKOFF_SECONDS[idx]


def _normalize_hour(value, default: str = "06:00") -> str:
    """Convert integer hour (0-23) or 'HH:MM' string to canonical 'HH:MM' format."""
    if value is None:
        return default
    try:
        if isinstance(value, int) or str(value).isdigit():
            hour = int(value)
            if 0 <= hour <= 23:
                return f"{hour:02d}:00"
            return default
        hour_s, minute_s = str(value).split(":", 1)
        hour, minute = int(hour_s), int(minute_s)
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return f"{hour:02d}:{minute:02d}"
    except (ValueError, TypeError):
        pass
    return default


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
    max_tool_iterations: int = 10,
    enabled: bool = True,
    always_on: bool = False,
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
    active_hours_start = _normalize_hour(active_hours_start, "06:00")
    active_hours_end = _normalize_hour(active_hours_end, "20:00")

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
        if action_type == "heartbeat":
            existing = conn.execute(
                "SELECT id FROM scheduled_actions WHERE agent = ? AND action_type = 'heartbeat'",
                (agent,),
            ).fetchone()
            if existing:
                return {"error": f"Agent '{agent}' already has a heartbeat (id={existing['id']})"}

        conn.execute(
            """INSERT INTO scheduled_actions
               (id, agent, created_by_email, action_type, name, description,
                schedule_type, cron_expression, interval_minutes, run_at,
                active_hours_start, active_hours_end, active_hours_tz,
                prompt, model_override, max_tool_iterations, enabled, always_on,
                next_run)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                action_id, agent, created_by_email, action_type, name, description,
                schedule_type, cron_expression, interval_minutes, run_at,
                active_hours_start, active_hours_end, active_hours_tz,
                prompt, model_override, max_tool_iterations,
                1 if enabled else 0, 1 if always_on else 0, next_run,
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
        "enabled", "triage_enabled", "notify_on_action", "always_on",
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

        if "active_hours_start" in updates:
            updates["active_hours_start"] = _normalize_hour(updates["active_hours_start"], "06:00")
        if "active_hours_end" in updates:
            updates["active_hours_end"] = _normalize_hour(updates["active_hours_end"], "20:00")

        for bool_field in ("enabled", "triage_enabled", "notify_on_action", "always_on"):
            if bool_field in updates:
                updates[bool_field] = 1 if updates[bool_field] else 0
        if "enabled" in updates and updates["enabled"] == 1 and action.get("consecutive_errors", 0) >= AUTO_DISABLE_THRESHOLD:
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
        if row["action_type"] == "heartbeat":
            return {"error": "Cannot delete heartbeat actions. Disable it instead with update_scheduled_action."}
        conn.execute("DELETE FROM scheduled_actions WHERE id = ?", (action_id,))
        conn.commit()

    return {"ok": True, "id": action_id, "deleted": True}


def get_due_actions() -> list[dict]:
    """Get due actions (non-leased). Used as fallback; prefer claim_due_actions."""
    conn = db.get_db()
    now = _now_utc()
    rows = conn.execute(
        """SELECT * FROM scheduled_actions
           WHERE enabled = 1 AND next_run IS NOT NULL AND next_run <= ?
           AND (lease_id IS NULL OR leased_until <= ?)
           ORDER BY next_run ASC""",
        (now, now),
    ).fetchall()
    return [dict(r) for r in rows]


def claim_due_actions(
    available_capacity: int,
    exclude_agents: set[str] | None = None,
) -> list[dict]:
    """Atomically claim due actions. At most one action per agent."""
    if available_capacity <= 0:
        return []

    conn = db.get_db()
    now = _now_utc()
    lease_id = str(uuid.uuid4())
    lease_until = (datetime.now(timezone.utc) + timedelta(minutes=_DEFAULT_LEASE_MINUTES)).strftime("%Y-%m-%dT%H:%M:%S")

    with db.write_lock():
        query = """SELECT * FROM scheduled_actions
                   WHERE enabled = 1
                     AND next_run IS NOT NULL
                     AND next_run <= ?
                     AND (lease_id IS NULL OR leased_until <= ?)"""
        params: list = [now, now]

        if exclude_agents:
            placeholders = ",".join("?" * len(exclude_agents))
            query += f" AND agent NOT IN ({placeholders})"
            params.extend(exclude_agents)

        query += " ORDER BY next_run ASC"
        rows = conn.execute(query, params).fetchall()

        if not rows:
            return []

        seen_agents: set[str] = set()
        filtered: list[dict] = []
        for r in rows:
            agent = r["agent"]
            if agent not in seen_agents:
                seen_agents.add(agent)
                filtered.append(dict(r))
                if len(filtered) >= available_capacity:
                    break

        if not filtered:
            return []

        ids = [a["id"] for a in filtered]
        placeholders = ",".join("?" * len(ids))
        conn.execute(
            f"UPDATE scheduled_actions SET lease_id = ?, leased_until = ? WHERE id IN ({placeholders})",
            [lease_id, lease_until] + ids,
        )
        conn.commit()

    for a in filtered:
        a["lease_id"] = lease_id
        a["leased_until"] = lease_until
    return filtered


def claim_single_action(action_id: str) -> dict | None:
    """Atomically claim a single action for manual execution."""
    conn = db.get_db()
    now = _now_utc()
    lease_id = str(uuid.uuid4())
    lease_until = (datetime.now(timezone.utc) + timedelta(minutes=_DEFAULT_LEASE_MINUTES)).strftime("%Y-%m-%dT%H:%M:%S")

    with db.write_lock():
        row = conn.execute("SELECT * FROM scheduled_actions WHERE id = ?", (action_id,)).fetchone()
        if not row:
            return None
        if row["lease_id"] is not None and row["leased_until"] and row["leased_until"] > now:
            return None
        sibling = conn.execute(
            "SELECT 1 FROM scheduled_actions WHERE agent = ? AND id != ? AND lease_id IS NOT NULL AND leased_until > ? LIMIT 1",
            (row["agent"], action_id, now),
        ).fetchone()
        if sibling:
            return None
        conn.execute(
            "UPDATE scheduled_actions SET lease_id = ?, leased_until = ? WHERE id = ?",
            (lease_id, lease_until, action_id),
        )
        conn.commit()

    action = dict(row)
    action["lease_id"] = lease_id
    action["leased_until"] = lease_until
    return action


def release_lease(action_id: str, lease_id: str, advance_next_run: bool = False) -> None:
    """Release a lease. Only clears if lease_id matches."""
    conn = db.get_db()
    with db.write_lock():
        if advance_next_run:
            row = conn.execute(
                "SELECT * FROM scheduled_actions WHERE id = ? AND lease_id = ?",
                (action_id, lease_id),
            ).fetchone()
            if not row:
                return
            action = dict(row)
            action["last_run"] = _now_utc()
            next_run = compute_next_run(action)
            conn.execute(
                "UPDATE scheduled_actions SET lease_id = NULL, leased_until = NULL, next_run = ? WHERE id = ? AND lease_id = ?",
                (next_run, action_id, lease_id),
            )
        else:
            conn.execute(
                "UPDATE scheduled_actions SET lease_id = NULL, leased_until = NULL WHERE id = ? AND lease_id = ?",
                (action_id, lease_id),
            )
        conn.commit()


def renew_lease(action_id: str, lease_id: str, extra_minutes: int = 15) -> bool:
    """Extend a lease. Returns True if renewed, False if reclaimed."""
    conn = db.get_db()
    new_until = (datetime.now(timezone.utc) + timedelta(minutes=extra_minutes)).strftime("%Y-%m-%dT%H:%M:%S")
    with db.write_lock():
        cursor = conn.execute(
            "UPDATE scheduled_actions SET leased_until = ? WHERE id = ? AND lease_id = ?",
            (new_until, action_id, lease_id),
        )
        conn.commit()
        return cursor.rowcount > 0


def release_expired_leases() -> int:
    """Clear leases that have expired (process died mid-execution).

    Treats each expired lease as an execution failure so consecutive_errors
    increments and backoff applies. Uses ``require_expired_before`` to
    prevent racing with lease renewal.
    """
    from . import history

    conn = db.get_db()
    now = _now_utc()
    expired_rows = conn.execute(
        "SELECT id, lease_id FROM scheduled_actions WHERE lease_id IS NOT NULL AND leased_until <= ?",
        (now,),
    ).fetchall()
    if not expired_rows:
        return 0

    count = 0
    for row in expired_rows:
        action_row = conn.execute("SELECT * FROM scheduled_actions WHERE id = ?", (row["id"],)).fetchone()
        action = dict(action_row) if action_row else None
        completed = mark_executed(
            row["id"], "error", "stuck run: lease expired", 0,
            lease_id=row["lease_id"], require_expired_before=now,
        )
        if not completed:
            continue
        count += 1

        if action:
            old_errors = action.get("consecutive_errors", 0)
            new_errors = old_errors + 1
            from . import notifications
            if new_errors >= notifications.FAILURE_ALERT_THRESHOLD:
                try:
                    notifications.evaluate_failure_alert(
                        action, new_errors, "stuck run: lease expired", action.get("agent", ""),
                    )
                except Exception as e:
                    logger.debug("Failure alert for expired lease failed: %s", e)

        stale = conn.execute(
            "SELECT id FROM execution_history WHERE action_id = ? AND status = 'running' ORDER BY started_at DESC LIMIT 1",
            (row["id"],),
        ).fetchone()
        if stale:
            history.record_complete(
                stale["id"], status="lease_lost",
                result_summary="Process died: lease expired",
            )
    return count


def mark_executed(
    action_id: str,
    status: str,
    result: str,
    duration_ms: int = 0,
    input_tokens: int = 0,
    output_tokens: int = 0,
    lease_id: str | None = None,
    require_expired_before: str | None = None,
) -> bool:
    """Mark an action as executed and schedule its next run.

    Returns True if completed, False if lease mismatch (stale worker).
    ``require_expired_before`` adds an extra ``leased_until <= ?`` guard so
    the sweeper cannot mark a renewed lease as expired (race-safe).
    """
    conn = db.get_db()
    now = _now_utc()

    with db.write_lock():
        row = conn.execute("SELECT * FROM scheduled_actions WHERE id = ?", (action_id,)).fetchone()
        if not row:
            return False

        if lease_id is not None:
            if row["lease_id"] != lease_id:
                logger.warning("Lease mismatch for %s: expected %s, got %s", action_id, row["lease_id"], lease_id)
                return False
            if require_expired_before and row["leased_until"] and row["leased_until"] > require_expired_before:
                return False
        elif row["lease_id"] is not None:
            logger.warning("Unleased caller for %s but row has lease %s", action_id, row["lease_id"])
            return False

        action = dict(row)
        action["last_run"] = now

        consecutive_errors = action.get("consecutive_errors", 0)
        if status == "error":
            consecutive_errors += 1
        else:
            consecutive_errors = 0

        natural_next = compute_next_run(action)

        if status == "error" and consecutive_errors > 0 and natural_next and action["schedule_type"] != "once":
            backoff_s = _error_backoff_seconds(consecutive_errors)
            backoff_time = (datetime.now(timezone.utc) + timedelta(seconds=backoff_s)).strftime("%Y-%m-%dT%H:%M:%S")
            next_run = max(natural_next, backoff_time)
        else:
            next_run = natural_next

        enabled = action["enabled"]
        if action["schedule_type"] == "once":
            enabled = 0
            next_run = None

        if consecutive_errors >= AUTO_DISABLE_THRESHOLD:
            enabled = 0
            logger.warning("Action %s auto-disabled after %d consecutive errors", action_id, consecutive_errors)

        conn.execute(
            """UPDATE scheduled_actions SET
               last_run = ?, last_status = ?, last_result = ?,
               last_duration_ms = ?, last_input_tokens = ?, last_output_tokens = ?,
               consecutive_errors = ?, total_runs = total_runs + 1,
               total_input_tokens = total_input_tokens + ?,
               total_output_tokens = total_output_tokens + ?,
               next_run = ?, enabled = ?, updated_at = ?,
               lease_id = NULL, leased_until = NULL
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
    return True


def ensure_default_actions(agent_slug: str) -> None:
    """Create a default heartbeat action for an agent if none exists."""
    existing = list_actions(agent=agent_slug, action_type="heartbeat")
    if existing:
        for action in existing:
            if not action.get("always_on"):
                update_action(action["id"], always_on=True)
        return

    create_action(
        agent=agent_slug,
        schedule_type="interval",
        name="Heartbeat",
        description="Periodic check against HEARTBEAT.md checklist",
        interval_minutes=30,
        active_hours_tz="America/Chicago",
        prompt="Perform your heartbeat check now.",
        action_type="heartbeat",
        always_on=True,
    )
    logger.info("Created default heartbeat for agent %s", agent_slug)


def ensure_default_actions_all() -> None:
    """Ensure all onboarded agents have default actions. Called by sweeper/startup."""
    try:
        from agents.db import list_agents
        agents = list_agents()
        for agent in agents:
            if agent.get("onboarding_complete"):
                ensure_default_actions(agent["slug"])
    except Exception as e:
        logger.debug("ensure_default_actions_all: %s", e)


def get_heartbeat_stats() -> dict:
    conn = db.get_db()
    rows = conn.execute(
        "SELECT agent, last_run, last_status, last_duration_ms, consecutive_errors, enabled "
        "FROM scheduled_actions WHERE action_type = 'heartbeat'"
    ).fetchall()
    return {"heartbeats": [dict(r) for r in rows]}


def get_token_usage_summary() -> dict:
    conn = db.get_db()
    row = conn.execute(
        "SELECT SUM(total_input_tokens) as total_input, SUM(total_output_tokens) as total_output, "
        "SUM(total_runs) as total_runs FROM scheduled_actions"
    ).fetchone()
    return dict(row) if row else {"total_input": 0, "total_output": 0, "total_runs": 0}
