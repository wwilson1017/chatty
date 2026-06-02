"""Chatty -- Event log database (data/events.db).

General-purpose event log with category + event_type for filtering.
First tenant: security events. Schema supports future expansion to
integration events, system events, etc.
"""

import json
import logging
import sqlite3
import threading
import uuid
from pathlib import Path

from core.storage import safe_init_sqlite

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
DB_PATH = DATA_DIR / "events.db"
GCS_KEY = "events.db"

_connection: sqlite3.Connection | None = None
_write_lock = threading.Lock()


def get_db() -> sqlite3.Connection:
    if _connection is None:
        raise RuntimeError("Events DB not initialized -- call init_db() first")
    return _connection


def write_lock() -> threading.Lock:
    return _write_lock


def _setup_connection() -> None:
    global _connection
    _connection = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    _connection.row_factory = sqlite3.Row
    _connection.execute("PRAGMA journal_mode=WAL")
    _connection.execute("PRAGMA foreign_keys=ON")
    _connection.execute("PRAGMA busy_timeout=5000")
    _connection.execute("PRAGMA synchronous=FULL")

    _connection.executescript("""
        CREATE TABLE IF NOT EXISTS event_log (
            id TEXT PRIMARY KEY,
            timestamp TEXT NOT NULL DEFAULT (datetime('now')),
            category TEXT NOT NULL,
            event_type TEXT NOT NULL,
            severity TEXT NOT NULL DEFAULT 'info',
            agent_slug TEXT,
            source TEXT,
            summary TEXT NOT NULL,
            details TEXT,
            acknowledged INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_events_category
            ON event_log(category, timestamp DESC);
        CREATE INDEX IF NOT EXISTS idx_events_agent
            ON event_log(agent_slug, timestamp DESC);
        CREATE INDEX IF NOT EXISTS idx_events_severity
            ON event_log(severity, timestamp DESC);
    """)


def init_db() -> dict:
    return safe_init_sqlite(DB_PATH, GCS_KEY, init_fn=_setup_connection)


def close_db() -> None:
    global _connection
    if _connection:
        _connection.close()
        _connection = None


def log_event(
    category: str,
    event_type: str,
    summary: str,
    *,
    severity: str = "info",
    agent_slug: str | None = None,
    source: str | None = None,
    details: dict | str | None = None,
) -> str:
    event_id = str(uuid.uuid4())
    details_str = json.dumps(details) if isinstance(details, dict) else details
    conn = get_db()
    with _write_lock:
        conn.execute(
            """INSERT INTO event_log
               (id, category, event_type, severity, agent_slug, source, summary, details)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (event_id, category, event_type, severity, agent_slug, source,
             summary[:500], details_str),
        )
        conn.commit()
    return event_id


def query_events(
    *,
    category: str | None = None,
    agent_slug: str | None = None,
    severity: str | None = None,
    limit: int = 100,
    offset: int = 0,
    since: str | None = None,
) -> list[dict]:
    conn = get_db()
    clauses: list[str] = []
    params: list = []
    if category:
        clauses.append("category = ?")
        params.append(category)
    if agent_slug:
        clauses.append("agent_slug = ?")
        params.append(agent_slug)
    if severity:
        clauses.append("severity = ?")
        params.append(severity)
    if since:
        clauses.append("timestamp >= ?")
        params.append(since)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.extend([limit, offset])
    rows = conn.execute(
        f"SELECT * FROM event_log {where} ORDER BY timestamp DESC LIMIT ? OFFSET ?",
        params,
    ).fetchall()
    def _row_to_dict(r):
        d = dict(r)
        d["acknowledged"] = bool(d.get("acknowledged", 0))
        return d
    return [_row_to_dict(r) for r in rows]


def get_event_counts(category: str | None = None) -> dict:
    conn = get_db()
    if category:
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM event_log WHERE category = ? AND acknowledged = 0",
            (category,),
        ).fetchone()
        return {category: row["cnt"]}
    rows = conn.execute(
        "SELECT category, COUNT(*) as cnt FROM event_log WHERE acknowledged = 0 GROUP BY category"
    ).fetchall()
    return {r["category"]: r["cnt"] for r in rows}


def acknowledge_event(event_id: str) -> None:
    conn = get_db()
    with _write_lock:
        conn.execute(
            "UPDATE event_log SET acknowledged = 1 WHERE id = ?", (event_id,)
        )
        conn.commit()


def purge_old_events(retention_days: int) -> int:
    conn = get_db()
    with _write_lock:
        cursor = conn.execute(
            "DELETE FROM event_log WHERE timestamp < datetime('now', ?)",
            (f"-{retention_days} days",),
        )
        conn.commit()
        return cursor.rowcount
