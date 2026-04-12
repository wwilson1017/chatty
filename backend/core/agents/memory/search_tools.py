"""Memory search and fact tools — handler functions for the tool registry.

Dispatched via ``kind="memory"`` in ``ToolRegistry.execute_tool``.
Each function takes ``(data_dir, gcs_prefix, ...)`` and retrieves a cached
``MemoryDB`` instance (created during startup or on first access).
"""

import logging
from pathlib import Path

from .db import MemoryDB, get_instance
from .types import validate_memory_type

logger = logging.getLogger(__name__)


def _get_db(data_dir: str, gcs_prefix: str) -> MemoryDB:
    """Get or lazily create a MemoryDB for *data_dir*."""
    db = get_instance(data_dir)
    if db is not None:
        return db
    # Lazy init (shouldn't normally happen — startup inits everything)
    db = MemoryDB(Path(data_dir), gcs_prefix)
    db.init_db()
    return db


# ------------------------------------------------------------------
# search_memory
# ------------------------------------------------------------------

def search_memory(
    data_dir: str,
    gcs_prefix: str,
    query: str,
    source_type: str | None = None,
    memory_type: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 20,
) -> dict:
    """Full-text search across daily notes, MEMORY.md, topic files, and facts."""
    if not query or not query.strip():
        return {"error": "query is required"}
    try:
        limit = max(1, min(int(limit), 100))
    except (TypeError, ValueError):
        limit = 20

    db = _get_db(data_dir, gcs_prefix)
    results = db.search(
        query=query,
        source_type=source_type,
        memory_type=validate_memory_type(memory_type),
        date_from=date_from,
        date_to=date_to,
        limit=limit,
    )
    return {"query": query, "results": results, "total": len(results)}


# ------------------------------------------------------------------
# add_fact
# ------------------------------------------------------------------

def add_fact(
    data_dir: str,
    gcs_prefix: str,
    subject: str,
    predicate: str,
    object: str,
    valid_from: str | None = None,
    created_by: str = "agent",
    source: str = "",
    confidence: float = 1.0,
    memory_type: str | None = None,
) -> dict:
    """Add a temporal fact to the knowledge base."""
    if not subject or not subject.strip():
        return {"error": "subject is required"}
    if not predicate or not predicate.strip():
        return {"error": "predicate is required"}
    if not object or not object.strip():
        return {"error": "object is required"}

    db = _get_db(data_dir, gcs_prefix)
    result = db.add_fact(
        subject=subject.strip(),
        predicate=predicate.strip(),
        object_=object.strip(),
        valid_from=valid_from,
        created_by=created_by,
        source=source,
        confidence=confidence,
        memory_type=memory_type,
    )
    # Background GCS backup
    try:
        db.backup_to_gcs()
    except Exception:
        logger.debug("GCS backup after add_fact failed", exc_info=True)
    return result


# ------------------------------------------------------------------
# query_facts
# ------------------------------------------------------------------

def query_facts(
    data_dir: str,
    gcs_prefix: str,
    subject: str | None = None,
    predicate: str | None = None,
    as_of: str | None = None,
    memory_type: str | None = None,
    include_expired: bool = False,
    limit: int = 50,
) -> dict:
    """Query temporal facts with optional filters."""
    try:
        limit = max(1, min(int(limit), 500))
    except (TypeError, ValueError):
        limit = 50

    db = _get_db(data_dir, gcs_prefix)
    facts = db.query_facts(
        subject=subject,
        predicate=predicate,
        as_of=as_of,
        memory_type=validate_memory_type(memory_type),
        include_expired=bool(include_expired),
        limit=limit,
    )
    return {"facts": facts, "total": len(facts)}


# ------------------------------------------------------------------
# invalidate_fact
# ------------------------------------------------------------------

def invalidate_fact(
    data_dir: str,
    gcs_prefix: str,
    fact_id: int,
    valid_to: str | None = None,
) -> dict:
    """Mark a fact as no longer valid (sets valid_to)."""
    try:
        fact_id = int(fact_id)
    except (TypeError, ValueError):
        return {"error": "fact_id must be an integer"}

    db = _get_db(data_dir, gcs_prefix)
    result = db.invalidate_fact(fact_id, valid_to=valid_to)
    if result.get("ok"):
        try:
            db.backup_to_gcs()
        except Exception:
            logger.debug("GCS backup after invalidate_fact failed", exc_info=True)
    return result
