"""
Chatty — Agent engine factory with LRU cache.

Creates and caches live agent instances. Each agent has its own:
  - AgentConfig
  - ContextManager (data/agents/{slug}/context/)
  - ChatHistoryDB + ChatHistoryService (data/agents/{slug}/chat.db)
  - ToolRegistry (built fresh per-request since access_token may change)

The LRU cache holds the initialized DB + context manager so we don't
re-init SQLite on every request.
"""

import logging
from functools import lru_cache
from pathlib import Path

from core.agents.config import AgentConfig
from core.agents.context_manager import ContextManager
from core.agents.chat_history.db import ChatHistoryDB
from core.agents.chat_history.service import ChatHistoryService
from .onboarding import get_onboarding_topics, get_onboarding_personality

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "agents"


def _agent_dir(slug: str) -> Path:
    return DATA_DIR / slug


def _context_dir(slug: str) -> Path:
    return _agent_dir(slug) / "context"


def _gcs_prefix(slug: str) -> str:
    return f"agents/{slug}/"


@lru_cache(maxsize=32)
def _get_initialized_db(slug: str) -> ChatHistoryDB:
    """Return an initialized ChatHistoryDB for the given agent slug.

    LRU cache ensures we reuse the same DB connection across requests.
    """
    agent_dir = _agent_dir(slug)
    db = ChatHistoryDB(
        data_dir=agent_dir,
        gcs_prefix=_gcs_prefix(slug),
        db_filename="chat.db",
    )
    db.init_db()
    return db


def build_agent_config(agent_row: dict) -> AgentConfig:
    """Build an AgentConfig from a DB row."""
    slug = agent_row["slug"]
    topics = get_onboarding_topics()
    personality = agent_row.get("personality") or get_onboarding_personality(agent_row["agent_name"])

    google_accounts = agent_row.get("google_accounts") or {}

    return AgentConfig(
        agent_id=agent_row["id"],
        agent_name=agent_row["agent_name"],
        slug=slug,
        personality=personality,
        provider_override=agent_row.get("provider_override", ""),
        model_override=agent_row.get("model_override", ""),
        gmail_enabled=bool(agent_row.get("gmail_enabled", 0)),
        gmail_send_enabled=bool(agent_row.get("gmail_send_enabled", 0)),
        calendar_enabled=bool(agent_row.get("calendar_enabled", 0)),
        calendar_write_enabled=bool(agent_row.get("calendar_write_enabled", 0)),
        drive_enabled=bool(agent_row.get("drive_enabled", 0)),
        drive_write_enabled=bool(agent_row.get("drive_write_enabled", 0)),
        google_accounts=google_accounts,
        context_dir=str(_context_dir(slug)),
        gcs_prefix=_gcs_prefix(slug) + "context/",
        chat_db_path=str(_agent_dir(slug) / "chat.db"),
        onboarding_complete=bool(agent_row.get("onboarding_complete", 0)),
        training_topics=topics,
    )


def get_context_manager(slug: str) -> ContextManager:
    """Return a ContextManager for the given agent slug."""
    return ContextManager(
        data_dir=_context_dir(slug),
        gcs_prefix=_gcs_prefix(slug) + "context/",
    )


@lru_cache(maxsize=32)
def _get_initialized_memory_db(slug: str):
    """Return an initialized MemoryDB for the given agent slug.

    LRU cache ensures we reuse the same DB connection across requests.
    """
    from core.agents.memory.db import MemoryDB
    ctx_dir = _context_dir(slug)
    db = MemoryDB(ctx_dir, _gcs_prefix(slug) + "context/")
    db.init_db()
    # Reindex all files on first init so FTS5 has data
    ctx_manager = get_context_manager(slug)
    db.reindex_all(ctx_manager)
    return db


def ensure_memory_db(slug: str):
    """Ensure the MemoryDB is initialized for this agent. Called lazily."""
    return _get_initialized_memory_db(slug)


def get_chat_service(slug: str) -> ChatHistoryService:
    """Return an initialized ChatHistoryService for the given agent slug."""
    db = _get_initialized_db(slug)
    return ChatHistoryService(db)


def invalidate_cache(slug: str) -> None:
    """Invalidate the LRU cache entry for a given slug (e.g. after deletion)."""
    _get_initialized_db.cache_clear()


def close_all_agent_dbs() -> None:
    """Close all cached chat DB connections and clear LRU cache (for backup/restore)."""
    from .db import list_agents
    try:
        for agent in list_agents():
            try:
                db = _get_initialized_db(agent["slug"])
                db.close()
            except Exception:
                pass
    except Exception:
        pass
    _get_initialized_db.cache_clear()
