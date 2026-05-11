"""Tests for tool schema generation and metadata maps."""

from core.agents.tool_definitions import (
    get_tool_definitions,
    build_writes_map,
    build_context_memory_map,
)


def _tool_names(defs: list[dict]) -> set[str]:
    return {t["name"] for t in defs}


class TestDefaultToolSet:
    def test_includes_core_tools(self):
        names = _tool_names(get_tool_definitions())
        assert "list_context_files" in names
        assert "append_daily_note" in names
        assert "list_shared_context" in names
        assert "web_search" in names
        assert "create_reminder" in names

    def test_excludes_google_when_disabled(self):
        names = _tool_names(get_tool_definitions())
        assert "search_emails" not in names
        assert "send_email" not in names
        assert "list_calendar_events" not in names
        assert "search_drive_files" not in names


class TestGoogleFlagGating:
    def test_gmail_read_adds_read_tools(self):
        names = _tool_names(get_tool_definitions(gmail_read_enabled=True))
        assert "search_emails" in names
        assert "send_email" not in names

    def test_gmail_send_adds_write_tools(self):
        names = _tool_names(get_tool_definitions(gmail_send_enabled=True))
        assert "send_email" in names

    def test_calendar_read_write_gating(self):
        read_names = _tool_names(get_tool_definitions(calendar_read_enabled=True))
        assert "list_calendar_events" in read_names
        assert "create_calendar_event" not in read_names

        write_names = _tool_names(get_tool_definitions(calendar_write_enabled=True))
        assert "create_calendar_event" in write_names

    def test_drive_read_write_gating(self):
        read_names = _tool_names(get_tool_definitions(drive_read_enabled=True))
        assert "search_drive_files" in read_names
        assert "create_drive_folder" not in read_names

        write_names = _tool_names(get_tool_definitions(drive_write_enabled=True))
        assert "create_drive_folder" in write_names

    def test_legacy_gmail_enabled_falls_through_to_read(self):
        names = _tool_names(get_tool_definitions(gmail_enabled=True))
        assert "search_emails" in names
        assert "send_email" not in names


class TestFeatureFlags:
    def test_disabling_web_removes_tools(self):
        names = _tool_names(get_tool_definitions(web_enabled=False))
        assert "web_search" not in names

    def test_disabling_memory_removes_tools(self):
        names = _tool_names(get_tool_definitions(memory_enabled=False))
        assert "append_daily_note" not in names

    def test_disabling_shared_context_removes_tools(self):
        names = _tool_names(get_tool_definitions(shared_context_enabled=False))
        assert "list_shared_context" not in names


class TestImportMode:
    def test_returns_only_readonly_context_and_import_tools(self):
        defs = get_tool_definitions(import_mode=True)
        names = _tool_names(defs)
        assert "list_context_files" in names
        assert "read_context_file" in names
        assert "write_context_file" not in names
        assert "web_search" not in names
        assert "send_email" not in names


class TestMultiAccountInjection:
    def test_multi_gmail_injects_account_param(self):
        defs = get_tool_definitions(gmail_read_enabled=True, multi_gmail=True)
        gmail_tools = [t for t in defs if t.get("kind") == "gmail"]
        for tool in gmail_tools:
            props = tool["input_schema"]["properties"]
            assert "account" in props, f"{tool['name']} missing account param"

    def test_single_account_no_injection(self):
        defs = get_tool_definitions(gmail_read_enabled=True, multi_gmail=False)
        gmail_tools = [t for t in defs if t.get("kind") == "gmail"]
        for tool in gmail_tools:
            props = tool["input_schema"]["properties"]
            assert "account" not in props


class TestToolMerging:
    def test_integration_tools_appended(self):
        custom = [{"name": "custom_tool", "kind": "custom", "input_schema": {"type": "object", "properties": {}}}]
        names = _tool_names(get_tool_definitions(integration_tools=custom))
        assert "custom_tool" in names

    def test_dynamic_real_tools_appended(self):
        dyn = [{"name": "my_script", "kind": "real", "input_schema": {"type": "object", "properties": {}}}]
        names = _tool_names(get_tool_definitions(dynamic_real_tools=dyn))
        assert "my_script" in names


class TestMetadataMaps:
    def test_writes_map_classifies_correctly(self):
        defs = get_tool_definitions(gmail_read_enabled=True, gmail_send_enabled=True)
        wmap = build_writes_map(defs)
        assert wmap["send_email"] is True
        assert wmap["search_emails"] is False
        assert wmap["list_context_files"] is False

    def test_context_memory_map_classifies_correctly(self):
        defs = get_tool_definitions()
        cm_map = build_context_memory_map(defs)
        assert cm_map["write_context_file"] is True
        assert cm_map["append_daily_note"] is True
        assert cm_map["web_search"] is False


class TestSchemaIntegrity:
    def test_all_tools_have_required_fields(self):
        defs = get_tool_definitions(
            gmail_read_enabled=True, gmail_send_enabled=True,
            calendar_read_enabled=True, calendar_write_enabled=True,
            drive_read_enabled=True, drive_write_enabled=True,
        )
        for tool in defs:
            assert "name" in tool, f"Tool missing name: {tool}"
            assert "input_schema" in tool, f"{tool['name']} missing input_schema"
            assert "kind" in tool, f"{tool['name']} missing kind"

    def test_no_duplicate_names(self):
        defs = get_tool_definitions(
            gmail_read_enabled=True, gmail_send_enabled=True,
            calendar_read_enabled=True, calendar_write_enabled=True,
            drive_read_enabled=True, drive_write_enabled=True,
        )
        names = [t["name"] for t in defs]
        assert len(names) == len(set(names)), f"Duplicate names: {[n for n in names if names.count(n) > 1]}"
