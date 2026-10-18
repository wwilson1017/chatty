"""
Chatty — paired terminals store (SQLite).

`pairings` holds the short-lived device-code requests a `chatty login` makes;
`devices` holds the long-lived per-terminal tokens they turn into. Only
sha256 hashes of device codes and tokens are stored.
"""

import logging
import sqlite3
import threading
from pathlib import Path

from core.storage import safe_init_sqlite

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "terminal"
DB_PATH = DATA_DIR / "terminal.db"
GCS_KEY = "terminal/terminal.db"

_connection: sqlite3.Connection | None = None
# Guards every use of the one shared connection, reads too.
_write_lock = threading.RLock()
_init_lock = threading.Lock()


def get_db() -> sqlite3.Connection:
    """Return the connection, lazily initializing if needed."""
    if _connection is None:
        with _init_lock:
            if _connection is None:
                init_db()
    assert _connection is not None
    return _connection


def _setup_connection() -> None:
    global _connection
    _connection = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    _connection.row_factory = sqlite3.Row
    _connection.execute("PRAGMA journal_mode=WAL")
    _connection.execute("PRAGMA busy_timeout=5000")
    _connection.executescript("""
        CREATE TABLE IF NOT EXISTS pairings (
            user_code        TEXT PRIMARY KEY,
            device_code_hash TEXT NOT NULL UNIQUE,
            host             TEXT NOT NULL DEFAULT '',
            platform         TEXT NOT NULL DEFAULT '',
            ip               TEXT NOT NULL DEFAULT '',
            label            TEXT NOT NULL DEFAULT '',
            created_at       TEXT NOT NULL,
            expires_at       TEXT NOT NULL,
            status           TEXT NOT NULL DEFAULT 'pending'
                             CHECK(status IN ('pending','approved','denied','claimed'))
        );
        CREATE TABLE IF NOT EXISTS devices (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            label        TEXT NOT NULL DEFAULT '',
            host         TEXT NOT NULL DEFAULT '',
            platform     TEXT NOT NULL DEFAULT '',
            token_hash   TEXT NOT NULL UNIQUE,
            created_at   TEXT NOT NULL,
            last_seen_at TEXT
        );
    """)
    _connection.commit()
    logger.info("Terminal pairing DB initialized at %s", DB_PATH)


def init_db() -> dict:
    """Initialize with integrity check + GCS download-on-missing."""
    return safe_init_sqlite(DB_PATH, GCS_KEY, init_fn=_setup_connection)


def close_db() -> None:
    """Close the connection (for backup/restore)."""
    global _connection
    if _connection:
        _connection.close()
        _connection = None


def write_lock() -> threading.RLock:
    return _write_lock
