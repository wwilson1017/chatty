"""Tests for integrations.registry — enable/disable and status logic."""

import json

import pytest


@pytest.fixture()
def registry_dir(tmp_path, monkeypatch, encryption_env):
    """Point registry DATA_DIR at a temp directory and stub app_credentials."""
    import integrations.registry as reg

    integrations_dir = tmp_path / "integrations"
    integrations_dir.mkdir()
    monkeypatch.setattr(reg, "DATA_DIR", integrations_dir)
    monkeypatch.setattr(
        "integrations.app_credentials.has_app_credentials", lambda _name: False
    )
    return integrations_dir


class TestIsEnabled:
    def test_returns_false_when_no_json_file(self, registry_dir):
        from integrations.registry import is_enabled

        assert is_enabled("odoo") is False

    def test_returns_true_when_enabled(self, registry_dir):
        from integrations.registry import save_credentials, is_enabled

        save_credentials("odoo", {"enabled": True})
        assert is_enabled("odoo") is True

    def test_returns_false_when_disabled(self, registry_dir):
        from integrations.registry import save_credentials, is_enabled

        save_credentials("odoo", {"enabled": False})
        assert is_enabled("odoo") is False


class TestEnableDisable:
    def test_enable_then_is_enabled_roundtrip(self, registry_dir):
        from integrations.registry import enable, is_enabled

        assert is_enabled("bamboohr") is False
        enable("bamboohr")
        assert is_enabled("bamboohr") is True

    def test_disable_preserves_credential_data(self, registry_dir):
        from integrations.registry import (
            disable,
            enable,
            get_credentials,
            save_credentials,
        )

        save_credentials("odoo", {
            "url": "https://myodoo.com",
            "api_key": "secret-key",
            "enabled": True,
        })
        disable("odoo")

        creds = get_credentials("odoo")
        assert creds["enabled"] is False
        assert creds["url"] == "https://myodoo.com"
        assert creds["api_key"] == "secret-key"


class TestToolMode:
    def test_default_is_normal(self, registry_dir):
        from integrations.registry import get_tool_mode, save_credentials

        save_credentials("odoo", {"enabled": True})
        assert get_tool_mode("odoo") == "normal"

    def test_set_then_get_roundtrip(self, registry_dir):
        from integrations.registry import (
            get_tool_mode,
            save_credentials,
            set_tool_mode,
        )

        save_credentials("odoo", {"enabled": True})
        set_tool_mode("odoo", "power")
        assert get_tool_mode("odoo") == "power"


class TestListIntegrations:
    def test_returns_all_available(self, registry_dir):
        from integrations.registry import AVAILABLE_INTEGRATIONS, list_integrations

        result = list_integrations()
        ids = {entry["id"] for entry in result}
        assert ids == set(AVAILABLE_INTEGRATIONS.keys())
