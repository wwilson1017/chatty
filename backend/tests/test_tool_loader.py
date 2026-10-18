"""Tests for integration tool loading and agent handler construction."""

import asyncio
import re
from pathlib import Path
from unittest.mock import patch
from types import ModuleType

from agents import tool_loader
from agents.tool_loader import format_current_time, load_integration_tools, build_agent_handlers, tool_flags

BACKEND = Path(__file__).resolve().parent.parent


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

    def test_callable_defs_and_executors_load(self):
        """A module may build its tool list at load time; async executors pass through."""
        async def run(**kw):
            return {"ok": True}

        fake_mod = ModuleType("fake_dynamic")
        fake_mod.TODOIST_TOOL_DEFS = lambda: [{"name": "dyn_tool", "kind": "integration", "input_schema": {},
                                               "context_aware": True}]
        fake_mod.TOOL_EXECUTORS = lambda: {"dyn_tool": run}

        with patch("integrations.registry.is_enabled", side_effect=lambda n: n == "todoist"), \
             patch("importlib.import_module", return_value=fake_mod):
            defs, execs = load_integration_tools()

        assert [(d["name"], d["integration"], d["context_aware"]) for d in defs] == [("dyn_tool", "todoist", True)]
        assert asyncio.iscoroutinefunction(execs["dyn_tool"])
        assert tool_flags(defs) == {"dyn_tool": {"context_aware": True}}


class TestToolFlags:
    def test_collects_only_flag_keys(self):
        defs = [{"name": "a", "context_aware": True, "writes": True}, {"name": "b"}]
        assert tool_flags(defs) == {"a": {"context_aware": True}, "b": {}}


class TestEveryEntryPointSharesTheLoader:
    """Telegram, WhatsApp and Paperclip used to carry private copies of the integration
    map; they now get the exact same tool set as web chat, and every ToolRegistry that
    takes integration executors also gets the server-owned flags map."""

    FORMER_COPIES = ("integrations.telegram.service", "integrations.whatsapp.service",
                     "integrations.paperclip.webhook")

    def test_former_copies_use_the_shared_loader(self):
        import importlib
        for path in self.FORMER_COPIES:
            mod = importlib.import_module(path)
            assert mod.load_integration_tools is tool_loader.load_integration_tools, path
            assert mod.INTEGRATION_MODULES is tool_loader.INTEGRATION_MODULES, path
            assert not hasattr(mod, "_INTEGRATION_MODULES") and not hasattr(mod, "_load_integration_tools"), path

    def test_every_registry_with_executors_gets_the_flags_map(self):
        sites = 0
        for py in BACKEND.rglob("*.py"):
            if "tests" in py.parts or ".venv" in py.parts:
                continue
            src = py.read_text(encoding="utf-8")
            for m in re.finditer(r"ToolRegistry\((.*?)\n\s*\)", src, re.S):
                if "integration_executors=" not in m.group(1):
                    continue
                sites += 1
                assert "integration_tool_flags=tool_flags(integration_tool_defs)" in m.group(1), \
                    f"{py.relative_to(BACKEND)} builds a ToolRegistry without the flags map"
        assert sites >= 10  # router ×2, cli, heartbeat, cron, coach, telegram ×2, whatsapp, paperclip


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
