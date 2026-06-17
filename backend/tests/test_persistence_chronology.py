"""Integration tests for faithful, chronological conversation persistence.

Drives chat()/run_sync() against a REAL ChatHistoryService over a temp DB and
asserts the stored rows. These guard the core of the persistence epic:

  * every model iteration that has text OR tool calls is saved as its own row
    (the old `if turn_text` gate dropped tool-only iterations — the chronology
    bug), carrying THAT iteration's own tool_calls, not a turn-global blob;
  * full tool results are attached to the right row and carried across turns;
  * approved write tools reconcile onto the pending row (no "[Approved]" user
    row, no duplicate exchange);
  * exit_plan_mode wrap-up narration is persisted; pending-confirmation rows
    stay NULL until approval.
"""

import json
from dataclasses import dataclass, field

import pytest
from unittest.mock import MagicMock, AsyncMock

from core.agents.ai_service import chat, run_sync
from tests.conftest import collect_events
from tests.test_ai_service import MockAIProvider


# ---------------------------------------------------------------------------
# Fixtures (mirror test_ai_service, plus a real chat-history service)
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
def mock_registry():
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


@pytest.fixture
def chat_service(tmp_path):
    from core.agents.chat_history.db import ChatHistoryDB
    from core.agents.chat_history.service import ChatHistoryService
    db = ChatHistoryDB(data_dir=tmp_path, gcs_prefix="test/", db_filename="chat.db")
    db._setup_connection()
    db.backup_to_gcs = lambda: None  # no GCS in tests
    return ChatHistoryService(db)


def _no_caps(ids):
    return {
        "gmail_read_enabled": False, "gmail_send_enabled": False,
        "calendar_read_enabled": False, "calendar_write_enabled": False,
        "drive_read_enabled": False, "drive_write_enabled": False,
    }


@pytest.fixture(autouse=True)
def _patch_externals(monkeypatch):
    monkeypatch.setattr("integrations.google.policy.google_capabilities_union", _no_caps)
    monkeypatch.setattr("core.agents.ai_service.load_all_real_tools", lambda path: [])
    monkeypatch.setattr("core.agents.ai_service._log_chat_completion", lambda *a, **kw: None)
    monkeypatch.setattr("core.agents.ai_service._sync_context_after_tool", lambda *a, **kw: None)
    # Background playbook review builds its own provider and calls an LLM — stub it.
    monkeypatch.setattr("core.agents.playbooks.review.maybe_schedule_review", lambda *a, **k: False)


_EMAIL_TOOL = [{
    "name": "send_email", "kind": "gmail", "writes": True,
    "input_schema": {"type": "object", "properties": {}}, "description": "Send an email",
}]


def _rows(chat_service, cid):
    return chat_service.get_conversation(cid)["messages"]


# ---------------------------------------------------------------------------
# Per-iteration chronology
# ---------------------------------------------------------------------------

class TestChronology:
    async def test_tool_only_iteration_is_persisted(
            self, fake_config, mock_prov, mock_registry, mock_ctx, chat_service):
        # Iteration 1: a tool call with NO assistant text. Iteration 2: final text.
        # The old `if turn_text` gate dropped iteration 1 entirely.
        cid = chat_service.create_conversation()["id"]
        mock_prov.set_responses([
            [{"type": "_turn_complete",
              "tool_calls": [{"name": "list_context_files", "id": "tu1", "args": {}}],
              "stop_reason": "tool_use", "usage": {"input_tokens": 5}}],
            [{"type": "text", "text": "Done."},
             {"type": "_turn_complete", "tool_calls": [], "stop_reason": "stop",
              "usage": {"input_tokens": 10}}],
        ])
        await collect_events(chat(
            fake_config, mock_prov, mock_registry, mock_ctx,
            [{"role": "user", "content": "list files"}], tool_mode="power",
            chat_service=chat_service, conversation_id=cid))

        rows = _rows(chat_service, cid)
        # user, assistant(tool-only iteration), assistant(final text)
        assert [r["role"] for r in rows] == ["user", "assistant", "assistant"]
        tool_row = rows[1]
        assert json.loads(tool_row["tool_calls"])[0]["tool"] == "list_context_files"
        # Results were attached to the SAME tool row via the true UPDATE.
        assert tool_row["tool_results"] is not None
        assert json.loads(tool_row["tool_results"])[0]["tool_use_id"] == "tu1"
        # Final text row carries no tool calls.
        assert rows[2]["content"] == "Done." and rows[2]["tool_calls"] is None

    async def test_each_row_holds_its_own_tool_calls_not_the_accumulator(
            self, fake_config, mock_prov, mock_registry, mock_ctx, chat_service):
        # Two tool iterations then a final answer. Each assistant row must hold
        # ONLY its own call — not the turn-global accumulation onto a later row.
        cid = chat_service.create_conversation()["id"]
        mock_prov.set_responses([
            [{"type": "_turn_complete",
              "tool_calls": [{"name": "tool_a", "id": "ta", "args": {"i": 1}}],
              "stop_reason": "tool_use", "usage": {}}],
            [{"type": "_turn_complete",
              "tool_calls": [{"name": "tool_b", "id": "tb", "args": {"i": 2}}],
              "stop_reason": "tool_use", "usage": {}}],
            [{"type": "text", "text": "final"},
             {"type": "_turn_complete", "tool_calls": [], "stop_reason": "stop", "usage": {}}],
        ])
        await collect_events(chat(
            fake_config, mock_prov, mock_registry, mock_ctx,
            [{"role": "user", "content": "go"}], tool_mode="power",
            chat_service=chat_service, conversation_id=cid))

        rows = _rows(chat_service, cid)
        assistant_tool_rows = [r for r in rows if r["role"] == "assistant" and r["tool_calls"]]
        assert len(assistant_tool_rows) == 2
        calls = [json.loads(r["tool_calls"]) for r in assistant_tool_rows]
        assert [c[0]["tool"] for c in calls] == ["tool_a", "tool_b"]
        assert all(len(c) == 1 for c in calls)  # one call each, no accumulation

    async def test_context_builds_across_turns(
            self, fake_config, mock_prov, mock_registry, mock_ctx, chat_service):
        # Turn 1 fetches a big result; turn 2's assembled history carries it in full.
        cid = chat_service.create_conversation()["id"]
        big = {"article": "Z" * 6000}
        mock_registry.execute_tool = AsyncMock(return_value=big)
        mock_prov.set_responses([
            [{"type": "_turn_complete",
              "tool_calls": [{"name": "list_context_files", "id": "tu1", "args": {}}],
              "stop_reason": "tool_use", "usage": {}}],
            [{"type": "text", "text": "Got it."},
             {"type": "_turn_complete", "tool_calls": [], "stop_reason": "stop", "usage": {}}],
        ])
        await collect_events(chat(
            fake_config, mock_prov, mock_registry, mock_ctx,
            [{"role": "user", "content": "fetch"}], tool_mode="power",
            chat_service=chat_service, conversation_id=cid))

        # Turn 2: capture what the provider is asked to stream.
        seen = {}
        orig = mock_prov.stream_turn

        async def _spy(messages, tools, system_prompt):
            seen["messages"] = messages
            async for ev in orig(messages, tools, system_prompt):
                yield ev
        mock_prov.stream_turn = _spy
        mock_prov.set_responses([MockAIProvider._default_response()])
        await collect_events(chat(
            fake_config, mock_prov, mock_registry, mock_ctx,
            [{"role": "user", "content": "summarize it"}], tool_mode="power",
            chat_service=chat_service, conversation_id=cid))

        blob = json.dumps(seen["messages"])
        assert "Z" * 6000 in blob  # the full turn-1 result is present in turn-2 context


# ---------------------------------------------------------------------------
# Write-confirmation + approval reconciliation
# ---------------------------------------------------------------------------

class TestApprovalReconciliation:
    async def test_pending_confirmation_saves_null_results_no_wrapup_row(
            self, fake_config, mock_prov, mock_registry, mock_ctx, chat_service):
        cid = chat_service.create_conversation()["id"]
        mock_prov.set_responses([
            [{"type": "_turn_complete",
              "tool_calls": [{"name": "send_email", "id": "tu1", "args": {"to": "a@b.com"}}],
              "stop_reason": "tool_use", "usage": {}}],
            [{"type": "text", "text": "I'll send it once you confirm."},
             {"type": "_turn_complete", "tool_calls": [], "stop_reason": "stop", "usage": {}}],
        ])
        events = await collect_events(chat(
            fake_config, mock_prov, mock_registry, mock_ctx,
            [{"role": "user", "content": "email a@b.com"}], tool_mode="normal",
            integration_tool_defs=_EMAIL_TOOL,
            chat_service=chat_service, conversation_id=cid))

        assert any(e["type"] == "confirm" for e in events)
        rows = _rows(chat_service, cid)
        # user + the pending tool row only; the "confirm?" wrap-up is NOT persisted
        # (it would contradict the approved result after reconciliation).
        assert [r["role"] for r in rows] == ["user", "assistant"]
        pending = rows[1]
        assert json.loads(pending["tool_calls"])[0]["tool"] == "send_email"
        # The pending placeholder IS persisted (so a non-approval next turn shows
        # "pending", not "result not recorded"); approval merges the real result.
        results = json.loads(pending["tool_results"])
        assert "pending_user_approval" in results[0]["content"]

    async def test_approval_reconciles_pending_row_without_duplicate(
            self, fake_config, mock_prov, mock_registry, mock_ctx, chat_service):
        cid = chat_service.create_conversation()["id"]
        # Turn 1: propose the write (pending).
        mock_prov.set_responses([
            [{"type": "_turn_complete",
              "tool_calls": [{"name": "send_email", "id": "tu1", "args": {"to": "a@b.com"}}],
              "stop_reason": "tool_use", "usage": {}}],
            [{"type": "text", "text": "Confirm?"},
             {"type": "_turn_complete", "tool_calls": [], "stop_reason": "stop", "usage": {}}],
        ])
        await collect_events(chat(
            fake_config, mock_prov, mock_registry, mock_ctx,
            [{"role": "user", "content": "email a@b.com"}], tool_mode="normal",
            integration_tool_defs=_EMAIL_TOOL,
            chat_service=chat_service, conversation_id=cid))

        # Turn 2: user approves; frontend sends the executed result + "[Approved]".
        mock_prov.set_responses([
            [{"type": "text", "text": "Sent!"},
             {"type": "_turn_complete", "tool_calls": [], "stop_reason": "stop", "usage": {}}],
        ])
        await collect_events(chat(
            fake_config, mock_prov, mock_registry, mock_ctx,
            [{"role": "user", "content": "[Approved] send_email"}], tool_mode="normal",
            integration_tool_defs=_EMAIL_TOOL,
            approved_tool={"tool": "send_email", "args": {"to": "a@b.com"},
                           "toolUseId": "tu1", "result": {"status": "sent", "id": "e99"}},
            chat_service=chat_service, conversation_id=cid))

        rows = _rows(chat_service, cid)
        # No "[Approved]" user row was persisted.
        assert not any(r["role"] == "user" and "[Approved]" in r["content"] for r in rows)
        assert chat_service.count_user_messages(cid) == 1  # only the original
        # The pending row was reconciled in place (not duplicated).
        send_rows = [r for r in rows if r["tool_calls"]
                     and json.loads(r["tool_calls"])[0]["tool"] == "send_email"]
        assert len(send_rows) == 1
        results = json.loads(send_rows[0]["tool_results"])
        assert results[0]["content"] == json.dumps({"status": "sent", "id": "e99"})
        # A fresh assistant reaction was appended.
        assert any(r["role"] == "assistant" and r["content"] == "Sent!" for r in rows)

    async def test_approval_keeps_parallel_read_result_executed_same_iteration(
            self, fake_config, mock_prov, mock_registry, mock_ctx, chat_service):
        # One iteration issues a read (executes) AND a write (needs approval).
        # The read result must survive the approval merge, not get clobbered.
        cid = chat_service.create_conversation()["id"]
        mock_registry.execute_tool = AsyncMock(return_value={"contacts": ["bob"]})
        mock_prov.set_responses([
            [{"type": "_turn_complete", "tool_calls": [
                {"name": "list_context_files", "id": "tr", "args": {}},
                {"name": "send_email", "id": "tw", "args": {"to": "a@b.com"}}],
              "stop_reason": "tool_use", "usage": {}}],
            [{"type": "text", "text": "Found bob — confirm send?"},
             {"type": "_turn_complete", "tool_calls": [], "stop_reason": "stop", "usage": {}}],
        ])
        await collect_events(chat(
            fake_config, mock_prov, mock_registry, mock_ctx,
            [{"role": "user", "content": "email my contact"}], tool_mode="normal",
            integration_tool_defs=_EMAIL_TOOL,
            chat_service=chat_service, conversation_id=cid))

        # Pending row holds the read result + the write placeholder.
        pending = next(r for r in _rows(chat_service, cid) if r["tool_calls"])
        by_id = {x["tool_use_id"]: x for x in json.loads(pending["tool_results"])}
        assert "bob" in by_id["tr"]["content"]
        assert "pending_user_approval" in by_id["tw"]["content"]

        # Approve the write → merge keeps the read, fills the write.
        mock_prov.set_responses([
            [{"type": "text", "text": "Sent."},
             {"type": "_turn_complete", "tool_calls": [], "stop_reason": "stop", "usage": {}}]])
        await collect_events(chat(
            fake_config, mock_prov, mock_registry, mock_ctx,
            [{"role": "user", "content": "[Approved] send_email"}], tool_mode="normal",
            integration_tool_defs=_EMAIL_TOOL,
            approved_tool={"tool": "send_email", "args": {}, "toolUseId": "tw",
                           "result": {"status": "sent"}},
            chat_service=chat_service, conversation_id=cid))

        pending = next(r for r in _rows(chat_service, cid) if r["tool_calls"])
        by_id = {x["tool_use_id"]: x for x in json.loads(pending["tool_results"])}
        assert "bob" in by_id["tr"]["content"]                       # read preserved
        assert by_id["tw"]["content"] == json.dumps({"status": "sent"})  # write filled


# ---------------------------------------------------------------------------
# Plan mode
# ---------------------------------------------------------------------------

class TestPlanMode:
    async def test_exit_plan_mode_wrapup_is_persisted(
            self, fake_config, mock_prov, mock_registry, mock_ctx, chat_service):
        cid = chat_service.create_conversation()["id"]
        mock_prov.set_responses([
            [{"type": "_turn_complete",
              "tool_calls": [{"name": "exit_plan_mode", "id": "tp1", "args": {"plan": "Step 1, 2, 3"}}],
              "stop_reason": "tool_use", "usage": {}}],
            [{"type": "text", "text": "Here's my plan — let me know."},
             {"type": "_turn_complete", "tool_calls": [], "stop_reason": "stop", "usage": {}}],
        ])
        events = await collect_events(chat(
            fake_config, mock_prov, mock_registry, mock_ctx,
            [{"role": "user", "content": "plan it"}], tool_mode="power", plan_mode=True,
            chat_service=chat_service, conversation_id=cid))

        assert any(e["type"] == "plan_ready" for e in events)
        rows = _rows(chat_service, cid)
        # The exit_plan_mode tool row has its result attached, and the wrap-up
        # narration is persisted as its own assistant row.
        plan_row = next(r for r in rows if r["tool_calls"]
                        and json.loads(r["tool_calls"])[0]["tool"] == "exit_plan_mode")
        assert plan_row["tool_results"] is not None
        assert any(r["role"] == "assistant" and r["content"] == "Here's my plan — let me know."
                   for r in rows)


# ---------------------------------------------------------------------------
# run_sync (messaging path)
# ---------------------------------------------------------------------------

class TestCompactionIntegration:
    async def test_gist_replaces_middle_in_assembled_context(
            self, fake_config, mock_prov, mock_registry, mock_ctx, chat_service, monkeypatch):
        # Drive a real chat() turn on an over-threshold thread and assert the
        # provider sees a <conversation_summary> gist with the aged middle gone.
        _GIST = "EARLIER: user planned a Rome trip; budget $5000; 5/17 booked."

        class _Blk:
            def __init__(self, t): self.type = "text"; self.text = t

        class _Messages:
            def create(self, **kw):
                return type("R", (), {"content": [_Blk(_GIST)]})()

        class _Client:
            def __init__(self, *a, **k): self.messages = _Messages()
        import anthropic
        monkeypatch.setattr(anthropic, "Anthropic", _Client)

        mock_prov.context_window_value = 2000  # small window → easy threshold
        cid = chat_service.create_conversation()["id"]
        for i in range(12):
            chat_service.save_message(cid, f"u{i}", "user", f"MARK{i}MARK " + "U" * 400)
            chat_service.save_message(cid, f"a{i}", "assistant", f"REPLY{i}END " + "A" * 400)
        chat_service.set_turn_usage(cid, 1700, 2000, "mock-model")  # over 70%

        seen = {}
        orig = mock_prov.stream_turn

        async def _spy(messages, tools, system_prompt):
            seen["messages"] = messages
            async for ev in orig(messages, tools, system_prompt):
                yield ev
        mock_prov.stream_turn = _spy
        mock_prov.set_responses([MockAIProvider._default_response()])

        events = await collect_events(chat(
            fake_config, mock_prov, mock_registry, mock_ctx,
            [{"role": "user", "content": "what's next?"}], tool_mode="power",
            chat_service=chat_service, conversation_id=cid))

        blob = json.dumps(seen["messages"])
        assert "conversation_summary" in blob          # gist injected
        assert "EARLIER: user planned a Rome trip" in blob
        assert "MARK0MARK" in blob                      # head kept verbatim
        assert "MARK3MARK" not in blob                  # aged middle dropped
        assert "what's next?" in blob                   # newest turn kept
        # A compaction boundary was persisted.
        summary, first_kept = chat_service.get_compaction(cid)
        assert summary and first_kept is not None
        # And the UI was signalled so it can show the "compacted" chip.
        assert any(e["type"] == "compacted" for e in events)


class TestRunSyncPersistence:
    async def test_run_sync_persists_tool_iteration_and_usage(
            self, fake_config, mock_prov, mock_registry, mock_ctx, chat_service):
        cid = chat_service.create_conversation()["id"]
        mock_prov.set_responses([
            [{"type": "_turn_complete",
              "tool_calls": [{"name": "list_context_files", "id": "tu1", "args": {}}],
              "stop_reason": "tool_use", "usage": {"input_tokens": 5}}],
            [{"type": "text", "text": "ok"},
             {"type": "_turn_complete", "tool_calls": [], "stop_reason": "stop",
              "usage": {"input_tokens": 1234, "cache_read_input_tokens": 2000}}],
        ])
        out = await run_sync(
            fake_config, mock_prov, mock_registry, mock_ctx,
            [{"role": "user", "content": "list"}],
            chat_service=chat_service, conversation_id=cid, source="telegram")

        assert out == "ok"
        rows = _rows(chat_service, cid)
        tool_row = next(r for r in rows if r["tool_calls"])
        assert tool_row["tool_results"] is not None
        # Main-turn fullness persisted for the durable compaction trigger.
        ct, cw, _ = chat_service.get_turn_usage(cid)
        assert ct == 1234 + 2000  # cache-inclusive
