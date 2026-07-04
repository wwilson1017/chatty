"""Gemini schema sanitizer — union types must collapse to a single proto-safe type."""

from core.providers.google_provider import _clean_schema


def test_union_type_collapses_to_first_concrete_type_with_nullable():
    schema = {
        "type": "array",
        "items": {"type": ["string", "number", "boolean", "null"]},
    }
    cleaned = _clean_schema(schema)
    assert cleaned["items"]["type"] == "string"
    assert cleaned["items"]["nullable"] is True


def test_union_type_without_null_is_not_nullable():
    cleaned = _clean_schema({"type": ["string", "number"]})
    assert cleaned["type"] == "string"
    assert "nullable" not in cleaned


def test_all_null_union_falls_back_to_string():
    cleaned = _clean_schema({"type": ["null"]})
    assert cleaned["type"] == "string"
    assert cleaned["nullable"] is True


def test_single_type_untouched():
    cleaned = _clean_schema({"type": "object", "properties": {"a": {"type": "integer"}}})
    assert cleaned["type"] == "object"
    assert cleaned["properties"]["a"]["type"] == "integer"


def test_workspace_write_tools_have_no_type_lists_after_cleaning():
    from core.agents.tool_definitions import WORKSPACE_WRITE_TOOLS

    def no_lists(node):
        if isinstance(node, dict):
            assert not isinstance(node.get("type"), list)
            for v in node.values():
                no_lists(v)
        elif isinstance(node, list):
            for v in node:
                no_lists(v)

    for tool in WORKSPACE_WRITE_TOOLS:
        no_lists(_clean_schema(tool["input_schema"]))
