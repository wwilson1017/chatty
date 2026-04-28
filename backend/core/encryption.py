"""
Chatty — Encryption at rest for credentials.

Encrypts sensitive fields (API keys, OAuth tokens) using Fernet (AES-128-CBC)
before writing to disk. The encryption key is sourced from (in priority order):

1. ENCRYPTION_KEY environment variable  (deployed instances — Railway, etc.)
2. OS keychain via `keyring` library     (local macOS / Windows / Linux)
3. File fallback: data/.encryption-key   (headless Linux, CI, Docker)

Encrypted values are prefixed with "enc:v1:" so plaintext values (pre-migration)
are detected and auto-encrypted on first load.
"""

import logging
import os
from pathlib import Path

from cryptography.fernet import Fernet

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent.parent / "data"
KEY_FILE_PATH = DATA_DIR / ".encryption-key"

KEYCHAIN_SERVICE = "chatty"
KEYCHAIN_ACCOUNT = "encryption-key"

ENCRYPTED_PREFIX = "enc:v1:"

# JSON keys whose values contain secrets and must be encrypted on disk.
# When adding a new integration, add any secret field names here.
SENSITIVE_FIELDS = frozenset({
    "key",              # API keys  (auth-profiles.json)
    "token",            # setup tokens (auth-profiles.json)
    "access",           # OAuth access tokens
    "refresh",          # OAuth refresh tokens
    "api_key",          # integration API keys (odoo, bamboohr)
    "access_token",     # integration OAuth (quickbooks)
    "refresh_token",    # integration OAuth (quickbooks)
    "client_secret",    # integration OAuth (quickbooks)
    "webhook_secret",   # integration webhooks (paperclip)
    "session_cookie",   # session auth (paperclip)
    "password",         # login credentials (paperclip)
})


# ---------------------------------------------------------------------------
# Key management
# ---------------------------------------------------------------------------

class EncryptionKeyManager:
    """Resolve or generate a Fernet encryption key.  Result is cached."""

    _cached_key: bytes | None = None

    @classmethod
    def get_key(cls) -> bytes:
        if cls._cached_key is not None:
            return cls._cached_key

        key = cls._try_env() or cls._try_keychain() or cls._try_file()
        if not key:
            key = cls._generate_and_store()

        cls._cached_key = key
        return key

    @classmethod
    def reset_cache(cls) -> None:
        """Clear the cached key (useful for tests)."""
        cls._cached_key = None

    # -- sources -------------------------------------------------------------

    @classmethod
    def _try_env(cls) -> bytes | None:
        raw = os.environ.get("ENCRYPTION_KEY")
        if not raw:
            return None
        try:
            key = raw.encode()
            Fernet(key)  # validate
            logger.info("Using encryption key from ENCRYPTION_KEY env var")
            return key
        except Exception:
            logger.warning("ENCRYPTION_KEY env var is not a valid Fernet key, ignoring")
            return None

    @classmethod
    def _try_keychain(cls) -> bytes | None:
        try:
            import keyring
            stored = keyring.get_password(KEYCHAIN_SERVICE, KEYCHAIN_ACCOUNT)
            if stored:
                key = stored.encode()
                Fernet(key)  # validate
                logger.info("Using encryption key from OS keychain")
                return key
        except Exception as exc:
            logger.debug("Keychain not available: %s", exc)
        return None

    @classmethod
    def _try_file(cls) -> bytes | None:
        if not KEY_FILE_PATH.exists():
            return None
        try:
            key = KEY_FILE_PATH.read_text(encoding="utf-8").strip().encode()
            Fernet(key)  # validate
            logger.info("Using encryption key from file: %s", KEY_FILE_PATH)
            return key
        except Exception:
            logger.warning("Key file exists but is invalid, will regenerate")
            return None

    # -- generation ----------------------------------------------------------

    @classmethod
    def _generate_and_store(cls) -> bytes:
        key = Fernet.generate_key()

        # Try keychain first
        stored_in_keychain = False
        try:
            import keyring
            keyring.set_password(KEYCHAIN_SERVICE, KEYCHAIN_ACCOUNT, key.decode())
            stored_in_keychain = True
            logger.info("Generated new encryption key, stored in OS keychain")
        except Exception as exc:
            logger.debug("Cannot store in keychain: %s", exc)

        if not stored_in_keychain:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            KEY_FILE_PATH.write_text(key.decode(), encoding="utf-8")
            if os.name != "nt":
                KEY_FILE_PATH.chmod(0o600)
            else:
                logger.warning(
                    "Key file %s written with default ACLs — "
                    "restrict access manually on shared machines",
                    KEY_FILE_PATH,
                )
            logger.info(
                "Generated new encryption key, stored in file: %s", KEY_FILE_PATH
            )

        return key


# ---------------------------------------------------------------------------
# Value-level encrypt / decrypt
# ---------------------------------------------------------------------------

def encrypt_value(plaintext: str) -> str:
    """Encrypt a single string value → ``enc:v1:<fernet_token>``."""
    if not plaintext or plaintext.startswith(ENCRYPTED_PREFIX):
        return plaintext  # empty or already encrypted
    key = EncryptionKeyManager.get_key()
    token = Fernet(key).encrypt(plaintext.encode()).decode()
    return f"{ENCRYPTED_PREFIX}{token}"


def decrypt_value(stored: str) -> str:
    """Decrypt a value.  Returns ``""`` on failure (tamper / wrong key).

    Plaintext values (no ``enc:v1:`` prefix) pass through unchanged — this
    provides backwards compatibility during migration.
    """
    if not stored or not stored.startswith(ENCRYPTED_PREFIX):
        return stored  # plaintext pass-through
    token = stored[len(ENCRYPTED_PREFIX):]
    try:
        key = EncryptionKeyManager.get_key()
        return Fernet(key).decrypt(token.encode()).decode()
    except Exception as exc:
        logger.warning("Failed to decrypt value (tampered or wrong key): %s", exc)
        return ""


# ---------------------------------------------------------------------------
# Dict-level helpers  (recursive for nested profile dicts)
# ---------------------------------------------------------------------------

def encrypt_dict(data: dict) -> dict:
    """Return a copy with sensitive string fields encrypted (recurses into nested dicts)."""
    result = {}
    for k, v in data.items():
        if k in SENSITIVE_FIELDS and isinstance(v, str):
            result[k] = encrypt_value(v)
        elif isinstance(v, dict):
            result[k] = encrypt_dict(v)
        else:
            result[k] = v
    return result


def decrypt_dict(data: dict) -> dict:
    """Return a copy with sensitive string fields decrypted (recurses into nested dicts)."""
    result = {}
    for k, v in data.items():
        if k in SENSITIVE_FIELDS and isinstance(v, str):
            result[k] = decrypt_value(v)
        elif isinstance(v, dict):
            result[k] = decrypt_dict(v)
        else:
            result[k] = v
    return result


def needs_migration(data: dict) -> bool:
    """Return True if any sensitive field is still plaintext (not encrypted)."""
    for k, v in data.items():
        if k in SENSITIVE_FIELDS and isinstance(v, str) and v and not v.startswith(ENCRYPTED_PREFIX):
            return True
        if isinstance(v, dict) and needs_migration(v):
            return True
    return False
