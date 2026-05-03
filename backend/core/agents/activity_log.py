"""Chatty — Unified activity log for chat events.

Logs completed chat turns into the execution_history table alongside
scheduled action records. Provides a single activity stream across
web chat, Telegram, WhatsApp, and Paperclip.
"""

import json
import logging
import uuid
from datetime import datetime, timezone

from core.agents.reminders import db

logger = logging.getLogger(__name__)


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def _normalize_tool_calls(tool_calls: list[dict]) -> list[dict]:
    """Normalize tool call shapes: rename elapsed_ms → duration_ms."""
    normalized = []
    for tc in tool_calls:
        entry = dict(tc)
        if "elapsed_ms" in entry and "duration_ms" not in entry:
            entry["duration_ms"] = entry.pop("elapsed_ms")
        normalized.append(entry)
    return normalized


def log_chat_event(
    agent: str,
    *,
    conversation_id: str = "",
    source: str = "chat",
    status: str = "ok",
    result_summary: str = "",
    tool_calls: list | None = None,
    model_used: str = "",
    input_tokens: int = 0,
    output_tokens: int = 0,
    duration_ms: int = 0,
) -> str:
    """Record a completed chat turn in the unified activity log."""
    event_id = str(uuid.uuid4())
    now = _now_utc()

    if tool_calls:
        tool_calls = _normalize_tool_calls(tool_calls)
    tool_calls_json = json.dumps(tool_calls)[:10240] if tool_calls else None

    conn = db.get_db()
    with db.write_lock():
        conn.execute(
            """INSERT INTO execution_history
               (id, action_id, agent, action_type, event_type, source,
                conversation_id, started_at, completed_at, status,
                result_summary, tool_calls, model_used,
                input_tokens, output_tokens, duration_ms)
               VALUES (?, ?, ?, 'chat', 'chat', ?,
                       ?, ?, ?, ?,
                       ?, ?, ?,
                       ?, ?, ?)""",
            (event_id, event_id, agent, source,
             conversation_id, now, now, status,
             result_summary[:500], tool_calls_json, model_used,
             input_tokens, output_tokens, duration_ms),
        )
        conn.commit()
    return event_id
