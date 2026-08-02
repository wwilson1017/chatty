"""Tests for integrations.registry — enable/disable and status logic."""


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


class TestCrmDemotion:
    """CRM Lite is a normal opt-in integration: default OFF, no always_on lock."""

    def test_fresh_install_crm_disabled(self, registry_dir):
        from integrations.registry import is_enabled

        assert is_enabled("crm_lite") is False

    def test_crm_entry_has_no_always_on(self):
        from integrations.registry import AVAILABLE_INTEGRATIONS

        assert "always_on" not in AVAILABLE_INTEGRATIONS["crm_lite"]

    def test_no_credential_integrations_report_configured(self, registry_dir):
        # auth_type "none" integrations have nothing to set up, and the enable
        # endpoint requires configured — so they must always report configured.
        from integrations.registry import list_integrations

        entries = {e["id"]: e for e in list_integrations()}
        assert entries["crm_lite"]["configured"] is True
        assert entries["crm_lite"]["enabled"] is False
        assert entries["qb_csv"]["configured"] is True

    def test_preexisting_enabled_state_honored(self, registry_dir):
        from integrations.registry import is_enabled, list_integrations, save_credentials

        save_credentials("crm_lite", {"enabled": True})
        assert is_enabled("crm_lite") is True
        entries = {e["id"]: e for e in list_integrations()}
        assert entries["crm_lite"]["enabled"] is True

    def test_crm_can_be_disabled(self, registry_dir):
        from integrations.registry import disable, is_enabled, save_credentials

        save_credentials("crm_lite", {"enabled": True})
        disable("crm_lite")
        assert is_enabled("crm_lite") is False
