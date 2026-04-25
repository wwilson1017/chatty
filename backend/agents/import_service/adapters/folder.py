"""Source adapter that reads markdown files from a local directory."""

from __future__ import annotations

import os
import re
from pathlib import Path

from ..scrubber import scrub, should_skip_file, FRONT_MATTER_RE
from .base import FileEntry, SourceAdapter, SourceInfo


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

    MAX_FILES = 200

    def list_files(self) -> list[FileEntry]:
        entries: list[FileEntry] = []
        _PRUNE_DIRS = {"node_modules", "__pycache__", ".venv", "venv", "dist", "build"}
        for dirpath, dirs, filenames in os.walk(self._root):
            dirs[:] = [d for d in dirs if d not in _PRUNE_DIRS and not d.startswith(".")]

            rel_dir = Path(dirpath).relative_to(self._root)
            if any(part.startswith(".") for part in rel_dir.parts):
                continue

            for fname in filenames:
                full = Path(dirpath) / fname
                rel = str(full.relative_to(self._root))

                if not full.suffix.lower() == ".md":
                    continue
                if should_skip_file(rel):
                    continue

                try:
                    stat = full.stat()
                except OSError:
                    continue
                entries.append(FileEntry(path=rel, size_bytes=stat.st_size, mtime=stat.st_mtime))
                if len(entries) >= self.MAX_FILES:
                    break
            if len(entries) >= self.MAX_FILES:
                break

        entries.sort(key=lambda e: e.path)
        return entries

    def read_file(self, path: str) -> str:
        if ".." in path or path.startswith("/") or "\\" in path or "\0" in path:
            raise ValueError(f"Unsafe path: {path}")

        full = self._root / path
        if not full.resolve().is_relative_to(self._root.resolve()):
            raise ValueError(f"Path escapes source directory: {path}")
        if not full.is_file():
            raise FileNotFoundError(f"File not found: {path}")

        raw = full.read_text(encoding="utf-8", errors="replace")
        stripped = FRONT_MATTER_RE.sub("", raw, count=1)
        scrubbed, _ = scrub(stripped)
        return scrubbed
