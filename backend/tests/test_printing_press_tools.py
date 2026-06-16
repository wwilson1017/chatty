"""Wiring tests: ToolRegistry printed_cli dispatch, delimiters, dynamic loader."""

import pytest

from core.agents.security import delimiters
from core.agents.tool_registry import ToolRegistry


# ── delimiters ────────────────────────────────────────────────────────────

def test_printed_cli_output_is_wrapped_as_untrusted():
    assert delimiters.should_wrap("openalex__authors_list", "printed_cli") is True
    assert delimiters.should_wrap("cli_call", "printed_cli_bridge") is True


# ── registry dispatch (hermetic) ──────────────────────────────────────────

async def test_registry_dispatches_printed_cli_to_executor(tmp_path):
    seen = {}

    def exec_fn(**args):
        seen.update(args)
        return {"meta": {}, "results": [{"ok": True}]}

    registry = ToolRegistry(
        context_dir=str(tmp_path / "agent" / "context"),
        printed_cli_executors={"demo__things_list": exec_fn},
    )
    out = await registry.execute_tool("demo__things_list", {"per_page": 3}, "printed_cli")
    assert out == {"meta": {}, "results": [{"ok": True}]}
    assert seen == {"per_page": 3}


async def test_registry_unknown_printed_cli_tool_errors(tmp_path):
    registry = ToolRegistry(context_dir=str(tmp_path / "a" / "context"))
    out = await registry.execute_tool("missing__tool", {}, "printed_cli")
    assert "not available" in out["error"]


# ── live wiring through the real install (skipped if not built locally) ────

def _openalex_ready():
    try:
        from integrations.printing_press import store
        return store.is_enabled("openalex")
    except Exception:
        return False


pytestmark_live = pytest.mark.skipif(
    not _openalex_ready(), reason="openalex CLI not installed locally"
)


@pytestmark_live
def test_dynamic_loader_collapses_to_bridge():
    # openalex has 43 commands → well over the flat-tool budget → bridge.
    from agents.tool_loader import load_all_dynamic_tools

    dyn = load_all_dynamic_tools()
    names = {d["name"] for d in dyn.tool_defs}
    assert names >= {"cli_search", "cli_describe", "cli_call"}
    assert all(d["kind"] == "printed_cli_bridge" for d in dyn.tool_defs)
    assert set(dyn.printed_executors) == {"cli_search", "cli_describe", "cli_call"}
    # Per-CLI ceiling is still threaded for the resolve-then-confirm gate.
    assert dyn.printed_tool_modes.get("pp:openalex") in ("normal", "power", "read-only")


@pytestmark_live
async def test_end_to_end_registry_runs_real_cli_via_bridge(tmp_path):
    from agents.tool_loader import load_all_dynamic_tools

    dyn = load_all_dynamic_tools()
    registry = ToolRegistry(
        context_dir=str(tmp_path / "agent" / "context"),
        printed_cli_executors=dyn.printed_executors,
    )
    out = await registry.execute_tool(
        "cli_call",
        {"command": "openalex__authors_list", "arguments": {"per_page": 2}},
        "printed_cli_bridge",
    )
    assert "results" in out or "meta" in out
