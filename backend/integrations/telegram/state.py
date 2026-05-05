"""Telegram integration — Persistent state (SQLite).

Stores user mappings (Telegram user ID -> agent), registration windows,
and conversation state for multi-turn context.
"""

import logging
import secrets
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from core.storage import safe_init_sqlite

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "telegram"
DB_PATH = DATA_DIR / "telegram.db"
GCS_KEY = "telegram/telegram.db"

_connection: sqlite3.Connection | None = None
_write_lock = threading.Lock()


def _get_db() -> sqlite3.Connection:
    if _connection is None:
        raise RuntimeError("Telegram state DB not initialized — call init_db() first")
    return _connection


def _migrate_user_mappings_v2(conn: sqlite3.Connection) -> None:
    """Migrate user_mappings from UNIQUE(platform, platform_user_id) to
    UNIQUE(platform, platform_user_id, agent_id) so one Telegram user
    can be mapped to multiple agents simultaneously."""
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='user_mappings'"
    ).fetchone()
    if not row:
        return
    create_sql = row[0] or ""
    if "platform_user_id, agent_id)" in create_sql:
        return

    logger.info("Migrating user_mappings to support multi-agent per user...")
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("""
            CREATE TABLE user_mappings_v2 (
                id TEXT PRIMARY KEY,
                platform TEXT NOT NULL,
                platform_user_id TEXT NOT NULL,
                agent_id TEXT NOT NULL,
                sender_name TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                UNIQUE(platform, platform_user_id, agent_id)
            )
        """)
        conn.execute("""
            INSERT OR IGNORE INTO user_mappings_v2
            SELECT id, platform, platform_user_id, agent_id, sender_name, created_at
            FROM user_mappings
        """)
        conn.execute("DROP TABLE user_mappings")
        conn.execute("ALTER TABLE user_mappings_v2 RENAME TO user_mappings")
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    logger.info("user_mappings migration complete")


def _setup_connection() -> None:
    """Open connection, set PRAGMAs, create schema."""
    global _connection
    _connection = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    _connection.row_factory = sqlite3.Row
    _connection.execute("PRAGMA journal_mode=WAL")
    _connection.execute("PRAGMA foreign_keys=ON")
    _connection.execute("PRAGMA busy_timeout=5000")

    _migrate_user_mappings_v2(_connection)

    _connection.executescript("""
        CREATE TABLE IF NOT EXISTS user_mappings (
            id TEXT PRIMARY KEY,
            platform TEXT NOT NULL,
            platform_user_id TEXT NOT NULL,
            agent_id TEXT NOT NULL,
            sender_name TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            UNIQUE(platform, platform_user_id, agent_id)
        );

        CREATE TABLE IF NOT EXISTS telegram_registration_windows (
            agent_id TEXT PRIMARY KEY,
            opened_at   TEXT NOT NULL,
            expires_at  TEXT NOT NULL,
            registered_user_id TEXT
        );

        CREATE TABLE IF NOT EXISTS webhook_secrets (
            agent_id TEXT PRIMARY KEY,
            secret TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS conversations (
            id TEXT PRIMARY KEY,
            platform TEXT NOT NULL,
            sender_id TEXT NOT NULL,
            agent_id TEXT NOT NULL,
            chatty_conversation_id TEXT,
            last_active TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(platform, sender_id, agent_id)
        );
    """)
    logger.info("Telegram state DB initialized at %s", DB_PATH)


def init_db() -> dict:
    """Initialize with integrity check."""
    return safe_init_sqlite(DB_PATH, GCS_KEY, init_fn=_setup_connection)


def close_db() -> None:
    """Close the connection (for backup/restore)."""
    global _connection
    if _connection:
        _connection.close()
        _connection = None


# ---------------------------------------------------------------------------
# User mappings
# ---------------------------------------------------------------------------

def get_user_mappings() -> list[dict]:
    conn = _get_db()
    rows = conn.execute(
        "SELECT id, platform, platform_user_id, agent_id, sender_name, created_at "
        "FROM user_mappings ORDER BY created_at DESC"
    ).fetchall()
    return [dict(r) for r in rows]


def get_mapping_by_sender(platform: str, platform_user_id: str, agent_id: str) -> dict | None:
    conn = _get_db()
    row = conn.execute(
        "SELECT id, platform, platform_user_id, agent_id, sender_name "
        "FROM user_mappings WHERE platform = ? AND platform_user_id = ? AND agent_id = ?",
        (platform, platform_user_id, agent_id),
    ).fetchone()
    return dict(row) if row else None


def create_mapping(
    platform: str, platform_user_id: str, agent_id: str, sender_name: str = "",
) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    mapping_id = str(uuid.uuid4())
    conn = _get_db()
    with _write_lock:
        conn.execute(
            """INSERT INTO user_mappings
               (id, platform, platform_user_id, agent_id, sender_name, created_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(platform, platform_user_id, agent_id)
               DO UPDATE SET sender_name = excluded.sender_name""",
            (mapping_id, platform, platform_user_id, agent_id, sender_name, now),
        )
        conn.commit()
        row = conn.execute(
            "SELECT id FROM user_mappings WHERE platform = ? AND platform_user_id = ? AND agent_id = ?",
            (platform, platform_user_id, agent_id),
        ).fetchone()
        actual_id = row["id"] if row else mapping_id
    return {
        "id": actual_id, "platform": platform,
        "platform_user_id": platform_user_id,
        "agent_id": agent_id, "sender_name": sender_name,
    }


def delete_mapping(mapping_id: str) -> bool:
    conn = _get_db()
    with _write_lock:
        cursor = conn.execute(
            "DELETE FROM user_mappings WHERE id = ?", (mapping_id,),
        )
        conn.commit()
    return cursor.rowcount > 0


# ---------------------------------------------------------------------------
# Conversation state
# ---------------------------------------------------------------------------

def get_or_create_conversation(
    sender_id: str, agent_id: str, platform: str = "telegram",
) -> dict:
    """Look up an existing conversation or create a new one."""
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_db()

    with _write_lock:
        row = conn.execute(
            """SELECT id, chatty_conversation_id FROM conversations
               WHERE platform = ? AND sender_id = ? AND agent_id = ?""",
            (platform, sender_id, agent_id),
        ).fetchone()

        if row:
            conn.execute(
                "UPDATE conversations SET last_active = ? WHERE id = ?",
                (now, row["id"]),
            )
            conn.commit()
            return {
                "id": row["id"],
                "chatty_conversation_id": row["chatty_conversation_id"],
                "is_new": False,
            }

        conv_id = str(uuid.uuid4())
        conn.execute(
            """INSERT INTO conversations
               (id, platform, sender_id, agent_id, last_active, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (conv_id, platform, sender_id, agent_id, now, now),
        )
        conn.commit()
        return {"id": conv_id, "chatty_conversation_id": None, "is_new": True}


def set_chatty_conversation_id(conv_id: str, chatty_conversation_id: str) -> None:
    conn = _get_db()
    with _write_lock:
        conn.execute(
            "UPDATE conversations SET chatty_conversation_id = ? WHERE id = ?",
            (chatty_conversation_id, conv_id),
        )
        conn.commit()


# ---------------------------------------------------------------------------
# Telegram registration windows
# ---------------------------------------------------------------------------

def open_registration_window(agent_id: str, minutes: int = 10) -> dict:
    """Open (or re-open) a registration window for an agent's Telegram bot."""
    now = datetime.now(timezone.utc)
    expires = now + timedelta(minutes=minutes)
    now_iso = now.isoformat()
    expires_iso = expires.isoformat()

    conn = _get_db()
    with _write_lock:
        conn.execute(
            """INSERT INTO telegram_registration_windows
               (agent_id, opened_at, expires_at, registered_user_id)
               VALUES (?, ?, ?, NULL)
               ON CONFLICT(agent_id)
               DO UPDATE SET opened_at = excluded.opened_at,
                             expires_at = excluded.expires_at,
                             registered_user_id = NULL""",
            (agent_id, now_iso, expires_iso),
        )
        conn.commit()
    return {"agent_id": agent_id, "opened_at": now_iso, "expires_at": expires_iso}


def get_registration_window(agent_id: str) -> dict | None:
    conn = _get_db()
    row = conn.execute(
        "SELECT * FROM telegram_registration_windows WHERE agent_id = ?",
        (agent_id,),
    ).fetchone()
    return dict(row) if row else None


def close_registration_window(agent_id: str, user_id: str) -> None:
    """Close the window by recording the registered user ID."""
    conn = _get_db()
    with _write_lock:
        conn.execute(
            "UPDATE telegram_registration_windows SET registered_user_id = ? WHERE agent_id = ?",
            (user_id, agent_id),
        )
        conn.commit()


def is_registration_open(agent_id: str) -> bool:
    """Check if a registration window is currently open (not expired, not used)."""
    window = get_registration_window(agent_id)
    if not window:
        return False
    if window.get("registered_user_id"):
        return False
    now = datetime.now(timezone.utc).isoformat()
    return now < window["expires_at"]


# ---------------------------------------------------------------------------
# Webhook secrets (per-agent)
# ---------------------------------------------------------------------------

def get_or_create_webhook_secret(agent_id: str) -> str:
    """Get the webhook secret for an agent, creating one if it doesn't exist."""
    conn = _get_db()
    row = conn.execute(
        "SELECT secret FROM webhook_secrets WHERE agent_id = ?", (agent_id,),
    ).fetchone()
    if row:
        return row["secret"]

    secret = secrets.token_urlsafe(32)
    with _write_lock:
        conn.execute(
            """INSERT INTO webhook_secrets (agent_id, secret) VALUES (?, ?)
               ON CONFLICT(agent_id) DO UPDATE SET secret = excluded.secret""",
            (agent_id, secret),
        )
        conn.commit()
    return secret


def get_webhook_secret(agent_id: str) -> str | None:
    """Get the webhook secret for an agent, or None if not set."""
    conn = _get_db()
    row = conn.execute(
        "SELECT secret FROM webhook_secrets WHERE agent_id = ?", (agent_id,),
    ).fetchone()
    return row["secret"] if row else None


def delete_webhook_secret(agent_id: str) -> None:
    """Delete the webhook secret for an agent."""
    conn = _get_db()
    with _write_lock:
        conn.execute("DELETE FROM webhook_secrets WHERE agent_id = ?", (agent_id,))
        conn.commit()
