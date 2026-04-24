"""Source adapter for pasted markdown text."""

from __future__ import annotations

import re

from ..scrubber import scrub, FRONT_MATTER_RE
from .base import FileEntry, SourceAdapter, SourceInfo

MAX_PASTE_BYTES = 500 * 1024  # 500 KB
_HEADING_RE = re.compile(r"^#\s+(.+)", re.MULTILINE)


class PasteSourceAdapter(SourceAdapter):
    """Treat pasted markdown as one or more logical files.

    If the text contains multiple top-level `# Heading` sections, each becomes
    a separate file (e.g., ``heading.md``). Otherwise the entire text is treated
    as a single file named ``pasted.md``.
    """

    def __init__(self, text: str) -> None:
        if len(text.encode("utf-8")) > MAX_PASTE_BYTES:
            raise ValueError(
                f"Pasted text exceeds {MAX_PASTE_BYTES // 1024} KB limit. "
                "Use a file or zip instead."
            )

        stripped = FRONT_MATTER_RE.sub("", text, count=1)
        scrubbed, _ = scrub(stripped)
        self._files = self._split_sections(scrubbed)

    @staticmethod
    def _split_sections(text: str) -> dict[str, str]:
        headings = list(_HEADING_RE.finditer(text))
        if len(headings) < 2:
            return {"pasted.md": text.strip()}

        files: dict[str, str] = {}
        for i, m in enumerate(headings):
            end = headings[i + 1].start() if i + 1 < len(headings) else len(text)
            title = m.group(1).strip()
            slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:60]
            content = text[m.start():end].strip()
            files[f"{slug}.md"] = content
        return files

    def discover(self) -> SourceInfo:
        total = sum(len(c.encode("utf-8")) for c in self._files.values())
        return SourceInfo(agent_name=None, file_count=len(self._files), total_bytes=total)

    def list_files(self) -> list[FileEntry]:
        return [
            FileEntry(path=name, size_bytes=len(content.encode("utf-8")))
            for name, content in self._files.items()
        ]

    def read_file(self, path: str) -> str:
        if path not in self._files:
            raise FileNotFoundError(f"No pasted section: {path}")
        return self._files[path]
