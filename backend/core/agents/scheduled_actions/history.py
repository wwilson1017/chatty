"""Chatty — Execution history for scheduled actions.

Records every heartbeat and cron execution with tool calls, model,
tokens, and duration. Provides paginated queries for the activity feed.
"""

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone

from core.agents.reminders import db

logger = logging.getLogger(__name__)


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def record_start(action_id: str, agent: str, action_type: str) -> str:
    execution_id = str(uuid.uuid4())
    conn = db.get_db()
    with db.write_lock():
        conn.execute(
            """INSERT INTO execution_history
               (id, action_id, agent, action_type, started_at, status)
               VALUES (?, ?, ?, ?, ?, 'running')""",
            (execution_id, action_id, agent, action_type, _now_utc()),
        )
        conn.commit()
    return execution_id


def record_complete(
    execution_id: str,
    *,
    status: str,
    result_summary: str = "",
    result_full: str = "",
    tool_calls: list | None = None,
    model_used: str = "",
    input_tokens: int = 0,
    output_tokens: int = 0,
    duration_ms: int = 0,
    notification_sent: bool = False,
) -> None:
    conn = db.get_db()
    tool_calls_json = json.dumps(tool_calls)[:10240] if tool_calls else None
    with db.write_lock():
        conn.execute(
            """UPDATE execution_history SET
               completed_at = ?, status = ?, result_summary = ?,
               result_full = ?, tool_calls = ?, model_used = ?,
               input_tokens = ?, output_tokens = ?, duration_ms = ?,
               notification_sent = ?
               WHERE id = ?""",
            (
                _now_utc(), status, result_summary[:500],
                result_full[:5000], tool_calls_json, model_used,
                input_tokens, output_tokens, duration_ms,
                1 if notification_sent else 0,
                execution_id,
            ),
        )
        conn.commit()


def get_history(
    agent: str | None = None,
    action_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
    status_filter: str | None = None,
    event_type: str | None = None,
    since: str | None = None,
) -> list[dict]:
    conn = db.get_db()
    query = "SELECT * FROM execution_history WHERE 1=1"
    params: list = []

    if agent:
        query += " AND agent = ?"
        params.append(agent)
    if action_id:
        query += " AND action_id = ?"
        params.append(action_id)
    if event_type:
        if event_type == "scheduled_action":
            query += " AND (event_type = 'scheduled_action' OR event_type IS NULL)"
        else:
            query += " AND event_type = ?"
            params.append(event_type)
    if since:
        query += " AND started_at >= ?"
        params.append(since)
    if status_filter:
        if status_filter == "action_taken":
            query += " AND status NOT IN ('ok', 'skipped', 'running', 'lease_lost')"
        else:
            query += " AND status = ?"
            params.append(status_filter)

    query += " ORDER BY started_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    rows = conn.execute(query, params).fetchall()
    results = []
    for row in rows:
        d = dict(row)
        if d.get("tool_calls"):
            try:
                d["tool_calls"] = json.loads(d["tool_calls"])
            except (json.JSONDecodeError, TypeError):
                pass
        results.append(d)
    return results


def get_execution(execution_id: str) -> dict | None:
    conn = db.get_db()
    row = conn.execute(
        "SELECT * FROM execution_history WHERE id = ?", (execution_id,)
    ).fetchone()
    if not row:
        return None
    d = dict(row)
    if d.get("tool_calls"):
        try:
            d["tool_calls"] = json.loads(d["tool_calls"])
        except (json.JSONDecodeError, TypeError):
            pass
    return d


def get_recent_errors(agent: str, action_id: str | None = None, limit: int = 3) -> list[dict]:
    conn = db.get_db()
    if action_id:
        rows = conn.execute(
            """SELECT started_at, status, result_summary, action_type
               FROM execution_history
               WHERE agent = ? AND action_id = ? AND status = 'error'
               ORDER BY started_at DESC LIMIT ?""",
            (agent, action_id, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT started_at, status, result_summary, action_type
               FROM execution_history
               WHERE agent = ? AND status = 'error'
               ORDER BY started_at DESC LIMIT ?""",
            (agent, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def cleanup_old(retention_days: int = 7) -> int:
    conn = db.get_db()
    now = datetime.now(timezone.utc)
    sa_cutoff = (now - timedelta(days=retention_days)).strftime("%Y-%m-%dT%H:%M:%S")
    chat_cutoff = (now - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%S")
    with db.write_lock():
        c1 = conn.execute(
            "DELETE FROM execution_history WHERE (event_type = 'scheduled_action' OR event_type IS NULL) AND started_at < ?",
            (sa_cutoff,),
        )
        c2 = conn.execute(
            "DELETE FROM execution_history WHERE event_type = 'chat' AND started_at < ?",
            (chat_cutoff,),
        )
        conn.commit()
        deleted = c1.rowcount + c2.rowcount
    if deleted:
        logger.info("Cleaned up %d old execution history records", deleted)
    return deleted
