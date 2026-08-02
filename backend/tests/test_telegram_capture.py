"""Tests for the Telegram deterministic capture intercept."""

import pytest

import core.todo.db as tododb
from core.todo import service as todo_service
from integrations.telegram import router as tg_router
from integrations.telegram.router import _parse_capture


@pytest.fixture()
def todo_db(tmp_path, monkeypatch):
    monkeypatch.setattr(tododb, "DATA_DIR", tmp_path / "todo")
    monkeypatch.setattr(tododb, "DB_PATH", tmp_path / "todo" / "todo.db")
    (tmp_path / "todo").mkdir()
    tododb.close_db()
    tododb._setup_connection()
    yield
    tododb.close_db()


class TestParseCapture:
    @pytest.mark.parametrize("text,expected", [
        ("/capture milk", "milk"),
        ("/capture@MyBot milk", "milk"),
        ("capture milk", "milk"),
        ("Capture milk", "milk"),
        ("CAPTURE: buy milk", "buy milk"),
        ("  capture   milk  ", "milk"),
        ("/capture", ""),
        ("capture", ""),
        ("captured milk yesterday", None),
        ("recapture x", None),
        ("please capture milk", None),
        ("what does capture mean?", None),  # anchored: only a LEADING "capture" triggers
        ("", None),
    ])
    def test_cases(self, text, expected):
        assert _parse_capture(text) == expected


@pytest.fixture()
def telegram_env(monkeypatch, todo_db):
    """Monkeypatched agent + mapping + outbound messages for _safe_process_telegram."""
    sent: list[tuple[int, str]] = []

    agent = {
        "id": 1,
        "slug": "helper",
        "agent_name": "Helper",
        "telegram_bot_token": "tok",
        "telegram_enabled": 1,
        "telegram_bot_username": "HelperBot",
    }
    monkeypatch.setattr(tg_router.agent_db, "get_agent_by_slug", lambda slug: agent)
    monkeypatch.setattr(tg_router.state, "get_mapping_by_sender", lambda *a: {"id": 1})
    monkeypatch.setattr(tg_router, "send_message", lambda chat_id, text, token: sent.append((chat_id, text)))

    # The AI path must never run for captures — make it loud if it does.
    async def _boom(*a, **k):
        raise AssertionError("AI path invoked for a capture message")

    monkeypatch.setattr(tg_router.service, "process_message", _boom)
    monkeypatch.setattr(tg_router.service, "save_message_only", _boom)
    return sent


class TestPrivateIntercept:
    def test_capture_inserts_and_replies_captured(self, telegram_env):
        tg_router._safe_process_telegram("helper", "42", "Will", "/capture buy milk", 100)
        assert telegram_env == [(100, "captured")]
        todos = todo_service.list_todos(status="inbox")
        assert [t["title"] for t in todos] == ["buy milk"]
        assert todos[0]["source"] == "telegram"

    def test_bare_capture_asks_what(self, telegram_env):
        tg_router._safe_process_telegram("helper", "42", "Will", "capture", 100)
        assert telegram_env == [(100, "capture what?")]
        assert todo_service.list_todos() == []

    def test_natural_prefix_works(self, telegram_env):
        tg_router._safe_process_telegram("helper", "42", "Will", "capture call the dentist", 100)
        assert telegram_env == [(100, "captured")]
        assert todo_service.list_todos()[0]["title"] == "call the dentist"

    def test_insert_failure_replies_terse_error(self, telegram_env, monkeypatch):
        monkeypatch.setattr(todo_service, "capture", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db gone")))
        tg_router._safe_process_telegram("helper", "42", "Will", "/capture x", 100)
        assert telegram_env == [(100, "capture failed — try again")]

    def test_unregistered_sender_cannot_capture(self, telegram_env, monkeypatch):
        monkeypatch.setattr(tg_router.state, "get_mapping_by_sender", lambda *a: None)
        monkeypatch.setattr(tg_router.lifecycle, "try_auto_register", lambda *a: False)
        tg_router._safe_process_telegram("helper", "42", "Will", "/capture sneaky", 100)
        assert telegram_env == [(100, "Registration window is closed. Please ask the admin to reset it in Chatty.")]
        assert todo_service.list_todos() == []


class TestGroupIntercept:
    @pytest.fixture()
    def group_env(self, telegram_env, monkeypatch):
        from integrations.telegram import group

        monkeypatch.setattr(group, "is_addressed_to_bot", lambda *a: True)
        monkeypatch.setattr(group, "should_respond", lambda *a: (True, ""))
        monkeypatch.setattr(group, "record_human_message", lambda *a: None)
        monkeypatch.setattr(group, "record_bot_message", lambda *a: None)
        monkeypatch.setattr(group, "record_response", lambda *a: None)
        return telegram_env

    def test_mention_prefixed_capture(self, group_env):
        tg_router._safe_process_telegram(
            "helper", "42", "Will", "@HelperBot capture order labels", 200,
            chat_type="supergroup", from_username="will",
        )
        assert group_env == [(200, "captured")]
        assert todo_service.list_todos()[0]["title"] == "order labels"

    def test_bot_sender_never_captures(self, group_env, monkeypatch):
        async def fake_group_ai(**kwargs):
            return "AI-REPLY"

        monkeypatch.setattr(tg_router.service, "process_group_message", fake_group_ai)
        tg_router._safe_process_telegram(
            "helper", "43", "OtherBot", "capture spam from a bot", 200,
            chat_type="supergroup", is_bot=True, from_username="otherbot",
        )
        assert group_env == [(200, "AI-REPLY")]
        assert todo_service.list_todos() == []
