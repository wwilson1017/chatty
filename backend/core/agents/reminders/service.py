"""Chatty — Reminder CRUD service.

Pure functions for creating, listing, cancelling, and querying reminders.
"""

import json
import logging
import uuid
from calendar import monthrange
from datetime import datetime, timedelta, timezone

from . import db

logger = logging.getLogger(__name__)


def create_reminder(
    agent: str,
    message: str,
    due_at: str,
    context: str | None = None,
    created_by_email: str = "user",
    recurrence_rule: str | None = None,
    series_id: str | None = None,
) -> dict:
    """Create a new self-reminder, optionally recurring."""
    # Validate and normalize due_at to bare YYYY-MM-DDTHH:MM:SS (UTC assumed)
    try:
        parsed_dt = datetime.fromisoformat(due_at.replace("Z", "+00:00"))
        if parsed_dt.tzinfo is not None:
            parsed_dt = parsed_dt.astimezone(timezone.utc).replace(tzinfo=None)
        due_at = parsed_dt.strftime("%Y-%m-%dT%H:%M:%S")
    except (ValueError, AttributeError):
        return {"error": f"due_at must be a valid ISO 8601 datetime, got: {due_at}"}

    if recurrence_rule:
        try:
            rule = json.loads(recurrence_rule)
            if "type" not in rule:
                return {"error": "recurrence_rule must include a 'type' field"}
        except (json.JSONDecodeError, TypeError):
            return {"error": f"recurrence_rule must be valid JSON, got: {recurrence_rule}"}

    reminder_id = str(uuid.uuid4())
    if recurrence_rule and not series_id:
        series_id = reminder_id
    conn = db.get_db()

    with db.write_lock():
        conn.execute(
            """INSERT INTO reminders (id, agent, created_by_email, reminder_type,
               message, context, due_at, recurrence_rule, series_id)
               VALUES (?, ?, ?, 'self', ?, ?, ?, ?, ?)""",
            (reminder_id, agent, created_by_email, message, context, due_at,
             recurrence_rule, series_id),
        )
        conn.commit()

    result = {
        "ok": True,
        "id": reminder_id,
        "agent": agent,
        "message": message,
        "due_at": due_at,
    }
    if recurrence_rule:
        result["recurring"] = True
        result["series_id"] = series_id
    return result


def list_reminders(
    agent: str,
    status: str = "pending",
    limit: int = 20,
) -> list[dict]:
    """List reminders for an agent, filtered by status."""
    conn = db.get_db()

    query = "SELECT * FROM reminders WHERE agent = ?"
    params: list = [agent]

    if status:
        query += " AND status = ?"
        params.append(status)

    query += " ORDER BY due_at ASC LIMIT ?"
    params.append(limit)

    rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def cancel_reminder(reminder_id: str) -> dict:
    """Cancel a pending reminder. For recurring reminders, stops the series."""
    conn = db.get_db()

    with db.write_lock():
        row = conn.execute(
            "SELECT * FROM reminders WHERE id = ?", (reminder_id,)
        ).fetchone()

        if not row:
            return {"error": f"Reminder {reminder_id} not found"}
        if row["status"] != "pending":
            return {"error": f"Reminder is already {row['status']}"}

        conn.execute(
            "UPDATE reminders SET status = 'cancelled' WHERE id = ?",
            (reminder_id,),
        )
        conn.commit()

    result: dict = {"ok": True, "id": reminder_id, "status": "cancelled"}
    if row["recurrence_rule"]:
        result["note"] = "This was a recurring reminder. The series has been stopped."
    return result


def get_due_reminders() -> list[dict]:
    """Return all pending reminders that are due (due_at <= now UTC)."""
    conn = db.get_db()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    rows = conn.execute(
        "SELECT * FROM reminders WHERE status = 'pending' AND due_at <= ? ORDER BY due_at ASC",
        (now,),
    ).fetchall()
    return [dict(r) for r in rows]


def mark_fired(reminder_id: str, result: str) -> None:
    """Mark a reminder as fired with a result message."""
    conn = db.get_db()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

    with db.write_lock():
        conn.execute(
            "UPDATE reminders SET status = 'fired', fired_at = ?, result = ? WHERE id = ?",
            (now, result, reminder_id),
        )
        conn.commit()


# ── Recurring reminder support ─────────────────────────────────────────


def compute_next_due(current_due: str, rule: dict) -> str | None:
    """Compute the next due_at from the current one and a recurrence rule."""
    try:
        dt = datetime.fromisoformat(current_due)
    except (ValueError, TypeError):
        return None

    rtype = rule.get("type")
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    if rtype == "daily":
        dt += timedelta(days=1)
        # Skip past if we've missed occurrences
        while dt <= now:
            dt += timedelta(days=1)
        return dt.strftime("%Y-%m-%dT%H:%M:%S")

    if rtype == "interval":
        hours = rule.get("hours", 0)
        minutes = rule.get("minutes", 0)
        delta = timedelta(hours=hours, minutes=minutes)
        if delta.total_seconds() < 60:
            return None
        dt += delta
        while dt <= now:
            dt += delta
        return dt.strftime("%Y-%m-%dT%H:%M:%S")

    if rtype == "weekly":
        days = rule.get("days", [])
        if not days:
            return None
        days_set = set(days)
        dt += timedelta(days=1)
        # Advance until we hit a matching weekday (ISO: Mon=1..Sun=7)
        for _ in range(14):
            if dt.isoweekday() in days_set and dt > now:
                return dt.strftime("%Y-%m-%dT%H:%M:%S")
            dt += timedelta(days=1)
        return None

    if rtype == "monthly":
        target_day = rule.get("day", dt.day)
        month = dt.month + 1
        year = dt.year
        if month > 12:
            month = 1
            year += 1
        max_day = monthrange(year, month)[1]
        clamped_day = min(target_day, max_day)
        dt = dt.replace(year=year, month=month, day=clamped_day)
        while dt <= now:
            month = dt.month + 1
            year = dt.year
            if month > 12:
                month = 1
                year += 1
            max_day = monthrange(year, month)[1]
            clamped_day = min(target_day, max_day)
            dt = dt.replace(year=year, month=month, day=clamped_day)
        return dt.strftime("%Y-%m-%dT%H:%M:%S")

    if rtype == "cron":
        expression = rule.get("expression")
        if not expression:
            return None
        try:
            from croniter import croniter
            cron = croniter(expression, dt)
            next_dt = cron.get_next(datetime)
            while next_dt <= now:
                next_dt = cron.get_next(datetime)
            return next_dt.strftime("%Y-%m-%dT%H:%M:%S")
        except Exception:
            return None

    return None


def create_next_occurrence(fired_reminder: dict) -> dict | None:
    """After a recurring reminder fires, create the next pending occurrence."""
    rule_str = fired_reminder.get("recurrence_rule")
    if not rule_str:
        return None

    try:
        rule = json.loads(rule_str)
    except (json.JSONDecodeError, TypeError):
        logger.warning("Invalid recurrence_rule for reminder %s", fired_reminder["id"])
        return None

    next_due = compute_next_due(fired_reminder["due_at"], rule)
    if not next_due:
        logger.warning("Could not compute next due for reminder %s", fired_reminder["id"])
        return None

    return create_reminder(
        agent=fired_reminder["agent"],
        message=fired_reminder["message"],
        due_at=next_due,
        context=fired_reminder.get("context"),
        created_by_email=fired_reminder.get("created_by_email", "user"),
        recurrence_rule=rule_str,
        series_id=fired_reminder.get("series_id") or fired_reminder["id"],
    )


# ── API queries ────────────────────────────────────────────────────────


def list_reminders_for_api(
    agent: str | None = None,
    status: str | None = None,
    limit: int = 50,
) -> list[dict]:
    """List reminders for the REST API, optionally filtered."""
    conn = db.get_db()
    query = "SELECT * FROM reminders WHERE 1=1"
    params: list = []

    if agent:
        query += " AND agent = ?"
        params.append(agent)
    if status:
        query += " AND status = ?"
        params.append(status)

    order = "ASC" if status == "pending" else "DESC"
    query += f" ORDER BY due_at {order} LIMIT ?"
    params.append(limit)

    rows = conn.execute(query, params).fetchall()
    results = []
    for r in rows:
        d = dict(r)
        d["is_recurring"] = bool(d.get("recurrence_rule"))
        results.append(d)
    return results


def get_series_history(series_id: str, limit: int = 20) -> list[dict]:
    """Get all reminders in a recurring series."""
    conn = db.get_db()
    rows = conn.execute(
        "SELECT * FROM reminders WHERE series_id = ? ORDER BY due_at DESC LIMIT ?",
        (series_id, limit),
    ).fetchall()
    results = []
    for r in rows:
        d = dict(r)
        d["is_recurring"] = bool(d.get("recurrence_rule"))
        results.append(d)
    return results
