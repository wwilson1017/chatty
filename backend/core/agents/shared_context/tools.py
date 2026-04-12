"""Shared context — Agent tool handler functions.

Dispatched via ``kind="shared_context"`` in ``ToolRegistry.execute_tool``.
Read tools receive ``(shared_data_dir, ...)``.
Write tools receive ``(shared_data_dir, gcs_prefix, agent_name, ...)``.
"""

import logging

from . import db, service

logger = logging.getLogger(__name__)


def list_shared_context(shared_data_dir: str, category: str = "") -> dict:
    """List available shared files and entries."""
    files = service.list_files()
    entries = db.list_entries(category=category or None, limit=50)
    return {
        "files": [{"name": f["name"], "headline": f["headline"]} for f in files],
        "entries": [
            {
                "id": e["id"],
                "agent_name": e["agent_name"],
                "title": e["title"],
                "category": e.get("category", ""),
                "created_at": e["created_at"],
            }
            for e in entries
        ],
    }


def read_shared_context(shared_data_dir: str, filename: str = "", entry_id: str = "") -> dict:
    """Read a shared file by name or an entry by ID."""
    if filename:
        content = service.read_file(filename)
        if content is None:
            return {"error": f"Shared file '{filename}' not found"}
        return {"filename": filename, "content": content}

    if entry_id:
        entry = db.get_entry(entry_id)
        if not entry:
            return {"error": f"Shared entry '{entry_id}' not found"}
        return {"entry": entry}

    return {"error": "Provide either filename or entry_id"}


def write_shared_context(
    shared_data_dir: str,
    gcs_prefix: str,
    agent_name: str,
    title: str,
    content: str,
    category: str = "",
) -> dict:
    """Publish a knowledge entry visible to all agents."""
    if not title or not title.strip():
        return {"error": "title is required"}
    if not content or not content.strip():
        return {"error": "content is required"}

    entry = db.add_entry(
        agent_name=agent_name,
        title=title.strip(),
        content=content.strip(),
        category=category.strip(),
    )
    try:
        db.backup_to_gcs()
    except Exception:
        logger.debug("GCS backup after write_shared_context failed", exc_info=True)
    return {"id": entry["id"], "ok": True}
