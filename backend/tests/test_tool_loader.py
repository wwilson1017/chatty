"""Tests for integration tool loading and agent handler construction."""

from unittest.mock import patch, MagicMock
from types import ModuleType

from agents.tool_loader import format_current_time, load_integration_tools, build_agent_handlers


class TestFormatCurrentTime:
    def test_returns_date_and_time_strings(self):
        date_str, time_str = format_current_time()
        assert isinstance(date_str, str)
        assert isinstance(time_str, str)
        assert len(date_str) > 0
        assert len(time_str) > 0

    def test_invalid_timezone_falls_back(self):
        date_str, time_str = format_current_time("Not/A/Timezone")
        assert isinstance(date_str, str)
        assert len(date_str) > 0


class TestLoadIntegrationTools:
    def test_no_integrations_enabled(self):
        with patch("integrations.registry.is_enabled", return_value=False):
            defs, execs = load_integration_tools()
            assert defs == []
            assert execs == {}

    def test_enabled_integration_loads_tools(self):
        fake_mod = ModuleType("fake_integration")
        # todoist's defs_attr is "TODOIST_TOOL_DEFS" per INTEGRATION_MODULES
        fake_mod.TODOIST_TOOL_DEFS = [{"name": "fake_tool", "kind": "fake", "input_schema": {}}]
        fake_mod.TOOL_EXECUTORS = {"fake_tool": lambda: None}

        def is_enabled(name):
            return name == "todoist"

        with patch("integrations.registry.is_enabled", side_effect=is_enabled), \
             patch("importlib.import_module", return_value=fake_mod):
            defs, execs = load_integration_tools()

        assert len(defs) == 1
        assert defs[0]["name"] == "fake_tool"
        assert defs[0]["integration"] == "todoist"
        assert "fake_tool" in execs

    def test_failed_import_logged_not_crashed(self):
        def is_enabled(name):
            return name == "odoo"

        with patch("integrations.registry.is_enabled", side_effect=is_enabled), \
             patch("importlib.import_module", side_effect=ImportError("no module")):
            defs, execs = load_integration_tools()

        assert defs == []
        assert execs == {}


class TestBuildAgentHandlers:
    def test_returns_expected_handler_keys(self):
        reminders, scheduled = build_agent_handlers("test-agent")
        assert set(reminders.keys()) == {"create_reminder", "list_reminders", "cancel_reminder"}
        assert set(scheduled.keys()) == {
            "create_scheduled_action", "list_scheduled_actions",
            "update_scheduled_action", "delete_scheduled_action",
        }

    def test_handlers_are_callable(self):
        reminders, scheduled = build_agent_handlers("test-agent")
        for name, fn in {**reminders, **scheduled}.items():
            assert callable(fn), f"{name} is not callable"
