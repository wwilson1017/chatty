"""Chatty — Memory + daily note tools.

Pure functions for the agent's living MEMORY.md snapshot and per-day daily
notes. All operations go through ContextManager so local writes and GCS
sync stay consistent with the rest of the context system.

Handlers take `(data_dir, gcs_prefix, ...)` and build a ContextManager
internally. Dispatched via `kind="memory"` in ToolRegistry.execute_tool.
"""

import hashlib
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from core.agents.context_manager import ContextManager
from core.agents.memory.types import validate_memory_type, type_tag

logger = logging.getLogger(__name__)

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
CT_TZ = ZoneInfo("America/Chicago")


def _make_cm(data_dir: str, gcs_prefix: str) -> ContextManager:
    return ContextManager(Path(data_dir), gcs_prefix)


# ---------------------------------------------------------------------------
# Write-ahead log for MEMORY.md
# ---------------------------------------------------------------------------

def _write_wal_entry(data_dir: str, source: str, previous_content: str, new_content_bytes: int) -> None:
    """Append a WAL entry before a MEMORY.md overwrite.  Fire-and-forget."""
    try:
        wal_path = Path(data_dir) / "memory_wal.jsonl"
        entry = {
            "timestamp": datetime.now(CT_TZ).isoformat(),
            "source": source,
            "previous_hash": hashlib.sha256(previous_content.encode()).hexdigest(),
            "previous_content": previous_content,
            "new_bytes": new_content_bytes,
        }
        with open(wal_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        logger.debug("Failed to write WAL entry", exc_info=True)


# ---------------------------------------------------------------------------
# Fire-and-forget FTS5 indexing
# ---------------------------------------------------------------------------

def _maybe_index_memory(data_dir: str, gcs_prefix: str, content: str) -> None:
    """Update the FTS5 index for MEMORY.md.  Non-critical."""
    try:
        from core.agents.memory.db import get_instance
        db = get_instance(data_dir)
        if db:
            db.index_document("memory", "MEMORY.md", "MEMORY.md", content)
    except Exception:
        logger.debug("FTS5 index update for MEMORY.md failed", exc_info=True)


def _maybe_index_daily(data_dir: str, gcs_prefix: str, note_date: str) -> None:
    """Re-index today's daily note in FTS5.  Non-critical."""
    try:
        from core.agents.memory.db import get_instance
        db = get_instance(data_dir)
        if db:
            cm = _make_cm(data_dir, gcs_prefix)
            content = cm.read_daily_note(note_date)
            if content:
                db.index_document("daily", note_date, note_date, content, date=note_date)
    except Exception:
        logger.debug("FTS5 index update for daily note %s failed", note_date, exc_info=True)


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------

def append_daily_note(
    data_dir: str,
    gcs_prefix: str,
    content: str,
    date: str | None = None,
    memory_type: str | None = None,
) -> dict:
    """Append a timestamped event to today's (or the specified day's) daily note."""
    if date is not None and not _DATE_RE.match(date):
        return {"error": f"date must be YYYY-MM-DD, got: {date}"}
    if not content or not content.strip():
        return {"error": "content is required"}

    # Prefix content with type tag if a valid memory type is provided
    validated_type = validate_memory_type(memory_type)
    if validated_type:
        content = f"{type_tag(validated_type)} {content}"

    result = _make_cm(data_dir, gcs_prefix).append_daily_note(content, date=date)

    # Fire-and-forget FTS5 indexing
    note_date = result.get("date") or date
    if note_date:
        _maybe_index_daily(data_dir, gcs_prefix, note_date)

    return result


def read_daily_note(data_dir: str, gcs_prefix: str, date: str) -> dict:
    """Read the full contents of a daily note for the given date."""
    if not _DATE_RE.match(date or ""):
        return {"error": f"date must be YYYY-MM-DD, got: {date}"}
    content = _make_cm(data_dir, gcs_prefix).read_daily_note(date)
    if not content:
        return {"date": date, "content": "", "exists": False}
    return {"date": date, "content": content, "exists": True}


def list_daily_notes(data_dir: str, gcs_prefix: str, limit: int = 30) -> dict:
    """List recent daily notes (newest first) with headlines."""
    try:
        limit = max(1, min(int(limit), 365))
    except (TypeError, ValueError):
        limit = 30
    notes = _make_cm(data_dir, gcs_prefix).list_daily_notes(limit=limit)
    return {"notes": notes}


def read_memory(data_dir: str, gcs_prefix: str) -> dict:
    """Return the current MEMORY.md content."""
    return {"content": _make_cm(data_dir, gcs_prefix).read_memory()}


def update_memory(data_dir: str, gcs_prefix: str, content: str) -> dict:
    """Overwrite MEMORY.md with new content.

    Always include the full desired content — this replaces the file.
    Agents should typically read_memory first, then write back the merged
    snapshot.
    """
    if content is None:
        return {"error": "content is required"}

    cm = _make_cm(data_dir, gcs_prefix)

    # WAL: save previous content before overwriting
    previous = cm.read_memory()
    _write_wal_entry(data_dir, "tool", previous, len(content.encode("utf-8")))

    cm.write_memory(content)

    # Update FTS5 index
    _maybe_index_memory(data_dir, gcs_prefix, content)

    return {"filename": "MEMORY.md", "ok": True}


def consolidate_memory(
    data_dir: str,
    gcs_prefix: str,
    api_key: str,
    days: int = 7,
) -> dict:
    """Regenerate MEMORY.md by synthesizing the last N days of daily notes.

    Calls Claude Sonnet with the current MEMORY.md + recent daily notes
    and asks for a tight, bulleted snapshot organized into Key People,
    Active Projects, Decisions, and Lessons Learned.
    """
    try:
        days = max(1, min(int(days), 90))
    except (TypeError, ValueError):
        days = 7

    if not api_key:
        return {"error": "no API key configured"}

    cm = _make_cm(data_dir, gcs_prefix)
    current_memory = cm.read_memory()
    notes = cm.list_daily_notes(limit=days)
    if not notes and not current_memory:
        return {"ok": False, "error": "nothing to consolidate — no MEMORY.md and no daily notes"}

    parts: list[str] = []
    if current_memory:
        parts.append("## Current MEMORY.md\n\n" + current_memory.strip())
    for entry in notes:
        content = cm.read_daily_note(entry["date"])
        if content:
            parts.append(f"## Daily note — {entry['date']}\n\n{content.strip()}")
    corpus = "\n\n---\n\n".join(parts)

    system_prompt = (
        "You maintain an AI agent's MEMORY.md — a living, bulleted snapshot of the "
        "most important durable knowledge the agent carries across sessions.\n\n"
        "Regenerate MEMORY.md by synthesizing the existing MEMORY.md (if any) with "
        "the recent daily notes below. Output MUST be markdown with exactly these "
        "four H2 sections, in this order:\n\n"
        "## Key People\n"
        "## Active Projects\n"
        "## Decisions\n"
        "## Lessons Learned\n\n"
        "Guidelines:\n"
        "- Keep it tight. One line per person / project / decision / lesson.\n"
        "- When synthesizing, weight items by durability:\n"
        "  - ALWAYS keep: decisions and preferences (these are durable knowledge).\n"
        "  - Keep if recent (last ~2 weeks): person context, insights, references.\n"
        "  - Keep if still relevant: milestones, ideas, problems.\n"
        "  - Drop when resolved: tasks, someday-maybe items.\n"
        "- If a daily note entry has a [type] tag (e.g. [decision], [task]), use it to "
        "judge importance per the durability tiers above.\n"
        "- Drop stale items that haven't been mentioned recently and no longer matter.\n"
        "- Preserve anything still relevant from the existing MEMORY.md even if it "
        "wasn't mentioned in the recent daily notes.\n"
        "- Do NOT wrap the output in triple backticks. Do NOT add preamble or "
        "explanation — emit ONLY the markdown.\n"
    )

    user_message = f"Regenerate MEMORY.md from the following material:\n\n{corpus}"

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4096,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )
    except Exception as e:
        logger.warning("consolidate_memory Claude call failed: %s", e)
        return {"error": f"Claude call failed: {e}"}

    new_memory = ""
    for block in response.content:
        if getattr(block, "type", None) == "text":
            new_memory += block.text

    new_memory = new_memory.strip()
    if not new_memory:
        return {"error": "Claude returned empty content"}

    # WAL: save previous content before overwriting
    _write_wal_entry(data_dir, "consolidation", current_memory, len(new_memory.encode("utf-8")))

    cm.write_memory(new_memory)

    # Update FTS5 index
    _maybe_index_memory(data_dir, gcs_prefix, new_memory)

    input_tokens = getattr(response.usage, "input_tokens", 0) if hasattr(response, "usage") else 0
    output_tokens = getattr(response.usage, "output_tokens", 0) if hasattr(response, "usage") else 0
    logger.info(
        "consolidate_memory wrote MEMORY.md (%d chars, tokens: %d/%d, days=%d)",
        len(new_memory), input_tokens, output_tokens, days,
    )
    return {
        "ok": True,
        "filename": "MEMORY.md",
        "bytes_written": len(new_memory),
        "days_synthesized": days,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
    }
