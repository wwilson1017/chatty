"""
Chatty — Multi-agent registry database.

SQLite database tracking all agents. Each agent has its own context
directory and chat history database under data/agents/{slug}/.

Single-user: no email primary key. ID is a UUID.
"""

import logging
import re
import sqlite3
import threading
import uuid
from pathlib import Path

from core.storage import download_file, upload_file

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DB_PATH = DATA_DIR / "agents.db"
GCS_KEY = "agents.db"

_connection: sqlite3.Connection | None = None
_write_lock = threading.Lock()


def _get_db() -> sqlite3.Connection:
    if _connection is None:
        raise RuntimeError("Agent registry DB not initialized — call init_db() first")
    return _connection


def init_db() -> None:
    """Initialize the registry DB: restore from GCS if available, create schema."""
    global _connection
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    if not DB_PATH.exists():
        download_file(DB_PATH, GCS_KEY)

    _connection = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    _connection.row_factory = sqlite3.Row
    _connection.execute("PRAGMA journal_mode=WAL")
    _connection.execute("PRAGMA foreign_keys=ON")
    _connection.execute("PRAGMA busy_timeout=5000")

    _connection.executescript("""
        CREATE TABLE IF NOT EXISTS agents (
            id                  TEXT PRIMARY KEY,
            slug                TEXT NOT NULL UNIQUE,
            agent_name          TEXT NOT NULL DEFAULT 'My Agent',
            avatar_url          TEXT NOT NULL DEFAULT '',
            personality         TEXT NOT NULL DEFAULT '',
            onboarding_complete INTEGER NOT NULL DEFAULT 0,
            provider_override   TEXT NOT NULL DEFAULT '',
            model_override      TEXT NOT NULL DEFAULT '',
            gmail_enabled       INTEGER NOT NULL DEFAULT 0,
            calendar_enabled    INTEGER NOT NULL DEFAULT 0,
            telegram_enabled    INTEGER NOT NULL DEFAULT 0,
            telegram_bot_token  TEXT NOT NULL DEFAULT '',
            telegram_bot_username TEXT NOT NULL DEFAULT '',
            whatsapp_session_id TEXT NOT NULL DEFAULT '',
            created_at          TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at          TEXT NOT NULL DEFAULT (datetime('now'))
        );
    """)

    # Migrations for existing databases
    for col, typedef in [
        ("telegram_enabled", "INTEGER NOT NULL DEFAULT 0"),
        ("telegram_bot_token", "TEXT NOT NULL DEFAULT ''"),
        ("telegram_bot_username", "TEXT NOT NULL DEFAULT ''"),
        ("whatsapp_session_id", "TEXT NOT NULL DEFAULT ''"),
    ]:
        try:
            _connection.execute(f"ALTER TABLE agents ADD COLUMN {col} {typedef}")
        except sqlite3.OperationalError:
            pass  # Column already exists

    _connection.commit()
    logger.info("Agent registry DB initialized at %s", DB_PATH)


def _slugify(name: str) -> str:
    """Convert agent name to a URL-safe slug."""
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    return slug or "agent"


def _unique_slug(name: str) -> str:
    """Generate a unique slug, appending a short UUID suffix if needed."""
    base = _slugify(name)
    db = _get_db()
    existing = db.execute("SELECT slug FROM agents WHERE slug LIKE ?", (f"{base}%",)).fetchall()
    existing_slugs = {row["slug"] for row in existing}
    if base not in existing_slugs:
        return base
    for _ in range(10):
        candidate = f"{base}-{uuid.uuid4().hex[:6]}"
        if candidate not in existing_slugs:
            return candidate
    return f"{base}-{uuid.uuid4().hex[:8]}"


def create_agent(agent_name: str, personality: str = "") -> dict:
    """Create a new agent. Returns the created row as dict."""
    agent_id = str(uuid.uuid4())
    with _write_lock:
        slug = _unique_slug(agent_name)
        _get_db().execute(
            """INSERT INTO agents (id, slug, agent_name, personality)
               VALUES (?, ?, ?, ?)""",
            (agent_id, slug, agent_name, personality),
        )
        _get_db().commit()
    return get_agent(agent_id)


def get_agent(agent_id: str) -> dict | None:
    """Get agent by ID. Returns dict or None."""
    row = _get_db().execute("SELECT * FROM agents WHERE id = ?", (agent_id,)).fetchone()
    return dict(row) if row else None


def get_agent_by_slug(slug: str) -> dict | None:
    """Get agent by slug. Returns dict or None."""
    row = _get_db().execute("SELECT * FROM agents WHERE slug = ?", (slug,)).fetchone()
    return dict(row) if row else None


def list_agents() -> list[dict]:
    """List all agents ordered by creation date (newest first)."""
    rows = _get_db().execute(
        "SELECT * FROM agents ORDER BY created_at DESC"
    ).fetchall()
    return [dict(r) for r in rows]


UPDATABLE_FIELDS = {
    "agent_name", "avatar_url", "personality",
    "onboarding_complete", "provider_override", "model_override",
    "gmail_enabled", "calendar_enabled", "whatsapp_session_id",
    "telegram_enabled", "telegram_bot_token", "telegram_bot_username",
}


def update_agent(agent_id: str, **fields) -> dict | None:
    """Update agent fields. Returns updated row or None if not found."""
    filtered = {k: v for k, v in fields.items() if k in UPDATABLE_FIELDS}
    if not filtered:
        return get_agent(agent_id)

    # If agent_name changes, update slug too
    extra = {}
    if "agent_name" in filtered:
        with _write_lock:
            new_slug = _unique_slug(filtered["agent_name"])
        extra["slug"] = new_slug

    all_fields = {**filtered, **extra}
    set_clause = ", ".join(f"{k} = ?" for k in all_fields)
    values = list(all_fields.values()) + [agent_id]

    with _write_lock:
        cursor = _get_db().execute(
            f"UPDATE agents SET {set_clause}, updated_at = datetime('now') WHERE id = ?",
            values,
        )
        _get_db().commit()

    if cursor.rowcount == 0:
        return None
    return get_agent(agent_id)


def delete_agent(agent_id: str) -> bool:
    """Delete an agent. Returns True if deleted."""
    with _write_lock:
        cursor = _get_db().execute("DELETE FROM agents WHERE id = ?", (agent_id,))
        _get_db().commit()
    return cursor.rowcount > 0


def close_db() -> None:
    """Close the registry DB connection (for backup/restore)."""
    global _connection
    if _connection:
        _connection.close()
        _connection = None


def backup_to_gcs() -> None:
    """Checkpoint WAL then upload the registry DB to GCS."""
    if _connection is not None:
        try:
            _connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except Exception as e:
            logger.warning("WAL checkpoint before backup failed: %s", e)
    upload_file(DB_PATH, GCS_KEY)
