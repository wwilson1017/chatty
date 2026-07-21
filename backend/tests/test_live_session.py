"""Live meeting sessions: registry, transcript assembly, chunk pipeline,
finalize chain, startup recovery, and the HTTP surface."""

import asyncio
import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

import core.agents.live.pipeline as pipeline
import core.agents.live.session as live
from tests.test_http_agents import make_agent


@pytest.fixture(autouse=True)
def live_env(monkeypatch):
    """Fresh registry + busy map per test."""
    monkeypatch.setattr(live, "_active", None)
    monkeypatch.setattr(live, "_busy", {})
    yield


def _fake_agent():
    return {"id": "a1", "slug": "test-agent", "agent_name": "Test Agent"}


# ---------------------------------------------------------------------------
# Registry + transcript assembly
# ---------------------------------------------------------------------------

def test_one_active_session(monkeypatch, tmp_path):
    monkeypatch.setattr(live, "recordings_dir", lambda slug: tmp_path / slug / "recordings")
    s1 = live.start_session(_fake_agent(), "conv-1", "prep")
    assert live.get_active() is s1
    with pytest.raises(RuntimeError):
        live.start_session(_fake_agent(), "conv-2", "")
    live.clear_active(s1)
    assert live.get_active() is None


def test_transcript_text_ordering_and_markers(monkeypatch, tmp_path):
    monkeypatch.setattr(live, "recordings_dir", lambda slug: tmp_path / slug / "recordings")
    s = live.start_session(_fake_agent(), "conv-1", "")
    s.segments[2] = live.Segment(index=2, filename="chunk-00002.webm", status="done", text="second")
    s.segments[0] = live.Segment(index=0, filename="chunk-00000.webm", status="done", text="first")
    s.segments[1] = live.Segment(index=1, filename="chunk-00001.webm", status="failed")
    s.segments[3] = live.Segment(index=3, filename="chunk-00003.webm", status="done",
                                 text="fourth", gap_before=True)
    text = live.transcript_text(s)
    assert text.index("first") < text.index("[transcription gap]") < text.index("second")
    assert "[recording gap — interruption]" in text
    assert text.index("second") < text.index("fourth")
    # tail cap
    assert live.transcript_text(s, tail_chars=10).startswith("…")


def test_snapshot_roundtrip(monkeypatch, tmp_path):
    monkeypatch.setattr(live, "recordings_dir", lambda slug: tmp_path / slug / "recordings")
    s = live.start_session(_fake_agent(), "conv-1", "quarterly review")
    s.segments[0] = live.Segment(index=0, filename="chunk-00000.webm", status="done",
                                 text="hello", audio_seconds=19.5, received_at=123.0)
    s.chunk_audio_seconds = 19.5
    live.save_snapshot(s)
    loaded = live.load_snapshot(s.chunk_dir / "session.json")
    assert loaded.session_id == s.session_id
    assert loaded.prep_note == "quarterly review"
    assert loaded.segments[0].text == "hello"
    assert loaded.chunk_audio_seconds == 19.5


def test_busy_map_ttl(monkeypatch):
    live.mark_conversation_busy("c1")
    assert live.is_conversation_busy("c1")
    live.clear_conversation_busy("c1")
    assert not live.is_conversation_busy("c1")
    # Stale entries expire
    live.mark_conversation_busy("c2")
    monkeypatch.setattr(live, "_BUSY_TTL", 0)
    time.sleep(0.01)
    assert not live.is_conversation_busy("c2")


def test_live_meeting_block(monkeypatch, tmp_path):
    monkeypatch.setattr(live, "recordings_dir", lambda slug: tmp_path / slug / "recordings")
    assert live.live_meeting_block("test-agent", "conv-x") == ""
    s = live.start_session(_fake_agent(), "conv-x", "close the deal")
    s.segments[0] = live.Segment(index=0, filename="f", status="done", text="they want a discount")
    block = live.live_meeting_block("test-agent", "conv-x")
    assert "Live Meeting In Progress" in block
    assert "close the deal" in block
    assert "they want a discount" in block
    # Wrong conversation or wrong agent → nothing
    assert live.live_meeting_block("test-agent", "other-conv") == ""
    assert live.live_meeting_block("other-agent", "conv-x") == ""


# ---------------------------------------------------------------------------
# Chunk worker
# ---------------------------------------------------------------------------

def test_chunk_worker_failure_marks_gap(monkeypatch, tmp_path):
    import core.agents.transcription.service as svc

    monkeypatch.setattr(live, "recordings_dir", lambda slug: tmp_path / slug / "recordings")
    monkeypatch.setattr(pipeline, "_RETRY_DELAY_S", 0.01)
    acks = []
    monkeypatch.setattr(live, "post_assistant_message",
                        lambda session, text: acks.append(text))
    s = live.start_session(_fake_agent(), "conv-1", "")

    async def fake_chunk(path, *, ext, client_duration_s=None, prev_tail=""):
        if "00001" in str(path):
            raise svc.TranscriptionError("boom")
        return {"text": f"text-{path.stem}", "model": "m", "provider": "openai",
                "input_tokens": 1, "output_tokens": 2, "duration_seconds": 20.0}

    monkeypatch.setattr(svc, "transcribe_chunk", fake_chunk)

    async def run():
        worker = asyncio.get_running_loop().create_task(pipeline.chunk_worker(s))
        for i in range(3):
            (s.chunk_dir / f"chunk-0000{i}.webm").write_bytes(b"x")
            s.segments[i] = live.Segment(index=i, filename=f"chunk-0000{i}.webm",
                                         received_at=time.time())
            s.queue.put_nowait(i)
        for _ in range(100):
            if all(seg.status != "pending" for seg in s.segments.values()):
                break
            await asyncio.sleep(0.05)
        worker.cancel()

    asyncio.run(run())
    assert s.segments[0].status == "done"
    assert s.segments[1].status == "failed"  # retried once, then failed
    assert s.segments[2].status == "done"
    assert "[transcription gap]" in live.transcript_text(s)
    assert s.chunk_input_tokens == 2 and s.chunk_output_tokens == 4
    # First successful chunk → exactly one health ack
    assert len(acks) == 1 and "I'm listening" in acks[0]


def test_chunk_worker_first_failure_warns(monkeypatch, tmp_path):
    """A failing FIRST chunk posts a transcription warning instead of the ack."""
    import core.agents.transcription.service as svc

    monkeypatch.setattr(live, "recordings_dir", lambda slug: tmp_path / slug / "recordings")
    monkeypatch.setattr(pipeline, "_RETRY_DELAY_S", 0.01)
    acks = []
    monkeypatch.setattr(live, "post_assistant_message",
                        lambda session, text: acks.append(text))
    s = live.start_session(_fake_agent(), "conv-1", "")

    async def always_fail(path, *, ext, client_duration_s=None, prev_tail=""):
        raise svc.TranscriptionError("no key")

    monkeypatch.setattr(svc, "transcribe_chunk", always_fail)

    async def run():
        worker = asyncio.get_running_loop().create_task(pipeline.chunk_worker(s))
        (s.chunk_dir / "chunk-00000.webm").write_bytes(b"x")
        s.segments[0] = live.Segment(index=0, filename="chunk-00000.webm",
                                     received_at=time.time())
        s.queue.put_nowait(0)
        for _ in range(200):
            if s.segments[0].status != "pending":
                break
            await asyncio.sleep(0.05)
        worker.cancel()

    asyncio.run(run())
    assert s.segments[0].status == "failed"
    assert len(acks) == 1 and "transcription failed" in acks[0]


# ---------------------------------------------------------------------------
# Finalize chain
# ---------------------------------------------------------------------------

@pytest.fixture
def finalize_env(monkeypatch, tmp_path):
    """Session with two chunks + all external steps stubbed and recorded."""
    import core.agents.live.coach as coach_mod
    import core.agents.activity_log as activity_mod
    import core.agents.tools.memory_tools as memory_mod
    import core.agents.transcription.audio as audio_mod
    import core.agents.transcription.service as svc
    import agents.engine as engine_mod

    monkeypatch.setattr(engine_mod, "DATA_DIR", tmp_path)
    monkeypatch.setattr(live, "recordings_dir", lambda slug: tmp_path / slug / "recordings")

    s = live.start_session(_fake_agent(), "conv-1", "vendor negotiation")
    for i in range(2):
        (s.chunk_dir / f"chunk-0000{i}.webm").write_bytes(b"aud")
        s.segments[i] = live.Segment(index=i, filename=f"chunk-0000{i}.webm",
                                     status="done", text=f"line{i}",
                                     audio_seconds=20.0, received_at=time.time())
    s.chunk_audio_seconds = 40.0
    s.chunk_model = "gpt-4o-transcribe"
    s.chunk_provider = "openai"

    calls = SimpleNamespace(concat=[], saved=[], usage=[], wrapup=[])

    def fake_concat(chunks, dst):
        calls.concat.append(list(chunks))
        Path(dst).write_bytes(b"mp3")
        return dst

    monkeypatch.setattr(audio_mod, "concat_audio", fake_concat)
    monkeypatch.setattr(audio_mod, "probe_duration_seconds", lambda p: 40.0)
    monkeypatch.setattr(svc, "pick_backend", lambda: None)  # → stitched live text

    def fake_save(data_dir, gcs_prefix, title, transcript, **kw):
        calls.saved.append({"data_dir": data_dir, "title": title,
                            "transcript": transcript, **kw})
        return {"filename": "2026-07-19-meeting.md", "title": title, "date": "2026-07-19"}

    monkeypatch.setattr(memory_mod, "save_meeting_transcript", fake_save)
    monkeypatch.setattr(activity_mod, "log_transcription_event",
                        lambda *a, **kw: calls.usage.append(kw) or "id")

    async def fake_wrapup(session, ctx, delta, **kw):
        calls.wrapup.append(kw)

    monkeypatch.setattr(coach_mod, "build_coach_context", lambda agent: {"stub": True})
    monkeypatch.setattr(coach_mod, "run_coach_turn", fake_wrapup)
    monkeypatch.setattr(
        "agents.db.list_agents", lambda: [_fake_agent()]
    )
    return s, calls


def test_finalize_end_to_end(finalize_env):
    s, calls = finalize_env
    asyncio.run(pipeline.finalize(s, "stopped"))

    assert s.status == "finalized"
    assert len(calls.concat) == 1 and len(calls.concat[0]) == 2
    assert (s.chunk_dir / "recording.mp3").exists()
    assert not list(s.chunk_dir.glob("chunk-*.webm"))  # chunks deleted post-concat
    assert len(calls.saved) == 1
    saved = calls.saved[0]
    assert saved["title"] == "vendor negotiation"
    assert "line0" in saved["transcript"] and "line1" in saved["transcript"]
    assert "no speaker labels" in saved["transcript"]
    assert saved["source_filename"] == f"recordings/{s.session_id}/recording.mp3"
    assert len(calls.usage) == 1  # ONE aggregate row (no archival pass w/o backend)
    assert calls.usage[0]["audio_seconds"] == 40
    assert calls.usage[0]["model_used"] == "gpt-4o-transcribe"
    assert len(calls.wrapup) == 1 and calls.wrapup[0]["wrapup"] is True
    assert live.get_active() is None
    snap = json.loads((s.chunk_dir / "session.json").read_text())
    assert snap["status"] == "finalized"


def test_finalize_idempotent_single_task(finalize_env):
    s, calls = finalize_env

    async def run():
        t1 = pipeline.ensure_finalize(s, "stopped")
        t2 = pipeline.ensure_finalize(s, "idle timeout")
        assert t1 is t2
        await t1

    asyncio.run(run())
    assert len(calls.saved) == 1
    assert len(calls.wrapup) == 1


def test_finalize_resume_skips_completed_steps(finalize_env):
    s, calls = finalize_env
    # Simulate a prior crash after save: artifacts + flags already present.
    (s.chunk_dir / "recording.mp3").write_bytes(b"mp3")
    s.meeting_filename = "already-saved.md"
    s.usage_logged = True
    asyncio.run(pipeline.finalize(s, "server restart"))
    assert calls.concat == []      # recording.mp3 existed
    assert calls.saved == []       # meeting_filename set
    assert calls.usage == []       # usage_logged set
    assert len(calls.wrapup) == 1  # wrap-up still runs once
    assert s.status == "finalized"


def test_finalize_openai_archival_pass(finalize_env, monkeypatch):
    """With a capable backend, the whole-file pass replaces stitched text —
    including for OpenAI-only users (recovers never-transcribed chunks)."""
    import core.agents.transcription.service as svc

    s, calls = finalize_env
    s.segments[1].status = "pending"  # uploaded but never live-transcribed

    async def fake_transcribe_file(path, filename):
        yield {"stage": "transcribing", "message": "…", "percent": 50}
        yield {"done": True, "transcript": "WHOLE-FILE TRANSCRIPT",
               "duration_seconds": 40.0, "model": "gpt-4o-transcribe",
               "input_tokens": 10, "output_tokens": 20, "provider": "openai"}

    monkeypatch.setattr(svc, "pick_backend", lambda: ("openai", "key"))
    monkeypatch.setattr(svc, "transcribe_file", fake_transcribe_file)
    # Mark the never-transcribed chunk failed so the drain loop doesn't wait
    # out its 120 s deadline — the archival pass is what recovers its audio.
    s.segments[1].status = "failed"

    asyncio.run(pipeline.finalize(s, "stopped"))
    assert calls.saved[0]["transcript"] == "WHOLE-FILE TRANSCRIPT"
    assert calls.saved[0]["transcribed_by"] == "gpt-4o-transcribe"
    assert len(calls.usage) == 2  # archival row + aggregate chunk row


# ---------------------------------------------------------------------------
# Watchdog + recovery
# ---------------------------------------------------------------------------

def test_watchdog_idle_finalize(finalize_env, monkeypatch):
    s, calls = finalize_env
    monkeypatch.setattr(pipeline, "_WATCHDOG_INTERVAL_S", 0.01)
    monkeypatch.setattr(pipeline, "IDLE_FINALIZE_S", 0.05)
    s.last_chunk_at = time.time() - 1

    async def run():
        task = asyncio.get_running_loop().create_task(pipeline.watchdog(s))
        for _ in range(200):
            if s.finalize_task is not None:
                await s.finalize_task
                break
            await asyncio.sleep(0.01)
        task.cancel()

    asyncio.run(run())
    assert s.status == "finalized"
    assert s.finalize_reason == "idle timeout"


def test_recover_orphaned_sessions(monkeypatch, tmp_path):
    import agents.engine as engine_mod

    monkeypatch.setattr(engine_mod, "DATA_DIR", tmp_path)
    chunk_dir = tmp_path / "test-agent" / "recordings" / "abcdef123456"
    chunk_dir.mkdir(parents=True)
    snapshot = {
        "session_id": "abcdef123456", "agent_id": "a1", "agent_slug": "test-agent",
        "agent_name": "Test Agent", "conversation_id": "conv-1", "prep_note": "",
        "status": "recording", "started_at": "2026-07-19T10:00:00+00:00",
        "last_chunk_at": 0.0,
        "segments": [{"index": 0, "filename": "chunk-00000.webm", "status": "done",
                      "text": "hi", "audio_seconds": 20.0, "received_at": 1.0,
                      "gap_before": False}],
    }
    (chunk_dir / "session.json").write_text(json.dumps(snapshot))
    # A chunk that arrived after the last snapshot (crash window) — disk is truth
    (chunk_dir / "chunk-00000.webm").write_bytes(b"x")
    (chunk_dir / "chunk-00001.webm").write_bytes(b"y")

    finalized = []

    async def fake_finalize(session, reason):
        finalized.append((session, reason))
        session.status = "finalized"

    monkeypatch.setattr(pipeline, "finalize", fake_finalize)
    asyncio.run(pipeline.recover_orphaned_sessions())

    assert len(finalized) == 1
    session, reason = finalized[0]
    assert reason == "server restart"
    assert set(session.segments) == {0, 1}          # orphan chunk recovered
    assert session.segments[1].status == "pending"
    assert session.segments[0].text == "hi"         # snapshot text preserved


# ---------------------------------------------------------------------------
# HTTP surface
# ---------------------------------------------------------------------------

@pytest.fixture
def live_client(client, monkeypatch):
    """Authenticated client with capture-friendly live-session guards."""
    import core.agents.live.coach as coach_mod
    import core.agents.transcription.audio as audio_mod
    import core.agents.transcription.service as svc
    import core.providers as providers_mod

    monkeypatch.setattr(audio_mod, "ffmpeg_available", lambda: True)
    monkeypatch.setattr(svc, "pick_chunk_backend", lambda: ("openai", "key"))
    monkeypatch.setattr(providers_mod, "get_ai_provider", lambda **kw: object())

    async def fake_chunk(path, *, ext, client_duration_s=None, prev_tail=""):
        return {"text": "hi", "model": "m", "provider": "openai",
                "input_tokens": 1, "output_tokens": 1,
                "duration_seconds": client_duration_s or 20.0}

    monkeypatch.setattr(svc, "transcribe_chunk", fake_chunk)
    monkeypatch.setattr(coach_mod, "build_coach_context",
                        lambda agent: (_ for _ in ()).throw(RuntimeError("no coach in tests")))
    return client


def _start(live_client, agent_id, **body):
    return live_client.post(f"/api/agents/{agent_id}/live/start",
                            json={"prep_note": "", **body})


def test_live_start_guards(live_client, monkeypatch):
    import core.agents.transcription.audio as audio_mod
    import core.agents.transcription.service as svc

    agent_id = make_agent(live_client, name="Live Agent")["id"]

    monkeypatch.setattr(audio_mod, "ffmpeg_available", lambda: False)
    assert _start(live_client, agent_id).status_code == 400

    monkeypatch.setattr(audio_mod, "ffmpeg_available", lambda: True)
    monkeypatch.setattr(svc, "pick_chunk_backend", lambda: None)
    assert _start(live_client, agent_id).status_code == 400

    monkeypatch.setattr(svc, "pick_chunk_backend", lambda: ("openai", "key"))
    res = _start(live_client, agent_id)
    assert res.status_code == 200
    data = res.json()
    assert data["session_id"] and data["conversation_id"]
    assert data["chunk_seconds"] == live.CHUNK_SECONDS
    assert data["last_chunk_index"] is None

    # Second session for another conversation → 409 with active info
    res2 = _start(live_client, agent_id, conversation_id="other-conv")
    assert res2.status_code == 409
    assert res2.json()["detail"]["active"]["session_id"] == data["session_id"]

    # Idempotent re-start for the same conversation → 200, same session
    res3 = _start(live_client, agent_id, conversation_id=data["conversation_id"])
    assert res3.status_code == 200
    assert res3.json()["session_id"] == data["session_id"]

    # /api/live/active reports it
    active = live_client.get("/api/live/active").json()["active"]
    assert active["session_id"] == data["session_id"]
    assert active["agent_name"]


def test_live_chunk_flow(live_client):
    agent_id = make_agent(live_client, name="Chunk Agent")["id"]
    session = _start(live_client, agent_id).json()
    sid = session["session_id"]

    def post_chunk(index, data=b"audio-bytes", name="c.webm"):
        return live_client.post(
            f"/api/agents/{agent_id}/live/{sid}/chunk",
            files={"file": (name, data, "audio/webm")},
            data={"index": str(index)},
        )

    assert post_chunk(0).status_code == 202
    assert post_chunk(0).json() == {"duplicate": True, "index": 0}
    assert post_chunk(2).status_code == 202            # out-of-order accepted
    assert post_chunk(3, name="c.exe").status_code == 422
    assert post_chunk(4, data=b"").status_code == 422
    big = b"x" * (live.CHUNK_MAX_BYTES + 1)
    assert post_chunk(5, data=big).status_code == 413

    s = live.get_active()
    assert set(s.segments) == {0, 2}
    assert (s.chunk_dir / "chunk-00000.webm").exists()

    # Stop → chunk uploads now rejected
    assert live_client.post(f"/api/agents/{agent_id}/live/{sid}/stop").status_code == 200
    for _ in range(100):
        if s.status == "finalized":
            break
        time.sleep(0.05)
    assert post_chunk(6).status_code in (404, 409)  # finalized may clear registry


def test_live_events_snapshot_and_replay(live_client):
    agent_id = make_agent(live_client, name="Events Agent")["id"]
    session = _start(live_client, agent_id).json()
    sid = session["session_id"]
    s = live.get_session(sid)
    s.coach_events.append({"type": "coach", "message": {"id": "m1", "role": "assistant",
                                                        "content": "nudge"},
                           "tier": "mid", "escalated": False, "wrapup": False})
    # Finalized session → snapshot + replay, then the stream ends
    s.status = "finalized"
    res = live_client.get(f"/api/agents/{agent_id}/live/{sid}/events")
    events = [json.loads(line[6:]) for line in res.text.split("\n") if line.startswith("data: ")]
    assert events[0]["type"] == "status"
    assert events[0]["state"] == "finalized"
    assert events[1]["type"] == "coach"
    assert events[1]["message"]["id"] == "m1"


def test_live_audio_download(live_client, tmp_path):
    agent_id = make_agent(live_client, name="Audio Agent")["id"]
    slug_dir = live.recordings_dir(
        live_client.get(f"/api/agents/{agent_id}").json()["slug"])
    rec_dir = slug_dir / "abcdef123456"
    rec_dir.mkdir(parents=True)
    (rec_dir / "recording.mp3").write_bytes(b"mp3data")

    ok = live_client.get(f"/api/agents/{agent_id}/live/recordings/abcdef123456/audio")
    assert ok.status_code == 200
    assert ok.content == b"mp3data"

    missing = live_client.get(f"/api/agents/{agent_id}/live/recordings/deadbeef0000/audio")
    assert missing.status_code == 404

    traversal = live_client.get(f"/api/agents/{agent_id}/live/recordings/..%2F..%2Fetc/audio")
    assert traversal.status_code in (404, 422)


def test_transcript_text_missing_index_marker(monkeypatch, tmp_path):
    """An index with no Segment at all must not read as continuous audio."""
    monkeypatch.setattr(live, "recordings_dir", lambda slug: tmp_path / slug / "recordings")
    s = live.start_session(_fake_agent(), "conv-1", "")
    s.segments[0] = live.Segment(index=0, filename="f0", status="done", text="alpha")
    s.segments[3] = live.Segment(index=3, filename="f3", status="done", text="delta")
    text = live.transcript_text(s)
    assert text.index("alpha") < text.index("[missing audio segment]") < text.index("delta")


def test_finalize_concat_failure_keeps_chunks(finalize_env, monkeypatch):
    import core.agents.transcription.audio as audio_mod

    s, calls = finalize_env
    monkeypatch.setattr(audio_mod, "concat_audio",
                        lambda chunks, dst: (_ for _ in ()).throw(RuntimeError("ffmpeg died")))
    asyncio.run(pipeline.finalize(s, "stopped"))
    assert s.status == "finalized"
    assert "stitch" in s.finalize_error
    assert "ffmpeg died" not in s.finalize_error  # raw stderr never reaches client
    assert not (s.chunk_dir / "recording.mp3").exists()
    assert len(list(s.chunk_dir.glob("chunk-*.webm"))) == 2  # originals preserved
    assert len(calls.saved) == 1  # transcript still saved from live text


def test_finalize_save_failure_still_finalizes(finalize_env, monkeypatch):
    import core.agents.tools.memory_tools as memory_mod

    s, calls = finalize_env
    monkeypatch.setattr(memory_mod, "save_meeting_transcript",
                        lambda *a, **kw: (_ for _ in ()).throw(OSError("disk full")))
    asyncio.run(pipeline.finalize(s, "stopped"))
    assert s.status == "finalized"
    assert "save" in s.finalize_error and "disk full" not in s.finalize_error
    assert s.meeting_filename == ""
    assert len(calls.wrapup) == 1  # wrap-up still runs


def test_finalize_wrapup_crash_marks_done(finalize_env, monkeypatch):
    """A crashed wrap-up is logged, not retried — finalize still completes."""
    import core.agents.live.coach as coach_mod

    s, calls = finalize_env

    async def boom(*a, **kw):
        raise RuntimeError("provider down")

    monkeypatch.setattr(coach_mod, "run_coach_turn", boom)
    asyncio.run(pipeline.finalize(s, "stopped"))
    assert s.status == "finalized"
    assert s.wrapup_done is True


# ---------------------------------------------------------------------------
# Stage-2 review fixes (Codex round)
# ---------------------------------------------------------------------------

def test_busy_map_refcounted():
    """Two holders (user stream + coach) must not clear each other's lease."""
    live.mark_conversation_busy("c1")   # user stream
    live.mark_conversation_busy("c1")   # coach turn
    live.clear_conversation_busy("c1")  # coach finishes first
    assert live.is_conversation_busy("c1")   # user stream still holds
    live.clear_conversation_busy("c1")
    assert not live.is_conversation_busy("c1")


def test_emit_terminal_event_evicts_when_full(monkeypatch, tmp_path):
    monkeypatch.setattr(live, "recordings_dir", lambda slug: tmp_path / slug / "recordings")
    s = live.start_session(_fake_agent(), "conv-1", "")
    q = asyncio.Queue(maxsize=2)
    s.listeners.append(q)
    live.emit(s, {"type": "chunk", "index": 0})
    live.emit(s, {"type": "chunk", "index": 1})
    live.emit(s, {"type": "chunk", "index": 2})   # dropped (full, non-terminal)
    live.emit(s, {"type": "done"})                # must evict to land
    events = []
    while not q.empty():
        events.append(q.get_nowait()["type"])
    assert "done" in events


def test_get_session_resolves_last_finalized(monkeypatch, tmp_path):
    """A reloading client can still hit /events for the just-finished session."""
    monkeypatch.setattr(live, "recordings_dir", lambda slug: tmp_path / slug / "recordings")
    s = live.start_session(_fake_agent(), "conv-1", "")
    sid = s.session_id
    s.status = "finalized"
    live.clear_active(s)
    assert live.get_active() is None
    assert live.get_session(sid) is s


def test_live_chunk_rejects_cross_agent_session(live_client):
    agent_a = make_agent(live_client, name="Agent A")["id"]
    agent_b = make_agent(live_client, name="Agent B")["id"]
    sid = _start(live_client, agent_a).json()["session_id"]
    res = live_client.post(
        f"/api/agents/{agent_b}/live/{sid}/chunk",
        files={"file": ("c.webm", b"x", "audio/webm")},
        data={"index": "0"},
    )
    assert res.status_code == 404
    assert live_client.post(f"/api/agents/{agent_b}/live/{sid}/stop").status_code == 404
    assert live_client.get(f"/api/agents/{agent_b}/live/{sid}/events").status_code == 404


def test_live_start_sanitizes_prep_note(live_client):
    agent_id = make_agent(live_client, name="Prep Agent")["id"]
    res = live_client.post(f"/api/agents/{agent_id}/live/start",
                           json={"prep_note": "close the\ndeal\x00 today"})
    assert res.status_code == 200
    s = live.get_active()
    assert "\n" not in s.prep_note and "\x00" not in s.prep_note
    assert "close the deal today" == s.prep_note


def test_transcript_text_leading_missing_marker(monkeypatch, tmp_path):
    monkeypatch.setattr(live, "recordings_dir", lambda slug: tmp_path / slug / "recordings")
    s = live.start_session(_fake_agent(), "conv-1", "")
    s.segments[2] = live.Segment(index=2, filename="f2", status="done", text="late start")
    text = live.transcript_text(s)
    assert text.index("[missing audio segment]") < text.index("late start")


def test_events_replays_done_for_finalized(live_client):
    agent_id = make_agent(live_client, name="Done Agent")["id"]
    session = _start(live_client, agent_id).json()
    sid = session["session_id"]
    s = live.get_session(sid)
    s.status = "finalized"
    s.done_event = {"type": "done", "meeting_filename": "m.md", "audio_url": None,
                    "duration_seconds": 1.0, "title": "T", "error": None}
    live.clear_active(s)  # registry keeps it via the last-finalized slot
    res = live_client.get(f"/api/agents/{agent_id}/live/{sid}/events")
    events = [json.loads(line[6:]) for line in res.text.split("\n") if line.startswith("data: ")]
    assert events[-1]["type"] == "done"
    assert events[-1]["meeting_filename"] == "m.md"
