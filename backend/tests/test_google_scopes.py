"""Tests for build_google_scopes and GMAIL_SCOPE_LEVELS in core.config."""

from core.config import build_google_scopes, GMAIL_SCOPE_LEVELS


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
