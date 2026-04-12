"""Shared context — File CRUD, manifest builder, and GCS sync helpers.

Manages markdown files in the shared data directory and provides the
compact manifest string injected into every agent's system prompt.
"""

import logging
from datetime import datetime
from pathlib import Path

from core.storage import upload_config, delete_config

from . import db

logger = logging.getLogger(__name__)

SHARED_DATA_DIR = db.DATA_DIR
GCS_PREFIX = "shared/"


# ------------------------------------------------------------------
# File CRUD (admin-managed markdown files)
# ------------------------------------------------------------------

def list_files() -> list[dict]:
    """List all .md files in the shared directory."""
    if not SHARED_DATA_DIR.exists():
        return []
    files = []
    for f in sorted(SHARED_DATA_DIR.glob("*.md")):
        stat = f.stat()
        content = f.read_text(encoding="utf-8", errors="replace")
        files.append({
            "name": f.name,
            "size_bytes": stat.st_size,
            "modified": stat.st_mtime,
            "headline": _first_headline(content),
        })
    return files


def _safe_filename(filename: str) -> bool:
    """Validate filename: must be .md, no path separators, no traversal."""
    if not filename or not filename.endswith(".md"):
        return False
    if "/" in filename or "\\" in filename or ".." in filename:
        return False
    return True


def read_file(filename: str) -> str | None:
    """Read a shared file.  Returns content or None if not found."""
    if not _safe_filename(filename):
        return None
    path = SHARED_DATA_DIR / filename
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def write_file(filename: str, content: str) -> None:
    """Create or overwrite a shared file.  Syncs to GCS."""
    if not _safe_filename(filename):
        raise ValueError("filename must end with .md and contain no path separators")
    SHARED_DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = SHARED_DATA_DIR / filename
    path.write_text(content, encoding="utf-8")
    try:
        upload_config(path, filename, prefix=GCS_PREFIX)
    except Exception:
        logger.warning("GCS upload failed for shared/%s", filename, exc_info=True)


def delete_file(filename: str) -> bool:
    """Delete a shared file.  Returns True if it existed."""
    if not _safe_filename(filename):
        return False
    path = SHARED_DATA_DIR / filename
    if not path.exists():
        return False
    path.unlink()
    try:
        delete_config(filename, prefix=GCS_PREFIX)
    except Exception:
        logger.warning("GCS delete failed for shared/%s", filename, exc_info=True)
    return True


# ------------------------------------------------------------------
# Manifest for system prompt injection
# ------------------------------------------------------------------

def get_shared_manifest() -> str:
    """Return a compact manifest of shared files + recent entries.

    Injected into every agent's system prompt so they know what shared
    knowledge exists.  Agents call ``read_shared_context`` to get details.
    """
    parts: list[str] = []

    # Files
    files = list_files()
    if files:
        parts.append("## Shared Files")
        for f in files:
            modified = datetime.fromtimestamp(f["modified"]).strftime("%Y-%m-%d")
            headline = f["headline"] or f["name"]
            parts.append(f"- {f['name']} · {headline} · {modified}")
        parts.append("")

    # Recent entries (last 20)
    try:
        entries = db.list_entries(limit=20)
    except Exception:
        entries = []
    if entries:
        parts.append("## Recent Shared Entries")
        for e in entries:
            date_str = e["created_at"][:10] if e.get("created_at") else ""
            cat = f" ({e['category']})" if e.get("category") else ""
            parts.append(f"- [{e['agent_name']}, {date_str}] {e['title']}{cat}")
        parts.append("")

    return "\n".join(parts)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _first_headline(content: str) -> str:
    """Extract a short headline from a markdown file."""
    if not content:
        return ""
    for raw in content.splitlines():
        line = raw.strip()
        if not line or line.startswith("---"):
            continue
        if line.startswith("#"):
            return line.lstrip("#").strip()[:120]
        return line[:120]
    return ""
