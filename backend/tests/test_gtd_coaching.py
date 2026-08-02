"""Tests for GTD coaching: prompt block, settings clamps, agent update tool."""

import pytest

import core.admin_settings as admin
from core.todo.coaching import DEFAULT_GTD_COACHING, MAX_COACHING_CHARS, gtd_coaching_block

_TODO_TOOL = {"name": "todo_list", "kind": "todo", "writes": False}
_OTHER_TOOL = {"name": "web_search", "kind": "web", "writes": False}


@pytest.fixture()
def settings_file(tmp_path, monkeypatch):
    monkeypatch.setattr(admin, "ADMIN_SETTINGS_FILE", tmp_path / "admin-settings.json")
    monkeypatch.setattr(admin, "_cached_settings", None)
    monkeypatch.setattr(admin, "_cached_mtime", 0.0)
    return tmp_path / "admin-settings.json"


class TestCoachingBlock:
    def test_default_text_injected_when_todo_tools_present(self, settings_file):
        block = gtd_coaching_block([_TODO_TOOL, _OTHER_TOOL])
        assert block.startswith("\n\n# GTD Todo System\n\n")
        assert "Getting Things Done" in block

    def test_empty_without_todo_tools(self, settings_file):
        assert gtd_coaching_block([_OTHER_TOOL]) == ""
        assert gtd_coaching_block([]) == ""
        assert gtd_coaching_block(None) == ""

    def test_blanked_text_disables(self, settings_file):
        admin.set_admin_setting("gtd_coaching_text", "")
        assert gtd_coaching_block([_TODO_TOOL]) == ""

    def test_custom_text_used(self, settings_file):
        admin.set_admin_setting("gtd_coaching_text", "Custom coaching here.")
        assert "Custom coaching here." in gtd_coaching_block([_TODO_TOOL])


class TestClamps:
    def test_token_charset_and_length(self, settings_file):
        settings = admin.set_admin_setting("todo_capture_token", "abc/../?&$" + "x" * 200)
        token = settings["todo_capture_token"]
        assert "/" not in token and "?" not in token and "$" not in token
        assert len(token) <= 128

    def test_non_string_values_fall_back(self, settings_file):
        admin.set_admin_setting("todo_capture_token", 12345)
        loaded = admin.load_admin_settings()
        assert loaded["todo_capture_token"] == ""
        admin.set_admin_setting("gtd_coaching_text", ["not", "a", "string"])
        assert admin.load_admin_settings()["gtd_coaching_text"] == DEFAULT_GTD_COACHING

    def test_coaching_capped(self, settings_file):
        admin.set_admin_setting("gtd_coaching_text", "y" * (MAX_COACHING_CHARS + 500))
        assert len(admin.load_admin_settings()["gtd_coaching_text"]) == MAX_COACHING_CHARS

    def test_defaults_present_on_fresh_load(self, settings_file):
        loaded = admin.load_admin_settings()
        assert loaded["todo_capture_token"] == ""
        assert loaded["gtd_coaching_text"] == DEFAULT_GTD_COACHING


class TestUpdateCoachingTool:
    def test_full_replace_returns_previous(self, settings_file):
        from core.todo.tools import TODO_TOOL_EXECUTORS

        result = TODO_TOOL_EXECUTORS["todo_update_gtd_coaching"](text="New rules.")
        assert result["ok"] is True
        assert result["previous_text"] == DEFAULT_GTD_COACHING
        assert result["coaching_disabled"] is False
        assert admin.load_admin_settings()["gtd_coaching_text"] == "New rules."

    def test_empty_disables(self, settings_file):
        from core.todo.tools import TODO_TOOL_EXECUTORS

        result = TODO_TOOL_EXECUTORS["todo_update_gtd_coaching"](text="")
        assert result["ok"] is True
        assert result["coaching_disabled"] is True
        assert gtd_coaching_block([_TODO_TOOL]) == ""

    def test_oversize_rejected(self, settings_file):
        from core.todo.tools import TODO_TOOL_EXECUTORS

        result = TODO_TOOL_EXECUTORS["todo_update_gtd_coaching"](text="z" * (MAX_COACHING_CHARS + 1))
        assert "error" in result
        assert admin.load_admin_settings()["gtd_coaching_text"] == DEFAULT_GTD_COACHING
