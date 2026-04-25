"""Source adapter that extracts a zip file to a temp directory."""

from __future__ import annotations

import logging
import shutil
import tempfile
import zipfile
from pathlib import Path

from .base import FileEntry, SourceAdapter, SourceInfo
from .folder import FolderSourceAdapter

logger = logging.getLogger(__name__)

MAX_ZIP_SIZE = 25 * 1024 * 1024  # 25 MB
MAX_FILES = 500


class ZipSourceAdapter(SourceAdapter):
    """Extract a zip archive to a temp directory and read its markdown files."""

    def __init__(self, zip_path: str | Path) -> None:
        zip_path = Path(zip_path)
        if not zip_path.is_file():
            raise FileNotFoundError(f"Zip not found: {zip_path}")
        if zip_path.stat().st_size > MAX_ZIP_SIZE:
            raise ValueError(f"Zip exceeds {MAX_ZIP_SIZE // (1024*1024)} MB limit")

        self._tmp = tempfile.mkdtemp(prefix="chatty-import-")

        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                members = zf.namelist()
                if len(members) > MAX_FILES:
                    raise ValueError(f"Zip contains {len(members)} files (max {MAX_FILES})")
                safe = [
                    m for m in members
                    if not m.startswith("/") and ".." not in m and "\\" not in m
                    and not zf.getinfo(m).is_dir()
                    and ((zf.getinfo(m).external_attr >> 16) & 0o120000) != 0o120000
                ]
                total_uncompressed = sum(zf.getinfo(m).file_size for m in safe)
                if total_uncompressed > 100 * 1024 * 1024:
                    raise ValueError(f"Uncompressed size {total_uncompressed // (1024*1024)} MB exceeds 100 MB limit")
                zf.extractall(self._tmp, members=safe)
        except Exception:
            shutil.rmtree(self._tmp, ignore_errors=True)
            raise

        # Find the actual content root (skip single top-level directory wrappers)
        root = Path(self._tmp)
        children = [c for c in root.iterdir() if not c.name.startswith(".")]
        if len(children) == 1 and children[0].is_dir():
            root = children[0]

        self._inner = FolderSourceAdapter(root)

    def discover(self) -> SourceInfo:
        return self._inner.discover()

    def list_files(self) -> list[FileEntry]:
        return self._inner.list_files()

    def read_file(self, path: str) -> str:
        return self._inner.read_file(path)

    def close(self) -> None:
        self._inner.close()
        shutil.rmtree(self._tmp, ignore_errors=True)
        logger.info("Cleaned up import temp dir: %s", self._tmp)
