"""Live meeting HTTP surface: start/chunk/stop, session SSE, active, audio.

Mounted without a prefix (absolute paths) because it mixes agent-scoped
routes with the top-level /api/live/active reattach probe.
"""

import asyncio
import json
import logging
import re
import time

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel

from core.auth import get_current_user
from core.agents.live import session as live
from core.agents.live import pipeline
from core.agents.live.session import (
    CHUNK_EXTENSIONS,
    CHUNK_MAX_BYTES,
    CHUNK_SECONDS,
    LiveSession,
)

logger = logging.getLogger(__name__)

router = APIRouter()

_SID_RE = re.compile(r"^[a-f0-9]{12}$")


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data)}\n\n"


def _get_agent_or_404(agent_id: str) -> dict:
    from agents import db as agent_db

    agent = agent_db.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


def _session_or_404(session_id: str, agent: dict | None = None) -> LiveSession:
    session = live.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Live session not found")
    if agent is not None and session.agent_id != str(agent.get("id", "")):
        # Session ids are agent-scoped in the URL; don't accept cross-agent use.
        raise HTTPException(status_code=404, detail="Live session not found")
    return session


def _active_payload(session: LiveSession) -> dict:
    return {
        "session_id": session.session_id,
        "agent_id": session.agent_id,
        "agent_name": session.agent_name,
        "conversation_id": session.conversation_id,
        "state": session.status,
        "started_at": session.started_at,
        "last_chunk_index": max(session.segments) if session.segments else None,
        "chunk_seconds": CHUNK_SECONDS,
    }


class LiveStartRequest(BaseModel):
    prep_note: str = ""
    conversation_id: str | None = None


@router.post("/api/agents/{agent_id}/live/start")
async def live_start(agent_id: str, req: LiveStartRequest, user=Depends(get_current_user)):
    from agents.engine import get_chat_service
    from core.agents.transcription.audio import ffmpeg_available
    from core.agents.transcription.service import NO_PROVIDER_MESSAGE, pick_chunk_backend
    from core.providers import get_ai_provider

    agent = _get_agent_or_404(agent_id)

    active = live.get_active()
    if active is not None:
        if (active.agent_slug == agent["slug"]
                and req.conversation_id
                and active.conversation_id == req.conversation_id):
            return _active_payload(active)  # idempotent re-start
        raise HTTPException(status_code=409, detail={
            "error": "A live session is already active.",
            "active": _active_payload(active),
        })

    if not ffmpeg_available():
        raise HTTPException(status_code=400, detail=(
            "Live recording needs ffmpeg to stitch the meeting audio, and "
            "ffmpeg isn't installed."
        ))
    if pick_chunk_backend() is None:
        raise HTTPException(status_code=400, detail=NO_PROVIDER_MESSAGE)
    if get_ai_provider() is None:
        raise HTTPException(status_code=400, detail="No AI provider configured")

    # Control chars / newlines stripped: prep rides trusted prompt text and
    # YAML-ish status lines, so keep it a plain single line.
    prep = re.sub(r"\s+", " ", re.sub(r"[\x00-\x1f\x7f]", " ", req.prep_note or "")).strip()[:500]
    chat_service = get_chat_service(agent["slug"])
    conversation_id = req.conversation_id
    if not conversation_id:
        conv = chat_service.create_conversation(
            source="live", title=(prep[:60] or "Live meeting"))
        conversation_id = conv["id"]

    try:
        session = live.start_session(agent, conversation_id, prep)
    except RuntimeError:
        active = live.get_active()
        raise HTTPException(status_code=409, detail={
            "error": "A live session is already active.",
            "active": _active_payload(active) if active else None,
        })

    # Seed a user row: providers reject assistant-first conversations, and
    # this gives the meeting thread a sensible opening + title source.
    import uuid as _uuid
    try:
        seed = "[Live meeting session started]" if not prep else (
            f"[Live meeting session started — {prep}]")
        chat_service.save_message(conversation_id, str(_uuid.uuid4()), "user", seed)
    except Exception:
        logger.warning("Live seed message failed", exc_info=True)

    loop = asyncio.get_running_loop()
    session.worker_task = loop.create_task(pipeline.chunk_worker(session))
    session.watchdog_task = loop.create_task(pipeline.watchdog(session))

    async def _coach():
        from core.agents.live.coach import build_coach_context, coach_loop
        try:
            ctx = await asyncio.to_thread(build_coach_context, agent)
        except Exception:
            logger.exception("Coach context build failed; coaching disabled for %s",
                             session.session_id)
            return
        await coach_loop(session, ctx)

    session.coach_task = loop.create_task(_coach())

    logger.info("Live session %s started for %s (conversation %s)",
                session.session_id, agent["slug"], conversation_id)
    return _active_payload(session)


@router.post("/api/agents/{agent_id}/live/{session_id}/chunk")
async def live_chunk(agent_id: str, session_id: str, file: UploadFile,
                     index: int = Form(...), duration_ms: int | None = Form(None),
                     user=Depends(get_current_user)):
    from core.storage import atomic_write_bytes

    agent = _get_agent_or_404(agent_id)
    session = _session_or_404(session_id, agent)
    if session.status != "recording":
        raise HTTPException(status_code=409, detail="Session is not recording")
    if index < 0 or index >= live.MAX_CHUNKS:
        raise HTTPException(status_code=422, detail="Chunk index out of range")
    if index in session.segments:
        return {"duplicate": True, "index": index}

    ext = (file.filename or "").rsplit(".", 1)[-1].lower()
    if ext not in CHUNK_EXTENSIONS:
        raise HTTPException(status_code=422, detail=f"Unsupported chunk type .{ext}")

    data = await file.read(CHUNK_MAX_BYTES + 1)
    if len(data) > CHUNK_MAX_BYTES:
        raise HTTPException(status_code=413, detail="Chunk too large")
    if not data:
        raise HTTPException(status_code=422, detail="Empty chunk")

    filename = f"chunk-{index:05d}.{ext}"
    await asyncio.to_thread(atomic_write_bytes, session.chunk_dir / filename, data)
    # audio_seconds starts as the client hint; the worker overwrites it with
    # the ffprobe-measured duration once transcribed.
    seg = live.Segment(index=index, filename=filename, received_at=time.time(),
                       audio_seconds=(duration_ms or 0) / 1000)
    session.segments[index] = seg
    session.last_chunk_at = time.time()
    live.save_snapshot(session)  # accepted chunks are durable pre-transcription
    session.queue.put_nowait(index)
    live.emit(session, {"type": "chunk", "index": index, "status": "received",
                        "audio_seconds": round((duration_ms or 0) / 1000, 1)})
    return JSONResponse(status_code=202, content={"accepted": True, "index": index})


@router.post("/api/agents/{agent_id}/live/{session_id}/stop")
async def live_stop(agent_id: str, session_id: str, user=Depends(get_current_user)):
    agent = _get_agent_or_404(agent_id)
    session = _session_or_404(session_id, agent)
    pipeline.ensure_finalize(session, "stopped")
    return {"state": session.status}


@router.get("/api/agents/{agent_id}/live/{session_id}/events")
async def live_events(agent_id: str, session_id: str, user=Depends(get_current_user)):
    agent = _get_agent_or_404(agent_id)
    session = _session_or_404(session_id, agent)

    async def event_generator():
        q: asyncio.Queue = asyncio.Queue(maxsize=256)
        session.listeners.append(q)
        try:
            # Snapshot + coach replay on every (re)connect — the client's
            # catch-up mechanism (deduped by message id client-side).
            yield _sse(live.status_event(session))
            for ev in list(session.coach_events):
                yield _sse(ev)
            if session.status == "finalized":
                if session.done_event:
                    yield _sse(session.done_event)
                return
            while True:
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield _sse({"type": "ping"})
                    continue
                if ev.get("type") == "_close":
                    return
                yield _sse(ev)
        finally:
            try:
                session.listeners.remove(q)
            except ValueError:
                pass

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/api/live/active")
async def live_active(user=Depends(get_current_user)):
    session = live.get_active()
    return {"active": _active_payload(session) if session else None}


@router.get("/api/agents/{agent_id}/live/recordings/{session_id}/audio")
async def live_recording_audio(agent_id: str, session_id: str,
                               user=Depends(get_current_user)):
    agent = _get_agent_or_404(agent_id)
    if not _SID_RE.match(session_id):
        raise HTTPException(status_code=404, detail="Recording not found")
    path = live.recordings_dir(agent["slug"]) / session_id / "recording.mp3"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Recording not found")
    return FileResponse(path, media_type="audio/mpeg",
                        filename=f"meeting-{session_id}.mp3")
