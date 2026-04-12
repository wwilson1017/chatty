"""Context usage tracker — records which knowledge files agents interact with.

Signals are used by the dreaming scorer to determine file value and
prioritize context loading order.
"""

import logging
from datetime import datetime, timezone, timedelta

from core.agents.reminders import db

logger = logging.getLogger(__name__)


def record_context_event(
    agent: str,
    filename: str,
    event_type: str,
    source: str = "chat",
    conversation_id: str | None = None,
) -> None:
    """Record a context usage event. Fire-and-forget — never raises."""
    try:
        conn = db.get_db()
        with db.write_lock():
            conn.execute(
                """INSERT INTO context_usage (agent, filename, event_type, source, conversation_id)
                   VALUES (?, ?, ?, ?, ?)""",
                (agent, filename, event_type, source, conversation_id),
            )
            conn.commit()
    except Exception as e:
        logger.debug("Failed to record context event: %s", e)


def record_load_events(agent: str, loaded: list[str], truncated: list[str], source: str = "chat") -> None:
    """Batch-record load/truncated events for files in a single prompt build."""
    try:
        conn = db.get_db()
        with db.write_lock():
            for f in loaded:
                conn.execute(
                    "INSERT INTO context_usage (agent, filename, event_type, source) VALUES (?, ?, 'loaded', ?)",
                    (agent, f, source),
                )
            for f in truncated:
                conn.execute(
                    "INSERT INTO context_usage (agent, filename, event_type, source) VALUES (?, ?, 'truncated', ?)",
                    (agent, f, source),
                )
            conn.commit()
    except Exception as e:
        logger.debug("Failed to record load events: %s", e)


def get_file_scores(agent: str, days: int = 30) -> list[dict]:
    """Aggregate context usage into per-file event counts for the scorer."""
    conn = db.get_db()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")
    rows = conn.execute(
        """SELECT filename, event_type, COUNT(*) as cnt
           FROM context_usage
           WHERE agent = ? AND created_at >= ?
           GROUP BY filename, event_type
           ORDER BY filename""",
        (agent, cutoff),
    ).fetchall()

    # Pivot into per-file dicts
    files: dict[str, dict] = {}
    for row in rows:
        fname = row["filename"]
        if fname not in files:
            files[fname] = {"filename": fname, "write": 0, "append": 0, "loaded": 0, "truncated": 0, "mentioned_in_response": 0, "delete": 0}
        files[fname][row["event_type"]] = row["cnt"]

    return list(files.values())


def get_recent_events(agent: str, limit: int = 50) -> list[dict]:
    """Return recent context usage events for an agent."""
    conn = db.get_db()
    rows = conn.execute(
        "SELECT * FROM context_usage WHERE agent = ? ORDER BY created_at DESC LIMIT ?",
        (agent, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def cleanup_old(retention_days: int = 90) -> int:
    """Delete context usage records older than retention period."""
    conn = db.get_db()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).strftime("%Y-%m-%dT%H:%M:%S")
    with db.write_lock():
        cursor = conn.execute("DELETE FROM context_usage WHERE created_at < ?", (cutoff,))
        conn.commit()
        return cursor.rowcount
