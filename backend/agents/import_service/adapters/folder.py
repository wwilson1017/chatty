"""Source adapter that reads markdown files from a local directory."""

from __future__ import annotations

import os
import re
from pathlib import Path

from ..scrubber import scrub, should_skip_file
from .base import FileEntry, SourceAdapter, SourceInfo

_FRONT_MATTER_RE = re.compile(r"^---\n[\s\S]*?\n---\n?")
_BINARY_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".db", ".sqlite", ".wasm", ".zip", ".tar", ".gz"}


class FolderSourceAdapter(SourceAdapter):
    """Walk a local directory and return scrubbed .md files."""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root).expanduser().resolve()
        if not self._root.is_dir():
            raise FileNotFoundError(f"Not a directory: {self._root}")

    @property
    def root(self) -> Path:
        return self._root

    def discover(self) -> SourceInfo:
        files = self.list_files()
        total = sum(f.size_bytes for f in files)
        return SourceInfo(agent_name=None, file_count=len(files), total_bytes=total)

    def list_files(self) -> list[FileEntry]:
        entries: list[FileEntry] = []
        for dirpath, _dirs, filenames in os.walk(self._root):
            # Skip hidden directories and common junk
            rel_dir = Path(dirpath).relative_to(self._root)
            if any(part.startswith(".") for part in rel_dir.parts):
                continue

            for fname in filenames:
                full = Path(dirpath) / fname
                rel = str(full.relative_to(self._root))

                if full.suffix.lower() in _BINARY_EXTENSIONS:
                    continue
                if not full.suffix.lower() == ".md":
                    continue
                if should_skip_file(rel):
                    continue

                try:
                    stat = full.stat()
                except OSError:
                    continue
                entries.append(FileEntry(path=rel, size_bytes=stat.st_size, mtime=stat.st_mtime))

        entries.sort(key=lambda e: e.path)
        return entries

    def read_file(self, path: str) -> str:
        if ".." in path or path.startswith("/"):
            raise ValueError(f"Unsafe path: {path}")

        full = self._root / path
        if not full.is_file():
            raise FileNotFoundError(f"File not found: {path}")

        raw = full.read_text(encoding="utf-8", errors="replace")
        stripped = _FRONT_MATTER_RE.sub("", raw, count=1)
        scrubbed, _ = scrub(stripped)
        return scrubbed
