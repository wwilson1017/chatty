"""
Chatty — Todo (GTD) SQLite database.

Global todo store shared by all agents, the web UI, the /capture endpoints,
and the Telegram capture intercept. One life, one list — this is a core
feature, not an integration, so it is always available.

Schema: projects, todos.
"""

import logging
import sqlite3
import threading
from pathlib import Path

from core.storage import safe_init_sqlite

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "todo"
DB_PATH = DATA_DIR / "todo.db"
GCS_KEY = "todo/todo.db"

TODO_STATUSES = (
    "inbox",
    "next_action",
    "waiting_for",
    "delegated",
    "someday_maybe",
    "done",
    "dropped",
)
PROJECT_STATUSES = ("active", "someday", "completed", "dropped")
TODO_SOURCES = ("capture_web", "telegram", "agent", "ui")

_connection: sqlite3.Connection | None = None
_write_lock = threading.Lock()
_init_lock = threading.Lock()


def get_db() -> sqlite3.Connection:
    """Return the connection, lazily initializing if needed.

    Lazy init is double-checked under a lock: the Telegram webhook thread pool,
    the CLI, and tests can all be first-touch callers.
    """
    if _connection is None:
        with _init_lock:
            if _connection is None:
                init_db()
    assert _connection is not None
    return _connection


def _setup_connection() -> None:
    """Open connection, set PRAGMAs, create schema."""
    global _connection
    _connection = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    _connection.row_factory = sqlite3.Row
    _connection.execute("PRAGMA journal_mode=WAL")
    _connection.execute("PRAGMA foreign_keys=ON")
    _connection.execute("PRAGMA busy_timeout=5000")
    _connection.execute("PRAGMA synchronous=FULL")

    _connection.executescript("""
        CREATE TABLE IF NOT EXISTS projects (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT NOT NULL COLLATE NOCASE UNIQUE,
            notes       TEXT NOT NULL DEFAULT '',
            status      TEXT NOT NULL DEFAULT 'active'
                        CHECK(status IN ('active','someday','completed','dropped')),
            created_at  TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS todos (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            title        TEXT NOT NULL,
            notes        TEXT NOT NULL DEFAULT '',
            project_id   INTEGER REFERENCES projects(id) ON DELETE SET NULL,
            context      TEXT NOT NULL DEFAULT '',
            tags         TEXT NOT NULL DEFAULT '[]',
            status       TEXT NOT NULL DEFAULT 'inbox'
                         CHECK(status IN ('inbox','next_action','waiting_for','delegated',
                                          'someday_maybe','done','dropped')),
            star         INTEGER NOT NULL DEFAULT 0,
            due_date     TEXT,
            source       TEXT NOT NULL DEFAULT 'agent',
            created_at   TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at   TEXT NOT NULL DEFAULT (datetime('now')),
            completed_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_todos_status ON todos(status);
        CREATE INDEX IF NOT EXISTS idx_todos_project ON todos(project_id);
        CREATE INDEX IF NOT EXISTS idx_todos_due ON todos(due_date);
    """)
    _connection.commit()
    logger.info("Todo DB initialized at %s", DB_PATH)


def init_db() -> dict:
    """Initialize with integrity check + GCS download-on-missing."""
    return safe_init_sqlite(DB_PATH, GCS_KEY, init_fn=_setup_connection)


def close_db() -> None:
    """Close the todo DB connection (for backup/restore)."""
    global _connection
    if _connection:
        _connection.close()
        _connection = None


def write_lock() -> threading.Lock:
    return _write_lock
