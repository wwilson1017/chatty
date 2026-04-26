"""Chatty — In-app alert service.

Alerts are created by the heartbeat processor when an agent takes action.
They show as badges on the dashboard and as a banner in the chat view.
"""

import logging
import uuid
from datetime import datetime, timedelta, timezone

from core.agents.reminders import db

logger = logging.getLogger(__name__)


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def create_alert(
    agent: str,
    title: str,
    message: str,
    source: str = "heartbeat",
    source_id: str | None = None,
) -> dict:
    alert_id = str(uuid.uuid4())
    conn = db.get_db()
    with db.write_lock():
        conn.execute(
            """INSERT INTO alerts (id, agent, source, source_id, title, message)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (alert_id, agent, source, source_id, title, message[:500]),
        )
        conn.commit()
    return {"ok": True, "id": alert_id, "agent": agent}


def list_alerts(
    agent: str | None = None,
    status: str = "active",
    limit: int = 50,
) -> list[dict]:
    conn = db.get_db()
    query = "SELECT * FROM alerts WHERE 1=1"
    params: list = []

    if agent:
        query += " AND agent = ?"
        params.append(agent)
    if status:
        query += " AND status = ?"
        params.append(status)

    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)

    rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def get_alert_counts() -> dict[str, int]:
    conn = db.get_db()
    rows = conn.execute(
        "SELECT agent, COUNT(*) as cnt FROM alerts WHERE status = 'active' GROUP BY agent"
    ).fetchall()
    return {r["agent"]: r["cnt"] for r in rows}


def acknowledge_alert(alert_id: str) -> dict:
    conn = db.get_db()
    now = _now_utc()
    with db.write_lock():
        row = conn.execute("SELECT id FROM alerts WHERE id = ?", (alert_id,)).fetchone()
        if not row:
            return {"error": f"Alert {alert_id} not found"}
        conn.execute(
            "UPDATE alerts SET status = 'acknowledged', acknowledged_at = ? WHERE id = ?",
            (now, alert_id),
        )
        conn.commit()
    return {"ok": True, "id": alert_id}


def resolve_alert(alert_id: str) -> dict:
    conn = db.get_db()
    now = _now_utc()
    with db.write_lock():
        row = conn.execute("SELECT id FROM alerts WHERE id = ?", (alert_id,)).fetchone()
        if not row:
            return {"error": f"Alert {alert_id} not found"}
        conn.execute(
            "UPDATE alerts SET status = 'resolved', resolved_at = ? WHERE id = ?",
            (now, alert_id),
        )
        conn.commit()
    return {"ok": True, "id": alert_id}


def get_active_alerts_text(agent: str, max_alerts: int = 5) -> str:
    alerts = list_alerts(agent=agent, status="active", limit=max_alerts)
    if not alerts:
        return ""
    lines = []
    for a in alerts:
        lines.append(f"- **{a['title']}** ({a['created_at']}): {a['message']}")
    return "\n".join(lines)


def cleanup_old(retention_days: int = 30) -> int:
    conn = db.get_db()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).strftime(
        "%Y-%m-%dT%H:%M:%S"
    )
    with db.write_lock():
        cursor = conn.execute(
            "DELETE FROM alerts WHERE status = 'resolved' AND resolved_at < ?",
            (cutoff,),
        )
        conn.commit()
        deleted = cursor.rowcount
    if deleted:
        logger.info("Cleaned up %d old resolved alerts", deleted)
    return deleted
