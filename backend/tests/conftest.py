"""Shared test fixtures for the Chatty backend test suite."""

import json

import pytest


@pytest.fixture
def tmp_data_dir(tmp_path):
    """Create a minimal data directory tree for tests."""
    data = tmp_path / "data"
    (data / "agents" / "test-agent" / "context").mkdir(parents=True)
    (data / "integrations").mkdir(parents=True)
    return data


@pytest.fixture
def agent_db(monkeypatch, tmp_path):
    """Fresh agent registry DB using production schema."""
    import agents.db as db_mod

    db_file = tmp_path / "agents.db"
    monkeypatch.setattr(db_mod, "DB_PATH", db_file)
    monkeypatch.setattr(db_mod, "DATA_DIR", tmp_path)

    # Patch DATA_DIR in modules that import their own copy
    try:
        import agents.engine as engine_mod
        monkeypatch.setattr(engine_mod, "DATA_DIR", tmp_path)
    except ImportError:
        pass

    db_mod._setup_connection()
    yield db_mod._connection

    db_mod.close_db()


@pytest.fixture
def encryption_env(monkeypatch, tmp_path):
    """Isolate encryption: deterministic key, no keychain or file leakage."""
    from cryptography.fernet import Fernet
    from core.encryption import EncryptionKeyManager

    key = Fernet.generate_key()
    monkeypatch.setenv("ENCRYPTION_KEY", key.decode())
    monkeypatch.setattr(
        "core.encryption.KEY_FILE_PATH", tmp_path / ".encryption-key"
    )
    EncryptionKeyManager._cached_key = None
    yield key
    EncryptionKeyManager._cached_key = None


async def collect_events(async_gen):
    """Drain a chat() SSE generator into a list of parsed event dicts."""
    events = []
    async for line in async_gen:
        if line.startswith("data: "):
            try:
                events.append(json.loads(line[6:].strip()))
            except json.JSONDecodeError:
                pass
    return events
