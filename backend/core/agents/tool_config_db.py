"""Chatty — Per-agent tool toggle configuration.

Simple SQLite table that lets users enable/disable tool categories per agent
without code changes. All agents default to all-enabled.
"""

import logging
import sqlite3
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "agent_configs"
DB_PATH = DATA_DIR / "tool_configs.db"

_connection: sqlite3.Connection | None = None
_write_lock = threading.Lock()

# Toggle columns — Chatty-specific (no Odoo/DIMM/CRM/etc.)
TOGGLE_COLUMNS = [
    "web_enabled",
    "reports_enabled",
    "gmail_enabled",
    "calendar_enabled",
    "python_tools_enabled",
    "reminders_enabled",
    "scheduled_actions_enabled",
    "memory_enabled",
    "shared_context_enabled",
]


def get_db() -> sqlite3.Connection:
    if _connection is None:
        raise RuntimeError("Tool config DB not initialized — call init_db() first")
    return _connection


def write_lock() -> threading.Lock:
    return _write_lock


def init_db() -> None:
    """Create schema. All toggles default to 1 (enabled)."""
    global _connection

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    _connection = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    _connection.row_factory = sqlite3.Row
    _connection.execute("PRAGMA journal_mode=WAL")
    _connection.execute("PRAGMA busy_timeout=5000")

    columns_sql = ", ".join(f"{col} INTEGER NOT NULL DEFAULT 1" for col in TOGGLE_COLUMNS)
    _connection.executescript(f"""
        CREATE TABLE IF NOT EXISTS agent_tool_configs (
            agent_name TEXT PRIMARY KEY,
            {columns_sql},
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
    """)
    logger.info("Tool config DB initialized at %s", DB_PATH)


def get_config(agent_name: str) -> dict | None:
    """Get toggle config for an agent.  Returns None if no row exists (use defaults)."""
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM agent_tool_configs WHERE agent_name = ?",
        (agent_name,),
    ).fetchone()
    return dict(row) if row else None


def get_defaults() -> dict[str, int]:
    """Return the default config (all enabled)."""
    return {col: 1 for col in TOGGLE_COLUMNS}


def update_config(agent_name: str, **fields) -> dict:
    """Update toggle(s) for an agent.  Creates the row if missing."""
    conn = get_db()
    with _write_lock:
        existing = conn.execute(
            "SELECT * FROM agent_tool_configs WHERE agent_name = ?",
            (agent_name,),
        ).fetchone()
        if not existing:
            # Insert with defaults, then update
            conn.execute(
                "INSERT INTO agent_tool_configs (agent_name) VALUES (?)",
                (agent_name,),
            )
            conn.commit()

        # Apply requested changes
        valid_fields = {k: v for k, v in fields.items() if k in TOGGLE_COLUMNS}
        if valid_fields:
            set_clause = ", ".join(f"{k} = ?" for k in valid_fields)
            params = list(valid_fields.values()) + [agent_name]
            conn.execute(
                f"UPDATE agent_tool_configs SET {set_clause}, updated_at = datetime('now') WHERE agent_name = ?",
                params,
            )
            conn.commit()

    return get_config(agent_name) or get_defaults()


def list_configs() -> list[dict]:
    """List all agent configs."""
    conn = get_db()
    rows = conn.execute("SELECT * FROM agent_tool_configs ORDER BY agent_name").fetchall()
    return [dict(r) for r in rows]
