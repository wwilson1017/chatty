"""Live meeting pipeline: chunk worker, watchdog, and the finalize chain.

Finalize is an idempotent, resumable step chain: every step is flag- or
artifact-guarded so a crash mid-finalize resumes at server startup without
repeating completed work, and audio chunks are never deleted unless the
stitched recording exists.
"""

import asyncio
import logging
import time
from pathlib import Path

from core.agents.live import session as live
from core.agents.live.session import (
    GAP_THRESHOLD_S,
    IDLE_FINALIZE_S,
    MAX_CHUNKS,
    MAX_SESSION_S,
    LiveSession,
    save_snapshot,
)

logger = logging.getLogger(__name__)


async def chunk_worker(session: LiveSession) -> None:
    """Transcribe accepted chunks in arrival order."""
    from core.agents.transcription.service import transcribe_chunk

    while True:
        idx = await session.queue.get()
        seg = session.segments.get(idx)
        if seg is None or seg.status != "pending":
            continue
        path = session.chunk_dir / seg.filename
        ext = seg.filename.rsplit(".", 1)[-1].lower()
        prev = session.segments.get(idx - 1)
        prev_tail = prev.text[-200:] if (prev and prev.status == "done") else ""

        result = None
        for attempt in (1, 2):
            try:
                result = await asyncio.wait_for(
                    transcribe_chunk(path, ext=ext, prev_tail=prev_tail,
                                     client_duration_s=seg.audio_seconds or None),
                    timeout=90,
                )
                break
            except Exception as e:
                # Broad by design: one bad chunk (provider error, timeout, or
                # even a bug) must never kill the session — mark it failed and
                # keep recording; the archival pass recovers its audio.
                logger.warning("Chunk %s transcription attempt %d failed: %s", idx, attempt, e)
                if attempt == 1:
                    await asyncio.sleep(_RETRY_DELAY_S)

        if result is None:
            seg.status = "failed"
        else:
            seg.status = "done"
            seg.text = result["text"]
            seg.audio_seconds = result["duration_seconds"] or 0.0
            session.chunk_input_tokens += result["input_tokens"]
            session.chunk_output_tokens += result["output_tokens"]
            session.chunk_audio_seconds += seg.audio_seconds
            session.chunk_model = result["model"]
            session.chunk_provider = result["provider"]

        if prev and seg.received_at and prev.received_at:
            seg.gap_before = (seg.received_at - prev.received_at) > GAP_THRESHOLD_S

        save_snapshot(session)
        live.emit(session, {
            "type": "chunk", "index": idx, "status": seg.status,
            "audio_seconds": round(seg.audio_seconds, 1),
        })

        # First-chunk health ack: the moment mic → upload → transcription is
        # proven end-to-end, the agent says so in chat (canned, no LLM call).
        # A failing first chunk gets a warning instead. Text-only — nothing
        # audible or push-notified, so it can't disrupt the room.
        if not session.ack_posted:
            session.ack_posted = True
            if seg.status == "done":
                prep = (f" Noted: {session.prep_note}." if session.prep_note else "")
                live.post_assistant_message(session, (
                    "🎙️ Recording started — I'm listening, and the first bit of "
                    f"audio came through clean.{prep} If it helps me coach, tell "
                    "me what kind of meeting this is and who's in the room — or "
                    "just ignore me and I'll follow along. I'll jump in when I "
                    "have something useful."
                ))
            else:
                live.post_assistant_message(session, (
                    "⚠️ Recording is running and your audio is being saved, but "
                    "transcription failed on the first segment — live coaching "
                    "won't work until it recovers. Check your OpenAI/Gemini key "
                    "in Settings if this persists. The full recording will "
                    "still be transcribed at the end if possible."
                ))

        if seg.status == "done" and seg.text:
            session.wake.set()


_WATCHDOG_INTERVAL_S = 30
_RETRY_DELAY_S = 5.0  # pause between chunk transcription attempts


async def watchdog(session: LiveSession) -> None:
    """Finalize abandoned or over-length sessions."""
    started = time.time()
    while session.status == "recording":
        await asyncio.sleep(_WATCHDOG_INTERVAL_S)
        if session.status != "recording":
            return
        if time.time() - session.last_chunk_at > IDLE_FINALIZE_S:
            ensure_finalize(session, "idle timeout")
            return
        if time.time() - started > MAX_SESSION_S:
            ensure_finalize(session, "6-hour limit")
            return
        if len(session.segments) >= MAX_CHUNKS:
            ensure_finalize(session, "chunk limit")
            return


def ensure_finalize(session: LiveSession, reason: str) -> asyncio.Task:
    """Create the finalize task exactly once (stop + watchdog + double-stop safe).

    All callers run on the single event loop, so create-once needs no lock.
    A finalize that crashes is picked up by startup recovery, not retried here.
    """
    if session.finalize_task is None:
        session.finalize_task = asyncio.get_running_loop().create_task(
            finalize(session, reason)
        )
    return session.finalize_task


def _chunk_files(session: LiveSession) -> list[Path]:
    """Chunk files on disk, sorted by index — ground truth for audio."""
    return sorted(session.chunk_dir.glob("chunk-*.*"))


async def finalize(session: LiveSession, reason: str) -> None:
    from agents.engine import DATA_DIR
    from core.agents.activity_log import log_transcription_event
    from core.agents.live.coach import build_coach_context, run_coach_turn
    from core.agents.tools.memory_tools import save_meeting_transcript
    from core.agents.transcription.audio import concat_audio, probe_duration_seconds
    from core.agents.transcription.service import pick_backend, transcribe_file

    if session.status == "finalized":
        return
    logger.info("Finalizing live session %s (%s)", session.session_id, reason)

    # 1. Flip state; chunk route now rejects; stop coach + watchdog.
    session.status = "finalizing"
    session.finalize_reason = session.finalize_reason or reason
    save_snapshot(session)
    live.emit(session, live.status_event(session))
    if session.watchdog_task and not session.watchdog_task.done():
        session.watchdog_task.cancel()
    if session.coach_task and not session.coach_task.done():
        try:
            await asyncio.wait_for(asyncio.shield(session.coach_task), timeout=10)
        except (asyncio.TimeoutError, Exception):
            session.coach_task.cancel()

    # 2. Drain the worker briefly, then cancel — stragglers only affect the
    #    live transcript; the archival pass re-transcribes the whole file.
    drain_deadline = time.time() + 120
    while (any(s.status == "pending" for s in session.segments.values())
           and time.time() < drain_deadline):
        if session.worker_task is None or session.worker_task.done():
            break  # no worker (orphan recovery) — pending chunks can't drain
        await asyncio.sleep(2)
    if session.worker_task and not session.worker_task.done():
        session.worker_task.cancel()

    recording = session.chunk_dir / "recording.mp3"
    chunks = _chunk_files(session)

    # 3. Concat (skip if already done — resumed finalize).
    if not recording.exists() and chunks:
        live.emit(session, {"type": "finalize", "stage": "concat",
                            "message": "Stitching recording…", "percent": None})
        try:
            await asyncio.to_thread(concat_audio, chunks, recording)
        except Exception:
            session.finalize_error = "Failed to stitch the recording — chunk files kept; see server logs."
            logger.exception("Concat failed for %s — keeping chunk files", session.session_id)
    if recording.exists():
        session.duration_seconds = (
            await asyncio.to_thread(probe_duration_seconds, recording)
            or session.chunk_audio_seconds
        )
        for chunk in chunks:
            try:
                chunk.unlink()
            except OSError:
                pass
    else:
        session.duration_seconds = session.chunk_audio_seconds
    save_snapshot(session)

    # 4. Archival transcript: whole-file pass over the stitched recording for
    #    whichever backend exists (recovers never-live-transcribed chunks);
    #    stitched live text is the fallback.
    transcript = ""
    transcribed_by = session.chunk_model
    if recording.exists() and pick_backend() is not None and not session.meeting_filename:
        try:
            async for ev in transcribe_file(recording, "recording.mp3"):
                if ev.get("done"):
                    transcript = ev["transcript"]
                    transcribed_by = ev["model"]
                    if not session.duration_seconds:
                        session.duration_seconds = ev.get("duration_seconds", 0.0)
                    if not session.usage_logged:
                        try:
                            log_transcription_event(
                                session.agent_slug,
                                conversation_id=session.conversation_id,
                                source_filename=f"recordings/{session.session_id}/recording.mp3",
                                provider=ev.get("provider", ""),
                                model_used=ev["model"],
                                audio_seconds=int(ev.get("duration_seconds") or 0),
                                input_tokens=ev.get("input_tokens", 0),
                                output_tokens=ev.get("output_tokens", 0),
                            )
                        except Exception:
                            logger.warning("Archival usage log failed", exc_info=True)
                else:
                    live.emit(session, {"type": "finalize", "stage": "transcribing",
                                        "message": ev.get("message", ""),
                                        "percent": ev.get("percent")})
        except Exception as e:
            logger.warning("Archival re-transcription failed (%s); using live text", e)
    if not transcript:
        transcript = "[Live-transcribed in chunks; no speaker labels.]\n\n" + (
            live.transcript_text(session) or "(no speech captured)"
        )

    # 5. Save the meeting once.
    if not session.meeting_filename:
        live.emit(session, {"type": "finalize", "stage": "saving",
                            "message": "Saving transcript…", "percent": None})
        title = (session.prep_note[:60].strip() or "Live meeting")
        try:
            saved = save_meeting_transcript(
                str(Path(DATA_DIR) / session.agent_slug / "context"),
                f"agents/{session.agent_slug}/context/",
                title,
                transcript,
                duration_seconds=int(session.duration_seconds or 0),
                source_filename=(
                    f"recordings/{session.session_id}/recording.mp3"
                    if recording.exists() else ""
                ),
                transcribed_by=transcribed_by or "live",
            )
            session.meeting_filename = saved.get("filename", "")
            session.meeting_title = saved.get("title", title)
        except Exception:
            session.finalize_error = "Failed to save the meeting transcript — see server logs."
            logger.exception("save_meeting_transcript failed for %s", session.session_id)
    save_snapshot(session)

    # 6. One aggregate usage row for the live chunk transcription.
    if not session.usage_logged and session.segments:
        try:
            log_transcription_event(
                session.agent_slug,
                conversation_id=session.conversation_id,
                source_filename=(
                    f"recordings/{session.session_id}/recording.mp3 "
                    f"({len(session.segments)} live chunks)"
                ),
                provider=session.chunk_provider,
                model_used=session.chunk_model or "live-chunks",
                audio_seconds=int(session.chunk_audio_seconds),
                input_tokens=session.chunk_input_tokens,
                output_tokens=session.chunk_output_tokens,
            )
        except Exception:
            logger.warning("Chunk usage log failed", exc_info=True)
    session.usage_logged = True
    save_snapshot(session)

    # 7. Wrap-up turn (ungated), posted into the conversation.
    if not session.wrapup_done:
        live.emit(session, {"type": "finalize", "stage": "wrapup",
                            "message": "Writing wrap-up…", "percent": None})
        try:
            from agents import db as agent_db
            agent = next((a for a in agent_db.list_agents()
                          if a["slug"] == session.agent_slug), None)
            if agent is not None:
                ctx = build_coach_context(agent)
                await run_coach_turn(session, ctx, "", wrapup=True,
                                     finalize_reason=session.finalize_reason)
        except Exception:
            logger.exception("Wrap-up turn failed for %s", session.session_id)
    session.wrapup_done = True

    # 8. Done.
    session.status = "finalized"
    save_snapshot(session)
    session.done_event = {
        "type": "done",
        "meeting_filename": session.meeting_filename or None,
        "audio_url": (
            f"/api/agents/{session.agent_id}/live/recordings/{session.session_id}/audio"
            if recording.exists() else None
        ),
        "duration_seconds": round(session.duration_seconds, 1),
        "title": session.meeting_title or "Live meeting",
        "error": session.finalize_error or None,
    }
    live.emit(session, {
        "type": "done",
        "meeting_filename": session.meeting_filename or None,
        "audio_url": (
            f"/api/agents/{session.agent_id}/live/recordings/{session.session_id}/audio"
            if recording.exists() else None
        ),
        "duration_seconds": round(session.duration_seconds, 1),
        "title": session.meeting_title or "Live meeting",
        "error": session.finalize_error or None,
    })
    live.emit(session, {"type": "_close"})
    live.clear_active(session)
    logger.info("Live session %s finalized (%s)", session.session_id, session.finalize_reason)


async def recover_orphaned_sessions() -> None:
    """Finalize sessions left recording/finalizing by a server restart.

    Chunk files on disk are ground truth: segments present as files but
    missing from the snapshot (crash between accept and snapshot) are
    recovered as pending — the archival whole-file pass transcribes them.
    """
    from agents.engine import DATA_DIR

    root = Path(DATA_DIR)
    if not root.exists():
        return
    for snap_path in sorted(root.glob("*/recordings/*/session.json")):
        session = live.load_snapshot(snap_path)
        if session is None or session.status == "finalized":
            continue
        for f in sorted(session.chunk_dir.glob("chunk-*.*")):
            try:
                idx = int(f.stem.split("-", 1)[1])
            except (IndexError, ValueError):
                continue
            if idx not in session.segments:
                session.segments[idx] = live.Segment(
                    index=idx, filename=f.name, status="pending",
                )
        if not live.adopt_active(session):
            logger.warning("Skipping orphan recovery for %s — another session active",
                           session.session_id)
            continue
        try:
            await finalize(session, "server restart")
        except Exception:
            logger.exception("Orphan recovery failed for %s", session.session_id)
            live.clear_active(session)
