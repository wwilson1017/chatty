"""CRUD operations for the notifications table."""

import json
import logging
import uuid
from datetime import datetime, timezone

from core.agents.reminders import db

logger = logging.getLogger(__name__)


def create_notification(
    agent: str,
    title: str,
    message: str,
    channels_sent: list[str] | None = None,
    notification_id: str | None = None,
) -> dict:
    title = title[:200]
    message = message[:5000]
    nid = notification_id or str(uuid.uuid4())
    channels_json = json.dumps(channels_sent or [])

    conn = db.get_db()
    conn.execute(
        """INSERT INTO notifications (id, agent, title, message, channels_sent)
           VALUES (?, ?, ?, ?, ?)""",
        (nid, agent, title, message, channels_json),
    )
    conn.commit()
    return {"ok": True, "id": nid, "agent": agent}


def list_notifications(
    agent: str | None = None,
    status: str = "active",
    limit: int = 10,
) -> list[dict]:
    conn = db.get_db()
    if agent:
        rows = conn.execute(
            """SELECT id, agent, title, message, status, channels_sent, created_at, dismissed_at
               FROM notifications WHERE agent = ? AND status = ?
               ORDER BY created_at DESC LIMIT ?""",
            (agent, status, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT id, agent, title, message, status, channels_sent, created_at, dismissed_at
               FROM notifications WHERE status = ?
               ORDER BY created_at DESC LIMIT ?""",
            (status, limit),
        ).fetchall()

    results = []
    for r in rows:
        channels = []
        try:
            channels = json.loads(r[5]) if r[5] else []
        except Exception:
            pass
        results.append({
            "id": r[0],
            "agent": r[1],
            "title": r[2],
            "message": r[3],
            "status": r[4],
            "channels_sent": channels,
            "created_at": r[6],
            "dismissed_at": r[7],
        })
    return results


def dismiss_notification(notification_id: str) -> dict:
    conn = db.get_db()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE notifications SET status = 'dismissed', dismissed_at = ? WHERE id = ?",
        (now, notification_id),
    )
    conn.commit()
    return {"ok": True, "id": notification_id}


def dismiss_all(agent: str | None = None) -> int:
    conn = db.get_db()
    now = datetime.now(timezone.utc).isoformat()
    if agent:
        cur = conn.execute(
            "UPDATE notifications SET status = 'dismissed', dismissed_at = ? WHERE agent = ? AND status = 'active'",
            (now, agent),
        )
    else:
        cur = conn.execute(
            "UPDATE notifications SET status = 'dismissed', dismissed_at = ? WHERE status = 'active'",
            (now,),
        )
    conn.commit()
    return cur.rowcount


def cleanup_old(retention_days: int = 30) -> int:
    conn = db.get_db()
    cur = conn.execute(
        "DELETE FROM notifications WHERE created_at < datetime('now', ?)",
        (f"-{retention_days} days",),
    )
    conn.commit()
    return cur.rowcount
