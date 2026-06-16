"""Unit tests for the printed-CLI install store (records + encrypted creds)."""

import json

import pytest

from integrations.printing_press import paths, store


@pytest.fixture
def clis_dir(monkeypatch, tmp_path):
    """Redirect the install store + staged sources to temp dirs."""
    d = tmp_path / "clis"
    monkeypatch.setattr(paths, "CLIS_DIR", d)
    monkeypatch.setattr(paths, "SRC_DIR", tmp_path / "src")
    return d


def _install(**kw):
    base = dict(slug="openalex", category="other", ref="main", sha="a" * 40)
    base.update(kw)
    return store.Install(**base)


def test_install_round_trip(clis_dir):
    rec = _install(api_name="openalex", tool_count=43, build_status=store.BUILD_READY,
                   binary="/x/bin/openalex-pp-cli")
    store.save_install(rec)
    got = store.get_install("openalex")
    assert got is not None
    assert got.slug == "openalex" and got.sha == "a" * 40
    assert got.tool_count == 43 and got.build_status == store.BUILD_READY
    assert got.installed_at and got.updated_at  # stamped on save


def test_get_install_missing_returns_none(clis_dir):
    assert store.get_install("nope") is None


def test_list_installed(clis_dir):
    store.save_install(_install(slug="openalex"))
    store.save_install(_install(slug="kit", category="marketing"))
    slugs = {r.slug for r in store.list_installed()}
    assert slugs == {"openalex", "kit"}


def test_is_enabled_requires_ready_and_enabled(clis_dir):
    store.save_install(_install(enabled=True, build_status=store.BUILD_READY))
    assert store.is_enabled("openalex") is True

    store.update_install("openalex", enabled=False)
    assert store.is_enabled("openalex") is False

    store.update_install("openalex", enabled=True, build_status=store.BUILD_BUILDING)
    assert store.is_enabled("openalex") is False


def test_update_install_patches_fields(clis_dir):
    store.save_install(_install(build_status=store.BUILD_PENDING))
    store.update_install("openalex", build_status=store.BUILD_ERROR, build_error="nope")
    got = store.get_install("openalex")
    assert got.build_status == store.BUILD_ERROR and got.build_error == "nope"


def test_invalid_tool_mode_falls_back_to_normal(clis_dir):
    store.save_install(_install(tool_mode="banana"))
    assert store.get_install("openalex").tool_mode == store.TOOL_MODE_NORMAL


def test_manifest_round_trip(clis_dir):
    store.save_install(_install())
    manifest = {"api_name": "openalex", "tools": [{"name": "authors_list"}]}
    store.save_manifest("openalex", manifest)
    assert store.get_manifest("openalex") == manifest


def test_remove_install_deletes_everything(clis_dir):
    store.save_install(_install())
    store.save_cli_credentials("openalex", {"OPENALEX_API_KEY": "k"})
    assert store.remove_install("openalex") is True
    assert store.get_install("openalex") is None
    assert not paths.cli_dir("openalex").exists()


def test_remove_install_prunes_staged_sources(clis_dir):
    store.save_install(_install())
    staged = paths.staged_src_dir("openalex", "b" * 40)
    staged.mkdir(parents=True)
    (staged / "go.mod").write_text("module x")
    assert store.remove_install("openalex") is True
    assert not staged.exists()


# ── credentials (encrypted at rest) ───────────────────────────────────────

def test_credentials_round_trip(clis_dir, encryption_env):
    store.save_cli_credentials("openalex", {"OPENALEX_API_KEY": "secret-123"})
    assert store.has_credentials("openalex") is True
    assert store.get_cli_credentials("openalex") == {"OPENALEX_API_KEY": "secret-123"}


def test_credentials_encrypted_on_disk(clis_dir, encryption_env):
    store.save_cli_credentials("openalex", {"OPENALEX_API_KEY": "secret-123"})
    raw = (paths.cli_dir("openalex") / store.CREDS_FILENAME).read_text()
    on_disk = json.loads(raw)
    # The arbitrary env-var name is covered even though it isn't in SENSITIVE_FIELDS.
    assert on_disk["env"]["OPENALEX_API_KEY"].startswith("enc:v1:")
    assert "secret-123" not in raw


def test_empty_credential_values_dropped(clis_dir, encryption_env):
    store.save_cli_credentials("openalex", {"A": "x", "B": ""})
    assert store.get_cli_credentials("openalex") == {"A": "x"}


def test_delete_credentials(clis_dir, encryption_env):
    store.save_cli_credentials("openalex", {"A": "x"})
    assert store.delete_cli_credentials("openalex") is True
    assert store.has_credentials("openalex") is False
    assert store.get_cli_credentials("openalex") == {}
