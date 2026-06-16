"""Unit tests for the no-confirm (background) write filter — plan R4.

Printed-CLI writes must NOT auto-run in background turns (scheduled actions,
heartbeat) unless the CLI is explicitly set to "power". Regular integrations
keep their existing behavior (only a "read-only" ceiling strips their writes).
"""

from agents.tool_loader import filter_no_confirm_writes


def _printed(name, writes, integ="pp:demo"):
    return {"name": name, "writes": writes, "integration": integ, "kind": "printed_cli"}


def _integ(name, writes, integ="odoo"):
    return {"name": name, "writes": writes, "integration": integ, "kind": "integration"}


def test_printed_write_blocked_in_background_by_default():
    tools = [_printed("demo__create", True)]
    assert filter_no_confirm_writes(tools, {"pp:demo": "normal"}) == []


def test_printed_write_allowed_when_power():
    tools = [_printed("demo__create", True)]
    assert filter_no_confirm_writes(tools, {"pp:demo": "power"}) == tools


def test_printed_read_always_allowed():
    tools = [_printed("demo__list", False)]
    for mode in ("normal", "power", "read-only"):
        assert filter_no_confirm_writes(tools, {"pp:demo": mode}) == tools


def test_printed_write_blocked_when_mode_missing():
    # No mode entry → default-block (treated as not "power").
    tools = [_printed("demo__create", True)]
    assert filter_no_confirm_writes(tools, {}) == []


def test_integration_write_keeps_existing_behavior():
    tools = [_integ("odoo_create", True)]
    # Normal/power integration writes DO run in background (unchanged).
    assert filter_no_confirm_writes(tools, {"odoo": "normal"}) == tools
    assert filter_no_confirm_writes(tools, {}) == tools  # default power
    # Only read-only strips them.
    assert filter_no_confirm_writes(tools, {"odoo": "read-only"}) == []


def test_context_memory_writes_never_stripped():
    tools = [{"name": "context_memory", "writes": True, "context_memory": True,
              "integration": "pp:demo"}]
    assert filter_no_confirm_writes(tools, {"pp:demo": "normal"}) == tools


def test_mixed_set():
    tools = [
        _printed("demo__list", False),
        _printed("demo__create", True),
        _integ("odoo_read", False),
        _integ("odoo_write", True),
    ]
    kept = filter_no_confirm_writes(tools, {"pp:demo": "normal", "odoo": "normal"})
    names = {t["name"] for t in kept}
    assert names == {"demo__list", "odoo_read", "odoo_write"}  # printed write dropped
