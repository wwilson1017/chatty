"""Tests for build_google_scopes and GMAIL_SCOPE_LEVELS in core.config."""

from core.config import build_google_scopes, GMAIL_SCOPE_LEVELS, WORKSPACE_SCOPE_LEVELS


class TestGmailScopeLevels:
    def test_send_level_includes_gmail_modify(self):
        assert "https://www.googleapis.com/auth/gmail.modify" in GMAIL_SCOPE_LEVELS["send"]

    def test_send_level_does_not_include_readonly(self):
        assert "https://www.googleapis.com/auth/gmail.readonly" not in GMAIL_SCOPE_LEVELS["send"]

    def test_read_level_uses_readonly(self):
        assert "https://www.googleapis.com/auth/gmail.readonly" in GMAIL_SCOPE_LEVELS["read"]


class TestBuildGoogleScopes:
    def test_defaults_return_identity_only(self):
        scopes = build_google_scopes()
        assert "openid" in scopes
        assert "email" in scopes
        assert "profile" in scopes
        assert len(scopes) == 3

    def test_gmail_send_includes_modify(self):
        scopes = build_google_scopes(gmail_level="send")
        assert "https://www.googleapis.com/auth/gmail.modify" in scopes
        assert "https://www.googleapis.com/auth/gmail.send" in scopes
        assert "https://www.googleapis.com/auth/gmail.compose" in scopes

    def test_gmail_read_includes_readonly(self):
        scopes = build_google_scopes(gmail_level="read")
        assert "https://www.googleapis.com/auth/gmail.readonly" in scopes

    def test_include_ai_adds_generative_language(self):
        scopes = build_google_scopes(include_ai=True)
        assert "https://www.googleapis.com/auth/generative-language" in scopes

    def test_no_duplicates(self):
        scopes = build_google_scopes(gmail_level="send", calendar_level="full", drive_level="full", include_ai=True)
        assert len(scopes) == len(set(scopes))

    def test_unknown_level_returns_identity_only(self):
        scopes = build_google_scopes(gmail_level="bogus")
        assert "openid" in scopes
        assert len(scopes) == 3

    def test_workspace_edit_includes_full_scopes(self):
        scopes = build_google_scopes(workspace_level="edit")
        assert "https://www.googleapis.com/auth/documents" in scopes
        assert "https://www.googleapis.com/auth/spreadsheets" in scopes
        assert "https://www.googleapis.com/auth/presentations" in scopes

    def test_workspace_read_uses_readonly_variants(self):
        scopes = build_google_scopes(workspace_level="read")
        assert "https://www.googleapis.com/auth/documents.readonly" in scopes
        assert "https://www.googleapis.com/auth/spreadsheets.readonly" in scopes
        assert "https://www.googleapis.com/auth/presentations.readonly" in scopes
        assert "https://www.googleapis.com/auth/documents" not in scopes

    def test_workspace_none_adds_nothing(self):
        scopes = build_google_scopes(workspace_level="none")
        assert len(scopes) == 3


class TestWorkspaceScopeLevels:
    def test_edit_is_full_not_readonly(self):
        assert "https://www.googleapis.com/auth/documents" in WORKSPACE_SCOPE_LEVELS["edit"]
        assert "https://www.googleapis.com/auth/documents.readonly" not in WORKSPACE_SCOPE_LEVELS["edit"]

    def test_none_is_empty(self):
        assert WORKSPACE_SCOPE_LEVELS["none"] == []


class TestGoogleCapabilitiesWorkspace:
    def test_capabilities_and_tool_flags(self, monkeypatch):
        from integrations.google import policy
        import integrations.registry as registry

        accounts = {
            "w_edit": {"connection_status": "ok", "scope_grants": {"workspace": "edit"}},
            "w_read": {"connection_status": "ok", "scope_grants": {"workspace": "read"}},
        }
        # policy.google_capabilities imports get_google_account from integrations.registry
        # lazily, so patch it on the registry module.
        monkeypatch.setattr(registry, "get_google_account", lambda aid: accounts.get(aid))

        edit = policy.google_capabilities("w_edit")
        assert edit["workspace_read_enabled"] is True
        assert edit["workspace_write_enabled"] is True

        read = policy.google_capabilities("w_read")
        assert read["workspace_read_enabled"] is True
        assert read["workspace_write_enabled"] is False

        # google_tool_flags scopes flags to the right service and emits multi_*
        flags = policy.google_tool_flags({"workspace": ["w_edit", "w_read"]})
        assert flags["workspace_read_enabled"] is True
        assert flags["workspace_write_enabled"] is True
        assert flags["multi_workspace"] is True
        assert flags["multi_gmail"] is False
        assert flags["gmail_read_enabled"] is False

    def test_shared_account_flags_scoped_per_service(self, monkeypatch):
        from integrations.google import policy
        import integrations.registry as registry

        # One account granted BOTH gmail-send and workspace-edit.
        accounts = {"shared": {"connection_status": "ok",
                               "scope_grants": {"gmail": "send", "workspace": "edit"}}}
        monkeypatch.setattr(registry, "get_google_account", lambda aid: accounts.get(aid))

        # Assigned to gmail only: its workspace grant must NOT leak into workspace flags.
        gmail_only = policy.google_tool_flags({"gmail": ["shared"]})
        assert gmail_only["gmail_send_enabled"] is True
        assert gmail_only["workspace_read_enabled"] is False
        assert gmail_only["workspace_write_enabled"] is False

        # Assigned to both services: each service's own flags turn on.
        both = policy.google_tool_flags({"gmail": ["shared"], "workspace": ["shared"]})
        assert both["gmail_send_enabled"] is True
        assert both["workspace_write_enabled"] is True
