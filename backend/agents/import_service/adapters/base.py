"""Base class for import source adapters."""

from __future__ import annotations

import abc
from dataclasses import dataclass


@dataclass
class FileEntry:
    path: str
    size_bytes: int
    mtime: float | None = None


@dataclass
class SourceInfo:
    agent_name: str | None
    file_count: int
    total_bytes: int


class SourceAdapter(abc.ABC):
    """Reads knowledge files from an external agent source."""

    @abc.abstractmethod
    def discover(self) -> SourceInfo:
        """Probe the source and return summary info."""

    @abc.abstractmethod
    def list_files(self) -> list[FileEntry]:
        """List available files (already filtered by skip rules)."""

    @abc.abstractmethod
    def read_file(self, path: str) -> str:
        """Read and return scrubbed file content.

        YAML front-matter is stripped. Secrets are redacted.
        """

    def close(self) -> None:
        """Clean up resources (temp dirs, connections). Default is no-op."""
