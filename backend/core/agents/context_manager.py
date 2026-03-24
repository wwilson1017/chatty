"""
Chatty — Context file manager.

Manages a directory of markdown context files that form an agent's long-term memory.
All .md files in data_dir are loaded into the system prompt.
"""

import logging
from pathlib import Path

from core.storage import upload_config, delete_config

logger = logging.getLogger(__name__)

# Cap total context injected into system prompt (characters, ~50k tokens)
MAX_CONTEXT_CHARS = 200_000


class ContextManager:
    """Per-agent context file manager parameterized by data dir and GCS prefix."""

    def __init__(self, data_dir: Path, gcs_prefix: str):
        self.data_dir = data_dir
        self.gcs_prefix = gcs_prefix

    def ensure_dir(self):
        """Create the data directory if it doesn't exist."""
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def load_all_context(self) -> str:
        """Load all .md files and concatenate them with headers. Used for system prompt.

        Enforces MAX_CONTEXT_CHARS to prevent prompt bloat. Files starting with '_'
        (like _training-progress.md) are loaded last so operational files take priority.
        """
        self.ensure_dir()
        files = sorted(self.data_dir.glob("*.md"), key=lambda f: (f.name.startswith("_"), f.name))
        parts = []
        total = 0
        for f in files:
            content = f.read_text(encoding="utf-8").strip()
            if not content:
                continue
            section = f"## {f.stem}\n\n{content}"
            if total + len(section) > MAX_CONTEXT_CHARS:
                parts.append(f"## {f.stem}\n\n(Truncated — context size limit reached)")
                logger.warning("Context size limit reached at %s (%d chars)", f.name, total)
                break
            parts.append(section)
            total += len(section)

        return "\n\n---\n\n".join(parts) if parts else ""

    def list_context_files(self) -> list[dict]:
        """List all context files with metadata."""
        self.ensure_dir()
        files = []
        for f in sorted(self.data_dir.glob("*.md")):
            stat = f.stat()
            files.append({
                "name": f.name,
                "size_bytes": stat.st_size,
                "modified": stat.st_mtime,
            })
        return files

    def read_context(self, filename: str) -> str:
        """Read a specific context file. Returns empty string if not found."""
        path = self.data_dir / filename
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")

    def write_context(self, filename: str, content: str):
        """Write a context file and sync to GCS."""
        self.ensure_dir()
        path = self.data_dir / filename
        path.write_text(content, encoding="utf-8")
        upload_config(path, filename, prefix=self.gcs_prefix)
        logger.info("Context file written and synced: %s", filename)

    def delete_context(self, filename: str) -> bool:
        """Delete a context file locally and from GCS. Returns True if deleted."""
        path = self.data_dir / filename
        if not path.exists():
            return False
        path.unlink()
        delete_config(filename, prefix=self.gcs_prefix)
        logger.info("Context file deleted and synced: %s", filename)
        return True
