"""Tests for core.encryption — keychain-backed credential encryption."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from cryptography.fernet import Fernet

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Generate a stable test key (never used outside tests)
TEST_KEY = Fernet.generate_key()


@pytest.fixture(autouse=True)
def _reset_key_cache():
    """Reset the cached encryption key between every test."""
    from core.encryption import EncryptionKeyManager
    EncryptionKeyManager.reset_cache()
    yield
    EncryptionKeyManager.reset_cache()


@pytest.fixture()
def env_key(monkeypatch):
    """Set ENCRYPTION_KEY env var to TEST_KEY for the duration of a test."""
    monkeypatch.setenv("ENCRYPTION_KEY", TEST_KEY.decode())
    return TEST_KEY


@pytest.fixture()
def no_env_key(monkeypatch):
    """Ensure ENCRYPTION_KEY is not set."""
    monkeypatch.delenv("ENCRYPTION_KEY", raising=False)


# ---------------------------------------------------------------------------
# encrypt_value / decrypt_value
# ---------------------------------------------------------------------------

class TestEncryptDecryptValue:
    def test_roundtrip(self, env_key):
        from core.encryption import decrypt_value, encrypt_value

        original = "sk-ant-api03-secret-key"
        encrypted = encrypt_value(original)
        assert encrypted.startswith("enc:v1:")
        assert encrypted != original
        assert decrypt_value(encrypted) == original

    def test_plaintext_passthrough(self, env_key):
        from core.encryption import decrypt_value

        # Pre-migration: no prefix → return as-is
        assert decrypt_value("sk-ant-plain") == "sk-ant-plain"

    def test_empty_string_noop(self, env_key):
        from core.encryption import decrypt_value, encrypt_value

        assert encrypt_value("") == ""
        assert decrypt_value("") == ""

    def test_already_encrypted_idempotent(self, env_key):
        from core.encryption import encrypt_value

        first = encrypt_value("my-secret")
        second = encrypt_value(first)
        assert first == second  # no double-encryption

    def test_tampered_ciphertext_returns_empty(self, env_key):
        from core.encryption import decrypt_value, encrypt_value

        encrypted = encrypt_value("real-secret")
        # Corrupt a byte in the Fernet token portion
        tampered = encrypted[:20] + "X" + encrypted[21:]
        assert decrypt_value(tampered) == ""

    def test_wrong_key_returns_empty(self, env_key):
        from core.encryption import decrypt_value, encrypt_value

        encrypted = encrypt_value("my-secret")

        # Switch to a different key
        from core.encryption import EncryptionKeyManager
        EncryptionKeyManager.reset_cache()
        other_key = Fernet.generate_key()
        EncryptionKeyManager._cached_key = other_key

        assert decrypt_value(encrypted) == ""


# ---------------------------------------------------------------------------
# encrypt_dict / decrypt_dict
# ---------------------------------------------------------------------------

class TestDictHelpers:
    def test_only_sensitive_fields_encrypted(self, env_key):
        from core.encryption import ENCRYPTED_PREFIX, encrypt_dict

        data = {
            "type": "api_key",
            "key": "sk-ant-secret",
            "active_provider": "anthropic",
        }
        result = encrypt_dict(data)
        assert result["type"] == "api_key"  # unchanged
        assert result["active_provider"] == "anthropic"  # unchanged
        assert result["key"].startswith(ENCRYPTED_PREFIX)

    def test_nested_dict_recursion(self, env_key):
        from core.encryption import ENCRYPTED_PREFIX, decrypt_dict, encrypt_dict

        data = {
            "active_provider": "anthropic",
            "profiles": {
                "anthropic:default": {"type": "api_key", "key": "sk-ant-xxx"},
                "google:default": {
                    "type": "oauth",
                    "access": "ya29.token",
                    "refresh": "1//refresh",
                    "expires": 9999999999,
                },
            },
        }
        encrypted = encrypt_dict(data)

        # Top-level metadata untouched
        assert encrypted["active_provider"] == "anthropic"
        # Nested sensitive fields encrypted
        assert encrypted["profiles"]["anthropic:default"]["key"].startswith(ENCRYPTED_PREFIX)
        assert encrypted["profiles"]["google:default"]["access"].startswith(ENCRYPTED_PREFIX)
        assert encrypted["profiles"]["google:default"]["refresh"].startswith(ENCRYPTED_PREFIX)
        # Non-sensitive nested fields untouched
        assert encrypted["profiles"]["anthropic:default"]["type"] == "api_key"
        assert encrypted["profiles"]["google:default"]["expires"] == 9999999999

        # Roundtrip
        decrypted = decrypt_dict(encrypted)
        assert decrypted == data

    def test_integration_credentials(self, env_key):
        from core.encryption import ENCRYPTED_PREFIX, decrypt_dict, encrypt_dict

        data = {
            "url": "https://myodoo.com",
            "database": "prod",
            "username": "admin",
            "api_key": "odoo-secret-key",
            "enabled": True,
            "version": "17.0",
        }
        encrypted = encrypt_dict(data)
        assert encrypted["api_key"].startswith(ENCRYPTED_PREFIX)
        assert encrypted["url"] == "https://myodoo.com"
        assert encrypted["enabled"] is True

        decrypted = decrypt_dict(encrypted)
        assert decrypted == data


# ---------------------------------------------------------------------------
# needs_migration
# ---------------------------------------------------------------------------

class TestNeedsMigration:
    def test_plaintext_detected(self, env_key):
        from core.encryption import needs_migration

        data = {
            "profiles": {
                "anthropic:default": {"type": "api_key", "key": "sk-ant-plain"},
            }
        }
        assert needs_migration(data) is True

    def test_all_encrypted(self, env_key):
        from core.encryption import encrypt_dict, needs_migration

        data = {
            "profiles": {
                "anthropic:default": {"type": "api_key", "key": "sk-ant-plain"},
            }
        }
        encrypted = encrypt_dict(data)
        assert needs_migration(encrypted) is False

    def test_empty_values_not_flagged(self, env_key):
        from core.encryption import needs_migration

        data = {"profiles": {"anthropic:default": {"type": "api_key", "key": ""}}}
        assert needs_migration(data) is False

    def test_no_sensitive_fields(self, env_key):
        from core.encryption import needs_migration

        data = {"active_provider": "anthropic", "active_model": "claude-opus-4-6"}
        assert needs_migration(data) is False


# ---------------------------------------------------------------------------
# EncryptionKeyManager
# ---------------------------------------------------------------------------

class TestKeyManager:
    def test_key_from_env_var(self, monkeypatch):
        from core.encryption import EncryptionKeyManager

        test_key = Fernet.generate_key()
        monkeypatch.setenv("ENCRYPTION_KEY", test_key.decode())
        assert EncryptionKeyManager.get_key() == test_key

    def test_invalid_env_var_skipped(self, monkeypatch):
        from core.encryption import EncryptionKeyManager

        monkeypatch.setenv("ENCRYPTION_KEY", "not-a-valid-fernet-key")
        # Should not raise — falls through to other sources
        with patch.object(EncryptionKeyManager, "_try_keychain", return_value=None), \
             patch.object(EncryptionKeyManager, "_try_file", return_value=None), \
             patch.object(EncryptionKeyManager, "_generate_and_store", return_value=Fernet.generate_key()):
            key = EncryptionKeyManager.get_key()
            assert key is not None

    def test_key_from_keychain(self, no_env_key):
        from core.encryption import EncryptionKeyManager

        test_key = Fernet.generate_key()
        mock_keyring = MagicMock()
        mock_keyring.get_password.return_value = test_key.decode()

        with patch.dict("sys.modules", {"keyring": mock_keyring}):
            EncryptionKeyManager.reset_cache()
            result = EncryptionKeyManager._try_keychain()
            assert result == test_key

    def test_key_from_file(self, no_env_key, tmp_path, monkeypatch):
        from core import encryption
        from core.encryption import EncryptionKeyManager

        test_key = Fernet.generate_key()
        key_file = tmp_path / ".encryption-key"
        key_file.write_text(test_key.decode())

        monkeypatch.setattr(encryption, "KEY_FILE_PATH", key_file)
        assert EncryptionKeyManager._try_file() == test_key

    def test_generate_stores_to_keychain(self, no_env_key):
        from core.encryption import EncryptionKeyManager

        mock_keyring = MagicMock()
        mock_keyring.set_password = MagicMock()

        with patch.dict("sys.modules", {"keyring": mock_keyring}):
            key = EncryptionKeyManager._generate_and_store()
            assert key is not None
            mock_keyring.set_password.assert_called_once()

    def test_generate_falls_back_to_file(self, no_env_key, tmp_path, monkeypatch):
        from core import encryption
        from core.encryption import EncryptionKeyManager

        key_file = tmp_path / ".encryption-key"
        data_dir = tmp_path
        monkeypatch.setattr(encryption, "KEY_FILE_PATH", key_file)
        monkeypatch.setattr(encryption, "DATA_DIR", data_dir)

        # Make keyring unavailable
        with patch.dict("sys.modules", {"keyring": None}):
            key = EncryptionKeyManager._generate_and_store()

        assert key is not None
        assert key_file.exists()
        assert key_file.read_text().encode() == key

    def test_key_is_cached(self, env_key):
        from core.encryption import EncryptionKeyManager

        key1 = EncryptionKeyManager.get_key()
        key2 = EncryptionKeyManager.get_key()
        assert key1 is key2  # same object, not just equal


# ---------------------------------------------------------------------------
# CredentialStore integration
# ---------------------------------------------------------------------------

class TestCredentialStoreIntegration:
    @pytest.fixture()
    def store_env(self, tmp_path, monkeypatch, env_key):
        """Set up a temporary data dir and return a CredentialStore factory."""
        from core import encryption
        from core.providers import credentials

        data_dir = tmp_path / "data"
        data_dir.mkdir()
        profiles_path = data_dir / "auth-profiles.json"

        monkeypatch.setattr(credentials, "DATA_DIR", data_dir)
        monkeypatch.setattr(credentials, "PROFILES_PATH", profiles_path)
        monkeypatch.setattr(encryption, "DATA_DIR", data_dir)

        return {"data_dir": data_dir, "profiles_path": profiles_path}

    def test_save_encrypts_on_disk(self, store_env):
        from core.encryption import ENCRYPTED_PREFIX
        from core.providers.credentials import CredentialStore

        store = CredentialStore()
        store.set_api_key("anthropic", "sk-ant-my-secret-key", "claude-opus-4-6")

        # Read raw file — key should be encrypted
        raw = json.loads(store_env["profiles_path"].read_text())
        raw_key = raw["profiles"]["anthropic:default"]["key"]
        assert raw_key.startswith(ENCRYPTED_PREFIX)

    def test_load_decrypts_in_memory(self, store_env):
        from core.providers.credentials import CredentialStore

        store = CredentialStore()
        store.set_api_key("anthropic", "sk-ant-my-secret-key", "claude-opus-4-6")

        # Reload from disk
        store2 = CredentialStore()
        _, profile = store2.get_active_profile()
        assert profile["key"] == "sk-ant-my-secret-key"

    def test_auto_migration(self, store_env):
        from core.encryption import ENCRYPTED_PREFIX
        from core.providers.credentials import CredentialStore

        # Write plaintext directly (simulating pre-encryption data)
        plaintext_data = {
            "active_provider": "anthropic",
            "active_model": "claude-opus-4-6",
            "profiles": {
                "anthropic:default": {"type": "api_key", "key": "sk-ant-plain-key"}
            },
        }
        store_env["profiles_path"].write_text(json.dumps(plaintext_data))

        # Loading should trigger migration
        store = CredentialStore()
        _, profile = store.get_active_profile()
        assert profile["key"] == "sk-ant-plain-key"  # decrypted in memory

        # File on disk should now be encrypted
        raw = json.loads(store_env["profiles_path"].read_text())
        assert raw["profiles"]["anthropic:default"]["key"].startswith(ENCRYPTED_PREFIX)

    def test_corrupted_credential_treated_as_missing(self, store_env):
        from core.encryption import ENCRYPTED_PREFIX
        from core.providers.credentials import CredentialStore

        # Write a corrupted encrypted value
        data = {
            "active_provider": "anthropic",
            "active_model": "claude-opus-4-6",
            "profiles": {
                "anthropic:default": {
                    "type": "api_key",
                    "key": f"{ENCRYPTED_PREFIX}corrupted-garbage-token",
                }
            },
        }
        store_env["profiles_path"].write_text(json.dumps(data))

        store = CredentialStore()
        _, profile = store.get_active_profile()
        assert profile["key"] == ""  # treated as missing

    def test_to_dict_still_works(self, store_env):
        from core.providers.credentials import CredentialStore

        store = CredentialStore()
        store.set_api_key("anthropic", "sk-ant-my-secret-key-1234", "claude-opus-4-6")

        summary = store.to_dict()
        assert summary["profiles"]["anthropic"]["configured"] is True
        assert summary["profiles"]["anthropic"]["key_preview"] == "...1234"

    def test_oauth_tokens_encrypted(self, store_env):
        from core.encryption import ENCRYPTED_PREFIX
        from core.providers.credentials import CredentialStore

        store = CredentialStore()
        store.set_oauth_tokens("google", "ya29.access", "1//refresh", 3600)

        raw = json.loads(store_env["profiles_path"].read_text())
        profile = raw["profiles"]["google:default"]
        assert profile["access"].startswith(ENCRYPTED_PREFIX)
        assert profile["refresh"].startswith(ENCRYPTED_PREFIX)
        assert isinstance(profile["expires"], int)  # not encrypted


# ---------------------------------------------------------------------------
# Integration registry integration
# ---------------------------------------------------------------------------

class TestRegistryIntegration:
    @pytest.fixture()
    def registry_env(self, tmp_path, monkeypatch, env_key):
        from core import encryption
        from integrations import registry

        data_dir = tmp_path / "integrations"
        data_dir.mkdir()
        monkeypatch.setattr(registry, "DATA_DIR", data_dir)
        monkeypatch.setattr(encryption, "DATA_DIR", tmp_path)
        return data_dir

    def test_save_encrypts_get_decrypts(self, registry_env):
        from core.encryption import ENCRYPTED_PREFIX
        from integrations.registry import get_credentials, save_credentials

        creds = {
            "url": "https://myodoo.com",
            "database": "prod",
            "username": "admin",
            "api_key": "odoo-secret",
            "enabled": True,
        }
        save_credentials("odoo", creds)

        # Raw file has encrypted api_key
        raw = json.loads((registry_env / "odoo.json").read_text())
        assert raw["api_key"].startswith(ENCRYPTED_PREFIX)
        assert raw["url"] == "https://myodoo.com"  # not encrypted

        # get_credentials returns decrypted
        loaded = get_credentials("odoo")
        assert loaded["api_key"] == "odoo-secret"

    def test_migration_on_get(self, registry_env):
        from core.encryption import ENCRYPTED_PREFIX
        from integrations.registry import get_credentials

        # Write plaintext directly
        path = registry_env / "bamboohr.json"
        path.write_text(json.dumps({
            "subdomain": "myco",
            "api_key": "bamboo-plain-key",
            "enabled": True,
        }))

        loaded = get_credentials("bamboohr")
        assert loaded["api_key"] == "bamboo-plain-key"

        # File should now be encrypted
        raw = json.loads(path.read_text())
        assert raw["api_key"].startswith(ENCRYPTED_PREFIX)

    def test_is_enabled_works(self, registry_env):
        from integrations.registry import is_enabled, save_credentials

        save_credentials("odoo", {"api_key": "secret", "enabled": True})
        assert is_enabled("odoo") is True

        save_credentials("odoo", {"api_key": "secret", "enabled": False})
        assert is_enabled("odoo") is False
