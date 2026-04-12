"""Chatty — Context file manager.

Manages a directory of markdown context files that form an agent's long-term memory.
All .md files in data_dir are loaded into the system prompt.
"""

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from core.storage import upload_config, delete_config

logger = logging.getLogger(__name__)

# Cap total context injected into system prompt (characters, ~50k tokens).
# Last-resort circuit breaker so a runaway file can't produce a multi-megabyte
# prompt; normal flow never hits this.
MAX_CONTEXT_CHARS = 200_000

CT_TZ = ZoneInfo("America/Chicago")

# English stopwords for the relevance pre-fetch scorer. Deliberately small —
# we want a cheap, directional match signal, not a full NLP pipeline.
_STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "if", "of", "in", "on", "at", "to",
    "for", "with", "by", "from", "as", "is", "are", "was", "were", "be", "been",
    "being", "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "can", "i", "you", "he", "she", "it", "we", "they",
    "me", "him", "her", "us", "them", "my", "your", "his", "its", "our", "their",
    "this", "that", "these", "those", "there", "here", "what", "which", "who",
    "whom", "whose", "when", "where", "why", "how", "not", "no", "yes", "so",
    "than", "then", "too", "very", "just", "about", "into", "over", "up", "down",
    "out", "off", "any", "all", "some", "each", "more", "most", "other", "such",
    "own", "same", "s", "t", "don", "now", "re", "ve", "ll", "d", "m",
}

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> list[str]:
    """Lowercase, split on non-alphanumerics, strip stopwords and 1-char tokens."""
    if not text:
        return []
    return [
        t for t in _TOKEN_RE.findall(text.lower())
        if len(t) > 1 and t not in _STOPWORDS
    ]


_DATE_HEADING_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIME_HEADING_RE = re.compile(r"^\d{1,2}:\d{2}\s*(am|pm)?", re.IGNORECASE)


def _first_headline(content: str) -> str:
    """Return a short headline for a markdown file.

    Preference order:
      1. A line starting with "Headline:" (used by the nightly daily-note
         summarizer to stamp each day with a one-line recap).
      2. The first heading that isn't just a date or timestamp.
      3. The first non-empty body line.

    Strips leading '#' characters and whitespace. Returns at most ~120 chars.
    """
    if not content:
        return ""
    heading_fallback = ""
    text_fallback = ""
    for raw in content.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("---"):
            continue
        if line.lower().startswith("headline:"):
            headline = line.split(":", 1)[1].strip()
            if headline:
                return headline[:120]
        if line.startswith("#"):
            stripped = line.lstrip("#").strip()
            if not stripped:
                continue
            # Skip date / timestamp headings — they're useless as summaries
            if _DATE_HEADING_RE.match(stripped) or _TIME_HEADING_RE.match(stripped):
                continue
            if not heading_fallback:
                heading_fallback = stripped[:120]
            continue
        if not text_fallback:
            text_fallback = line[:120]
    return heading_fallback or text_fallback


class ContextManager:
    """Per-agent context file manager parameterized by data dir and GCS prefix."""

    def __init__(self, data_dir: Path, gcs_prefix: str):
        self.data_dir = data_dir
        self.tools_dir = data_dir / "tools"
        self.daily_dir = data_dir / "daily"
        self.gcs_prefix = gcs_prefix

    def ensure_dir(self):
        """Create the data directory if it doesn't exist."""
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def ensure_daily_dir(self):
        """Create the daily notes subdirectory if it doesn't exist."""
        self.daily_dir.mkdir(parents=True, exist_ok=True)

    def _get_sorted_files(self) -> list[Path]:
        """Return .md files sorted by dreaming priority, then default rules.

        soul.md is pinned to position 1, MEMORY.md to position 2 (the agent's
        living snapshot, always loaded right after identity). Everything else
        follows dreaming priority, then alphabetical.
        """
        self.ensure_dir()

        # Check for dreaming-generated load order
        order_file = self.data_dir / "_load-order.json"
        priority: dict[str, int] = {}
        if order_file.exists():
            try:
                order = json.loads(order_file.read_text(encoding="utf-8"))
                priority = {name: i for i, name in enumerate(order)}
            except (json.JSONDecodeError, TypeError):
                pass

        return sorted(
            self.data_dir.glob("*.md"),
            key=lambda f: (
                f.name != "soul.md",           # soul.md always first
                f.name != "MEMORY.md",          # MEMORY.md pinned second
                f.name.startswith("_"),         # underscore files last
                priority.get(f.name, 999),      # dreaming priority
                f.name,                         # alpha fallback
            ),
        )

    def load_all_context(self, agent_name: str | None = None) -> str:
        """Load all .md files and concatenate them with headers. Used for system prompt.

        Enforces MAX_CONTEXT_CHARS to prevent prompt bloat. soul.md is loaded first
        as the agent's identity anchor. Files starting with '_' (like
        _training-progress.md) are loaded last so operational files take priority.

        If agent_name is provided, records load/truncation events for the dreaming system.
        """
        files = self._get_sorted_files()
        parts = []
        total = 0
        loaded_files: list[str] = []
        truncated_files: list[str] = []

        # Load soul.md first for identity prominence
        soul_file = self.data_dir / "soul.md"
        if soul_file.exists():
            soul_content = soul_file.read_text(encoding="utf-8").strip()
            if soul_content:
                section = f"## soul\n\n{soul_content}"
                parts.append(section)
                total += len(section)
                loaded_files.append("soul.md")

        # Load MEMORY.md second — the living snapshot. Always included if it
        # exists with content; no size gate (consolidation keeps it tight).
        memory_file = self.data_dir / "MEMORY.md"
        if memory_file.exists():
            memory_content = memory_file.read_text(encoding="utf-8").strip()
            if memory_content:
                section = f"## MEMORY\n\n{memory_content}"
                parts.append(section)
                total += len(section)
                loaded_files.append("MEMORY.md")

        truncated = False
        for f in files:
            if f.name == "soul.md" or f.name == "MEMORY.md":
                continue  # already loaded above
            if truncated:
                truncated_files.append(f.name)
                continue
            content = f.read_text(encoding="utf-8").strip()
            if not content:
                continue
            section = f"## {f.stem}\n\n{content}"
            if total + len(section) > MAX_CONTEXT_CHARS:
                parts.append(f"## {f.stem}\n\n(Truncated — context size limit reached)")
                logger.warning("Context size limit reached at %s (%d chars)", f.name, total)
                truncated_files.append(f.name)
                truncated = True
                continue
            parts.append(section)
            total += len(section)
            loaded_files.append(f.name)

        # Record load events for dreaming (fire-and-forget)
        if agent_name and (loaded_files or truncated_files):
            try:
                from core.agents.dreaming.tracker import record_load_events
                record_load_events(agent_name, loaded_files, truncated_files)
            except Exception:
                pass

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

    # ------------------------------------------------------------------
    # MEMORY.md — living snapshot helpers
    # ------------------------------------------------------------------

    def read_memory(self) -> str:
        """Return MEMORY.md contents (empty string if not yet created)."""
        path = self.data_dir / "MEMORY.md"
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")

    def write_memory(self, content: str) -> None:
        """Write MEMORY.md and sync to GCS. No size enforcement — the
        consolidation LLM prompt is responsible for keeping it tight.
        """
        self.write_context("MEMORY.md", content)

    # ------------------------------------------------------------------
    # Daily notes — per-day running log
    # ------------------------------------------------------------------

    def _today_str(self) -> str:
        return datetime.now(CT_TZ).strftime("%Y-%m-%d")

    def _daily_path(self, date: str) -> Path:
        return self.daily_dir / f"{date}.md"

    def append_daily_note(self, content: str, date: str | None = None) -> dict:
        """Append a timestamped entry to the given day's daily note.

        Creates the file (and the daily/ dir) if missing. Syncs the changed
        file to GCS under `daily/YYYY-MM-DD.md`.
        """
        self.ensure_daily_dir()
        date = date or self._today_str()
        path = self._daily_path(date)

        now = datetime.now(CT_TZ)
        # %I is zero-padded across platforms; strip leading 0 manually for readability
        stamp = now.strftime("%I:%M %p CT").lstrip("0")

        body = (content or "").strip()
        entry = f"\n### {stamp}\n\n{body}\n" if body else ""
        if not entry:
            return {"date": date, "ok": False, "error": "empty content"}

        if path.exists():
            existing = path.read_text(encoding="utf-8")
            new_content = existing.rstrip() + "\n" + entry
        else:
            new_content = f"# {date}\n{entry}"

        path.write_text(new_content, encoding="utf-8")
        try:
            upload_config(path, f"daily/{date}.md", prefix=self.gcs_prefix)
        except Exception:
            logger.warning("GCS upload failed for daily/%s.md", date, exc_info=True)
        logger.info("Daily note appended: %s", date)
        return {"date": date, "ok": True}

    def read_daily_note(self, date: str) -> str:
        """Return the full content of a daily note (empty string if missing)."""
        path = self._daily_path(date)
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")

    def today_daily_note_text(self) -> str:
        """Return today's daily note, or empty string if no entries yet today."""
        return self.read_daily_note(self._today_str())

    def list_daily_notes(self, limit: int = 30) -> list[dict]:
        """List recent daily notes, newest first."""
        self.ensure_daily_dir()
        entries: list[dict] = []
        for f in sorted(self.daily_dir.glob("*.md"), reverse=True):
            date = f.stem
            content = f.read_text(encoding="utf-8")
            stat = f.stat()
            entries.append({
                "name": f.name,
                "date": date,
                "headline": _first_headline(content),
                "size_bytes": stat.st_size,
                "modified": stat.st_mtime,
            })
            if len(entries) >= limit:
                break
        return entries

    def daily_notes_manifest(self, limit: int = 30) -> str:
        """Render the recent-daily-notes manifest for system prompt injection.

        One line per day: `- 2026-04-10 · <headline>`. Returns empty string
        if there are no daily notes yet.
        """
        entries = self.list_daily_notes(limit=limit)
        if not entries:
            return ""
        lines = []
        today = self._today_str()
        for e in entries:
            # Don't list today in the manifest — today's full content is
            # already injected elsewhere in the prompt.
            if e["date"] == today:
                continue
            headline = e["headline"] or "(no summary yet)"
            lines.append(f"- {e['date']} · {headline}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Daily note retention — archive old notes
    # ------------------------------------------------------------------

    def archive_old_daily_notes(self, max_age_days: int = 90) -> dict:
        """Move daily notes older than *max_age_days* to daily/archive/.

        Archived notes are excluded from manifests and pre-fetch but remain
        on disk (and in FTS5) so ``search_memory`` still finds them.
        Returns ``{"archived": N}``.
        """
        self.ensure_daily_dir()
        archive_dir = self.daily_dir / "archive"
        today = datetime.now(CT_TZ).date()
        count = 0
        for f in sorted(self.daily_dir.glob("*.md")):
            try:
                note_date = datetime.strptime(f.stem, "%Y-%m-%d").date()
            except ValueError:
                continue
            if (today - note_date).days > max_age_days:
                archive_dir.mkdir(parents=True, exist_ok=True)
                dest = archive_dir / f.name
                f.rename(dest)
                count += 1
        if count:
            logger.info("Archived %d daily notes older than %d days", count, max_age_days)
        return {"archived": count}

    # ------------------------------------------------------------------
    # Topic files manifest
    # ------------------------------------------------------------------

    def _manifest_topic_files(self) -> list[Path]:
        """Return topic files eligible for the manifest: *.md files that are
        not soul.md, not MEMORY.md, and not underscore-prefixed internals.
        """
        self.ensure_dir()
        result = []
        for f in sorted(self.data_dir.glob("*.md")):
            if f.name in ("soul.md", "MEMORY.md"):
                continue
            if f.name.startswith("_"):
                continue
            result.append(f)
        return result

    def topic_files_manifest(self) -> str:
        """Render the topic files manifest for system prompt injection.

        One line per non-always-loaded markdown file:
        `- filename.md · <headline or filename stem> · YYYY-MM-DD`
        """
        files = self._manifest_topic_files()
        if not files:
            return ""
        lines = []
        for f in files:
            try:
                content = f.read_text(encoding="utf-8")
            except Exception:
                content = ""
            headline = _first_headline(content) or f.stem.replace("-", " ")
            modified = datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d")
            lines.append(f"- {f.name} · {headline} · {modified}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Relevance pre-fetch — simple BM25-lite scorer over topic files +
    # recent daily notes. Returns every file whose score crosses the
    # match threshold; no fixed top-K, no content truncation.
    # ------------------------------------------------------------------

    def relevance_prefetch(self, first_user_message: str) -> list[dict]:
        """Score topic files and recent daily notes against the user message.

        Returns a list of `{"kind": "topic"|"daily", "name": str, "content": str}`
        for every file whose match score exceeds 0. Caller injects them
        fully (no truncation) into the system prompt under a "likely
        relevant" block.
        """
        query_tokens = _tokenize(first_user_message)
        if not query_tokens:
            return []
        query_set = set(query_tokens)

        results: list[tuple[float, dict]] = []

        # Topic files
        for f in self._manifest_topic_files():
            try:
                content = f.read_text(encoding="utf-8")
            except Exception:
                continue
            score = _score_match(
                query_set,
                name=f.name,
                headline=_first_headline(content),
                body=content,
            )
            if score > 0:
                results.append((score, {
                    "kind": "topic",
                    "name": f.name,
                    "content": content,
                }))

        # Recent daily notes (last ~30), skipping today (already loaded)
        today = self._today_str()
        for entry in self.list_daily_notes(limit=30):
            if entry["date"] == today:
                continue
            content = self.read_daily_note(entry["date"])
            if not content:
                continue
            score = _score_match(
                query_set,
                name=entry["name"],
                headline=entry["headline"],
                body=content,
            )
            if score > 0:
                results.append((score, {
                    "kind": "daily",
                    "name": entry["date"],
                    "content": content,
                }))

        # Sort by score descending, no truncation
        results.sort(key=lambda pair: pair[0], reverse=True)
        return [item for _, item in results]


def _score_match(query_tokens: set[str], *, name: str, headline: str, body: str) -> float:
    """BM25-lite relevance score. Filename and headline hits are weighted
    heavier than body hits because they're stronger topic signals.
    """
    if not query_tokens:
        return 0.0
    name_tokens = set(_tokenize(name))
    headline_tokens = set(_tokenize(headline))
    body_tokens = _tokenize(body)
    body_set = set(body_tokens)

    score = 0.0
    # Filename overlap: strong signal
    score += 5.0 * len(query_tokens & name_tokens)
    # Headline overlap: strong signal
    score += 3.0 * len(query_tokens & headline_tokens)
    # Body overlap: presence signal + frequency bonus
    body_hits = query_tokens & body_set
    score += 1.0 * len(body_hits)
    if body_hits and body_tokens:
        # Small frequency bonus, diminishing returns
        freq = sum(body_tokens.count(t) for t in body_hits)
        score += min(freq * 0.05, 2.0)
    return score
