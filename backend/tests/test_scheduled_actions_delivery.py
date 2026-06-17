"""Tests for the cron auto-delivery guarantee in scheduled_actions/processor.

A cron action's whole purpose is to report back, so its output must reach the
user even if the model never calls notify_user (the morning-brief silent-failure
bug). These tests drive _process_cron with its boundaries mocked, plus one
real-DB test that the observability marker survives history's 10 KB truncation.
"""

import json
import types

import pytest

from core.agents.scheduled_actions import processor


def _fake_result(text="", tool_log=None, error=False):
    return types.SimpleNamespace(
        text=text,
        tool_log=tool_log or [],
        error=error,
        input_tokens=10,
        output_tokens=20,
        model_used="claude-opus-4-6",
        provider="anthropic",
    )


def _action():
    return {
        "id": "act-123456",
        "agent": "tom",
        "lease_id": "lease-1",
        "prompt": "Generate the morning brief.",
        "name": "Morning Brief",
        "max_tool_iterations": 10,
        "active_hours_tz": "America/Chicago",
        "model_override": None,
    }


@pytest.fixture
def cron_env(monkeypatch):
    """Patch every boundary _process_cron touches; capture deliver + history calls."""
    captures = {"deliver": [], "record_complete": [], "deliver_should_raise": False, "result": None}

    monkeypatch.setattr(processor, "_resolve_agent", lambda slug: {
        "slug": slug, "agent_name": "Tom", "provider_override": None, "model_override": None,
    })
    monkeypatch.setattr(processor, "_build_tools", lambda *a, **k: ([], None, None))
    monkeypatch.setattr(processor, "_make_lease_renewer", lambda *a, **k: (lambda *_a, **_k: None))
    monkeypatch.setattr(processor, "_mark_and_alert", lambda *a, **k: True)

    monkeypatch.setattr(processor.history, "record_start", lambda *a, **k: "exec-1")
    monkeypatch.setattr(
        processor.history, "record_complete",
        lambda execution_id, **kwargs: captures["record_complete"].append(kwargs),
    )

    import agents.engine as engine_mod
    import agents.tool_loader as tool_loader_mod
    import core.agents.ai_service as ai_service_mod
    monkeypatch.setattr(engine_mod, "get_context_manager",
                        lambda slug: types.SimpleNamespace(load_all_context=lambda: ""))
    monkeypatch.setattr(engine_mod, "build_agent_config",
                        lambda agent: types.SimpleNamespace(model_tier="top", google_accounts=[]))
    monkeypatch.setattr(tool_loader_mod, "format_current_time", lambda tz: ("2026-06-16", "05:15"))
    monkeypatch.setattr(ai_service_mod, "_google_accounts_context", lambda aim, accts: "")

    import core.agents.notifications.delivery as delivery_mod

    def _deliver(agent_slug, title, message):
        captures["deliver"].append({"agent": agent_slug, "title": title, "message": message})
        if captures["deliver_should_raise"]:
            raise RuntimeError("telegram down")
        return {"ok": True, "notification_id": "n1", "channels_sent": ["telegram"]}

    monkeypatch.setattr(delivery_mod, "deliver_notification", _deliver)
    monkeypatch.setattr(processor, "run_background_turn", lambda **k: captures["result"])

    return captures


class TestCronAutoDelivery:
    def test_delivers_when_model_did_not_notify(self, cron_env):
        cron_env["result"] = _fake_result(text="Here is your brief: 3 meetings today.")
        processor._process_cron(_action())

        assert len(cron_env["deliver"]) == 1
        assert cron_env["deliver"][0]["title"] == "Morning Brief"
        assert "brief" in cron_env["deliver"][0]["message"]
        rc = cron_env["record_complete"][-1]
        assert rc["notification_sent"] is True
        # Marker is prepended so it survives history's tool_calls truncation.
        assert rc["tool_calls"][0]["tool"] == "auto_deliver"
        assert rc["tool_calls"][0]["ok"] is True

    def test_silent_marker_suppresses_delivery(self, cron_env):
        cron_env["result"] = _fake_result(text="[SILENT]")
        processor._process_cron(_action())

        assert cron_env["deliver"] == []
        rc = cron_env["record_complete"][-1]
        assert rc["notification_sent"] is False
        assert all(tc.get("tool") != "auto_deliver" for tc in rc["tool_calls"])

    def test_empty_text_no_delivery(self, cron_env):
        cron_env["result"] = _fake_result(text="   ")
        processor._process_cron(_action())

        assert cron_env["deliver"] == []
        assert cron_env["record_complete"][-1]["notification_sent"] is False

    def test_no_double_send_when_model_notified_successfully(self, cron_env):
        tool_log = [{"tool": "notify_user",
                     "result": json.dumps({"ok": True, "notification_id": "x", "channels_sent": ["web_push"]})}]
        cron_env["result"] = _fake_result(text="Brief body", tool_log=tool_log)
        processor._process_cron(_action())

        assert cron_env["deliver"] == []  # model already delivered → no double-send
        assert cron_env["record_complete"][-1]["notification_sent"] is True

    def test_no_double_send_when_model_used_post_message(self, cron_env):
        # post_message is the other tool _delivered_via_tool() honors; it returns
        # {"ok": True, "notification_created": True, ...} on success (tool_registry
        # _execute_post_message). A successful post_message must suppress the
        # auto-fallback exactly like notify_user.
        tool_log = [{"tool": "post_message",
                     "result": json.dumps({"ok": True, "notification_created": True, "external_sent": True})}]
        cron_env["result"] = _fake_result(text="Brief body", tool_log=tool_log)
        processor._process_cron(_action())

        assert cron_env["deliver"] == []  # model already delivered → no double-send
        assert cron_env["record_complete"][-1]["notification_sent"] is True

    def test_delivers_when_notify_user_errored(self, cron_env):
        # The bug guard: a notify_user that ERRORED (e.g. missing args) must NOT
        # count as delivered — the auto-fallback still fires.
        tool_log = [{"tool": "notify_user",
                     "result": json.dumps({"error": "Both title and message are required"})}]
        cron_env["result"] = _fake_result(text="Brief body", tool_log=tool_log)
        processor._process_cron(_action())

        assert len(cron_env["deliver"]) == 1
        assert cron_env["record_complete"][-1]["notification_sent"] is True

    def test_delivers_when_notify_user_budget_rejected(self, cron_env):
        # background_runner logs write-budget rejects under the same tool name.
        tool_log = [{"tool": "notify_user",
                     "result": json.dumps({"error": "Write budget exceeded (5 writes per turn). This write was rejected."})}]
        cron_env["result"] = _fake_result(text="Brief body", tool_log=tool_log)
        processor._process_cron(_action())

        assert len(cron_env["deliver"]) == 1
        assert cron_env["record_complete"][-1]["notification_sent"] is True

    def test_delivery_exception_recorded_not_crashing(self, cron_env):
        cron_env["deliver_should_raise"] = True
        cron_env["result"] = _fake_result(text="Brief body")
        processor._process_cron(_action())  # must not raise

        rc = cron_env["record_complete"][-1]
        assert rc["notification_sent"] is False
        marker = rc["tool_calls"][0]
        assert marker["tool"] == "auto_deliver"
        assert marker["ok"] is False
        assert "error" in marker

    def test_error_status_skips_delivery(self, cron_env):
        cron_env["result"] = _fake_result(text="boom", error=True)
        processor._process_cron(_action())

        assert cron_env["deliver"] == []


@pytest.fixture
def hb_env(monkeypatch, tmp_path):
    """Patch _process_heartbeat boundaries; bypass triage (off + triage_enabled
    False) and the lease re-check (lease_id None) to reach the full-run delivery."""
    captures = {"deliver": [], "record_complete": [], "deliver_should_raise": False, "result": None}

    (tmp_path / "HEARTBEAT.md").write_text("- Check the calendar each morning.\n", encoding="utf-8")

    monkeypatch.setattr(processor, "_resolve_agent", lambda slug: {
        "slug": slug, "agent_name": "Tom", "provider_override": None, "model_override": None,
    })
    monkeypatch.setattr(processor, "_build_tools", lambda *a, **k: ([], None, None))
    monkeypatch.setattr(processor, "_make_lease_renewer", lambda *a, **k: (lambda *_a, **_k: None))
    monkeypatch.setattr(processor, "_mark_and_alert", lambda *a, **k: True)
    monkeypatch.setattr(processor, "_build_error_context", lambda *a, **k: "")

    monkeypatch.setattr(processor.history, "record_start", lambda *a, **k: "exec-h")
    monkeypatch.setattr(
        processor.history, "record_complete",
        lambda execution_id, **kwargs: captures["record_complete"].append(kwargs),
    )

    import agents.engine as engine_mod
    import agents.tool_loader as tool_loader_mod
    import core.admin_settings as admin_mod
    import core.agents.ai_service as ai_service_mod
    import core.agents.memory.commitments as commitments_mod
    monkeypatch.setattr(engine_mod, "get_context_manager",
                        lambda slug: types.SimpleNamespace(data_dir=tmp_path, load_all_context=lambda: ""))
    monkeypatch.setattr(engine_mod, "build_agent_config",
                        lambda agent: types.SimpleNamespace(model_tier="top", google_accounts=[]))
    monkeypatch.setattr(tool_loader_mod, "format_current_time", lambda tz: ("2026-06-16", "05:15"))
    monkeypatch.setattr(ai_service_mod, "_google_accounts_context", lambda aim, accts: "")
    monkeypatch.setattr(admin_mod, "load_admin_settings", lambda: {"triage_mode": "off"})
    monkeypatch.setattr(commitments_mod, "peek_due_followups", lambda slug: [])

    import core.agents.notifications.delivery as delivery_mod

    def _deliver(agent_slug, title, message):
        captures["deliver"].append({"agent": agent_slug, "title": title, "message": message})
        if captures["deliver_should_raise"]:
            raise RuntimeError("telegram down")
        return {"ok": True, "notification_id": "n1", "channels_sent": ["telegram"]}

    monkeypatch.setattr(delivery_mod, "deliver_notification", _deliver)
    monkeypatch.setattr(processor, "run_background_turn", lambda **k: captures["result"])

    return captures


def _hb_action():
    return {
        "id": "hb-123456",
        "agent": "tom",
        "lease_id": None,
        "name": "Daily Heartbeat",
        "max_tool_iterations": 10,
        "active_hours_tz": "America/Chicago",
        "model_override": None,
        "triage_enabled": False,
    }


class TestHeartbeatAutoDelivery:
    """Heartbeat now matches OpenClaw: deliver the ACTION_TAKEN report unless the
    model went silent with HEARTBEAT_OK (or already delivered)."""

    def test_delivers_action_taken_report_with_marker_stripped(self, hb_env):
        hb_env["result"] = _fake_result(text="ACTION_TAKEN: Invoice #123 is 30 days overdue.")
        processor._process_heartbeat(_hb_action())

        assert len(hb_env["deliver"]) == 1
        assert hb_env["deliver"][0]["title"] == "Daily Heartbeat"
        assert hb_env["deliver"][0]["message"] == "Invoice #123 is 30 days overdue."
        rc = hb_env["record_complete"][-1]
        assert rc["notification_sent"] is True
        assert rc["tool_calls"][0]["tool"] == "auto_deliver"

    def test_heartbeat_ok_suppresses_delivery(self, hb_env):
        hb_env["result"] = _fake_result(text="HEARTBEAT_OK")
        processor._process_heartbeat(_hb_action())

        assert hb_env["deliver"] == []
        assert hb_env["record_complete"][-1]["notification_sent"] is False

    def test_no_double_send_when_model_notified(self, hb_env):
        tool_log = [{"tool": "notify_user", "result": json.dumps({"ok": True, "notification_id": "x"})}]
        hb_env["result"] = _fake_result(text="ACTION_TAKEN: Something", tool_log=tool_log)
        processor._process_heartbeat(_hb_action())

        assert hb_env["deliver"] == []
        assert hb_env["record_complete"][-1]["notification_sent"] is True

    def test_delivery_exception_recorded_not_crashing(self, hb_env):
        hb_env["deliver_should_raise"] = True
        hb_env["result"] = _fake_result(text="ACTION_TAKEN: Something urgent")
        processor._process_heartbeat(_hb_action())  # must not raise

        rc = hb_env["record_complete"][-1]
        assert rc["notification_sent"] is False
        assert rc["tool_calls"][0] == {"tool": "auto_deliver", "ok": False, "error": "telegram down"}


class TestStripActionMarker:
    def test_strips_prefix(self):
        assert processor._strip_action_marker("ACTION_TAKEN: foo bar") == "foo bar"

    def test_no_marker_returns_full(self):
        assert processor._strip_action_marker("just a report") == "just a report"

    def test_case_insensitive(self):
        assert processor._strip_action_marker("action_taken: hi") == "hi"

    def test_empty_after_marker_falls_back_to_full(self):
        assert processor._strip_action_marker("ACTION_TAKEN:") == "ACTION_TAKEN:"


class TestMarkerSurvivesTruncation:
    @pytest.fixture
    def reminders_env(self, monkeypatch, tmp_path):
        import core.agents.reminders.db as rdb

        monkeypatch.setattr(rdb, "DATA_DIR", tmp_path / "reminders")
        monkeypatch.setattr(rdb, "DB_PATH", tmp_path / "reminders" / "reminders.db")
        (tmp_path / "reminders").mkdir(parents=True, exist_ok=True)
        rdb.close_db()
        rdb._setup_connection()
        yield rdb
        rdb.close_db()

    def test_prepended_marker_survives_10kb_truncation(self, reminders_env):
        from core.agents.scheduled_actions import history

        eid = history.record_start("act-x", "tom", "cron")
        big = [{"tool": f"t{i}", "args": "x" * 200, "result": "y" * 200} for i in range(200)]
        tool_calls = [{"tool": "auto_deliver", "ok": True, "channels": ["telegram"]}] + big
        history.record_complete(eid, status="ok", tool_calls=tool_calls, notification_sent=True)

        stored = reminders_env.get_db().execute(
            "SELECT tool_calls FROM execution_history WHERE id = ?", (eid,)
        ).fetchone()[0]
        assert len(stored) <= 10240          # truncation happened
        assert "auto_deliver" in stored      # ...but the prepended marker survived
