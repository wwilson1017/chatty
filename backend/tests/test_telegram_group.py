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


class TestTurnContext:
    """Private chats run as the owner ("user"); group chats never do ("group"), but
    both stamp the chat they came from so delegated work reports back there."""

    def _drive(self, monkeypatch, tmp_path):
        import asyncio
        import types
        import integrations.registry as reg
        from integrations.telegram import service as tg_service

        agent = {"id": "a1", "slug": "ally", "telegram_enabled": 1}
        monkeypatch.setattr(tg_service.agent_db, "get_agent", lambda agent_id: agent)
        monkeypatch.setattr(tg_service, "build_agent_config", lambda a: types.SimpleNamespace(
            provider_override=None, model_override=None, model_tier="top", google_accounts={},
            context_dir=str(tmp_path / "context")))
        monkeypatch.setattr(tg_service, "get_context_manager", lambda slug: types.SimpleNamespace())
        monkeypatch.setattr(tg_service, "get_chat_service", lambda slug: None)
        monkeypatch.setattr(tg_service, "get_ai_provider", lambda **kw: object())
        monkeypatch.setattr(tg_service, "load_integration_tools", lambda: ([], {}))
        monkeypatch.setattr(reg, "list_google_accounts", lambda: {})
        monkeypatch.setattr(reg, "get_credentials", lambda name: {})
        monkeypatch.setattr(tg_service.state, "get_mapping_by_sender", lambda *a: {"id": 1})
        monkeypatch.setattr(tg_service.state, "get_or_create_conversation",
                            lambda sid, aid: {"id": "c1", "chatty_conversation_id": None})
        seen = {}

        async def run_sync(**kw):
            seen["registry"] = kw["registry"]
            return "ok"

        monkeypatch.setattr(tg_service.ai_service, "run_sync", run_sync)

        def turn(coro):
            asyncio.run(coro)
            reg_ = seen.pop("registry")
            return reg_._turn_origin, reg_._turn_route

        return tg_service, turn

    def test_group_turn_is_group_origin_routed_to_the_group(self, monkeypatch, tmp_path):
        tg_service, turn = self._drive(monkeypatch, tmp_path)
        assert turn(tg_service.process_group_message(-100123, "a1", "Ann", False, "Ops", "hi")) == (
            "group", {"channel": "telegram", "chat_id": "-100123", "group": True})
        assert turn(tg_service.process_message("42", "Will", "hi", "a1")) == (
            "user", {"channel": "telegram", "chat_id": "42"})

    def test_group_owner_is_only_the_owners_linked_account(self, monkeypatch, tmp_path):
        """The computer works in a group only for the account the owner paired in the dashboard."""
        import asyncio
        tg_service, _ = self._drive(monkeypatch, tmp_path)
        monkeypatch.setattr(tg_service.state, "get_mapping_by_sender",
                            lambda platform, sender, agent_id: {"id": 1} if (sender, agent_id) == ("555", "a1") else None)
        owners: list = []

        async def run_sync(**kw):
            owners.append(kw["registry"]._turn_group_owner)
            return "ok"

        monkeypatch.setattr(tg_service.ai_service, "run_sync", run_sync)
        for sender, is_bot in (("555", False), ("777", False), ("555", True), ("", False)):
            asyncio.run(tg_service.process_group_message(-100123, "a1", "Ann", is_bot, "Ops", "hi", sender_id=sender))
        assert owners == [True, False, False, False]
