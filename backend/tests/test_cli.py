"""Tests for the CLI test harness — SSE parsing, StreamRenderer, session management, and commands."""

import asyncio
from dataclasses import dataclass, field
from unittest.mock import patch, MagicMock

import pytest

from cli.output import parse_sse, StreamRenderer
from cli.session import Session, reset_conversation
from cli.commands import COMMANDS, handle_command


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@dataclass
class _FakeConfig:
    agent_name: str = "TestAgent"
    slug: str = "test-agent"
    context_dir: str = "/tmp/fake-context"
    gcs_prefix: str = ""
    provider_override: str = ""
    model_override: str = ""
    google_accounts: dict = field(default_factory=dict)


def _make_session(**overrides) -> Session:
    defaults = dict(
        agent={"slug": "test-agent", "agent_name": "TestAgent"},
        config=_FakeConfig(),
        provider=MagicMock(),
        registry=MagicMock(),
        ctx_manager=MagicMock(),
        chat_service=MagicMock(),
        tool_mode="normal",
        persist=False,
        verbose=False,
    )
    defaults.update(overrides)
    return Session(**defaults)


# ---------------------------------------------------------------------------
# parse_sse
# ---------------------------------------------------------------------------

class TestParseSSE:
    def test_valid_text_event(self):
        result = parse_sse('data: {"type":"text","text":"hello"}')
        assert result == {"type": "text", "text": "hello"}

    def test_valid_done_event(self):
        result = parse_sse('data: {"type":"done"}')
        assert result == {"type": "done"}

    def test_empty_line(self):
        assert parse_sse("") is None

    def test_whitespace_only(self):
        assert parse_sse("   ") is None

    def test_non_data_prefix(self):
        assert parse_sse("event: something") is None

    def test_invalid_json(self):
        assert parse_sse("data: {broken json}") is None

    def test_surrounding_whitespace(self):
        result = parse_sse('  data: {"type":"done"}  ')
        assert result == {"type": "done"}

    def test_complex_payload(self):
        result = parse_sse('data: {"type":"tool_end","tool":"read_file","result":{"ok":true},"elapsed_ms":42}')
        assert result["type"] == "tool_end"
        assert result["tool"] == "read_file"
        assert result["elapsed_ms"] == 42


# ---------------------------------------------------------------------------
# StreamRenderer
# ---------------------------------------------------------------------------

class TestStreamRendererTextAccumulation:
    def test_accumulates_text_chunks(self):
        r = StreamRenderer()
        session = _make_session()
        r.handle({"type": "text", "text": "Hello "}, session)
        r.handle({"type": "text", "text": "world"}, session)
        assert r.accumulated_text == "Hello world"

    def test_reset_clears_state(self):
        r = StreamRenderer()
        session = _make_session()
        r.handle({"type": "text", "text": "data"}, session)
        r.handle({"type": "confirm", "tool": "x", "args": {}, "tool_use_id": "1"}, session)
        r.reset()
        assert r.accumulated_text == ""
        assert r.pending_confirmation is None
        assert r._in_text is False


class TestStreamRendererConversationId:
    def test_sets_conversation_id(self):
        r = StreamRenderer()
        session = _make_session()
        r.handle({"type": "conversation_id", "id": "conv-abc"}, session)
        assert session.conversation_id == "conv-abc"


class TestStreamRendererUsage:
    def test_accumulates_usage(self):
        r = StreamRenderer()
        session = _make_session()
        r.handle({"type": "usage", "input_tokens": 100, "output_tokens": 50}, session)
        r.handle({"type": "usage", "input_tokens": 25, "output_tokens": 10}, session)
        assert session.usage["input_tokens"] == 125
        assert session.usage["output_tokens"] == 60

    def test_missing_token_fields(self):
        r = StreamRenderer()
        session = _make_session()
        r.handle({"type": "usage"}, session)
        assert session.usage["input_tokens"] == 0
        assert session.usage["output_tokens"] == 0


class TestStreamRendererConfirm:
    def test_captures_confirm_event(self):
        r = StreamRenderer()
        session = _make_session()
        r.handle({"type": "confirm", "tool": "send_email", "args": {"to": "x"}, "tool_use_id": "tu-1"}, session)
        assert r.pending_confirmation is not None
        assert r.pending_confirmation["tool"] == "send_email"
        assert r.pending_confirmation["tool_use_id"] == "tu-1"


class TestStreamRendererToolEvents:
    def test_tool_start_flushes_text(self):
        r = StreamRenderer()
        session = _make_session()
        r.handle({"type": "text", "text": "before"}, session)
        assert r._in_text is True
        r.handle({"type": "tool_start", "tool": "read_file"}, session)
        assert r._in_text is False


# ---------------------------------------------------------------------------
# Session reset
# ---------------------------------------------------------------------------

class TestResetConversation:
    def test_clears_messages(self):
        s = _make_session()
        s.messages.append({"role": "user", "content": "hi"})
        reset_conversation(s)
        assert s.messages == []

    def test_clears_conversation_id(self):
        s = _make_session()
        s.conversation_id = "conv-123"
        reset_conversation(s)
        assert s.conversation_id is None

    def test_resets_usage_counters(self):
        s = _make_session()
        s.usage = {"input_tokens": 500, "output_tokens": 200}
        reset_conversation(s)
        assert s.usage == {"input_tokens": 0, "output_tokens": 0}


# ---------------------------------------------------------------------------
# Slash commands
# ---------------------------------------------------------------------------

def _run(coro):
    return asyncio.run(coro)


class TestCommandQuit:
    def test_quit(self):
        s = _make_session()
        r = StreamRenderer()
        assert _run(handle_command("/quit", s, r)) == "quit"

    def test_exit(self):
        s = _make_session()
        r = StreamRenderer()
        assert _run(handle_command("/exit", s, r)) == "quit"


class TestCommandHelp:
    def test_returns_none(self):
        s = _make_session()
        r = StreamRenderer()
        assert _run(handle_command("/help", s, r)) is None


class TestCommandMode:
    def test_power_mode(self):
        s = _make_session()
        r = StreamRenderer()
        _run(handle_command("/mode power", s, r))
        assert s.tool_mode == "power"

    def test_readonly_mode(self):
        s = _make_session()
        r = StreamRenderer()
        _run(handle_command("/mode readonly", s, r))
        assert s.tool_mode == "read-only"

    def test_normal_mode(self):
        s = _make_session(tool_mode="power")
        r = StreamRenderer()
        _run(handle_command("/mode normal", s, r))
        assert s.tool_mode == "normal"

    def test_no_arg_preserves_mode(self):
        s = _make_session(tool_mode="power")
        r = StreamRenderer()
        _run(handle_command("/mode", s, r))
        assert s.tool_mode == "power"

    def test_invalid_mode_preserves_mode(self):
        s = _make_session(tool_mode="normal")
        r = StreamRenderer()
        _run(handle_command("/mode turbo", s, r))
        assert s.tool_mode == "normal"


class TestCommandVerbose:
    def test_toggles_on(self):
        s = _make_session(verbose=False)
        r = StreamRenderer(verbose=False)
        _run(handle_command("/verbose", s, r))
        assert s.verbose is True

    def test_toggles_off(self):
        s = _make_session(verbose=True)
        r = StreamRenderer(verbose=True)
        _run(handle_command("/verbose", s, r))
        assert s.verbose is False


class TestCommandUnknown:
    def test_unknown_returns_none(self):
        s = _make_session()
        r = StreamRenderer()
        assert _run(handle_command("/nonexistent", s, r)) is None


class TestCommandAgent:
    def test_runs_without_error(self):
        s = _make_session()
        s.provider.__class__.__name__ = "OllamaProvider"
        s.provider.model = "llama3.1:8b"
        r = StreamRenderer()
        assert _run(handle_command("/agent", s, r)) is None


class TestCommandUsage:
    def test_runs_without_error(self):
        s = _make_session()
        s.usage = {"input_tokens": 1000, "output_tokens": 500}
        r = StreamRenderer()
        assert _run(handle_command("/usage", s, r)) is None


class TestCommandReset:
    def test_clears_session(self):
        s = _make_session()
        s.messages.append({"role": "user", "content": "hi"})
        s.conversation_id = "conv-old"
        r = StreamRenderer()
        _run(handle_command("/reset", s, r))
        assert s.messages == []
        assert s.conversation_id is None


class TestCommandSearch:
    def test_no_arg_handled(self):
        s = _make_session()
        r = StreamRenderer()
        assert _run(handle_command("/search", s, r)) is None


class TestCommandRead:
    def test_rejects_path_traversal(self):
        s = _make_session()
        r = StreamRenderer()
        assert _run(handle_command("/read ../../etc/passwd", s, r)) is None

    def test_rejects_non_md_file(self):
        s = _make_session()
        r = StreamRenderer()
        assert _run(handle_command("/read secrets.json", s, r)) is None

    def test_rejects_empty_arg(self):
        s = _make_session()
        r = StreamRenderer()
        assert _run(handle_command("/read", s, r)) is None

    def test_accepts_valid_md(self):
        s = _make_session()
        s.ctx_manager.read_context.return_value = None
        r = StreamRenderer()
        assert _run(handle_command("/read notes.md", s, r)) is None
        s.ctx_manager.read_context.assert_called_once_with("notes.md")


class TestCommandDaily:
    def test_invalid_date_format(self):
        s = _make_session()
        r = StreamRenderer()
        assert _run(handle_command("/daily not-a-date", s, r)) is None

    def test_valid_date(self):
        s = _make_session()
        s.ctx_manager.read_daily_note = MagicMock(return_value=None)
        r = StreamRenderer()
        _run(handle_command("/daily 2026-01-15", s, r))
        s.ctx_manager.read_daily_note.assert_called_once_with("2026-01-15")


# ---------------------------------------------------------------------------
# COMMANDS dict sanity
# ---------------------------------------------------------------------------

class TestCommandsRegistry:
    def test_all_commands_start_with_slash(self):
        for cmd in COMMANDS:
            assert cmd.startswith("/"), f"{cmd} missing leading slash"

    def test_quit_and_exit_both_present(self):
        assert "/quit" in COMMANDS
        assert "/exit" in COMMANDS

    def test_all_descriptions_non_empty(self):
        for cmd, desc in COMMANDS.items():
            assert len(desc) > 0, f"{cmd} has empty description"
