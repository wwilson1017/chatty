"""Chatty — Reminder + Scheduled Actions SQLite database.

Single shared database for all agents. WAL mode for concurrent reads.
All writes go through _write_lock.
"""

import logging
import sqlite3
import threading
from pathlib import Path

from core.storage import safe_init_sqlite

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent.parent.parent / "data" / "reminders"
DB_PATH = DATA_DIR / "reminders.db"
GCS_KEY = "reminders/reminders.db"

_connection: sqlite3.Connection | None = None
_write_lock = threading.Lock()


def get_db() -> sqlite3.Connection:
    if _connection is None:
        raise RuntimeError("Reminders DB not initialized — call init_db() first")
    return _connection


def write_lock() -> threading.Lock:
    return _write_lock


def _setup_connection() -> None:
    """Open connection, set PRAGMAs, create schema."""
    global _connection
    _connection = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    _connection.row_factory = sqlite3.Row
    _connection.execute("PRAGMA journal_mode=WAL")
    _connection.execute("PRAGMA foreign_keys=ON")
    _connection.execute("PRAGMA busy_timeout=5000")

    _connection.executescript("""
        CREATE TABLE IF NOT EXISTS reminders (
            id TEXT PRIMARY KEY,
            agent TEXT NOT NULL,
            created_by_email TEXT NOT NULL DEFAULT 'user',
            reminder_type TEXT NOT NULL DEFAULT 'self' CHECK(reminder_type IN ('self', 'user')),
            target_email TEXT,
            message TEXT NOT NULL,
            context TEXT,
            due_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'fired', 'cancelled')),
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            fired_at TEXT,
            result TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_reminders_due ON reminders(status, due_at);

        CREATE TABLE IF NOT EXISTS scheduled_actions (
            id TEXT PRIMARY KEY,
            agent TEXT NOT NULL,
            created_by_email TEXT NOT NULL DEFAULT 'user',
            action_type TEXT NOT NULL CHECK(action_type IN ('heartbeat', 'cron')),
            name TEXT NOT NULL DEFAULT '',
            description TEXT NOT NULL DEFAULT '',
            schedule_type TEXT NOT NULL CHECK(schedule_type IN ('cron', 'interval', 'once')),
            cron_expression TEXT,
            interval_minutes INTEGER,
            run_at TEXT,
            active_hours_start TEXT DEFAULT '06:00',
            active_hours_end TEXT DEFAULT '20:00',
            active_hours_tz TEXT NOT NULL DEFAULT 'America/Chicago',
            prompt TEXT NOT NULL DEFAULT '',
            model_override TEXT,
            max_tool_iterations INTEGER NOT NULL DEFAULT 5,
            enabled INTEGER NOT NULL DEFAULT 1,
            next_run TEXT,
            last_run TEXT,
            last_status TEXT,
            last_result TEXT,
            last_duration_ms INTEGER,
            last_input_tokens INTEGER DEFAULT 0,
            last_output_tokens INTEGER DEFAULT 0,
            consecutive_errors INTEGER NOT NULL DEFAULT 0,
            total_runs INTEGER NOT NULL DEFAULT 0,
            total_input_tokens INTEGER NOT NULL DEFAULT 0,
            total_output_tokens INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_sa_next ON scheduled_actions(enabled, next_run);
        CREATE INDEX IF NOT EXISTS idx_sa_agent ON scheduled_actions(agent);

        CREATE TABLE IF NOT EXISTS context_usage (
            agent TEXT NOT NULL,
            filename TEXT NOT NULL,
            event_type TEXT NOT NULL,
            source TEXT DEFAULT 'chat',
            conversation_id TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_ctx_usage ON context_usage(agent, created_at);

        CREATE TABLE IF NOT EXISTS dreaming_runs (
            agent TEXT NOT NULL,
            files_scored INTEGER,
            files_archived INTEGER,
            load_order_changed INTEGER,
            details TEXT,
            duration_ms INTEGER,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_dreaming_agent ON dreaming_runs(agent, created_at);

        CREATE TABLE IF NOT EXISTS execution_history (
            id TEXT PRIMARY KEY,
            action_id TEXT NOT NULL,
            agent TEXT NOT NULL,
            action_type TEXT NOT NULL,
            started_at TEXT NOT NULL,
            completed_at TEXT,
            status TEXT NOT NULL DEFAULT 'running',
            result_summary TEXT,
            result_full TEXT,
            tool_calls TEXT,
            model_used TEXT,
            input_tokens INTEGER DEFAULT 0,
            output_tokens INTEGER DEFAULT 0,
            duration_ms INTEGER DEFAULT 0,
            notification_sent INTEGER DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_eh_action ON execution_history(action_id, started_at DESC);
        CREATE INDEX IF NOT EXISTS idx_eh_agent ON execution_history(agent, started_at DESC);

        CREATE TABLE IF NOT EXISTS alerts (
            id TEXT PRIMARY KEY,
            agent TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'heartbeat',
            source_id TEXT,
            title TEXT NOT NULL,
            message TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active'
                CHECK(status IN ('active', 'acknowledged', 'resolved')),
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            acknowledged_at TEXT,
            resolved_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_alerts_agent ON alerts(agent, status);
        CREATE INDEX IF NOT EXISTS idx_alerts_status ON alerts(status, created_at DESC);
    """)

    # Migration: add columns to scheduled_actions if missing
    cols = {r[1] for r in _connection.execute("PRAGMA table_info(scheduled_actions)").fetchall()}
    if "triage_enabled" not in cols:
        _connection.execute("ALTER TABLE scheduled_actions ADD COLUMN triage_enabled INTEGER NOT NULL DEFAULT 1")
    if "always_on" not in cols:
        _connection.execute("ALTER TABLE scheduled_actions ADD COLUMN always_on INTEGER NOT NULL DEFAULT 0")
    if "notify_on_action" not in cols:
        _connection.execute("ALTER TABLE scheduled_actions ADD COLUMN notify_on_action INTEGER NOT NULL DEFAULT 0")
    if "lease_id" not in cols:
        _connection.execute("ALTER TABLE scheduled_actions ADD COLUMN lease_id TEXT")
    if "leased_until" not in cols:
        _connection.execute("ALTER TABLE scheduled_actions ADD COLUMN leased_until TEXT")
    _connection.execute("CREATE INDEX IF NOT EXISTS idx_sa_lease ON scheduled_actions(lease_id, leased_until)")
    _connection.commit()

    logger.info("Reminders DB initialized at %s", DB_PATH)


def init_db() -> dict:
    """Initialize with integrity check and GCS restore."""
    return safe_init_sqlite(DB_PATH, GCS_KEY, init_fn=_setup_connection)


def close_db() -> None:
    """Close the reminders DB connection (for backup/restore)."""
    global _connection
    if _connection:
        _connection.close()
        _connection = None
