"""Shared context — SQLite database for agent-contributed entries.

Single shared database (like reminders.db) for cross-agent knowledge.
Thread safety: single connection, WAL mode, write-lock.
"""

import logging
import sqlite3
import threading
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from core.storage import download_file, upload_file

logger = logging.getLogger(__name__)

CT_TZ = ZoneInfo("America/Chicago")

DATA_DIR = Path(__file__).resolve().parent.parent.parent.parent / "data" / "shared"
DB_PATH = DATA_DIR / "shared_context.db"
GCS_KEY = "shared/shared_context.db"

_connection: sqlite3.Connection | None = None
_write_lock = threading.Lock()


def get_db() -> sqlite3.Connection:
    if _connection is None:
        raise RuntimeError("Shared context DB not initialized — call init_db() first")
    return _connection


def write_lock() -> threading.Lock:
    return _write_lock


def init_db() -> None:
    """Initialize: restore from GCS if available, create schema."""
    global _connection

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    if not DB_PATH.exists():
        download_file(DB_PATH, GCS_KEY)

    _connection = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    _connection.row_factory = sqlite3.Row
    _connection.execute("PRAGMA journal_mode=WAL")
    _connection.execute("PRAGMA busy_timeout=5000")

    _connection.executescript("""
        CREATE TABLE IF NOT EXISTS shared_entries (
            id TEXT PRIMARY KEY,
            agent_name TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT '',
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            created_by_email TEXT NOT NULL DEFAULT ''
        );

        CREATE INDEX IF NOT EXISTS idx_shared_entries_agent
            ON shared_entries(agent_name);
        CREATE INDEX IF NOT EXISTS idx_shared_entries_category
            ON shared_entries(category);
        CREATE INDEX IF NOT EXISTS idx_shared_entries_updated
            ON shared_entries(updated_at);
    """)
    logger.info("Shared context DB initialized at %s", DB_PATH)


def backup_to_gcs() -> None:
    if _connection is not None:
        try:
            _connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except Exception as e:
            logger.warning("WAL checkpoint before shared context backup failed: %s", e)
    upload_file(DB_PATH, GCS_KEY)


# ------------------------------------------------------------------
# CRUD
# ------------------------------------------------------------------

def add_entry(
    agent_name: str,
    title: str,
    content: str,
    category: str = "",
    created_by_email: str = "",
) -> dict:
    """Insert a new shared entry.  Returns the entry dict."""
    entry_id = str(uuid.uuid4())
    now = datetime.now(CT_TZ).isoformat()
    conn = get_db()
    with _write_lock:
        conn.execute(
            """INSERT INTO shared_entries
                   (id, agent_name, category, title, content, created_at, updated_at, created_by_email)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (entry_id, agent_name, category, title, content, now, now, created_by_email),
        )
        conn.commit()
    return {
        "id": entry_id,
        "agent_name": agent_name,
        "category": category,
        "title": title,
        "content": content,
        "created_at": now,
        "updated_at": now,
        "created_by_email": created_by_email,
    }


def list_entries(
    agent_name: str | None = None,
    category: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
    """List shared entries, newest first."""
    conn = get_db()
    sql = "SELECT * FROM shared_entries WHERE 1=1"
    params: list = []
    if agent_name:
        sql += " AND agent_name = ?"
        params.append(agent_name)
    if category:
        sql += " AND category = ?"
        params.append(category)
    sql += " ORDER BY updated_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def get_entry(entry_id: str) -> dict | None:
    conn = get_db()
    row = conn.execute("SELECT * FROM shared_entries WHERE id = ?", (entry_id,)).fetchone()
    return dict(row) if row else None


def update_entry(
    entry_id: str,
    title: str | None = None,
    content: str | None = None,
    category: str | None = None,
) -> dict | None:
    """Update fields on an existing entry.  Returns updated entry or None."""
    conn = get_db()
    with _write_lock:
        row = conn.execute("SELECT * FROM shared_entries WHERE id = ?", (entry_id,)).fetchone()
        if not row:
            return None
        now = datetime.now(CT_TZ).isoformat()
        new_title = title if title is not None else row["title"]
        new_content = content if content is not None else row["content"]
        new_category = category if category is not None else row["category"]
        conn.execute(
            """UPDATE shared_entries
               SET title=?, content=?, category=?, updated_at=?
               WHERE id=?""",
            (new_title, new_content, new_category, now, entry_id),
        )
        conn.commit()
    updated = get_entry(entry_id)
    return updated


def delete_entry(entry_id: str) -> bool:
    conn = get_db()
    with _write_lock:
        cursor = conn.execute("DELETE FROM shared_entries WHERE id = ?", (entry_id,))
        conn.commit()
    return cursor.rowcount > 0
