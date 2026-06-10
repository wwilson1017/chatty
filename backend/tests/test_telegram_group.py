"""Tests for Telegram group bot-to-bot reply limiting (should_respond).

Exercises the global admin-settings bot-reply-limit path that replaced the
per-agent telegram_respond_to_bots / telegram_max_bot_turns fields.
"""

import pytest

from integrations.telegram import group


@pytest.fixture(autouse=True)
def reset_group_state():
    group._group_states.clear()
    yield
    group._group_states.clear()


def _agent():
    return {"id": "agent-1", "telegram_group_enabled": 1, "telegram_bot_username": "mybot"}


def _set_limit(monkeypatch, *, enabled, limit):
    monkeypatch.setattr(
        "core.admin_settings.load_admin_settings",
        lambda: {"bot_reply_limit_enabled": enabled, "bot_reply_limit": limit},
    )


class TestBotReplyLimit:
    def test_bot_blocked_at_limit(self, monkeypatch):
        _set_limit(monkeypatch, enabled=True, limit=2)
        chat_id = 1001
        group.record_bot_message(chat_id)
        group.record_bot_message(chat_id)  # consecutive_bot_turns == 2 == limit
        ok, reason = group.should_respond(
            chat_id, sender_is_bot=True, sender_username="otherbot", agent=_agent(),
        )
        assert ok is False
        assert reason == "max_bot_turns"

    def test_bot_allowed_below_limit(self, monkeypatch):
        _set_limit(monkeypatch, enabled=True, limit=5)
        chat_id = 1002
        group.record_bot_message(chat_id)  # consecutive_bot_turns == 1 < 5
        ok, reason = group.should_respond(
            chat_id, sender_is_bot=True, sender_username="otherbot", agent=_agent(),
        )
        assert ok is True
        assert reason == "ok"

    def test_limit_disabled_allows_unlimited(self, monkeypatch):
        _set_limit(monkeypatch, enabled=False, limit=2)
        chat_id = 1003
        for _ in range(10):
            group.record_bot_message(chat_id)
        ok, reason = group.should_respond(
            chat_id, sender_is_bot=True, sender_username="otherbot", agent=_agent(),
        )
        assert ok is True
        assert reason == "ok"

    def test_human_message_resets_bot_counter(self, monkeypatch):
        _set_limit(monkeypatch, enabled=True, limit=2)
        chat_id = 1004
        group.record_bot_message(chat_id)
        group.record_bot_message(chat_id)
        group.record_human_message(chat_id)  # resets consecutive_bot_turns to 0
        ok, reason = group.should_respond(
            chat_id, sender_is_bot=True, sender_username="otherbot", agent=_agent(),
        )
        assert ok is True
        assert reason == "ok"
