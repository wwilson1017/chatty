"""Tests for deferred tool loading."""

import pytest

from core.agents.deferred_tools import (
    ALWAYS_LOADED_KINDS,
    DEFERRED_TOOL_THRESHOLD,
    MIN_ITERATIONS_FOR_DEFERRAL,
    MAX_FIND_TOOLS_RESULTS,
    FIND_TOOLS_DEF,
    SEARCH_ALIASES,
    should_defer_tools,
    build_tool_catalog,
    execute_find_tools,
    load_deferred_tools,
    handle_deferred_tool_call,
    build_provider_tools,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_tool(name: str, kind: str, writes: bool = False, integration: str = "") -> dict:
    return {
        "name": name,
        "description": f"Description for {name}",
        "input_schema": {"type": "object", "properties": {}, "required": []},
        "kind": kind,
        "writes": writes,
        "context_memory": kind in ("context", "memory"),
        "integration": integration,
    }


def _make_tool_set(count_per_kind: dict[str, int], integration_tools: list[dict] | None = None) -> list[dict]:
    """Create a tool set with specified counts per kind."""
    tools = []
    for kind, count in count_per_kind.items():
        for i in range(count):
            tools.append(_make_tool(f"{kind}_tool_{i}", kind))
    if integration_tools:
        tools.extend(integration_tools)
    return tools


def _large_tool_set() -> list[dict]:
    """Create a realistic 50+ tool set that exceeds the threshold."""
    tools = _make_tool_set({
        "context": 5,
        "memory": 10,
        "shared_context": 3,
        "reminder": 3,
        "scheduled_action": 4,
        "gmail": 11,
        "calendar": 7,
        "drive": 5,
        "web": 2,
        "setup": 3,
    })
    # Add integration tools
    for i in range(10):
        tools.append(_make_tool(f"crm_tool_{i}", "integration", integration="crm_lite"))
    for i in range(5):
        tools.append(_make_tool(f"qbo_tool_{i}", "integration", integration="quickbooks"))
    return tools


# ── should_defer_tools ───────────────────────────────────────────────────────

class TestShouldDeferTools:
    def test_below_threshold(self):
        assert should_defer_tools(20) is False

    def test_at_threshold(self):
        assert should_defer_tools(DEFERRED_TOOL_THRESHOLD) is False

    def test_above_threshold(self):
        assert should_defer_tools(DEFERRED_TOOL_THRESHOLD + 1) is True

    def test_low_iterations_skips(self):
        assert should_defer_tools(DEFERRED_TOOL_THRESHOLD + 1, max_iterations=2) is False
        assert should_defer_tools(DEFERRED_TOOL_THRESHOLD + 1, max_iterations=3) is False

    def test_sufficient_iterations(self):
        assert should_defer_tools(DEFERRED_TOOL_THRESHOLD + 1, max_iterations=MIN_ITERATIONS_FOR_DEFERRAL) is True
        assert should_defer_tools(DEFERRED_TOOL_THRESHOLD + 1, max_iterations=20) is True


# ── build_tool_catalog ───────────────────────────────────────────────────────

class TestBuildToolCatalog:
    def test_always_loaded_kinds_stay_active(self):
        tools = _large_tool_set()
        active, deferred, deferred_names, catalog = build_tool_catalog(tools)

        active_kinds = {t.get("kind") for t in active}
        for kind in ALWAYS_LOADED_KINDS:
            assert kind in active_kinds

        deferred_kinds = {t.get("kind") for t in deferred}
        for kind in ALWAYS_LOADED_KINDS:
            assert kind not in deferred_kinds

    def test_non_core_kinds_deferred(self):
        tools = _large_tool_set()
        active, deferred, deferred_names, catalog = build_tool_catalog(tools)

        deferred_kind_set = {t.get("kind") for t in deferred}
        assert "gmail" in deferred_kind_set
        assert "calendar" in deferred_kind_set
        assert "drive" in deferred_kind_set

    def test_deferred_names_set_accurate(self):
        tools = _large_tool_set()
        active, deferred, deferred_names, catalog = build_tool_catalog(tools)

        assert deferred_names == {t["name"] for t in deferred}
        for t in active:
            assert t["name"] not in deferred_names

    def test_catalog_text_format(self):
        tools = _large_tool_set()
        active, deferred, deferred_names, catalog = build_tool_catalog(tools)

        assert "## Available Tools" in catalog
        assert "find_tools" in catalog
        assert "**" in catalog  # Has bold category headers

    def test_catalog_contains_deferred_tool_names(self):
        tools = _large_tool_set()
        active, deferred, deferred_names, catalog = build_tool_catalog(tools)

        for t in deferred[:5]:
            assert t["name"] in catalog

    def test_empty_deferred_returns_empty_catalog(self):
        tools = _make_tool_set({"context": 5, "memory": 3})
        active, deferred, deferred_names, catalog = build_tool_catalog(tools)

        assert len(deferred) == 0
        assert len(deferred_names) == 0
        assert catalog == ""

    def test_integration_tools_grouped_by_integration(self):
        tools = _large_tool_set()
        _, _, _, catalog = build_tool_catalog(tools)

        assert "CRM" in catalog
        assert "QuickBooks" in catalog


# ── execute_find_tools ───────────────────────────────────────────────────────

class TestExecuteFindTools:
    def _get_deferred(self) -> list[dict]:
        tools = _large_tool_set()
        _, deferred, _, _ = build_tool_catalog(tools)
        return deferred

    def test_exact_name_match(self):
        deferred = self._get_deferred()
        result = execute_find_tools("gmail_tool_0", deferred)

        assert result["count"] == 1
        assert "gmail_tool_0" in result["loaded_names"]
        assert result["truncated"] is False

    def test_alias_match_email(self):
        deferred = self._get_deferred()
        result = execute_find_tools("email", deferred)

        assert result["count"] > 0
        for name in result["loaded_names"]:
            assert "gmail" in name

    def test_alias_match_invoice(self):
        deferred = self._get_deferred()
        result = execute_find_tools("invoice", deferred)

        assert result["count"] > 0
        for name in result["loaded_names"]:
            assert "qbo" in name

    def test_kind_match(self):
        deferred = self._get_deferred()
        result = execute_find_tools("calendar", deferred)

        assert result["count"] > 0

    def test_substring_match(self):
        deferred = self._get_deferred()
        result = execute_find_tools("tool_0", deferred)

        assert result["count"] > 0

    def test_no_match(self):
        deferred = self._get_deferred()
        result = execute_find_tools("nonexistent_xyz", deferred)

        assert result["count"] == 0
        assert result["truncated"] is False
        assert "No tools matched" in result["note"]

    def test_empty_query(self):
        deferred = self._get_deferred()
        result = execute_find_tools("", deferred)

        assert result["count"] == 0

    def test_empty_deferred(self):
        result = execute_find_tools("email", [])

        assert result["count"] == 0

    def test_truncation(self):
        # Create enough tools to exceed the cap
        deferred = [_make_tool(f"test_tool_{i}", "web") for i in range(30)]
        result = execute_find_tools("test", deferred)

        assert result["count"] == MAX_FIND_TOOLS_RESULTS
        assert result["truncated"] is True
        assert result["total_matches"] == 30
        assert "more specific" in result["note"]

    def test_loaded_names_are_strings_only(self):
        """The AI-facing result must contain only name strings, not full tool defs."""
        deferred = self._get_deferred()
        result = execute_find_tools("email", deferred)

        assert result["count"] > 0
        assert all(isinstance(n, str) for n in result["loaded_names"])

        # After the caller pops matched_tools, the remaining dict must not
        # contain any nested input_schema — only flat metadata.
        matched = result.pop("matched_tools", [])
        result_str = str(result)
        assert "input_schema" not in result_str

    def test_matched_tools_have_full_schemas(self):
        """matched_tools (for provider_tools) must have full schemas."""
        deferred = self._get_deferred()
        result = execute_find_tools("email", deferred)

        for t in result.get("matched_tools", []):
            assert "input_schema" in t
            assert "name" in t
            assert "description" in t


# ── load_deferred_tools ──────────────────────────────────────────────────────

class TestLoadDeferredTools:
    def test_adds_to_all_maps(self):
        tools = _large_tool_set()
        active, deferred, deferred_names, _ = build_tool_catalog(tools)

        kind_map = {t["name"]: t.get("kind", "context") for t in active}
        writes_map = {t["name"]: t.get("writes", False) for t in active}
        cm_map = {t["name"]: t.get("context_memory", False) for t in active}
        integration_map = {t["name"]: t.get("integration", "") for t in active}

        gmail_tools = [t for t in deferred if t.get("kind") == "gmail"]
        loaded = load_deferred_tools(
            gmail_tools, active, kind_map, deferred, deferred_names,
            writes_map=writes_map, cm_map=cm_map, integration_map=integration_map,
        )

        for name in loaded:
            assert name in kind_map
            assert name in writes_map
            assert name in cm_map
            assert name in integration_map
            assert name not in deferred_names

    def test_removes_from_deferred(self):
        tools = _large_tool_set()
        active, deferred, deferred_names, _ = build_tool_catalog(tools)
        kind_map = {t["name"]: t.get("kind", "context") for t in active}

        gmail_tools = [t for t in deferred if t.get("kind") == "gmail"]
        initial_deferred_count = len(deferred)

        load_deferred_tools(gmail_tools, active, kind_map, deferred, deferred_names)

        assert len(deferred) == initial_deferred_count - len(gmail_tools)

    def test_skips_already_loaded(self):
        tools = _large_tool_set()
        active, deferred, deferred_names, _ = build_tool_catalog(tools)
        kind_map = {t["name"]: t.get("kind", "context") for t in active}

        # Load once
        gmail_tools = [t for t in deferred if t.get("kind") == "gmail"]
        loaded1 = load_deferred_tools(gmail_tools, active, kind_map, deferred, deferred_names)

        # Try to load again
        loaded2 = load_deferred_tools(gmail_tools, active, kind_map, deferred, deferred_names)

        assert len(loaded1) > 0
        assert len(loaded2) == 0

    def test_optional_maps(self):
        """load_deferred_tools works with optional maps omitted."""
        tools = _large_tool_set()
        active, deferred, deferred_names, _ = build_tool_catalog(tools)
        kind_map = {t["name"]: t.get("kind", "context") for t in active}

        gmail_tools = [t for t in deferred if t.get("kind") == "gmail"]
        loaded = load_deferred_tools(gmail_tools, active, kind_map, deferred, deferred_names)

        assert len(loaded) > 0

    def test_union_across_calls(self):
        """Multiple load calls accumulate (union), not replace."""
        tools = _large_tool_set()
        active, deferred, deferred_names, _ = build_tool_catalog(tools)
        kind_map = {t["name"]: t.get("kind", "context") for t in active}

        gmail_tools = [t for t in deferred if t.get("kind") == "gmail"]
        cal_tools = [t for t in deferred if t.get("kind") == "calendar"]

        loaded1 = load_deferred_tools(gmail_tools, active, kind_map, deferred, deferred_names)
        loaded2 = load_deferred_tools(cal_tools, active, kind_map, deferred, deferred_names)

        all_loaded = set(loaded1 + loaded2)
        for name in all_loaded:
            assert name in kind_map


# ── SEARCH_ALIASES validation ────────────────────────────────────────────────

class TestSearchAliases:
    def test_all_aliases_have_valid_structure(self):
        for alias, (kinds, integrations, prefixes) in SEARCH_ALIASES.items():
            assert isinstance(kinds, list), f"Alias '{alias}' kinds must be a list"
            assert isinstance(integrations, list), f"Alias '{alias}' integrations must be a list"
            assert isinstance(prefixes, list), f"Alias '{alias}' prefixes must be a list"

    def test_email_alias_matches_gmail_tools(self):
        gmail_tools = [_make_tool(f"gmail_tool_{i}", "gmail") for i in range(5)]
        result = execute_find_tools("email", gmail_tools)
        assert result["count"] == 5

    def test_invoice_alias_matches_qbo_tools(self):
        qbo_tools = [_make_tool(f"qbo_tool_{i}", "integration", integration="quickbooks") for i in range(5)]
        result = execute_find_tools("invoice", qbo_tools)
        assert result["count"] == 5

    def test_calendar_alias_matches_calendar_tools(self):
        cal_tools = [_make_tool(f"calendar_tool_{i}", "calendar") for i in range(5)]
        result = execute_find_tools("meeting", cal_tools)
        assert result["count"] == 5


# ── FIND_TOOLS_DEF ───────────────────────────────────────────────────────────

class TestFindToolsDef:
    def test_has_required_fields(self):
        assert FIND_TOOLS_DEF["name"] == "find_tools"
        assert "description" in FIND_TOOLS_DEF
        assert "input_schema" in FIND_TOOLS_DEF
        assert FIND_TOOLS_DEF["kind"] == "meta"
        assert FIND_TOOLS_DEF["writes"] is False

    def test_schema_has_query_param(self):
        props = FIND_TOOLS_DEF["input_schema"]["properties"]
        assert "query" in props
        assert FIND_TOOLS_DEF["input_schema"]["required"] == ["query"]


# ── handle_deferred_tool_call ────────────────────────────────────────────────

class TestHandleDeferredToolCall:
    def _setup(self):
        tools = _large_tool_set()
        active, deferred, deferred_names, _ = build_tool_catalog(tools)
        kind_map = {t["name"]: t.get("kind", "context") for t in active}
        kind_map["find_tools"] = "meta"
        return active, deferred, deferred_names, kind_map

    def test_deferred_tool_returns_error(self):
        """Calling a deferred tool without find_tools returns a helpful error."""
        active, deferred, deferred_names, kind_map = self._setup()
        deferred_name = next(iter(deferred_names))

        result, tools_changed = handle_deferred_tool_call(
            deferred_name, {}, deferred, deferred_names,
            active, kind_map,
        )

        assert result is not None
        assert "error" in result
        assert "not loaded" in result["error"]
        assert "find_tools" in result["error"]
        assert tools_changed is False

    def test_find_tools_loads_and_returns_names(self):
        """find_tools call loads tools and returns names-only result."""
        active, deferred, deferred_names, kind_map = self._setup()
        initial_active_count = len(active)

        result, tools_changed = handle_deferred_tool_call(
            "find_tools", {"query": "email"}, deferred, deferred_names,
            active, kind_map,
        )

        assert result is not None
        assert tools_changed is True
        assert result["count"] > 0
        assert all(isinstance(n, str) for n in result["loaded_names"])
        assert "matched_tools" not in result
        assert len(active) > initial_active_count
        for name in result["loaded_names"]:
            assert name in kind_map

    def test_find_tools_with_empty_pool(self):
        """find_tools returns graceful empty result when pool is exhausted."""
        active, deferred, deferred_names, kind_map = self._setup()
        deferred.clear()
        deferred_names.clear()

        result, tools_changed = handle_deferred_tool_call(
            "find_tools", {"query": "email"}, deferred, deferred_names,
            active, kind_map,
        )

        assert result is not None
        assert result["count"] == 0
        assert tools_changed is False

    def test_normal_tool_not_intercepted(self):
        """A non-deferred, non-find_tools call returns None (not handled)."""
        active, deferred, deferred_names, kind_map = self._setup()

        result, tools_changed = handle_deferred_tool_call(
            "read_context_file", {"filename": "test.md"}, deferred, deferred_names,
            active, kind_map,
        )

        assert result is None
        assert tools_changed is False

    def test_hallucinated_tool_not_intercepted(self):
        """A tool name not in deferred_names or kind_map is not caught by guard."""
        active, deferred, deferred_names, kind_map = self._setup()

        result, tools_changed = handle_deferred_tool_call(
            "totally_fake_tool", {}, deferred, deferred_names,
            active, kind_map,
        )

        assert result is None
        assert tools_changed is False

    def test_maps_updated_on_load(self):
        """find_tools updates all provided maps."""
        active, deferred, deferred_names, kind_map = self._setup()
        writes_map: dict[str, bool] = {}
        cm_map: dict[str, bool] = {}
        integration_map: dict[str, str] = {}

        result, _ = handle_deferred_tool_call(
            "find_tools", {"query": "email"}, deferred, deferred_names,
            active, kind_map,
            writes_map=writes_map, cm_map=cm_map, integration_map=integration_map,
        )

        for name in result["loaded_names"]:
            assert name in writes_map
            assert name in cm_map
            assert name in integration_map


# ── build_provider_tools ─────────────────────────────────────────────────────

class TestBuildProviderTools:
    def test_strips_internal_fields(self):
        tools = [_make_tool("test_tool", "gmail", writes=True, integration="test")]
        provider = build_provider_tools(tools)

        assert len(provider) == 1
        assert "name" in provider[0]
        assert "description" in provider[0]
        assert "input_schema" in provider[0]
        assert "kind" not in provider[0]
        assert "writes" not in provider[0]
        assert "context_memory" not in provider[0]
        assert "integration" not in provider[0]
