"""
Chatty — CRM Lite SQLite database.

Lightweight contact/deal/task/activity tracker for small businesses.
Schema: contacts, deals, tasks, activity_log.
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


def _apply_migrations(conn: sqlite3.Connection) -> None:
    """Add columns introduced after the initial schema.

    SQLite doesn't support ALTER TABLE ... ADD COLUMN IF NOT EXISTS,
    so we wrap each in try/except (duplicate column raises OperationalError).
    """
    migrations = [
        # contacts — new columns
        "ALTER TABLE contacts ADD COLUMN title TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE contacts ADD COLUMN source TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE contacts ADD COLUMN status TEXT NOT NULL DEFAULT 'active'",
        "ALTER TABLE contacts ADD COLUMN tags TEXT NOT NULL DEFAULT ''",
        # deals — new columns
        "ALTER TABLE deals ADD COLUMN expected_close_date TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE deals ADD COLUMN probability INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE deals ADD COLUMN currency TEXT NOT NULL DEFAULT 'USD'",
    ]
    for sql in migrations:
        try:
            conn.execute(sql)
        except sqlite3.OperationalError:
            pass  # Column already exists
    conn.commit()


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
            title       TEXT NOT NULL DEFAULT '',
            source      TEXT NOT NULL DEFAULT '',
            status      TEXT NOT NULL DEFAULT 'active',
            tags        TEXT NOT NULL DEFAULT '',
            notes       TEXT NOT NULL DEFAULT '',
            created_at  TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_contacts_name ON contacts(name);
        CREATE INDEX IF NOT EXISTS idx_contacts_company ON contacts(company);
        CREATE INDEX IF NOT EXISTS idx_contacts_status ON contacts(status);
        CREATE INDEX IF NOT EXISTS idx_contacts_email ON contacts(email);

        CREATE TABLE IF NOT EXISTS deals (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            contact_id          INTEGER REFERENCES contacts(id) ON DELETE SET NULL,
            title               TEXT NOT NULL,
            stage               TEXT NOT NULL DEFAULT 'lead',
            value               REAL NOT NULL DEFAULT 0,
            expected_close_date TEXT NOT NULL DEFAULT '',
            probability         INTEGER NOT NULL DEFAULT 0,
            currency            TEXT NOT NULL DEFAULT 'USD',
            notes               TEXT NOT NULL DEFAULT '',
            created_at          TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at          TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_deals_stage ON deals(stage);
        CREATE INDEX IF NOT EXISTS idx_deals_contact ON deals(contact_id);
        CREATE INDEX IF NOT EXISTS idx_deals_expected_close ON deals(expected_close_date);

        CREATE TABLE IF NOT EXISTS tasks (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            contact_id  INTEGER REFERENCES contacts(id) ON DELETE SET NULL,
            deal_id     INTEGER REFERENCES deals(id) ON DELETE SET NULL,
            title       TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            due_date    TEXT NOT NULL DEFAULT '',
            completed   INTEGER NOT NULL DEFAULT 0,
            priority    TEXT NOT NULL DEFAULT 'medium',
            created_at  TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_tasks_due ON tasks(due_date);
        CREATE INDEX IF NOT EXISTS idx_tasks_contact ON tasks(contact_id);
        CREATE INDEX IF NOT EXISTS idx_tasks_completed ON tasks(completed);

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

    # Apply migrations for databases created before the schema expansion
    _apply_migrations(_connection)

    logger.info("CRM Lite DB initialized at %s", DB_PATH)


def close_db() -> None:
    """Close the CRM Lite DB connection (for backup/restore)."""
    global _connection
    if _connection:
        _connection.close()
        _connection = None


def write_lock() -> threading.Lock:
    return _write_lock
