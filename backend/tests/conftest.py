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


def parse_sse(response):
    """Parse a buffered TestClient SSE response body into event dicts."""
    events = []
    for line in response.text.split("\n"):
        if line.startswith("data: "):
            events.append(json.loads(line[len("data: "):]))
    return events


@pytest.fixture
def http_env(agent_db, encryption_env, monkeypatch, tmp_path):
    """Isolation patches for HTTP tests against main.app (no lifespan).

    Shared by both `client` and `anon_client`: a few routes are intentionally
    non-JWT (WhatsApp webhook, Paperclip heartbeat) and their handlers run
    during the 401 sweep, so even anonymous requests must hit tmp paths.
    """
    import agents.engine as engine_mod
    import agents.router as router_mod
    import branding.storage as branding_storage
    import core.admin_settings as admin_mod
    import core.agents.memory.db as memory_db_mod
    import core.agents.playbooks.service as pb_service
    import core.agents.reminders.db as reminders_db
    import core.agents.shared_context.bootstrap as bootstrap_mod
    import core.providers.credentials as creds_mod
    import integrations.pending_setup as pending_mod
    import integrations.registry as registry_mod

    # agents.router captures DATA_DIR from agents.engine at import time —
    # delete-agent rmtrees DATA_DIR/{slug}, so this must point at tmp.
    monkeypatch.setattr(router_mod, "DATA_DIR", tmp_path)
    # Empty integrations dir: no dev-integration leak, no mkdir of the real dir.
    monkeypatch.setattr(registry_mod, "DATA_DIR", tmp_path / "integrations")
    # Create-agent reads AND deletes pending-setup.json.
    monkeypatch.setattr(pending_mod, "DATA_DIR", tmp_path)
    # Chat route instantiates CredentialStore() — keep it off the real profiles.
    monkeypatch.setattr(creds_mod, "PROFILES_PATH", tmp_path / "auth-profiles.json")
    # Admin settings → defaults (always_power_mode off, injection_scanning flag).
    monkeypatch.setattr(admin_mod, "ADMIN_SETTINGS_FILE", tmp_path / "admin-settings.json")
    monkeypatch.setattr(admin_mod, "_cached_settings", None)
    monkeypatch.setattr(admin_mod, "_cached_mtime", 0.0)
    # Playbook GCS sync no-ops (matches playbook_env in test_playbooks_service.py).
    monkeypatch.setattr(pb_service, "upload_config", lambda *a, **k: None)
    monkeypatch.setattr(pb_service, "delete_config", lambda *a, **k: None)
    # Creating a 2nd agent spawns a shared-knowledge bootstrap thread otherwise.
    monkeypatch.setattr(bootstrap_mod, "should_bootstrap", lambda: False)
    # GET /api/branding/logo is public (the 401 sweep reaches its handler).
    monkeypatch.setattr(branding_storage, "BRANDING_DIR", tmp_path / "branding")
    monkeypatch.setattr(branding_storage, "CONFIG_FILE", tmp_path / "branding" / "config.json")
    monkeypatch.setattr(branding_storage, "LOGO_FILE", tmp_path / "branding" / "logo.png")
    # Reminders DB backs the activity log; chat's completion logging calls
    # get_db() which raises RuntimeError when uninitialized (lifespan never ran).
    monkeypatch.setattr(reminders_db, "DATA_DIR", tmp_path / "reminders")
    monkeypatch.setattr(reminders_db, "DB_PATH", tmp_path / "reminders" / "reminders.db")
    (tmp_path / "reminders").mkdir(exist_ok=True)
    reminders_db.close_db()
    reminders_db._setup_connection()
    # Per-slug caches would hand a previous test's DB to a same-named agent.
    engine_mod._get_initialized_db.cache_clear()
    engine_mod._get_initialized_memory_db.cache_clear()

    try:
        yield
    finally:
        engine_mod.close_all_agent_dbs()
        engine_mod._get_initialized_memory_db.cache_clear()
        # MemoryDB keeps a module-level instance cache with no close() API;
        # close handles so tmp-dir SQLite connections don't leak across tests.
        for inst in memory_db_mod._instances.values():
            if inst._connection is not None:
                inst._connection.close()
        memory_db_mod._instances.clear()
        reminders_db.close_db()


@pytest.fixture
def client(http_env):
    """Authenticated TestClient. No `with` block: lifespan never runs."""
    from fastapi.testclient import TestClient

    import main
    from core.auth import get_current_user

    main.app.dependency_overrides[get_current_user] = lambda: {"sub": "user", "role": "admin"}
    try:
        yield TestClient(main.app)
    finally:
        main.app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture
def anon_client(http_env):
    """Unauthenticated TestClient (same isolation patches, no auth override)."""
    from fastapi.testclient import TestClient

    import main
    from core.auth import get_current_user

    assert get_current_user not in main.app.dependency_overrides
    return TestClient(main.app)
