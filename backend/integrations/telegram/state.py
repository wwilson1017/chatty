"""Telegram integration — Persistent state (SQLite).

Stores user mappings (Telegram user ID -> agent), registration windows,
and conversation state for multi-turn context.
"""

import logging
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "telegram"
DB_PATH = DATA_DIR / "telegram.db"

_write_lock = threading.Lock()


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    """Create tables if they don't exist."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    conn = _get_conn()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS user_mappings (
            id TEXT PRIMARY KEY,
            platform TEXT NOT NULL,
            platform_user_id TEXT NOT NULL,
            agent_id TEXT NOT NULL,
            sender_name TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            UNIQUE(platform, platform_user_id)
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS telegram_registration_windows (
            agent_id TEXT PRIMARY KEY,
            opened_at   TEXT NOT NULL,
            expires_at  TEXT NOT NULL,
            registered_user_id TEXT
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS conversations (
            id TEXT PRIMARY KEY,
            platform TEXT NOT NULL,
            sender_id TEXT NOT NULL,
            agent_id TEXT NOT NULL,
            chatty_conversation_id TEXT,
            last_active TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(platform, sender_id, agent_id)
        )
    """)

    conn.commit()
    conn.close()
    logger.info("Telegram state DB initialized at %s", DB_PATH)


# ---------------------------------------------------------------------------
# User mappings
# ---------------------------------------------------------------------------

def get_user_mappings() -> list[dict]:
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT id, platform, platform_user_id, agent_id, sender_name, created_at "
            "FROM user_mappings ORDER BY created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_mapping_by_sender(platform: str, platform_user_id: str) -> dict | None:
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT id, platform, platform_user_id, agent_id, sender_name "
            "FROM user_mappings WHERE platform = ? AND platform_user_id = ?",
            (platform, platform_user_id),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def create_mapping(
    platform: str, platform_user_id: str, agent_id: str, sender_name: str = "",
) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    mapping_id = str(uuid.uuid4())
    with _write_lock:
        conn = _get_conn()
        try:
            conn.execute(
                """INSERT INTO user_mappings
                   (id, platform, platform_user_id, agent_id, sender_name, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(platform, platform_user_id)
                   DO UPDATE SET agent_id = excluded.agent_id,
                                 sender_name = excluded.sender_name""",
                (mapping_id, platform, platform_user_id, agent_id, sender_name, now),
            )
            conn.commit()
        finally:
            conn.close()
    return {
        "id": mapping_id, "platform": platform,
        "platform_user_id": platform_user_id,
        "agent_id": agent_id, "sender_name": sender_name,
    }


def delete_mapping(mapping_id: str) -> bool:
    with _write_lock:
        conn = _get_conn()
        try:
            cursor = conn.execute(
                "DELETE FROM user_mappings WHERE id = ?", (mapping_id,),
            )
            conn.commit()
            deleted = cursor.rowcount > 0
        finally:
            conn.close()
    return deleted


# ---------------------------------------------------------------------------
# Conversation state
# ---------------------------------------------------------------------------

def get_or_create_conversation(
    sender_id: str, agent_id: str, platform: str = "telegram",
) -> dict:
    """Look up an existing conversation or create a new one."""
    now = datetime.now(timezone.utc).isoformat()

    with _write_lock:
        conn = _get_conn()
        try:
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
        finally:
            conn.close()


def set_chatty_conversation_id(conv_id: str, chatty_conversation_id: str) -> None:
    with _write_lock:
        conn = _get_conn()
        try:
            conn.execute(
                "UPDATE conversations SET chatty_conversation_id = ? WHERE id = ?",
                (chatty_conversation_id, conv_id),
            )
            conn.commit()
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# Telegram registration windows
# ---------------------------------------------------------------------------

def open_registration_window(agent_id: str, minutes: int = 10) -> dict:
    """Open (or re-open) a registration window for an agent's Telegram bot."""
    now = datetime.now(timezone.utc)
    expires = now + timedelta(minutes=minutes)
    now_iso = now.isoformat()
    expires_iso = expires.isoformat()

    with _write_lock:
        conn = _get_conn()
        try:
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
        finally:
            conn.close()
    return {"agent_id": agent_id, "opened_at": now_iso, "expires_at": expires_iso}


def get_registration_window(agent_id: str) -> dict | None:
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM telegram_registration_windows WHERE agent_id = ?",
            (agent_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def close_registration_window(agent_id: str, user_id: str) -> None:
    """Close the window by recording the registered user ID."""
    with _write_lock:
        conn = _get_conn()
        try:
            conn.execute(
                "UPDATE telegram_registration_windows SET registered_user_id = ? WHERE agent_id = ?",
                (user_id, agent_id),
            )
            conn.commit()
        finally:
            conn.close()


def is_registration_open(agent_id: str) -> bool:
    """Check if a registration window is currently open (not expired, not used)."""
    window = get_registration_window(agent_id)
    if not window:
        return False
    if window.get("registered_user_id"):
        return False
    now = datetime.now(timezone.utc).isoformat()
    return now < window["expires_at"]
