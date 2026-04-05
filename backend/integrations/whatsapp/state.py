"""Chatty — WhatsApp messaging persistent state (SQLite).

Stores phone→agent mappings, registration windows, and conversation
state for multi-turn WhatsApp context.

Adapted from CAKE OS messaging/state.py for Chatty's single-user,
multi-agent architecture (agent_slug replaces agent_email).
"""

import logging
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "whatsapp"
DB_PATH = DATA_DIR / "whatsapp.db"

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
            agent_slug TEXT NOT NULL,
            sender_name TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            UNIQUE(platform, platform_user_id)
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS whatsapp_registration_windows (
            agent_slug TEXT PRIMARY KEY,
            opened_at   TEXT NOT NULL,
            expires_at  TEXT NOT NULL,
            registered_phone TEXT
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS conversations (
            id TEXT PRIMARY KEY,
            platform TEXT NOT NULL,
            sender_id TEXT NOT NULL,
            agent_slug TEXT NOT NULL,
            chatty_conversation_id TEXT,
            last_active TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(platform, sender_id, agent_slug)
        )
    """)

    conn.commit()
    conn.close()
    logger.info("WhatsApp state DB initialized at %s", DB_PATH)


# ---------------------------------------------------------------------------
# User mappings
# ---------------------------------------------------------------------------

def get_mapping_by_sender(platform: str, platform_user_id: str) -> dict | None:
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT id, platform, platform_user_id, agent_slug, sender_name "
            "FROM user_mappings WHERE platform = ? AND platform_user_id = ?",
            (platform, platform_user_id),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def create_mapping(
    platform: str, platform_user_id: str, agent_slug: str,
    sender_name: str = "",
) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    mapping_id = str(uuid.uuid4())
    with _write_lock:
        conn = _get_conn()
        try:
            conn.execute(
                """INSERT INTO user_mappings
                   (id, platform, platform_user_id, agent_slug, sender_name, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(platform, platform_user_id)
                   DO UPDATE SET agent_slug = excluded.agent_slug,
                                 sender_name = excluded.sender_name""",
                (mapping_id, platform, platform_user_id, agent_slug, sender_name, now),
            )
            conn.commit()
        finally:
            conn.close()
    return {
        "id": mapping_id, "platform": platform,
        "platform_user_id": platform_user_id,
        "agent_slug": agent_slug,
    }


def delete_mapping(mapping_id: str) -> bool:
    with _write_lock:
        conn = _get_conn()
        try:
            cursor = conn.execute(
                "DELETE FROM user_mappings WHERE id = ?", (mapping_id,),
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# WhatsApp registration windows
# ---------------------------------------------------------------------------

def open_registration_window(agent_slug: str, minutes: int = 10) -> dict:
    """Open (or re-open) a WhatsApp registration window for an agent."""
    now = datetime.now(timezone.utc)
    expires = now + timedelta(minutes=minutes)
    now_iso = now.isoformat()
    expires_iso = expires.isoformat()

    with _write_lock:
        conn = _get_conn()
        try:
            conn.execute(
                """INSERT INTO whatsapp_registration_windows
                   (agent_slug, opened_at, expires_at, registered_phone)
                   VALUES (?, ?, ?, NULL)
                   ON CONFLICT(agent_slug)
                   DO UPDATE SET opened_at = excluded.opened_at,
                                 expires_at = excluded.expires_at,
                                 registered_phone = NULL""",
                (agent_slug, now_iso, expires_iso),
            )
            conn.commit()
        finally:
            conn.close()
    return {"agent_slug": agent_slug, "opened_at": now_iso, "expires_at": expires_iso}


def get_registration_window(agent_slug: str) -> dict | None:
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM whatsapp_registration_windows WHERE agent_slug = ?",
            (agent_slug,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_any_open_window() -> dict | None:
    """Find any currently active (not expired, not used) registration window."""
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_conn()
    try:
        row = conn.execute(
            """SELECT * FROM whatsapp_registration_windows
               WHERE registered_phone IS NULL AND expires_at > ?
               ORDER BY opened_at DESC LIMIT 1""",
            (now,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def close_registration_window(agent_slug: str, phone: str) -> None:
    """Close a registration window by recording the registered phone."""
    with _write_lock:
        conn = _get_conn()
        try:
            conn.execute(
                "UPDATE whatsapp_registration_windows SET registered_phone = ? WHERE agent_slug = ?",
                (phone, agent_slug),
            )
            conn.commit()
        finally:
            conn.close()


def is_registration_open(agent_slug: str) -> bool:
    """Check if a registration window is currently open."""
    window = get_registration_window(agent_slug)
    if not window:
        return False
    if window.get("registered_phone"):
        return False
    now = datetime.now(timezone.utc).isoformat()
    return now < window["expires_at"]


# ---------------------------------------------------------------------------
# Conversation state
# ---------------------------------------------------------------------------

def get_or_create_conversation(
    sender_id: str, agent_slug: str, platform: str,
) -> dict:
    """Look up an existing conversation or create a new one."""
    now = datetime.now(timezone.utc).isoformat()

    with _write_lock:
        conn = _get_conn()
        try:
            row = conn.execute(
                """SELECT id, chatty_conversation_id FROM conversations
                   WHERE platform = ? AND sender_id = ? AND agent_slug = ?""",
                (platform, sender_id, agent_slug),
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
                   (id, platform, sender_id, agent_slug, last_active, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (conv_id, platform, sender_id, agent_slug, now, now),
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
