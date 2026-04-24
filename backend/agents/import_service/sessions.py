"""In-memory registry of active import sessions."""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field

from .adapters.base import SourceAdapter

logger = logging.getLogger(__name__)

SESSION_TTL = 30 * 60  # 30 minutes


@dataclass
class ImportSession:
    token: str
    adapter: SourceAdapter
    agent_id: str
    conversation_id: str
    started_at: float = field(default_factory=time.time)
    skipped_files: set[str] = field(default_factory=set)


_sessions: dict[str, ImportSession] = {}
_lock = threading.Lock()


def create_session(
    adapter: SourceAdapter,
    agent_id: str,
    conversation_id: str,
) -> ImportSession:
    token = str(uuid.uuid4())
    session = ImportSession(
        token=token,
        adapter=adapter,
        agent_id=agent_id,
        conversation_id=conversation_id,
    )
    with _lock:
        _sessions[token] = session
    return session


def get_session(token: str) -> ImportSession | None:
    with _lock:
        session = _sessions.get(token)
    if session and (time.time() - session.started_at) > SESSION_TTL:
        remove_session(token)
        return None
    return session


def get_session_by_conversation(conversation_id: str) -> ImportSession | None:
    with _lock:
        for s in _sessions.values():
            if s.conversation_id == conversation_id:
                if (time.time() - s.started_at) > SESSION_TTL:
                    _sessions.pop(s.token, None)
                    return None
                return s
    return None


def remove_session(token: str) -> None:
    with _lock:
        session = _sessions.pop(token, None)
    if session:
        try:
            session.adapter.close()
        except Exception:
            logger.warning("Failed to close adapter for session %s", token)


def sweep_expired() -> int:
    """Remove expired sessions. Returns count removed."""
    now = time.time()
    expired: list[str] = []
    with _lock:
        for token, session in _sessions.items():
            if now - session.started_at > SESSION_TTL:
                expired.append(token)
    for token in expired:
        remove_session(token)
    return len(expired)
