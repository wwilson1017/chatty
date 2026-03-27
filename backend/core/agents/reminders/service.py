"""Chatty — Reminder CRUD service.

Pure functions for creating, listing, cancelling, and querying reminders.
"""

import logging
import uuid
from datetime import datetime, timezone

from . import db

logger = logging.getLogger(__name__)


def create_reminder(
    agent: str,
    message: str,
    due_at: str,
    context: str | None = None,
    created_by_email: str = "user",
) -> dict:
    """Create a new self-reminder."""
    # Validate and normalize due_at to bare YYYY-MM-DDTHH:MM:SS (UTC assumed)
    try:
        parsed_dt = datetime.fromisoformat(due_at.replace("Z", "+00:00"))
        if parsed_dt.tzinfo is not None:
            parsed_dt = parsed_dt.astimezone(timezone.utc).replace(tzinfo=None)
        due_at = parsed_dt.strftime("%Y-%m-%dT%H:%M:%S")
    except (ValueError, AttributeError):
        return {"error": f"due_at must be a valid ISO 8601 datetime, got: {due_at}"}

    reminder_id = str(uuid.uuid4())
    conn = db.get_db()

    with db.write_lock():
        conn.execute(
            """INSERT INTO reminders (id, agent, created_by_email, reminder_type,
               message, context, due_at)
               VALUES (?, ?, ?, 'self', ?, ?, ?)""",
            (reminder_id, agent, created_by_email, message, context, due_at),
        )
        conn.commit()

    return {
        "ok": True,
        "id": reminder_id,
        "agent": agent,
        "message": message,
        "due_at": due_at,
    }


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
    """Cancel a pending reminder."""
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

    return {"ok": True, "id": reminder_id, "status": "cancelled"}


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
