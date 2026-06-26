"""Tests for _google_accounts_context system prompt builder."""

from core.agents.ai_service import _google_accounts_context


def _make_info(email, *, status="ok", gmail="send", calendar="full", drive="full", workspace="none"):
    return {
        "email": email,
        "connection_status": status,
        "scope_grants": {"gmail": gmail, "calendar": calendar, "drive": drive, "workspace": workspace},
    }


class TestUnassignedAccounts:
    def test_fully_unassigned_account_listed(self):
        info_map = {"a1": _make_info("alice@example.com")}
        result = _google_accounts_context(info_map, {})
        assert "alice@example.com" in result
        assert "Gmail, Calendar, Drive not assigned" in result

    def test_fully_assigned_account_not_listed(self):
        info_map = {"a1": _make_info("alice@example.com")}
        ga = {"gmail": ["a1"], "calendar": ["a1"], "drive": ["a1"]}
        result = _google_accounts_context(info_map, ga)
        assert "Not Assigned" not in result

    def test_partially_assigned_shows_missing_services(self):
        info_map = {"a1": _make_info("alice@example.com")}
        ga = {"gmail": ["a1"], "calendar": [], "drive": []}
        result = _google_accounts_context(info_map, ga)
        assert "Calendar, Drive not assigned" in result
        alice_line = [line for line in result.splitlines() if "alice@example.com" in line][0]
        assert "Gmail" not in alice_line

    def test_broken_account_excluded(self):
        info_map = {"a1": _make_info("broken@example.com", status="broken")}
        result = _google_accounts_context(info_map, {})
        assert "Not Assigned" not in result

    def test_account_with_no_grants_excluded(self):
        info_map = {"a1": _make_info("none@example.com", gmail="none", calendar="none", drive="none")}
        result = _google_accounts_context(info_map, {})
        assert "Not Assigned" not in result

    def test_includes_assignment_instructions(self):
        info_map = {"a1": _make_info("alice@example.com")}
        result = _google_accounts_context(info_map, {})
        assert "Settings (gear icon)" in result
        assert "Integrations tab" in result
        assert "Agent Assignments" in result

    def test_mixed_assigned_and_unassigned(self):
        info_map = {
            "a1": _make_info("alice@example.com"),
            "a2": _make_info("bob@example.com"),
        }
        ga = {"gmail": ["a1"], "calendar": ["a1"], "drive": ["a1"]}
        result = _google_accounts_context(info_map, ga)
        assert "alice@example.com" not in result
        assert "bob@example.com" in result

    def test_empty_account_info_map(self):
        result = _google_accounts_context({}, {})
        assert result == ""


class TestWorkspaceService:
    def test_workspace_grant_unassigned_is_surfaced(self):
        info_map = {"a1": _make_info("alice@example.com", workspace="edit")}
        ga = {"gmail": ["a1"], "calendar": ["a1"], "drive": ["a1"]}
        result = _google_accounts_context(info_map, ga)
        assert "Workspace not assigned" in result

    def test_workspace_fully_assigned_not_listed(self):
        info_map = {"a1": _make_info("alice@example.com", workspace="edit")}
        ga = {"gmail": ["a1"], "calendar": ["a1"], "drive": ["a1"], "workspace": ["a1"]}
        result = _google_accounts_context(info_map, ga)
        assert "Not Assigned" not in result

    def test_multi_workspace_section_uses_account_param_copy(self):
        info_map = {
            "a1": _make_info("w1@example.com", gmail="none", calendar="none", drive="none", workspace="edit"),
            "a2": _make_info("w2@example.com", gmail="none", calendar="none", drive="none", workspace="edit"),
        }
        ga = {"workspace": ["a1", "a2"]}
        result = _google_accounts_context(info_map, ga)
        assert "Workspace" in result
        assert "w1@example.com" in result and "w2@example.com" in result
