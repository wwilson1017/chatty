"""Live meeting session state, registry, and conversation busy map.

One live session may be active at a time (single-user app). The in-memory
LiveSession is authoritative while the server runs; session.json in the
chunk dir is a write-through snapshot consumed only by startup recovery and
post-restart /live/active. Chunk files on disk are ground truth for audio.
"""

import asyncio
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from core.storage import atomic_write_json

logger = logging.getLogger(__name__)

# ── Tunables ────────────────────────────────────────────────────────────────
CHUNK_SECONDS = 20                  # client records chunks of this length
IDLE_FINALIZE_S = 600               # no chunks for 10 min → finalize
MAX_SESSION_S = 6 * 3600            # mirror transcription's 6 h cap
GAP_THRESHOLD_S = 90                # arrival gap that marks an interruption
COACH_MIN_GAP_S = 45                # min seconds between coach turns
COACH_MIN_NEW_CHARS = 250           # min new transcript chars to run coach
ESCALATE_MIN_GAP_S = 150            # min seconds between top-tier escalations
COACH_TRANSCRIPT_TAIL = 30_000      # transcript chars sent to coach turns
CHAT_INJECT_TAIL = 24_000           # transcript chars injected into user turns
CHUNK_MAX_BYTES = 15 * 1024 * 1024  # single-chunk upload cap
MAX_CHUNKS = 2000                   # hard stop (≈11 h at 20 s — belt for 6 h cap)
TURN_TIMEOUT_S = 240                # coach turn wall-clock cap
TURN_TIMEOUT_LONG_S = 360           # escalated / wrap-up turn cap

CHUNK_EXTENSIONS = {"webm", "mp4", "m4a", "ogg", "opus", "wav"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Segment:
    index: int
    filename: str
    status: str = "pending"          # pending | done | failed
    text: str = ""
    audio_seconds: float = 0.0
    received_at: float = 0.0         # time.time() at accept — durable gap basis
    gap_before: bool = False


@dataclass
class LiveSession:
    session_id: str
    agent_id: str
    agent_slug: str
    agent_name: str
    conversation_id: str
    prep_note: str
    chunk_dir: Path
    status: str = "recording"        # recording | finalizing | finalized
    started_at: str = field(default_factory=_now_iso)
    last_chunk_at: float = field(default_factory=time.time)
    segments: dict[int, Segment] = field(default_factory=dict)

    # usage accumulators (live chunk transcription)
    chunk_input_tokens: int = 0
    chunk_output_tokens: int = 0
    chunk_audio_seconds: float = 0.0
    chunk_model: str = ""
    chunk_provider: str = ""

    # coach state
    coach_last_run_at: float = 0.0
    coach_last_escalate_at: float = 0.0
    reviewed_indexes: set[int] = field(default_factory=set)
    escalations: int = 0
    ack_posted: bool = False  # first-chunk health message sent (runtime-only)

    # finalize step flags (persisted so a crashed finalize resumes)
    finalize_reason: str = ""
    meeting_filename: str = ""
    meeting_title: str = ""
    usage_logged: bool = False
    wrapup_done: bool = False
    duration_seconds: float = 0.0
    finalize_error: str = ""

    # runtime-only (never serialized)
    queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    wake: asyncio.Event = field(default_factory=asyncio.Event)
    listeners: list[asyncio.Queue] = field(default_factory=list)
    coach_events: list[dict] = field(default_factory=list)
    done_event: dict | None = None  # retained for post-finalize reconnects
    worker_task: asyncio.Task | None = None
    coach_task: asyncio.Task | None = None
    watchdog_task: asyncio.Task | None = None
    finalize_task: asyncio.Task | None = None

    # ── snapshot ──────────────────────────────────────────────────────────
    def to_snapshot(self) -> dict:
        return {
            "session_id": self.session_id,
            "agent_id": self.agent_id,
            "agent_slug": self.agent_slug,
            "agent_name": self.agent_name,
            "conversation_id": self.conversation_id,
            "prep_note": self.prep_note,
            "status": self.status,
            "started_at": self.started_at,
            "last_chunk_at": self.last_chunk_at,
            "segments": [
                {
                    "index": s.index, "filename": s.filename, "status": s.status,
                    "text": s.text, "audio_seconds": s.audio_seconds,
                    "received_at": s.received_at, "gap_before": s.gap_before,
                }
                for s in sorted(self.segments.values(), key=lambda s: s.index)
            ],
            "chunk_input_tokens": self.chunk_input_tokens,
            "chunk_output_tokens": self.chunk_output_tokens,
            "chunk_audio_seconds": self.chunk_audio_seconds,
            "chunk_model": self.chunk_model,
            "chunk_provider": self.chunk_provider,
            "finalize_reason": self.finalize_reason,
            "meeting_filename": self.meeting_filename,
            "meeting_title": self.meeting_title,
            "usage_logged": self.usage_logged,
            "wrapup_done": self.wrapup_done,
            "duration_seconds": self.duration_seconds,
            "finalize_error": self.finalize_error,
        }

    @classmethod
    def from_snapshot(cls, data: dict, chunk_dir: Path) -> "LiveSession":
        session = cls(
            session_id=data["session_id"],
            agent_id=data.get("agent_id", ""),
            agent_slug=data.get("agent_slug", ""),
            agent_name=data.get("agent_name", ""),
            conversation_id=data.get("conversation_id", ""),
            prep_note=data.get("prep_note", ""),
            chunk_dir=chunk_dir,
            status=data.get("status", "recording"),
            started_at=data.get("started_at", _now_iso()),
            last_chunk_at=data.get("last_chunk_at", 0.0),
        )
        for seg in data.get("segments", []):
            session.segments[int(seg["index"])] = Segment(
                index=int(seg["index"]), filename=seg.get("filename", ""),
                status=seg.get("status", "pending"), text=seg.get("text", ""),
                audio_seconds=seg.get("audio_seconds", 0.0) or 0.0,
                received_at=seg.get("received_at", 0.0) or 0.0,
                gap_before=bool(seg.get("gap_before")),
            )
        session.chunk_input_tokens = data.get("chunk_input_tokens", 0) or 0
        session.chunk_output_tokens = data.get("chunk_output_tokens", 0) or 0
        session.chunk_audio_seconds = data.get("chunk_audio_seconds", 0.0) or 0.0
        session.chunk_model = data.get("chunk_model", "") or ""
        session.chunk_provider = data.get("chunk_provider", "") or ""
        session.finalize_reason = data.get("finalize_reason", "") or ""
        session.meeting_filename = data.get("meeting_filename", "") or ""
        session.meeting_title = data.get("meeting_title", "") or ""
        session.usage_logged = bool(data.get("usage_logged"))
        session.wrapup_done = bool(data.get("wrapup_done"))
        session.duration_seconds = data.get("duration_seconds", 0.0) or 0.0
        session.finalize_error = data.get("finalize_error", "") or ""
        return session


def save_snapshot(session: LiveSession) -> None:
    try:
        atomic_write_json(session.chunk_dir / "session.json", session.to_snapshot())
    except Exception:
        logger.warning("Live session snapshot failed for %s", session.session_id, exc_info=True)


def load_snapshot(path: Path) -> LiveSession | None:
    try:
        import json
        data = json.loads(path.read_text(encoding="utf-8"))
        return LiveSession.from_snapshot(data, path.parent)
    except Exception:
        logger.warning("Unreadable live session snapshot: %s", path, exc_info=True)
        return None


# ── Registry (one active session) ───────────────────────────────────────────
# Process-local by design: Chatty deploys as a single uvicorn process (no
# --workers), matching every other in-process registry here (APScheduler,
# import sessions, telegram busy map). Multi-worker would need shared state.

_active: LiveSession | None = None
_last_finalized: LiveSession | None = None  # kept so a reloading client can
# still resolve /events for the just-finished session and replay `done`
_registry_lock = threading.Lock()


def recordings_dir(agent_slug: str) -> Path:
    # DATA_DIR already ends in data/agents — do not append another "agents/"
    from agents.engine import DATA_DIR
    return Path(DATA_DIR) / agent_slug / "recordings"


def start_session(agent: dict, conversation_id: str, prep_note: str) -> LiveSession:
    """Create and register the active session. Raises RuntimeError if another
    session is active (caller maps to 409 / idempotent 200)."""
    global _active
    with _registry_lock:
        if _active is not None and _active.status != "finalized":
            raise RuntimeError("another live session is active")
        session_id = uuid.uuid4().hex[:12]
        chunk_dir = recordings_dir(agent["slug"]) / session_id
        chunk_dir.mkdir(parents=True, exist_ok=True)
        session = LiveSession(
            session_id=session_id,
            agent_id=str(agent.get("id", "")),
            agent_slug=agent["slug"],
            agent_name=agent.get("agent_name", agent.get("name", "")) or agent["slug"],
            conversation_id=conversation_id,
            prep_note=prep_note,
            chunk_dir=chunk_dir,
        )
        _active = session
    save_snapshot(session)
    return session


def get_active() -> LiveSession | None:
    with _registry_lock:
        return _active if (_active and _active.status != "finalized") else None


def get_session(session_id: str) -> LiveSession | None:
    with _registry_lock:
        if _active and _active.session_id == session_id:
            return _active
        if _last_finalized and _last_finalized.session_id == session_id:
            return _last_finalized
    return None


def get_active_for_conversation(agent_slug: str, conversation_id: str) -> LiveSession | None:
    session = get_active()
    if session and session.agent_slug == agent_slug and session.conversation_id == conversation_id:
        return session
    return None


def clear_active(session: LiveSession) -> None:
    global _active, _last_finalized
    with _registry_lock:
        if _active is session:
            _active = None
        if session.status == "finalized":
            _last_finalized = session


def adopt_active(session: LiveSession) -> bool:
    """Register a recovered session as active if the slot is free (startup)."""
    global _active
    with _registry_lock:
        if _active is not None and _active.status != "finalized":
            return False
        _active = session
        return True


# ── Conversation busy map (mirrors integrations/telegram/router.py) ────────
# Reference-counted: a user chat stream and a coach turn can hold leases on
# the same conversation concurrently — one holder finishing must not clear
# the other's lease. Each lease is a timestamp; stale ones (crashed holders
# that never cleared) age out via the TTL.

_busy: dict[str, list[float]] = {}
_busy_lock = threading.Lock()
_BUSY_TTL = 300  # stale leases treated as hung requests


def mark_conversation_busy(conversation_id: str) -> None:
    if not conversation_id:
        return
    with _busy_lock:
        _busy.setdefault(conversation_id, []).append(time.time())


def clear_conversation_busy(conversation_id: str) -> None:
    if not conversation_id:
        return
    with _busy_lock:
        leases = _busy.get(conversation_id)
        if leases:
            leases.pop(0)
        if not leases:
            _busy.pop(conversation_id, None)


def is_conversation_busy(conversation_id: str) -> bool:
    if not conversation_id:
        return False
    now = time.time()
    with _busy_lock:
        leases = [ts for ts in _busy.get(conversation_id, []) if now - ts <= _BUSY_TTL]
        if leases:
            _busy[conversation_id] = leases
            return True
        _busy.pop(conversation_id, None)
        return False


# ── Transcript assembly ─────────────────────────────────────────────────────

def transcript_text(session: LiveSession, *, tail_chars: int | None = None) -> str:
    """Rolling transcript: segments sorted by index, with gap/failure markers.

    Indexes with no Segment at all (chunk lost client-side or dropped at
    upload) get a synthesized marker too — an absent chunk must not read as
    a continuous transcript."""
    parts: list[str] = []
    prev_index = -1  # index 0 lost → leading marker, per the contract above
    for seg in sorted(session.segments.values(), key=lambda s: s.index):
        if seg.index > prev_index + 1:
            parts.append("[missing audio segment]")
        prev_index = seg.index
        if seg.gap_before:
            parts.append("[recording gap — interruption]")
        if seg.status == "failed":
            parts.append("[transcription gap]")
        elif seg.status == "done" and seg.text:
            parts.append(seg.text)
    text = "\n".join(parts).strip()
    if tail_chars and len(text) > tail_chars:
        text = "…" + text[-tail_chars:]
    return text


# ── Direct agent messages (no LLM call) ─────────────────────────────────────

def post_assistant_message(session: LiveSession, content: str) -> None:
    """Save a canned assistant message to the conversation and push it over
    the session SSE stream — used for instant status messages (recording
    health ack, transcription-failure warning) that need no model call."""
    import uuid as _uuid
    from datetime import datetime as _dt, timezone as _tz

    from agents.engine import get_chat_service

    msg_id = str(_uuid.uuid4())
    try:
        get_chat_service(session.agent_slug).save_message(
            session.conversation_id, msg_id, "assistant", content)
    except Exception:
        logger.warning("Live status message save failed", exc_info=True)
        return
    emit(session, {
        "type": "coach",
        "message": {"id": msg_id, "role": "assistant", "content": content,
                    "model": "", "created_at": _dt.now(_tz.utc).isoformat()},
        "tier": "status", "escalated": False, "wrapup": False,
    })


# ── SSE fan-out ─────────────────────────────────────────────────────────────

def emit(session: LiveSession, event: dict) -> None:
    """Push an event to every listener queue; retain coach events for replay."""
    if event.get("type") == "coach":
        session.coach_events.append(event)
        # Replay buffer cap: reconnects lose the oldest nudges past this
        # (they're still in the conversation itself).
        if len(session.coach_events) > 500:
            del session.coach_events[0]
    terminal = event.get("type") in ("done", "_close")
    for q in list(session.listeners):
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            if terminal:
                # Terminal events must land or the stream never closes —
                # evict the oldest buffered event to make room.
                try:
                    q.get_nowait()
                    q.put_nowait(event)
                except (asyncio.QueueEmpty, asyncio.QueueFull):
                    logger.warning("Live SSE listener wedged; terminal event dropped")
            else:
                logger.debug("Live SSE listener queue full; dropping event")


def status_event(session: LiveSession) -> dict:
    segs = session.segments.values()
    return {
        "type": "status",
        "state": session.status,
        "session_id": session.session_id,
        "conversation_id": session.conversation_id,
        "started_at": session.started_at,
        "last_chunk_at": session.last_chunk_at,
        "chunks_received": len(session.segments),
        "chunks_transcribed": sum(1 for s in segs if s.status == "done"),
        "chunks_failed": sum(1 for s in segs if s.status == "failed"),
        "audio_seconds": round(session.chunk_audio_seconds, 1),
        "escalations": session.escalations,
    }


# ── Mid-meeting chat context (volatile system-prompt hook) ─────────────────

def live_meeting_block(agent_slug: str, conversation_id: str | None) -> str:
    """Appended to the volatile system prompt of user chat turns while a live
    meeting is recording in this conversation. Empty string otherwise."""
    if not conversation_id:
        return ""
    session = get_active_for_conversation(agent_slug, conversation_id)
    if session is None or session.status != "recording":
        return ""
    from core.agents.security.delimiters import wrap_result

    tail = transcript_text(session, tail_chars=CHAT_INJECT_TAIL)
    prep = f"\nMeeting context from the user: {session.prep_note}" if session.prep_note else ""
    return (
        "\n\n# Live Meeting In Progress\n\n"
        "A live meeting is being recorded in this conversation right now; the "
        "user is likely mid-meeting, so keep replies brief and immediately "
        f"useful.{prep}\n"
        "The rolling machine transcript so far (partial, no speaker labels; "
        "an automatic coach also posts into this thread):\n\n"
        + wrap_result("live_meeting_transcript", tail or "(nothing transcribed yet)")
    )
