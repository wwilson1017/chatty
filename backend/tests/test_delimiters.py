"""Tests for tool result delimiter wrapping."""

import re

from core.agents.security.delimiters import (
    DELIMITER_SYSTEM_INSTRUCTION,
    should_wrap,
    wrap_result,
)


class TestShouldWrap:
    def test_external_kinds_wrapped(self):
        for kind in ("gmail", "calendar", "drive", "web"):
            assert should_wrap("some_tool", kind) is True

    def test_internal_kinds_not_wrapped(self):
        for kind in ("context", "memory", "shared_context", "reminder",
                      "scheduled_action", "report", "setup", "activity_log",
                      "meta", "real_tool", "import"):
            assert should_wrap("some_tool", kind) is False

    def test_integration_tools_wrapped_by_default(self):
        assert should_wrap("qbo_get_invoices", "integration") is True
        assert should_wrap("bamboohr_list_employees", "integration") is True
        assert should_wrap("odoo_search_records", "integration") is True

    def test_crm_lite_tools_not_wrapped(self):
        assert should_wrap("crm_list_contacts", "integration") is False
        assert should_wrap("crm_add_deal", "integration") is False

    def test_todo_content_tools_wrapped(self):
        # Todo content can arrive via the public /capture endpoint or Telegram,
        # i.e. potentially attacker-authored — content-bearing results are
        # wrapped so agents treat the text as data, not instructions.
        assert should_wrap("todo_list", "todo") is True
        assert should_wrap("todo_get", "todo") is True
        assert should_wrap("todo_update", "todo") is True

    def test_todo_structural_tools_not_wrapped(self):
        # Agent-authored echoes and structural results stay unwrapped.
        assert should_wrap("todo_create", "todo") is False
        assert should_wrap("todo_bulk_update", "todo") is False
        assert should_wrap("todo_list_projects", "todo") is False
        assert should_wrap("todo_delete", "todo") is False

    def test_unknown_kind_not_wrapped(self):
        assert should_wrap("mystery_tool", "unknown_kind") is False


class TestWrapResult:
    def test_produces_valid_structure(self):
        result = wrap_result("gmail_read_email", '{"subject": "hello"}')
        assert result.startswith('<untrusted_tool_result id="')
        assert 'tool="gmail_read_email"' in result
        match = re.search(r'id="([a-f0-9]+)"', result)
        assert match is not None
        assert result.endswith("</untrusted_tool_result>")
        assert '{"subject": "hello"}' in result

    def test_random_id_is_16_hex_chars(self):
        result = wrap_result("test_tool", "content")
        match = re.search(r'id="([a-f0-9]+)"', result)
        assert match is not None
        assert len(match.group(1)) == 16

    def test_different_ids_on_each_call(self):
        ids = set()
        for _ in range(20):
            result = wrap_result("test", "x")
            match = re.search(r'id="([a-f0-9]+)"', result)
            ids.add(match.group(1))
        assert len(ids) == 20

    def test_original_content_preserved(self):
        content = '{"key": "value with special chars: <>&\'"}'
        result = wrap_result("tool", content)
        assert content in result


class TestDelimiterInstruction:
    def test_instruction_is_nonempty_string(self):
        assert isinstance(DELIMITER_SYSTEM_INSTRUCTION, str)
        assert len(DELIMITER_SYSTEM_INSTRUCTION) > 100

    def test_instruction_mentions_untrusted_tag(self):
        assert "untrusted_tool_result" in DELIMITER_SYSTEM_INSTRUCTION

    def test_instruction_mentions_never_follow(self):
        assert "NEVER" in DELIMITER_SYSTEM_INSTRUCTION
