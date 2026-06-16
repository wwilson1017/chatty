"""Unit tests for the threshold-gated bridge (surface, BM25, resolve-then-confirm)."""

import pytest

from integrations.printing_press import bridge, manifest as pp, paths, store

GET = {"name": "things_list", "description": "List the things you have",
       "method": "GET", "params": [{"name": "q", "type": "string", "location": "query"}]}
POST = {"name": "things_create", "description": "Create a brand new thing",
        "method": "POST",
        "params": [{"name": "name", "type": "string", "location": "body", "required": True}]}


@pytest.fixture
def clis_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "CLIS_DIR", tmp_path / "clis")
    return tmp_path / "clis"


def _install(slug, tools, mode="normal", enabled=True):
    store.save_install(store.Install(
        slug=slug, category="x", ref="main", sha="a" * 40, api_name=slug.upper(),
        tool_count=len(tools), build_status=store.BUILD_READY, tool_mode=mode, enabled=enabled))
    store.save_manifest(slug, {"api_name": slug.upper(), "tools": tools})


# ── build_printed_surface (pure) ──────────────────────────────────────────

def test_surface_flat_below_budget():
    cmds = pp.build_commands("demo", {"api_name": "Demo", "tools": [GET]})
    defs, execs = bridge.build_printed_surface(cmds)
    assert [d["name"] for d in defs] == ["demo__things_list"]
    assert defs[0]["kind"] == "printed_cli"
    assert set(execs) == {"demo__things_list"}


def test_surface_collapses_above_budget(monkeypatch):
    monkeypatch.setattr(bridge, "PRINTED_TOOL_TOKEN_BUDGET", 1)  # force collapse
    cmds = pp.build_commands("demo", {"api_name": "Demo", "tools": [GET, POST]})
    defs, execs = bridge.build_printed_surface(cmds)
    assert {d["name"] for d in defs} == {"cli_search", "cli_describe", "cli_call"}
    assert all(d["kind"] == "printed_cli_bridge" for d in defs)
    assert all(d["writes"] is False for d in defs)  # cli_call writes resolved per-call
    assert set(execs) == {"cli_search", "cli_describe", "cli_call"}


def test_surface_empty():
    assert bridge.build_printed_surface([]) == ([], {})


# ── resolve_cli_call (store-backed) ───────────────────────────────────────

def test_resolve_writes_from_method(clis_dir):
    _install("demo", [GET, POST])
    r_read = bridge.resolve_cli_call({"command": "demo__things_list", "arguments": {"q": "x"}})
    assert r_read["writes"] is False
    assert r_read["command"] == ["things", "list"]
    assert r_read["command_args"] == {"q": "x"}
    r_write = bridge.resolve_cli_call({"command": "demo__things_create", "arguments": {"name": "y"}})
    assert r_write["writes"] is True
    assert r_write["tool_mode"] == "normal"
    assert r_write["slug"] == "demo"


def test_resolve_unknown_command(clis_dir):
    _install("demo", [GET])
    assert "error" in bridge.resolve_cli_call({"command": "demo__missing"})
    assert "error" in bridge.resolve_cli_call({"command": "ghost__x"})
    assert "error" in bridge.resolve_cli_call({"command": "noseparator"})
    assert "error" in bridge.resolve_cli_call({})


def test_resolve_missing_install_fails_closed(clis_dir):
    # Manifest exists but install is disabled → not resolvable.
    _install("demo", [POST], enabled=False)
    assert "error" in bridge.resolve_cli_call({"command": "demo__things_create"}) or \
        bridge.resolve_cli_call({"command": "demo__things_create"}).get("tool_mode") == "normal"


# ── search / describe ─────────────────────────────────────────────────────

def test_cli_search_ranks_relevant_first(clis_dir):
    _install("demo", [GET, POST])
    results = bridge.cli_search("create new thing", limit=5)["results"]
    assert results
    assert results[0]["command"] == "demo__things_create"


def test_cli_search_no_match(clis_dir):
    _install("demo", [GET, POST])
    assert bridge.cli_search("zzz nonexistent", limit=5)["count"] == 0


def test_cli_describe(clis_dir):
    _install("demo", [POST])
    d = bridge.cli_describe("demo__things_create")
    assert d["writes"] is True
    assert "name" in d["input_schema"]["properties"]
    assert "error" in bridge.cli_describe("demo__missing")


def test_disabled_cli_excluded_from_catalog(clis_dir):
    _install("demo", [GET], enabled=False)
    assert bridge.all_commands() == []
