"""
Chatty — Context file management tools.

Pure functions for reading/writing an agent's markdown context files.
These let agents organize and maintain their own long-term memory.
"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def list_context_files(data_dir: str) -> dict:
    """List all .md files in the context directory."""
    d = Path(data_dir)
    if not d.exists():
        return {"files": []}

    files = []
    for f in sorted(d.glob("*.md")):
        stat = f.stat()
        files.append({
            "name": f.name,
            "size_bytes": stat.st_size,
            "modified": stat.st_mtime,
        })

    return {"files": files}


def read_context_file(data_dir: str, filename: str) -> dict:
    """Read a specific context file."""
    if not _safe_filename(filename):
        return {"error": "Invalid filename"}

    path = Path(data_dir) / filename
    if not path.exists():
        return {"error": f"File '{filename}' not found"}

    content = path.read_text(encoding="utf-8")
    return {"filename": filename, "content": content}


def write_context_file(data_dir: str, filename: str, content: str) -> dict:
    """Write/overwrite a context file."""
    if not _safe_filename(filename):
        return {"error": "Invalid filename — must end with .md and contain no path separators"}

    d = Path(data_dir)
    d.mkdir(parents=True, exist_ok=True)
    path = d / filename
    path.write_text(content, encoding="utf-8")
    logger.info("Agent wrote context file: %s", filename)
    return {"filename": filename, "ok": True}


def append_to_context_file(data_dir: str, filename: str, content: str) -> dict:
    """Append content to an existing file (or create it)."""
    if not _safe_filename(filename):
        return {"error": "Invalid filename — must end with .md and contain no path separators"}

    d = Path(data_dir)
    d.mkdir(parents=True, exist_ok=True)
    path = d / filename

    existing = ""
    if path.exists():
        existing = path.read_text(encoding="utf-8")

    new_content = existing + "\n" + content if existing else content
    path.write_text(new_content, encoding="utf-8")
    logger.info("Agent appended to context file: %s", filename)
    return {"filename": filename, "ok": True}


def delete_context_file(data_dir: str, filename: str) -> dict:
    """Delete a context file."""
    if not _safe_filename(filename):
        return {"error": "Invalid filename"}

    path = Path(data_dir) / filename
    if not path.exists():
        return {"error": f"File '{filename}' not found"}

    path.unlink()
    logger.info("Agent deleted context file: %s", filename)
    return {"filename": filename, "deleted": True}


def _safe_filename(filename: str) -> bool:
    """Validate filename: must be .md, no path separators, no traversal."""
    if not filename or not filename.endswith(".md"):
        return False
    if "/" in filename or "\\" in filename or ".." in filename:
        return False
    return True
