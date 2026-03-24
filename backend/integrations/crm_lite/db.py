"""
Chatty — CRM Lite SQLite database.

Lightweight contact/deal/activity tracker for entrepreneurs.
Schema: contacts, deals, activity_log.
"""

import logging
import sqlite3
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "integrations"
DB_PATH = DATA_DIR / "crm_lite.db"

_connection: sqlite3.Connection | None = None
_write_lock = threading.Lock()


def _get_db() -> sqlite3.Connection:
    if _connection is None:
        raise RuntimeError("CRM Lite DB not initialized — call init_db() first")
    return _connection


def init_db() -> None:
    """Initialize the CRM Lite DB."""
    global _connection
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    _connection = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    _connection.row_factory = sqlite3.Row
    _connection.execute("PRAGMA journal_mode=WAL")
    _connection.execute("PRAGMA foreign_keys=ON")
    _connection.execute("PRAGMA busy_timeout=5000")

    _connection.executescript("""
        CREATE TABLE IF NOT EXISTS contacts (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT NOT NULL,
            email       TEXT NOT NULL DEFAULT '',
            phone       TEXT NOT NULL DEFAULT '',
            company     TEXT NOT NULL DEFAULT '',
            notes       TEXT NOT NULL DEFAULT '',
            created_at  TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_contacts_name ON contacts(name);
        CREATE INDEX IF NOT EXISTS idx_contacts_company ON contacts(company);

        CREATE TABLE IF NOT EXISTS deals (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            contact_id  INTEGER REFERENCES contacts(id) ON DELETE SET NULL,
            title       TEXT NOT NULL,
            stage       TEXT NOT NULL DEFAULT 'lead',
            value       REAL NOT NULL DEFAULT 0,
            notes       TEXT NOT NULL DEFAULT '',
            created_at  TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_deals_stage ON deals(stage);
        CREATE INDEX IF NOT EXISTS idx_deals_contact ON deals(contact_id);

        CREATE TABLE IF NOT EXISTS activity_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            contact_id  INTEGER REFERENCES contacts(id) ON DELETE SET NULL,
            deal_id     INTEGER REFERENCES deals(id) ON DELETE SET NULL,
            activity    TEXT NOT NULL,
            note        TEXT NOT NULL DEFAULT '',
            created_at  TEXT NOT NULL DEFAULT (datetime('now'))
        );
    """)
    _connection.commit()
    logger.info("CRM Lite DB initialized at %s", DB_PATH)


def write_lock() -> threading.Lock:
    return _write_lock
