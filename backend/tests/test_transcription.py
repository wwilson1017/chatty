"""Tests for meeting recording transcription: backend selection, meeting
transcript storage/manifest, per-minute pricing, and usage aggregation."""

from pathlib import Path

import pytest

from core.agents.context_manager import ContextManager
from core.providers.pricing import (
    MODEL_PRICING,
    TRANSCRIPTION_PRICING,
    estimate_transcription_cost,
    is_transcription_priced,
)


# ---------------------------------------------------------------------------
# Backend selection
# ---------------------------------------------------------------------------

class _FakeStore:
    def __init__(self, profiles):
        self.data = {"profiles": profiles}


def _patch_store(monkeypatch, profiles):
    import core.agents.transcription.service as svc
    monkeypatch.setattr(svc, "CredentialStore", lambda: _FakeStore(profiles))


def test_pick_backend_prefers_gemini(monkeypatch):
    from core.agents.transcription.service import pick_backend
    _patch_store(monkeypatch, {
        "google:default": {"type": "api_key", "key": "g-key"},
        "openai:default": {"type": "api_key", "key": "o-key"},
    })
    assert pick_backend() == ("google", "g-key")


def test_pick_backend_falls_back_to_openai(monkeypatch):
    from core.agents.transcription.service import pick_backend
    _patch_store(monkeypatch, {
        "openai:default": {"type": "api_key", "key": "o-key"},
    })
    assert pick_backend() == ("openai", "o-key")


def test_pick_backend_ignores_oauth_profiles(monkeypatch):
    """ChatGPT OAuth and Google OAuth tokens can't call the audio APIs."""
    from core.agents.transcription.service import pick_backend
    _patch_store(monkeypatch, {
        "openai:default": {"type": "chatgpt_oauth", "access": "tok"},
        "google:default": {"type": "oauth", "access": "tok"},
        "anthropic:default": {"type": "api_key", "key": "a-key"},
    })
    assert pick_backend() is None


def test_transcribe_file_without_provider_raises(monkeypatch):
    import asyncio
    from core.agents.transcription.service import TranscriptionError, transcribe_file
    _patch_store(monkeypatch, {})

    async def run():
        async for _ in transcribe_file(Path("/nonexistent.mp3"), "x.mp3"):
            pass

    with pytest.raises(TranscriptionError):
        asyncio.run(run())


def test_transcribe_file_rejects_overlong_duration(monkeypatch, tmp_path):
    """FIX B: a probed duration over the 6h cap must fail closed before any
    transcription API call — even for a byte size well under the 2GB cap."""
    import asyncio
    import core.agents.transcription.service as svc
    from core.agents.transcription.service import TranscriptionError, transcribe_file

    monkeypatch.setattr(svc, "pick_backend", lambda: ("openai", "fake-key"))
    monkeypatch.setattr(svc, "probe_duration_seconds", lambda path: 7 * 3600)

    fake_file = tmp_path / "long.mp3"
    fake_file.write_bytes(b"x")

    async def run():
        async for _ in transcribe_file(fake_file, "long.mp3"):
            pass

    with pytest.raises(TranscriptionError, match="6-hour limit"):
        asyncio.run(run())

    # Fail-closed variant (duration unknown + file > 500MB) needs a real
    # oversized file to exercise path.stat().st_size — not worth faking here;
    # applied but left untested.


def test_fmt_offset():
    from core.agents.transcription.service import _fmt_offset
    assert _fmt_offset(0) == "0:00:00"
    assert _fmt_offset(65) == "0:01:05"
    assert _fmt_offset(3723) == "1:02:03"


def test_format_hms():
    from core.agents.transcription.audio import format_hms
    assert format_hms(0) == "0:00:00"
    assert format_hms(65) == "0:01:05"
    assert format_hms(3723) == "1:02:03"


def test_whisper_native_extensions_exclude_unsupported():
    from core.agents.transcription.audio import AUDIO_EXTENSIONS, WHISPER_NATIVE_EXTENSIONS
    for ext in ("opus", "oga", "aac", "aiff", "mov"):
        assert ext in AUDIO_EXTENSIONS
        assert ext not in WHISPER_NATIVE_EXTENSIONS
    for ext in ("mp3", "wav", "m4a", "webm"):
        assert ext in WHISPER_NATIVE_EXTENSIONS


def test_should_wrap_meeting_tools():
    from core.agents.security.delimiters import should_wrap
    assert should_wrap("read_meeting", "memory") is True
    assert should_wrap("list_meetings", "memory") is True
    assert should_wrap("read_memory", "memory") is False


def test_transcribe_gemini_detects_truncation(monkeypatch, tmp_path):
    """FIX F: a MAX_TOKENS finish_reason must append a visible truncation
    marker to the transcript instead of silently returning a partial one."""
    import asyncio
    import sys
    import types as _types

    import core.agents.transcription.service as svc

    fake_genai = _types.ModuleType("google.generativeai")

    class FakeFile:
        def __init__(self, name="files/abc"):
            self.name = name
            self.state = _types.SimpleNamespace(name="ACTIVE")

    class FakeCandidate:
        finish_reason = _types.SimpleNamespace(name="MAX_TOKENS")

    class FakeResponse:
        text = "partial transcript"
        candidates = [FakeCandidate()]
        usage_metadata = _types.SimpleNamespace(prompt_token_count=10, candidates_token_count=20)

    class FakeModel:
        def __init__(self, name):
            pass

        def generate_content(self, contents, generation_config=None, request_options=None):
            return FakeResponse()

    fake_genai.configure = lambda api_key=None: None
    fake_genai.upload_file = lambda path, mime_type=None: FakeFile()
    fake_genai.get_file = lambda name: FakeFile(name)
    fake_genai.delete_file = lambda name: None
    fake_genai.GenerativeModel = FakeModel

    monkeypatch.setitem(sys.modules, "google.generativeai", fake_genai)

    audio_path = tmp_path / "rec.mp3"
    audio_path.write_bytes(b"fake")

    async def run():
        events = []
        async for event in svc._transcribe_gemini(audio_path, "rec.mp3", "fake-key", 30.0):
            events.append(event)
        return events

    events = asyncio.run(run())
    done = next(e for e in events if e.get("done"))
    assert "Transcript truncated" in done["transcript"]
    assert "partial transcript" in done["transcript"]


# ---------------------------------------------------------------------------
# Meeting transcript storage (ContextManager)
# ---------------------------------------------------------------------------

@pytest.fixture
def cm(tmp_path):
    return ContextManager(tmp_path, "agents/test/context/")


def test_save_and_read_meeting(cm):
    saved = cm.save_meeting_transcript(
        "Weekly Standup", "Speaker 1: hello\n\nSpeaker 2: hi",
        duration_seconds=3723, source_filename="standup.m4a",
        transcribed_by="gemini-2.5-flash",
    )
    assert saved["filename"].endswith("-weekly-standup.md")
    content = cm.read_meeting(saved["filename"])
    assert "Speaker 1: hello" in content
    assert "duration: 1:02:03" in content
    assert "source: standup.m4a" in content
    assert "transcribed_by: gemini-2.5-flash" in content


def test_meetings_not_loaded_into_system_prompt(cm):
    """Transcripts must stay out of load_all_context (prompt bloat guard)."""
    cm.save_meeting_transcript("Big Meeting", "x" * 50_000)
    assert "Big Meeting" not in cm.load_all_context()
    assert cm.list_context_files() == []


def test_list_meetings_and_manifest(cm):
    cm.save_meeting_transcript("Standup", "notes", duration_seconds=60,
                               source_filename="a.mp3")
    cm.save_meeting_transcript("Client Call", "notes", duration_seconds=120,
                               source_filename="b.mp3")
    meetings = cm.list_meetings()
    assert len(meetings) == 2
    titles = {m["title"] for m in meetings}
    assert titles == {"Standup", "Client Call"}
    manifest = cm.meetings_manifest()
    assert "Standup" in manifest and "Client Call" in manifest
    assert "0:01:00" in manifest


def test_read_meeting_rejects_traversal(cm, tmp_path):
    (tmp_path / "secret.md").write_text("secret", encoding="utf-8")
    assert cm.read_meeting("../secret.md") == ""
    assert cm.read_meeting("nope.md") == ""
    assert cm.read_meeting("not-markdown.txt") == ""


def test_meetings_manifest_empty(cm):
    assert cm.meetings_manifest() == ""


def test_slugify_title():
    assert ContextManager._slugify_title("Weekly Standup!") == "weekly-standup"
    assert ContextManager._slugify_title("") == "meeting"
    assert len(ContextManager._slugify_title("x" * 200)) <= 60


def test_save_meeting_sanitizes_control_chars(cm):
    """FIX A: a crafted title/filename with embedded newlines + a fake '---'
    frontmatter terminator must not break YAML frontmatter structure."""
    evil_title = "Weekly\nStandup\n---\ninjected: pwned"
    evil_source = "evil\nname.mp3"
    saved = cm.save_meeting_transcript(
        evil_title, "notes here",
        duration_seconds=60, source_filename=evil_source,
    )
    content = cm.read_meeting(saved["filename"])
    lines = content.splitlines()
    title_line = next(l for l in lines if l.startswith("title:"))
    source_line = next(l for l in lines if l.startswith("source:"))
    assert "\n" not in title_line
    assert "\n" not in source_line

    meta = ContextManager._parse_meeting_frontmatter(content)
    # Frontmatter parsed cleanly all the way through — proves the injected
    # "---" never landed on its own line to fake an early terminator.
    assert meta["duration_seconds"] == "60"
    assert meta["transcribed_by"] == ""
    assert "Weekly Standup" in meta["title"]


def test_save_meeting_filename_collision_suffix(cm, monkeypatch):
    """FIX D: two saves that resolve to the same date+time+slug filename
    (simulated via a frozen clock) must not collide — the second gets a
    random suffix and both transcripts are kept."""
    import core.agents.context_manager as ctx_mod

    class _FixedDateTime(ctx_mod.datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 7, 13, 12, 0, 0, tzinfo=tz)

    monkeypatch.setattr(ctx_mod, "datetime", _FixedDateTime)

    first = cm.save_meeting_transcript("Standup", "first content")
    second = cm.save_meeting_transcript("Standup", "second content")

    assert first["filename"] == "2026-07-13-120000-standup.md"
    assert second["filename"] != first["filename"]
    assert second["filename"].endswith("-standup.md")

    assert "first content" in cm.read_meeting(first["filename"])
    assert "second content" in cm.read_meeting(second["filename"])


# ---------------------------------------------------------------------------
# Memory tool handlers
# ---------------------------------------------------------------------------

def test_memory_tool_handlers(tmp_path):
    from core.agents.tools.memory_tools import list_meetings, read_meeting, save_meeting_transcript

    saved = save_meeting_transcript(str(tmp_path), "", "Kickoff", "transcript body",
                                    duration_seconds=30, source_filename="k.mp3")
    listed = list_meetings(str(tmp_path), "")
    assert listed["meetings"][0]["title"] == "Kickoff"

    read = read_meeting(str(tmp_path), "", saved["filename"])
    assert read["exists"] is True
    assert "transcript body" in read["content"]

    missing = read_meeting(str(tmp_path), "", "2020-01-01-000000-x.md")
    assert missing["exists"] is False
    assert read_meeting(str(tmp_path), "", "")["error"]


# ---------------------------------------------------------------------------
# Pricing
# ---------------------------------------------------------------------------

def test_transcription_pricing_openai_flat_rate():
    per_min = TRANSCRIPTION_PRICING["gpt-4o-transcribe"]
    assert estimate_transcription_cost("gpt-4o-transcribe", 3600) == pytest.approx(60 * per_min)
    # OpenAI's per-minute rate is all-inclusive — no token component
    # (gpt-4o-transcribe has no MODEL_PRICING entry)
    assert estimate_transcription_cost("gpt-4o-transcribe", 60, output_tokens=1000) == pytest.approx(per_min)


def test_transcription_pricing_gemini_adds_output_tokens():
    per_min = TRANSCRIPTION_PRICING["gemini-2.5-flash"]
    out_price = MODEL_PRICING["gemini-2.5-flash"][1]
    expected = 60 * per_min + 10_000 * out_price / 1_000_000
    assert estimate_transcription_cost("gemini-2.5-flash", 3600, output_tokens=10_000) == pytest.approx(expected)


def test_transcription_pricing_unknown_model():
    assert estimate_transcription_cost("mystery-model", 3600) == 0.0
    assert not is_transcription_priced("mystery-model")
    assert is_transcription_priced("gpt-4o-transcribe")


# ---------------------------------------------------------------------------
# Usage aggregation for transcription rows
# ---------------------------------------------------------------------------

@pytest.fixture
def reminders_db(monkeypatch, tmp_path):
    import core.agents.reminders.db as db_mod

    monkeypatch.setattr(db_mod, "DATA_DIR", tmp_path)
    monkeypatch.setattr(db_mod, "DB_PATH", tmp_path / "reminders.db")
    db_mod._connection = None
    db_mod.init_db()
    yield db_mod.get_db()
    if db_mod._connection:
        db_mod._connection.close()
    db_mod._connection = None


def test_log_transcription_event_and_usage_summary(reminders_db):
    from core.agents.activity_log import log_transcription_event
    from core.agents.usage.service import get_usage_summary

    log_transcription_event(
        "test-agent",
        source_filename="standup.m4a",
        provider="openai",
        model_used="gpt-4o-transcribe",
        audio_seconds=3600,
        duration_ms=45_000,
    )
    summary = get_usage_summary(days=7)
    expected = 60 * TRANSCRIPTION_PRICING["gpt-4o-transcribe"]
    assert summary["totals"]["cost"] == pytest.approx(expected)
    assert summary["unknown_pricing_models"] == []

    row = reminders_db.execute(
        "SELECT event_type, audio_seconds FROM execution_history").fetchone()
    assert row["event_type"] == "transcription"
    assert row["audio_seconds"] == 3600


def test_usage_summary_flags_unknown_transcription_model(reminders_db):
    from core.agents.activity_log import log_transcription_event
    from core.agents.usage.service import get_usage_summary

    log_transcription_event(
        "test-agent", provider="openai", model_used="whisper-99",
        audio_seconds=600,
    )
    summary = get_usage_summary(days=7)
    assert summary["totals"]["cost"] == 0.0
    assert "whisper-99" in summary["unknown_pricing_models"]


# ---------------------------------------------------------------------------
# Upload route helpers
# ---------------------------------------------------------------------------

def test_meeting_title_from_filename():
    from agents.router import _meeting_title_from_filename
    assert _meeting_title_from_filename("team_standup-2026.m4a") == "team standup 2026"
    assert _meeting_title_from_filename("---.mp3") == "Meeting recording"


def test_audio_extensions_cover_common_recorders():
    from core.agents.transcription.audio import AUDIO_EXTENSIONS
    # iPhone Voice Memos, Android recorder, Zoom, browser MediaRecorder
    for ext in ("m4a", "mp3", "wav", "mp4", "webm", "ogg"):
        assert ext in AUDIO_EXTENSIONS


# ---------------------------------------------------------------------------
# End-to-end: audio upload through the chat SSE stream
# ---------------------------------------------------------------------------

def _upload_audio(client, agent, filename="team_standup.mp3", text="here it is"):
    import json
    payload = {"messages": [{"role": "user", "content": text}]}
    return client.post(
        f"/api/agents/{agent['id']}/chat/upload",
        data={"payload": json.dumps(payload)},
        files=[("files", (filename, b"fake-audio-bytes", "audio/mpeg"))],
    )


@pytest.fixture
def transcribing_client(client, monkeypatch):
    """Authenticated client with a recording chat provider and a fake
    transcription backend (one progress event, then a canned transcript)."""
    import core.agents.transcription.service as svc
    from tests.test_http_chat import RecordingProvider

    provider = RecordingProvider()
    monkeypatch.setattr("agents.router.get_ai_provider", lambda **kw: provider)
    monkeypatch.setattr(svc, "pick_backend", lambda: ("openai", "fake-key"))

    async def fake_transcribe(path, filename):
        assert Path(path).exists()  # spooled temp file is on disk
        yield {"stage": "transcribing", "message": f"Transcribing {filename}…", "percent": 50}
        yield {
            "done": True,
            "transcript": "Speaker 1: quarterly numbers look great",
            "duration_seconds": 125,
            "model": "gpt-4o-transcribe",
            "provider": "openai",
            "input_tokens": 0,
            "output_tokens": 42,
            "processing_ms": 900,
        }

    monkeypatch.setattr(svc, "transcribe_file", fake_transcribe)
    client._provider = provider
    return client


def test_upload_audio_streams_progress_and_prepends_transcript(transcribing_client, tmp_path):
    from tests.conftest import parse_sse
    from tests.test_http_agents import make_agent

    agent = make_agent(transcribing_client)
    resp = _upload_audio(transcribing_client, agent)
    assert resp.status_code == 200
    events = parse_sse(resp)
    types = [e["type"] for e in events]

    # Progress events precede the AI turn; the final one is the saved marker
    tr = [e for e in events if e["type"] == "transcription"]
    assert len(tr) == 2
    assert tr[0]["percent"] == 50
    assert tr[1]["stage"] == "saved"
    assert types.index("transcription") < types.index("text")
    assert types[-1] == "done"

    # The AI turn saw the transcript block + leading-questions instruction
    seen = transcribing_client._provider.seen_messages[0][-1]["content"]
    assert "Speaker 1: quarterly numbers look great" in seen
    assert "team_standup.mp3 — duration 0:02:05" in seen
    assert "offer the" in seen and "here it is" in seen
    # Transcript body is wrapped as untrusted external content
    assert "untrusted_tool_result" in seen

    # Transcript persisted under the agent's context/meetings/
    meetings = list((tmp_path / agent["slug"] / "context" / "meetings").glob("*.md"))
    assert len(meetings) == 1
    content = meetings[0].read_text(encoding="utf-8")
    assert "title: team standup" in content
    assert "quarterly numbers" in content

    # Usage row logged with duration for per-minute pricing
    from core.agents.reminders.db import get_db
    row = get_db().execute(
        "SELECT model_used, audio_seconds, output_tokens FROM execution_history "
        "WHERE event_type='transcription'").fetchone()
    assert row["model_used"] == "gpt-4o-transcribe"
    assert row["audio_seconds"] == 125
    assert row["output_tokens"] == 42


def test_upload_audio_without_capable_provider_is_400(client, monkeypatch):
    import core.agents.transcription.service as svc
    from tests.test_http_agents import make_agent

    monkeypatch.setattr(svc, "pick_backend", lambda: None)
    agent = make_agent(client)
    resp = _upload_audio(client, agent)
    assert resp.status_code == 400
    assert "OpenAI or Google Gemini API key" in resp.json()["detail"]


def test_upload_audio_transcription_error_aborts_turn(transcribing_client, monkeypatch):
    import core.agents.transcription.service as svc
    from tests.conftest import parse_sse
    from tests.test_http_agents import make_agent

    async def failing_transcribe(path, filename):
        raise svc.TranscriptionError("boom: recording unreadable")
        yield  # pragma: no cover — makes this an async generator

    monkeypatch.setattr(svc, "transcribe_file", failing_transcribe)
    agent = make_agent(transcribing_client)
    events = parse_sse(_upload_audio(transcribing_client, agent))
    types = [e["type"] for e in events]
    assert "error" in types
    error = next(e for e in events if e["type"] == "error")
    assert "boom" in error["error"]
    # AI turn never ran
    assert "text" not in types
    assert transcribing_client._provider.seen_messages == []


def test_upload_all_empty_audio_cleans_temp_dir(transcribing_client, monkeypatch, tmp_path):
    """FIX 3: a temp dir created for audio uploads that all turn out to be
    0 bytes must still be removed (no pre_stream is built to own cleanup)."""
    import tempfile
    from tests.test_http_agents import make_agent

    known_dir = tmp_path / "known-audio-upload-dir"
    known_dir.mkdir()
    monkeypatch.setattr(tempfile, "mkdtemp", lambda **kw: str(known_dir))

    agent = make_agent(transcribing_client)
    import json
    payload = {"messages": [{"role": "user", "content": "here it is"}]}
    resp = transcribing_client.post(
        f"/api/agents/{agent['id']}/chat/upload",
        data={"payload": json.dumps(payload)},
        files=[("files", ("empty.mp3", b"", "audio/mpeg"))],
    )
    assert resp.status_code == 200
    assert not known_dir.exists()

    meetings_dir = tmp_path / agent["slug"] / "context" / "meetings"
    assert not (meetings_dir.exists() and list(meetings_dir.glob("*.md")))


def test_upload_two_audio_partial_failure_keeps_first(transcribing_client, monkeypatch, tmp_path):
    """FIX 6: when the first of two uploads transcribes+saves successfully
    but the second fails, the AI turn still runs with the first transcript
    intact (not discarded)."""
    import json

    import core.agents.transcription.service as svc
    from tests.conftest import parse_sse
    from tests.test_http_agents import make_agent

    async def fake_transcribe(path, filename):
        if filename == "good.mp3":
            yield {"stage": "transcribing", "message": "Transcribing…", "percent": 50}
            yield {
                "done": True,
                "transcript": "Speaker 1: good meeting notes",
                "duration_seconds": 60,
                "model": "gpt-4o-transcribe",
                "provider": "openai",
                "input_tokens": 0,
                "output_tokens": 10,
                "processing_ms": 500,
            }
        else:
            raise svc.TranscriptionError("boom: bad file")
            yield  # pragma: no cover — makes this an async generator

    monkeypatch.setattr(svc, "transcribe_file", fake_transcribe)

    agent = make_agent(transcribing_client)
    payload = {"messages": [{"role": "user", "content": "here are two"}]}
    resp = transcribing_client.post(
        f"/api/agents/{agent['id']}/chat/upload",
        data={"payload": json.dumps(payload)},
        files=[
            ("files", ("good.mp3", b"fake-audio-bytes", "audio/mpeg")),
            ("files", ("bad.mp3", b"fake-audio-bytes", "audio/mpeg")),
        ],
    )
    assert resp.status_code == 200
    events = parse_sse(resp)
    types = [e["type"] for e in events]
    assert "text" in types and "done" in types

    seen = transcribing_client._provider.seen_messages[0][-1]["content"]
    assert "Speaker 1: good meeting notes" in seen
    assert "bad.mp3" in seen  # failure note names the skipped file

    meetings = list((tmp_path / agent["slug"] / "context" / "meetings").glob("*.md"))
    assert len(meetings) == 1


def test_upload_audio_with_playbook_includes_transcript(transcribing_client, monkeypatch):
    """FIX E: an audio upload that ALSO invokes a playbook must build the
    playbook expansion AFTER the transcript is prepended, not before — the
    model must actually see the recording, not a transcript-less expansion."""
    import json

    import agents.router as router_mod

    captured = {}

    def fake_expansion(agent_slug, messages, playbook_slug):
        captured["messages_content"] = messages[-1]["content"]
        captured["playbook_slug"] = playbook_slug
        return "[EXPANDED]\n" + messages[-1]["content"]

    monkeypatch.setattr(router_mod, "_build_playbook_expansion", fake_expansion)

    from tests.test_http_agents import make_agent
    agent = make_agent(transcribing_client)
    payload = {
        "messages": [{"role": "user", "content": "here it is"}],
        "playbook_slug": "some-playbook",
    }
    resp = transcribing_client.post(
        f"/api/agents/{agent['id']}/chat/upload",
        data={"payload": json.dumps(payload)},
        files=[("files", ("team_standup.mp3", b"fake-audio-bytes", "audio/mpeg"))],
    )
    assert resp.status_code == 200

    # Expansion was built with the transcript already in the last user
    # message — proves it ran after pre_stream, not before it.
    assert "quarterly numbers look great" in captured["messages_content"]
    assert captured["playbook_slug"] == "some-playbook"

    seen = transcribing_client._provider.seen_messages[0][-1]["content"]
    assert seen.startswith("[EXPANDED]")
    assert "quarterly numbers look great" in seen


def test_upload_two_audio_save_failure_salvages_first(transcribing_client, monkeypatch, tmp_path):
    """FIX C: when the first recording transcribes+saves successfully but the
    second's SAVE step fails, the AI turn still runs with the first
    transcript intact (mirrors the existing transcription-failure salvage)."""
    import json

    import core.agents.transcription.service as svc
    import core.agents.tools.memory_tools as memory_tools_mod
    from tests.conftest import parse_sse
    from tests.test_http_agents import make_agent

    async def fake_transcribe(path, filename):
        yield {"stage": "transcribing", "message": "Transcribing…", "percent": 50}
        yield {
            "done": True,
            "transcript": f"Speaker 1: notes for {filename}",
            "duration_seconds": 60,
            "model": "gpt-4o-transcribe",
            "provider": "openai",
            "input_tokens": 0,
            "output_tokens": 10,
            "processing_ms": 500,
        }

    monkeypatch.setattr(svc, "transcribe_file", fake_transcribe)

    real_save = memory_tools_mod.save_meeting_transcript

    def flaky_save(data_dir, gcs_prefix, title, transcript, **kw):
        if kw.get("source_filename") == "bad.mp3":
            raise RuntimeError("disk full")
        return real_save(data_dir, gcs_prefix, title, transcript, **kw)

    monkeypatch.setattr(memory_tools_mod, "save_meeting_transcript", flaky_save)

    agent = make_agent(transcribing_client)
    payload = {"messages": [{"role": "user", "content": "here are two"}]}
    resp = transcribing_client.post(
        f"/api/agents/{agent['id']}/chat/upload",
        data={"payload": json.dumps(payload)},
        files=[
            ("files", ("good.mp3", b"fake-audio-bytes", "audio/mpeg")),
            ("files", ("bad.mp3", b"fake-audio-bytes", "audio/mpeg")),
        ],
    )
    assert resp.status_code == 200
    events = parse_sse(resp)
    types = [e["type"] for e in events]
    assert "text" in types and "done" in types

    seen = transcribing_client._provider.seen_messages[0][-1]["content"]
    assert "notes for good.mp3" in seen
    assert "saving the transcript" in seen and "bad.mp3" in seen

    meetings = list((tmp_path / agent["slug"] / "context" / "meetings").glob("*.md"))
    assert len(meetings) == 1


def test_upload_too_many_files_rejected(client):
    """FIX G: more than _MAX_FILES uploads must be rejected up front."""
    import json

    from tests.test_http_agents import make_agent

    agent = make_agent(client)
    payload = {"messages": [{"role": "user", "content": "hi"}]}
    files = [("files", (f"f{i}.txt", b"hello", "text/plain")) for i in range(6)]
    resp = client.post(
        f"/api/agents/{agent['id']}/chat/upload",
        data={"payload": json.dumps(payload)},
        files=files,
    )
    assert resp.status_code == 400
