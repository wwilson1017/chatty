"""Tests for agents.engine — config building and service getters."""

import uuid

import pytest

import agents.engine as engine_mod
from agents.engine import (
    build_agent_config,
    get_chat_service,
    get_context_manager,
    invalidate_cache,
)
from core.agents.config import AgentConfig
from core.agents.context_manager import ContextManager
from core.agents.chat_history.service import ChatHistoryService


def _make_agent_row(**overrides) -> dict:
    """Return a minimal agent DB row dict with sensible defaults."""
    row = {
        "id": str(uuid.uuid4()),
        "agent_name": "TestBot",
        "slug": "testbot",
        "personality": "You are helpful.",
        "provider_override": "",
        "model_override": "",
        "gmail_enabled": 0,
        "gmail_send_enabled": 0,
        "calendar_enabled": 0,
        "calendar_write_enabled": 0,
        "drive_enabled": 0,
        "drive_write_enabled": 0,
        "google_accounts": {},
        "onboarding_complete": 0,
    }
    row.update(overrides)
    return row


class TestBuildAgentConfig:
    """build_agent_config maps a DB row dict to an AgentConfig dataclass."""

    def test_maps_all_fields(self, monkeypatch, tmp_path):
        monkeypatch.setattr(engine_mod, "DATA_DIR", tmp_path)
        row = _make_agent_row(
            personality="Be cool.",
            provider_override="openai",
            model_override="gpt-4o",
        )

        cfg = build_agent_config(row)

        assert isinstance(cfg, AgentConfig)
        assert cfg.agent_id == row["id"]
        assert cfg.agent_name == "TestBot"
        assert cfg.slug == "testbot"
        assert cfg.personality == "Be cool."
        assert cfg.provider_override == "openai"
        assert cfg.model_override == "gpt-4o"
        assert cfg.google_accounts == {}
        assert isinstance(cfg.training_topics, list)
        assert len(cfg.training_topics) > 0

    def test_context_dir_is_absolute_path(self, monkeypatch, tmp_path):
        monkeypatch.setattr(engine_mod, "DATA_DIR", tmp_path)
        row = _make_agent_row(slug="my-agent")

        cfg = build_agent_config(row)

        assert cfg.context_dir.endswith("my-agent/context")
        from pathlib import Path
        assert Path(cfg.context_dir).is_absolute()

    def test_personality_falls_back_to_onboarding_default(self, monkeypatch, tmp_path):
        monkeypatch.setattr(engine_mod, "DATA_DIR", tmp_path)
        row = _make_agent_row(personality="")

        cfg = build_agent_config(row)

        assert "TestBot" in cfg.personality
        assert cfg.personality != ""

    def test_bool_conversion_from_int(self, monkeypatch, tmp_path):
        monkeypatch.setattr(engine_mod, "DATA_DIR", tmp_path)
        row = _make_agent_row(
            gmail_enabled=1,
            gmail_send_enabled=0,
            calendar_enabled=1,
            calendar_write_enabled=0,
            drive_enabled=1,
            drive_write_enabled=0,
            onboarding_complete=1,
        )

        cfg = build_agent_config(row)

        assert cfg.gmail_enabled is True
        assert cfg.gmail_send_enabled is False
        assert cfg.calendar_enabled is True
        assert cfg.calendar_write_enabled is False
        assert cfg.drive_enabled is True
        assert cfg.drive_write_enabled is False
        assert cfg.onboarding_complete is True


class TestServiceGetters:
    """get_context_manager and get_chat_service return the right types."""

    def test_get_context_manager(self, monkeypatch, tmp_path):
        monkeypatch.setattr(engine_mod, "DATA_DIR", tmp_path)

        cm = get_context_manager("some-slug")

        assert isinstance(cm, ContextManager)

    def test_get_chat_service(self, monkeypatch, tmp_path):
        monkeypatch.setattr(engine_mod, "DATA_DIR", tmp_path)
        agent_dir = tmp_path / "some-slug"
        agent_dir.mkdir(parents=True, exist_ok=True)

        try:
            svc = get_chat_service("some-slug")
            assert isinstance(svc, ChatHistoryService)
        finally:
            invalidate_cache("some-slug")
