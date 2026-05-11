"""Tests for the AI service chat flow, tool execution, and tool mode enforcement."""

import json
import time
from dataclasses import dataclass, field
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

from core.agents.ai_service import chat, run_sync
from core.providers.base import AIProvider
from tests.conftest import collect_events


# ---------------------------------------------------------------------------
# Mock provider
# ---------------------------------------------------------------------------

class MockAIProvider(AIProvider):
    """Fake provider that yields canned responses from a queue."""

    def __init__(self, responses=None):
        super().__init__(model="mock-model")
        self._responses = responses or [self._default_response()]
        self._call_index = 0

    @staticmethod
    def _default_response():
        return [
            {"type": "text", "text": "Hello from mock"},
            {
                "type": "_turn_complete",
                "tool_calls": [],
                "stop_reason": "stop",
                "usage": {"input_tokens": 10, "output_tokens": 5},
            },
        ]

    def set_responses(self, responses):
        self._responses = responses
        self._call_index = 0

    async def stream_turn(self, messages, tools, system_prompt):
        idx = min(self._call_index, len(self._responses) - 1)
        self._call_index += 1
        for event in self._responses[idx]:
            yield event

    def add_tool_results(self, messages, tool_calls, results):
        messages = list(messages)
        messages.append({"role": "assistant", "content": [
            {"type": "tool_use", "id": tc["id"], "name": tc["name"], "input": tc.get("args", {})}
            for tc in tool_calls
        ]})
        messages.append({"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": r["tool_use_id"], "content": r["content"]}
            for r in results
        ]})
        return messages

    async def list_models(self):
        return ["mock-model"]

    async def validate(self):
        return True

    @property
    def provider_name(self):
        return "mock"


# ---------------------------------------------------------------------------
# Minimal config / fixtures
# ---------------------------------------------------------------------------

@dataclass
class _FakeConfig:
    slug: str = "test-agent"
    agent_name: str = "Test Agent"
    context_dir: str = "/tmp/fake-context"
    gcs_prefix: str = ""
    provider_override: str = ""
    model_override: str = ""
    google_accounts: dict = field(default_factory=dict)
    personality: str = "You are a helpful test agent."


@pytest.fixture
def fake_config(tmp_path):
    ctx_dir = tmp_path / "context"
    ctx_dir.mkdir()
    return _FakeConfig(context_dir=str(ctx_dir))


@pytest.fixture
def mock_prov():
    return MockAIProvider()


@pytest.fixture
def mock_registry(tmp_path):
    reg = MagicMock()
    reg.execute_tool = AsyncMock(return_value={"result": "ok"})
    reg.account_info_map = None
    return reg


@pytest.fixture
def mock_ctx():
    ctx = MagicMock()
    ctx.load_all_context.return_value = ""
    ctx.topic_files_manifest.return_value = ""
    ctx.daily_notes_manifest.return_value = ""
    ctx.today_daily_note_text.return_value = ""
    ctx.relevance_prefetch.return_value = ""
    ctx.data_dir = "/tmp/fake"
    ctx.gcs_prefix = ""
    return ctx


def _no_caps(ids):
    return {
        "gmail_read_enabled": False, "gmail_send_enabled": False,
        "calendar_read_enabled": False, "calendar_write_enabled": False,
        "drive_read_enabled": False, "drive_write_enabled": False,
    }


@pytest.fixture(autouse=True)
def _patch_externals(monkeypatch):
    """Silence side-effects that reach into integrations, GCS, or activity log."""
    # google_capabilities_union is imported inside chat()/run_sync() — patch at source
    monkeypatch.setattr(
        "integrations.google.policy.google_capabilities_union", _no_caps,
    )
    # load_all_real_tools is a module-level import in ai_service
    monkeypatch.setattr(
        "core.agents.ai_service.load_all_real_tools", lambda path: [],
    )
    # These are module-level functions in ai_service
    monkeypatch.setattr(
        "core.agents.ai_service._log_chat_completion",
        lambda *a, **kw: None,
    )
    monkeypatch.setattr(
        "core.agents.ai_service._sync_context_after_tool",
        lambda *a, **kw: None,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestSingleTurn:
    async def test_simple_text_response(self, fake_config, mock_prov, mock_registry, mock_ctx):
        events = await collect_events(
            chat(fake_config, mock_prov, mock_registry, mock_ctx,
                 [{"role": "user", "content": "hi"}], tool_mode="power")
        )
        types = [e["type"] for e in events]
        assert "text" in types
        assert types[-1] == "done"
        text_events = [e for e in events if e["type"] == "text"]
        assert any("Hello from mock" in e["text"] for e in text_events)

    async def test_usage_event_emitted(self, fake_config, mock_prov, mock_registry, mock_ctx):
        events = await collect_events(
            chat(fake_config, mock_prov, mock_registry, mock_ctx,
                 [{"role": "user", "content": "hi"}], tool_mode="power")
        )
        usage = [e for e in events if e["type"] == "usage"]
        assert len(usage) == 1
        assert usage[0]["input_tokens"] == 10
        assert usage[0]["output_tokens"] == 5


class TestToolExecution:
    async def test_tool_call_executes_and_continues(self, fake_config, mock_prov, mock_registry, mock_ctx):
        mock_prov.set_responses([
            [
                {"type": "tool_start", "tool": "list_context_files", "tool_use_id": "tu1"},
                {"type": "_turn_complete", "tool_calls": [
                    {"name": "list_context_files", "id": "tu1", "args": {}}
                ], "stop_reason": "tool_use", "usage": {"input_tokens": 5, "output_tokens": 3}},
            ],
            MockAIProvider._default_response(),
        ])
        events = await collect_events(
            chat(fake_config, mock_prov, mock_registry, mock_ctx,
                 [{"role": "user", "content": "list files"}], tool_mode="power")
        )
        types = [e["type"] for e in events]
        assert "tool_start" in types
        assert "tool_end" in types
        assert types[-1] == "done"
        mock_registry.execute_tool.assert_called_once()

    async def test_tool_end_has_elapsed_ms(self, fake_config, mock_prov, mock_registry, mock_ctx):
        mock_prov.set_responses([
            [
                {"type": "_turn_complete", "tool_calls": [
                    {"name": "list_context_files", "id": "tu1", "args": {}}
                ], "stop_reason": "tool_use", "usage": {}},
            ],
            MockAIProvider._default_response(),
        ])
        events = await collect_events(
            chat(fake_config, mock_prov, mock_registry, mock_ctx,
                 [{"role": "user", "content": "go"}], tool_mode="power")
        )
        tool_ends = [e for e in events if e["type"] == "tool_end"]
        assert len(tool_ends) == 1
        assert "elapsed_ms" in tool_ends[0]


class TestToolModeEnforcement:
    async def test_normal_mode_emits_confirm_for_write_tool(self, fake_config, mock_prov, mock_registry, mock_ctx):
        mock_prov.set_responses([
            [
                {"type": "_turn_complete", "tool_calls": [
                    {"name": "send_email", "id": "tu1", "args": {"to": "a@b.com", "subject": "hi", "body": "test"}}
                ], "stop_reason": "tool_use", "usage": {}},
            ],
            MockAIProvider._default_response(),
        ])
        events = await collect_events(
            chat(fake_config, mock_prov, mock_registry, mock_ctx,
                 [{"role": "user", "content": "send email"}],
                 tool_mode="normal",
                 integration_tool_defs=[{
                     "name": "send_email", "kind": "gmail",
                     "writes": True, "input_schema": {"type": "object", "properties": {}},
                     "description": "Send an email",
                 }])
        )
        types = [e["type"] for e in events]
        assert "confirm" in types
        confirm = next(e for e in events if e["type"] == "confirm")
        assert confirm["tool"] == "send_email"
        assert confirm["tool_use_id"] == "tu1"

    async def test_power_mode_executes_write_without_confirm(self, fake_config, mock_prov, mock_registry, mock_ctx):
        mock_prov.set_responses([
            [
                {"type": "_turn_complete", "tool_calls": [
                    {"name": "send_email", "id": "tu1", "args": {}}
                ], "stop_reason": "tool_use", "usage": {}},
            ],
            MockAIProvider._default_response(),
        ])
        events = await collect_events(
            chat(fake_config, mock_prov, mock_registry, mock_ctx,
                 [{"role": "user", "content": "send email"}],
                 tool_mode="power",
                 integration_tool_defs=[{
                     "name": "send_email", "kind": "gmail",
                     "writes": True, "input_schema": {"type": "object", "properties": {}},
                     "description": "Send an email",
                 }])
        )
        types = [e["type"] for e in events]
        assert "confirm" not in types
        assert "tool_end" in types

    async def test_context_memory_write_bypasses_confirm_in_normal_mode(self, fake_config, mock_prov, mock_registry, mock_ctx):
        mock_prov.set_responses([
            [
                {"type": "_turn_complete", "tool_calls": [
                    {"name": "write_context_file", "id": "tu1", "args": {"filename": "test.md", "content": "data"}}
                ], "stop_reason": "tool_use", "usage": {}},
            ],
            MockAIProvider._default_response(),
        ])
        events = await collect_events(
            chat(fake_config, mock_prov, mock_registry, mock_ctx,
                 [{"role": "user", "content": "save this"}], tool_mode="normal")
        )
        types = [e["type"] for e in events]
        assert "confirm" not in types
        assert "tool_end" in types


class TestMultiTurn:
    async def test_max_iterations_emits_error(self, fake_config, mock_prov, mock_registry, mock_ctx):
        infinite_tool_response = [
            {"type": "_turn_complete", "tool_calls": [
                {"name": "list_context_files", "id": "tu1", "args": {}}
            ], "stop_reason": "tool_use", "usage": {}},
        ]
        mock_prov.set_responses([infinite_tool_response])
        events = await collect_events(
            chat(fake_config, mock_prov, mock_registry, mock_ctx,
                 [{"role": "user", "content": "loop"}], tool_mode="power")
        )
        types = [e["type"] for e in events]
        assert "error" in types


class TestErrorHandling:
    async def test_provider_error_yields_error_event(self, fake_config, mock_prov, mock_registry, mock_ctx):
        mock_prov.set_responses([
            [{"type": "error", "error": "Rate limited"}],
        ])
        events = await collect_events(
            chat(fake_config, mock_prov, mock_registry, mock_ctx,
                 [{"role": "user", "content": "hi"}], tool_mode="power")
        )
        errors = [e for e in events if e["type"] == "error"]
        assert len(errors) == 1
        assert "Rate limited" in errors[0]["error"]

    async def test_tool_error_continues_loop(self, fake_config, mock_prov, mock_registry, mock_ctx):
        mock_registry.execute_tool = AsyncMock(return_value={"error": "Tool broke"})
        mock_prov.set_responses([
            [
                {"type": "_turn_complete", "tool_calls": [
                    {"name": "list_context_files", "id": "tu1", "args": {}}
                ], "stop_reason": "tool_use", "usage": {}},
            ],
            MockAIProvider._default_response(),
        ])
        events = await collect_events(
            chat(fake_config, mock_prov, mock_registry, mock_ctx,
                 [{"role": "user", "content": "go"}], tool_mode="power")
        )
        types = [e["type"] for e in events]
        assert types[-1] == "done"
        assert "tool_end" in types


class TestSSEFormat:
    async def test_all_events_are_valid_sse(self, fake_config, mock_prov, mock_registry, mock_ctx):
        raw_lines = []
        async for line in chat(fake_config, mock_prov, mock_registry, mock_ctx,
                               [{"role": "user", "content": "hi"}], tool_mode="power"):
            raw_lines.append(line)
        for line in raw_lines:
            assert line.startswith("data: "), f"Not SSE format: {line!r}"
            assert line.endswith("\n\n"), f"Missing trailing newlines: {line!r}"
            json.loads(line[6:].strip())


class TestRunSync:
    async def test_returns_accumulated_text(self, fake_config, mock_prov, mock_registry, mock_ctx):
        result = await run_sync(
            fake_config, mock_prov, mock_registry, mock_ctx,
            [{"role": "user", "content": "hi"}],
        )
        assert "Hello from mock" in result
