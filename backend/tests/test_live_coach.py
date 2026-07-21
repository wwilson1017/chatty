"""Live-meeting coach: verdict parsing, tier plan, gated turns, escalation."""

import asyncio
import time
from types import SimpleNamespace

import pytest

import core.agents.live.coach as coach
import core.agents.live.session as live


@pytest.fixture(autouse=True)
def live_env(monkeypatch):
    monkeypatch.setattr(live, "_active", None)
    monkeypatch.setattr(live, "_busy", {})
    yield


# ---------------------------------------------------------------------------
# Verdict parsing
# ---------------------------------------------------------------------------

def test_parse_verdict_pass():
    assert coach.parse_verdict("VERDICT: PASS") == ("PASS", "", "")
    assert coach.parse_verdict("nothing to say\nVERDICT: PASS") == ("PASS", "nothing to say", "")


def test_parse_verdict_nudge_with_narration_above():
    text = "Let me check the CRM first.\nAsk about their Q3 volume.\nVERDICT: NUDGE"
    verdict, body, _ = coach.parse_verdict(text)
    assert verdict == "NUDGE"
    assert body == "Let me check the CRM first.\nAsk about their Q3 volume."


def test_parse_verdict_escalate_with_reason():
    verdict, body, reason = coach.parse_verdict("context\nVERDICT: ESCALATE — pricing pivot")
    assert verdict == "ESCALATE"
    assert body == "context"
    assert reason == "pricing pivot"


def test_parse_verdict_last_line_wins():
    text = "VERDICT: PASS\nmore thinking\nVERDICT: NUDGE"
    verdict, body, _ = coach.parse_verdict(text)
    assert verdict == "NUDGE"


def test_parse_verdict_markdown_and_case():
    assert coach.parse_verdict("hi\n**VERDICT: nudge**")[0] == "NUDGE"


def test_parse_verdict_missing_defaults_to_pass():
    assert coach.parse_verdict("just some rambling with no verdict")[0] == "PASS"
    assert coach.parse_verdict("")[0] == "PASS"


# ---------------------------------------------------------------------------
# Tier plan (honors admin lock / agent pins)
# ---------------------------------------------------------------------------

def _config(model_override="", provider_override="", model_tier="auto"):
    return SimpleNamespace(model_override=model_override,
                           provider_override=provider_override,
                           model_tier=model_tier,
                           agent_name="Test Agent", personality="")


def test_tier_plan_auto_gets_mid_with_escalation():
    plan = coach._coach_model_plan(_config())
    assert plan["base"] == {"model_tier": "mid", "provider_override": None}
    assert plan["escalate"] == {"model_tier": "top", "provider_override": None}


def test_tier_plan_admin_lock_pins_and_disables_escalation():
    # build_agent_config folds default_model_tier="top" into config.model_tier
    plan = coach._coach_model_plan(_config(model_tier="top"))
    assert plan["base"] == {"model_tier": "top", "provider_override": None}
    assert plan["escalate"] is None


def test_tier_plan_model_override_wins():
    plan = coach._coach_model_plan(_config(model_override="claude-opus-4-8",
                                           provider_override="anthropic"))
    assert plan["base"] == {"model_override": "claude-opus-4-8",
                           "provider_override": "anthropic"}
    assert plan["escalate"] is None


# ---------------------------------------------------------------------------
# Coach turns (run_background_turn_async stubbed)
# ---------------------------------------------------------------------------

def _session(monkeypatch, tmp_path):
    monkeypatch.setattr(live, "recordings_dir", lambda slug: tmp_path / slug / "recordings")
    return live.start_session(
        {"id": "a1", "slug": "test-agent", "agent_name": "Test Agent"}, "conv-1", "")


def _ctx(plan=None):
    return {
        "config": _config(),
        "tool_defs": [],
        "registry": SimpleNamespace(agent_slug="test-agent", _current_conversation_id=None),
        "context_snippet": "(no context)",
        "model_plan": plan or coach._coach_model_plan(_config()),
    }


class _FakeResult(SimpleNamespace):
    pass


def _result(text, model="mid-model", error=False):
    return _FakeResult(text=text, model_used=model, provider="anthropic",
                       input_tokens=1, output_tokens=1, tool_log=[], error=error)


@pytest.fixture
def turn_env(monkeypatch, tmp_path):
    """Patch the background runner + chat service; record calls."""
    import core.agents.background_runner as runner_mod
    import agents.engine as engine_mod

    calls = SimpleNamespace(turns=[], saved=[])
    results = []

    async def fake_turn(**kwargs):
        calls.turns.append(kwargs)
        return results.pop(0)

    class FakeChat:
        def save_message(self, conv_id, msg_id, role, content, **kw):
            calls.saved.append({"conv_id": conv_id, "role": role,
                                "content": content, **kw})

        def get_clean_history(self, conv_id, limit=None):
            return [{"role": "assistant", "content": "earlier nudge"}]

    monkeypatch.setattr(runner_mod, "run_background_turn_async", fake_turn)
    monkeypatch.setattr(engine_mod, "get_chat_service", lambda slug: FakeChat())
    session = _session(monkeypatch, tmp_path)
    return session, calls, results


def test_nudge_saved_and_emitted(turn_env):
    session, calls, results = turn_env
    results.append(_result("Ask about their timeline.\nVERDICT: NUDGE"))
    listener = asyncio.Queue()
    session.listeners.append(listener)

    asyncio.run(coach.run_coach_turn(session, _ctx(), "delta text"))

    assert len(calls.saved) == 1
    assert calls.saved[0]["role"] == "assistant"
    assert calls.saved[0]["content"] == "Ask about their timeline."
    assert calls.saved[0]["model"] == "mid-model"
    ev = listener.get_nowait()
    assert ev["type"] == "coach"
    assert ev["message"]["content"] == "Ask about their timeline."
    assert session.coach_events  # retained for SSE replay
    # Turn ran on the mid tier
    assert calls.turns[0]["model_tier"] == "mid"
    assert calls.turns[0]["source"] == "live_coach"


def test_pass_produces_nothing(turn_env):
    session, calls, results = turn_env
    results.append(_result("VERDICT: PASS"))
    asyncio.run(coach.run_coach_turn(session, _ctx(), "delta"))
    assert calls.saved == []
    assert session.coach_events == []


def test_escalate_reruns_on_top_tier(turn_env):
    session, calls, results = turn_env
    results.append(_result("VERDICT: ESCALATE — pricing moment"))
    results.append(_result("Hold at $450 — cite the June quote.\nVERDICT: NUDGE",
                           model="top-model"))

    asyncio.run(coach.run_coach_turn(session, _ctx(), "delta"))

    assert len(calls.turns) == 2
    assert calls.turns[0]["model_tier"] == "mid"
    assert calls.turns[1]["model_tier"] == "top"
    assert "pricing moment" in calls.turns[1]["user_message"]
    assert len(calls.saved) == 1
    assert calls.saved[0]["model"] == "top-model"
    assert session.escalations == 1


def test_escalate_rate_limited(turn_env):
    session, calls, results = turn_env
    session.coach_last_escalate_at = time.time()  # just escalated
    results.append(_result("VERDICT: ESCALATE — again"))
    asyncio.run(coach.run_coach_turn(session, _ctx(), "delta"))
    assert len(calls.turns) == 1  # no top re-run
    assert calls.saved == []


def test_escalate_with_pinned_tier_degrades_to_nudge(turn_env):
    session, calls, results = turn_env
    plan = coach._coach_model_plan(_config(model_tier="top"))
    results.append(_result("Important point here.\nVERDICT: ESCALATE — moment"))
    asyncio.run(coach.run_coach_turn(session, _ctx(plan), "delta"))
    # Escalation unavailable (pinned) → body becomes the nudge, single turn
    assert len(calls.turns) == 1
    assert calls.turns[0]["model_tier"] == "top"
    assert len(calls.saved) == 1
    assert calls.saved[0]["content"] == "Important point here."


def test_error_result_produces_nothing(turn_env):
    session, calls, results = turn_env
    results.append(_result("(provider error: boom)", error=True))
    asyncio.run(coach.run_coach_turn(session, _ctx(), "delta"))
    assert calls.saved == []


def test_wrapup_turn_always_delivers(turn_env):
    session, calls, results = turn_env
    session.segments[0] = live.Segment(index=0, filename="f", status="done",
                                       text="we agreed on the Q3 order")
    results.append(_result("Wrap-up: Q3 order agreed.\nVERDICT: NUDGE", model="top-model"))
    asyncio.run(coach.run_coach_turn(session, _ctx(), "", wrapup=True,
                                     finalize_reason="stopped"))
    assert len(calls.saved) == 1
    assert "Wrap-up" in calls.saved[0]["content"]
    assert calls.turns[0]["model_tier"] == "top"  # unpinned wrap-up runs top
    assert "meeting has ended" in calls.turns[0]["user_message"]


def test_coach_tool_filter():
    """Coach tool policy: outbound comms always denied; budget-exempt
    context_memory writes default-denied except the append-only allowlist;
    budgeted integration writes kept; other core writes denied."""
    defs = [
        {"name": "send_email", "writes": True},
        {"name": "post_message", "writes": True},
        {"name": "qbo_send_invoice", "writes": True, "integration": "quickbooks"},
        {"name": "odoo_send_ticket_reply", "writes": True, "integration": "odoo"},
        # budget-exempt destructive class — must be stripped
        {"name": "create_real_tool", "writes": True, "context_memory": True},
        {"name": "delete_context_file", "writes": True, "context_memory": True},
        {"name": "write_context_file", "writes": True, "context_memory": True},
        {"name": "update_memory", "writes": True, "context_memory": True},
        {"name": "save_playbook", "writes": True, "context_memory": True},
        # allowlisted append-only capture tools — must survive
        {"name": "create_reminder", "writes": True},
        {"name": "add_fact", "writes": True, "context_memory": True},
        {"name": "append_daily_note", "writes": True, "context_memory": True},
        {"name": "append_to_context_file", "writes": True, "context_memory": True},
        {"name": "notify_user", "writes": True},
        # budgeted integration write (locked product decision) — survives
        {"name": "qbo_create_invoice", "writes": True, "integration": "quickbooks"},
        # other core writes — denied
        {"name": "delete_scheduled_action", "writes": True},
        {"name": "setup_odoo", "writes": True},
        # reads always survive, even with 'send' in the name
        {"name": "search_memory", "writes": False},
        {"name": "qbo_get_send_history", "writes": False},
    ]
    names = {t["name"] for t in defs if coach._coach_tool_allowed(t)}
    assert names == {
        "create_reminder", "add_fact", "append_daily_note",
        "append_to_context_file", "notify_user", "qbo_create_invoice",
        "search_memory", "qbo_get_send_history",
    }


def test_coach_loop_gates_and_reviews_indexes(monkeypatch, tmp_path):
    """Loop waits for enough new chars, tracks reviewed indexes, defers on busy."""
    session = _session(monkeypatch, tmp_path)
    monkeypatch.setattr(live, "COACH_MIN_NEW_CHARS", 10)
    monkeypatch.setattr(coach, "COACH_MIN_NEW_CHARS", 10)
    monkeypatch.setattr(coach, "COACH_MIN_GAP_S", 0)

    ran = []

    async def fake_run(sess, ctx, delta_text, **kw):
        ran.append(delta_text)
        return True

    monkeypatch.setattr(coach, "run_coach_turn", fake_run)

    async def run():
        loop_task = asyncio.get_running_loop().create_task(
            coach.coach_loop(session, _ctx()))
        # Too little text → no turn
        session.segments[0] = live.Segment(index=0, filename="f", status="done", text="short")
        session.wake.set()
        await asyncio.sleep(0.1)
        assert ran == []
        # Enough text → one turn with both segments, indexes marked reviewed
        session.segments[1] = live.Segment(index=1, filename="f", status="done",
                                           text="plenty of new words arriving now")
        session.wake.set()
        await asyncio.sleep(0.1)
        assert len(ran) == 1
        assert "short" in ran[0] and "plenty" in ran[0]
        assert session.reviewed_indexes == {0, 1}
        # Same content again → nothing new → no second turn
        session.wake.set()
        await asyncio.sleep(0.1)
        assert len(ran) == 1
        # Busy conversation → loop defers the next turn until cleared
        live.mark_conversation_busy(session.conversation_id)
        session.segments[2] = live.Segment(index=2, filename="f", status="done",
                                           text="another chunk of meaningful content here")
        session.wake.set()
        await asyncio.sleep(0.3)
        assert len(ran) == 1  # deferred while busy
        live.clear_conversation_busy(session.conversation_id)
        for _ in range(30):  # loop polls busy at 1s cadence
            if len(ran) == 2:
                break
            await asyncio.sleep(0.1)
        assert len(ran) == 2
        session.status = "finalizing"
        session.wake.set()
        await asyncio.sleep(0.05)
        loop_task.cancel()

    asyncio.run(run())


def test_parse_verdict_body_excludes_prior_iterations():
    """Multi-iteration turn text: body starts after the previous verdict."""
    text = "interim narration\nVERDICT: PASS\nThe real nudge.\nVERDICT: NUDGE"
    verdict, body, _ = coach.parse_verdict(text)
    assert verdict == "NUDGE"
    assert body == "The real nudge."
