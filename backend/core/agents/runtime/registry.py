"""In-memory registry of live Hermes runs (the durable half is external_turns)."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

_TERMINAL_TTL_S = 600


@dataclass
class RunEntry:
    run_id: str
    agent_id: str
    conversation_id: str
    turn_id: str
    # request_id -> "pending" | "submitting" | "responded" | "expired" | "uncertain"
    pending_approvals: dict[str, str] = field(default_factory=dict)
    # request_id -> confirm payload (for handle_approval to echo back)
    approval_meta: dict[str, dict] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    terminal_at: float | None = None


_runs: dict[str, RunEntry] = {}
_by_conversation: dict[tuple[str, str], str] = {}


def register(run_id: str, agent_id: str, conversation_id: str, turn_id: str) -> RunEntry:
    sweep()
    entry = RunEntry(run_id, agent_id, conversation_id, turn_id)
    _runs[run_id] = entry
    _by_conversation[(agent_id, conversation_id)] = run_id
    return entry


def get(run_id: str) -> RunEntry | None:
    return _runs.get(run_id)


def get_by_conversation(agent_id: str, conversation_id: str) -> RunEntry | None:
    run_id = _by_conversation.get((agent_id, conversation_id))
    return _runs.get(run_id) if run_id else None


def finish(run_id: str) -> None:
    entry = _runs.get(run_id)
    if entry:
        entry.terminal_at = time.time()


def sweep(now: float | None = None) -> None:
    now = now or time.time()
    for run_id, entry in list(_runs.items()):
        if entry.terminal_at and now - entry.terminal_at > _TERMINAL_TTL_S:
            _runs.pop(run_id, None)
            key = (entry.agent_id, entry.conversation_id)
            if _by_conversation.get(key) == run_id:
                _by_conversation.pop(key, None)


def _reset_for_tests() -> None:
    _runs.clear()
    _by_conversation.clear()
