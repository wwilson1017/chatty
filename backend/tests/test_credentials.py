"""Tests for core.providers.credentials — CredentialStore gap behaviors.

Covers behaviors NOT tested in test_encryption.py:
- OAuth refresh token preservation on re-auth
- Token expiry with 60s grace period
- to_dict() sanitization (key_preview, no raw keys)
- Active provider switching and removal
- Ollama credential storage
"""

import time

import pytest

from core.providers.credentials import CredentialStore


@pytest.fixture
def store_env(encryption_env, tmp_path, monkeypatch):
    """Isolated CredentialStore: temp data dir, no disk leakage."""
    from core.providers import credentials

    monkeypatch.setattr(credentials, "DATA_DIR", tmp_path)
    monkeypatch.setattr(credentials, "PROFILES_PATH", tmp_path / "auth-profiles.json")
    return CredentialStore()


# ---------------------------------------------------------------------------
# OAuth refresh token preservation
# ---------------------------------------------------------------------------

class TestOAuthRefreshPreservation:
    def test_refresh_token_preserved_when_omitted(self, store_env):
        store = store_env
        store.set_oauth_tokens("google", "access-1", "refresh-original", 3600)

        # Re-auth omits refresh_token (Google behavior for existing grants)
        store.set_oauth_tokens("google", "access-2", "", 3600)

        _, profile = store.get_active_profile("google")
        assert profile["refresh"] == "refresh-original"
        assert profile["access"] == "access-2"

    def test_refresh_token_updated_when_provided(self, store_env):
        store = store_env
        store.set_oauth_tokens("google", "access-1", "refresh-old", 3600)
        store.set_oauth_tokens("google", "access-2", "refresh-new", 3600)

        _, profile = store.get_active_profile("google")
        assert profile["refresh"] == "refresh-new"


# ---------------------------------------------------------------------------
# Token expiry with 60s grace period
# ---------------------------------------------------------------------------

class TestTokenExpiry:
    def test_expired_token(self, store_env, monkeypatch):
        store = store_env
        # Fix time at 10000
        monkeypatch.setattr(time, "time", lambda: 10000)
        store.set_oauth_tokens("google", "access", "refresh", 3600)
        # expires = 10000 + 3600 = 13600

        # Jump past expiry
        monkeypatch.setattr(time, "time", lambda: 14000)
        assert store.is_token_expired("google") is True

    def test_within_grace_period(self, store_env, monkeypatch):
        store = store_env
        monkeypatch.setattr(time, "time", lambda: 10000)
        store.set_oauth_tokens("google", "access", "refresh", 3600)
        # expires = 13600, grace starts at 13540

        # At 13550: 50s before expiry, inside the 60s grace window
        monkeypatch.setattr(time, "time", lambda: 13550)
        assert store.is_token_expired("google") is True

    def test_not_expired_outside_grace(self, store_env, monkeypatch):
        store = store_env
        monkeypatch.setattr(time, "time", lambda: 10000)
        store.set_oauth_tokens("google", "access", "refresh", 3600)

        # At 13000: 600s before expiry, well outside grace
        monkeypatch.setattr(time, "time", lambda: 13000)
        assert store.is_token_expired("google") is False


# ---------------------------------------------------------------------------
# to_dict() sanitization
# ---------------------------------------------------------------------------

class TestToDict:
    def test_api_key_shows_preview_not_raw(self, store_env):
        store = store_env
        store.set_api_key("anthropic", "sk-ant-api03-secret-key-ABCD")

        result = store.to_dict()
        anthropic = result["profiles"]["anthropic"]
        assert anthropic["key_preview"] == "...ABCD"
        assert anthropic["configured"] is True
        # No raw key anywhere in the dict
        assert "sk-ant" not in str(result)

    def test_oauth_profile_has_no_tokens(self, store_env, monkeypatch):
        store = store_env
        monkeypatch.setattr(time, "time", lambda: 10000)
        store.set_oauth_tokens("google", "ya29.secret-access", "1//refresh", 3600)

        result = store.to_dict()
        google = result["profiles"]["google"]
        assert google["type"] == "oauth"
        assert google["configured"] is True
        assert "access" not in google
        assert "refresh" not in google


# ---------------------------------------------------------------------------
# Active provider switching and removal
# ---------------------------------------------------------------------------

class TestProviderManagement:
    def test_set_active_provider(self, store_env):
        store = store_env
        store.set_api_key("anthropic", "sk-ant-key")
        store.set_api_key("openai", "sk-openai-key")

        store.set_active_provider("anthropic")
        assert store.data["active_provider"] == "anthropic"

    def test_remove_active_provider_clears_active(self, store_env):
        store = store_env
        store.set_api_key("anthropic", "sk-ant-key")
        assert store.data["active_provider"] == "anthropic"

        store.remove_provider("anthropic")
        assert store.data["active_provider"] == ""
        assert store.data["active_model"] == ""
        assert "anthropic:default" not in store.data["profiles"]

    def test_remove_inactive_provider_keeps_active(self, store_env):
        store = store_env
        store.set_api_key("anthropic", "sk-ant-key")
        store.set_api_key("openai", "sk-openai-key")
        # openai is now active (last set_api_key call)

        store.remove_provider("anthropic")
        assert store.data["active_provider"] == "openai"
        assert "anthropic:default" not in store.data["profiles"]


# ---------------------------------------------------------------------------
# Ollama storage
# ---------------------------------------------------------------------------

class TestOllama:
    def test_set_ollama_stores_correctly(self, store_env):
        store = store_env
        store.set_ollama("http://192.168.1.50:11434", model="llama3")

        _, profile = store.get_active_profile("ollama")
        assert profile["type"] == "ollama_local"
        assert profile["base_url"] == "http://192.168.1.50:11434"
        assert store.data["active_provider"] == "ollama"
        assert store.data["active_model"] == "llama3"
