"""
Chatty — conversation history for an external runtime.

Hermes runs do not hydrate history from their session; every run carries the
conversation as `[{role, content}]`. This builds that list from Chatty's
mirror, reusing the native compaction fold and truncation helpers, text-only
(tool cards are display metadata and never travel), coalesced so no two
same-role rows are adjacent, and bounded to a hard character budget.
"""

from __future__ import annotations

import os

from core.agents.context_assembly import (
    HEAD_MSGS,
    _apply_compaction,
    _coalesce_consecutive,
    _truncate_text,
)

HISTORY_CHAR_BUDGET = int(os.environ.get("HERMES_HISTORY_CHAR_BUDGET", "60000"))
MAX_ROW_CHARS = int(os.environ.get("HERMES_MAX_ROW_CHARS", "8000"))
SNAPSHOT_CHAR_CAP = int(os.environ.get("HERMES_SNAPSHOT_CHAR_CAP", "40000"))
# Protected prefix (opening exchange + compaction-folded row) may use at most
# this share of the budget before it is itself truncated.
_PROTECTED_SHARE = 0.25


def _size(messages: list[dict]) -> int:
    return sum(len(m.get("content") or "") for m in messages)


def build_conversation_history(rows: list[dict], summary: str | None,
                               first_kept_seq: int | None,
                               *, budget: int = HISTORY_CHAR_BUDGET,
                               max_row_chars: int = MAX_ROW_CHARS) -> list[dict]:
    """rows: chat.db message rows (role/content/seq/...), oldest first, with
    the not-yet-sent user turn already excluded."""
    rows = [r for r in rows if r.get("role") in ("user", "assistant")]
    compacted = bool(summary and first_kept_seq is not None and len(rows) > HEAD_MSGS)
    rows = _apply_compaction(rows, summary, first_kept_seq)

    text_only = []
    for r in rows:
        content = r.get("content") or ""
        if not content:
            continue  # tool-only assistant iteration with no text
        text_only.append({"role": r["role"], "content": _truncate_text(content, max_row_chars)})

    messages = _coalesce_consecutive(text_only)

    # Protected prefix: HEAD_MSGS rows, plus the row the gist was folded into
    # (it directly follows the head after compaction).
    protected_n = min(len(messages), HEAD_MSGS + (1 if compacted else 0))

    # Trim whole exchanges (a user row and the assistant row that follows it)
    # after the protected prefix, oldest first, until within budget.
    while _size(messages) > budget and len(messages) > protected_n:
        i = protected_n
        # find the first user row at/after the boundary
        while i < len(messages) and messages[i]["role"] != "user":
            i += 1
        if i >= len(messages) - 1:
            break  # nothing droppable but the newest exchange
        end = i + 1
        if end < len(messages) and messages[end]["role"] == "assistant":
            end += 1
        del messages[i:end]
        messages = _coalesce_consecutive(messages)

    # Final hard bound: oversized protected rows are cut to their share.
    protected = messages[:protected_n]
    if protected and _size(protected) > budget * _PROTECTED_SHARE:
        per_row = max(200, int(budget * _PROTECTED_SHARE / len(protected)))
        for m in protected:
            m["content"] = _truncate_text(m["content"], per_row)
    if _size(messages) > budget:
        # Last resort: cap every remaining row proportionally.
        per_row = max(200, budget // max(1, len(messages)))
        for m in messages:
            m["content"] = _truncate_text(m["content"], per_row)
    return messages


def build_snapshot(personality: str, context_text: str, agent_name: str) -> str:
    """The immutable per-conversation context snapshot sent as `instructions`."""
    parts = [
        f"You are running behind Chatty as the agent \"{agent_name}\". "
        "The following is this agent's personality and knowledge as recorded in Chatty. "
        "Chatty tools may also be available to you over MCP.",
    ]
    if personality:
        parts.append(f"## Personality\n{personality}")
    if context_text:
        parts.append(f"## Knowledge\n{context_text}")
    text = "\n\n".join(parts)
    if len(text) > SNAPSHOT_CHAR_CAP:
        text = text[:SNAPSHOT_CHAR_CAP] + "\n…[snapshot truncated]"
    return text
