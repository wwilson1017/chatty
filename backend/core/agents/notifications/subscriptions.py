"""CRUD operations for push_subscriptions table."""

import logging
import uuid

from core.agents.reminders import db

logger = logging.getLogger(__name__)


def save_subscription(endpoint: str, p256dh: str, auth: str, user_agent: str = "") -> dict:
    conn = db.get_db()
    existing = conn.execute(
        "SELECT id FROM push_subscriptions WHERE endpoint = ?", (endpoint,)
    ).fetchone()

    if existing:
        conn.execute(
            "UPDATE push_subscriptions SET p256dh = ?, auth = ?, user_agent = ? WHERE endpoint = ?",
            (p256dh, auth, user_agent, endpoint),
        )
        conn.commit()
        return {"ok": True, "id": existing[0], "updated": True}

    sub_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO push_subscriptions (id, endpoint, p256dh, auth, user_agent) VALUES (?, ?, ?, ?, ?)",
        (sub_id, endpoint, p256dh, auth, user_agent),
    )
    conn.commit()
    return {"ok": True, "id": sub_id, "updated": False}


def remove_subscription(endpoint: str) -> dict:
    conn = db.get_db()
    cur = conn.execute("DELETE FROM push_subscriptions WHERE endpoint = ?", (endpoint,))
    conn.commit()
    return {"ok": True, "removed": cur.rowcount > 0}


def list_subscriptions() -> list[dict]:
    conn = db.get_db()
    rows = conn.execute(
        "SELECT id, endpoint, p256dh, auth, user_agent, created_at FROM push_subscriptions"
    ).fetchall()
    return [
        {"id": r[0], "endpoint": r[1], "p256dh": r[2], "auth": r[3], "user_agent": r[4], "created_at": r[5]}
        for r in rows
    ]
