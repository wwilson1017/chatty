"""HTTP tests for the provider tier endpoints (GET/PUT /api/providers/tiers).

Uses the shared authenticated `client` fixture (FastAPI TestClient) from conftest.
"""

import pytest


class _FakeProvider:
    """Stands in for a real provider so validation doesn't hit the network."""
    async def list_models(self):
        return ["claude-opus-4-8", "claude-sonnet-4-6", "claude-haiku-4-5"]


@pytest.fixture
def tiers_isolated(monkeypatch, tmp_path):
    """Point the tier store at a temp file and stub provider instantiation."""
    import core.providers as providers_pkg
    from core.providers import model_tiers

    monkeypatch.setattr(model_tiers, "TIERS_PATH", tmp_path / "model-tiers.json")
    monkeypatch.setattr(providers_pkg, "get_ai_provider", lambda **kw: _FakeProvider())
    yield


# ── Validation (no provider instantiation needed) ──────────────────────────────

def test_put_tiers_unknown_provider_400(client):
    r = client.put("/api/providers/tiers", json={"provider": "zzz", "models": {"top": "x"}})
    assert r.status_code == 400


def test_put_tiers_bad_tier_key_400(client):
    r = client.put("/api/providers/tiers", json={"provider": "anthropic", "models": {"ultra": "claude-opus-4-8"}})
    assert r.status_code == 400


# ── Validation against the live (stubbed) model list ───────────────────────────

def test_put_tiers_model_not_available_400(client, tiers_isolated):
    r = client.put("/api/providers/tiers", json={"provider": "anthropic", "models": {"top": "gpt-4-not-anthropic"}})
    assert r.status_code == 400


def test_put_tiers_model_id_too_long_400(client, tiers_isolated):
    r = client.put("/api/providers/tiers", json={"provider": "anthropic", "models": {"top": "x" * 201}})
    assert r.status_code == 400


def test_put_tiers_happy_path_persists_and_reflects(client, tiers_isolated):
    r = client.put("/api/providers/tiers", json={"provider": "anthropic", "models": {"top": "claude-sonnet-4-6"}})
    assert r.status_code == 200
    assert r.json()["tier_models"]["top"] == "claude-sonnet-4-6"

    # GET reflects the override (cheap, store-only).
    g = client.get("/api/providers/tiers")
    assert g.status_code == 200
    assert g.json()["tier_models"]["anthropic"]["top"] == "claude-sonnet-4-6"
    # Labels are always non-empty.
    assert all(g.json()["tier_labels"]["anthropic"].values())


def test_put_tiers_empty_clears_override(client, tiers_isolated):
    client.put("/api/providers/tiers", json={"provider": "anthropic", "models": {"top": "claude-sonnet-4-6"}})
    # Empty string clears the override → resolves back to inferred/hardcoded top.
    r = client.put("/api/providers/tiers", json={"provider": "anthropic", "models": {"top": ""}})
    assert r.status_code == 200
    assert r.json()["tier_models"]["top"] == "claude-opus-4-8"


def test_put_tiers_requires_auth(anon_client):
    r = anon_client.put("/api/providers/tiers", json={"provider": "anthropic", "models": {"top": "claude-opus-4-8"}})
    assert r.status_code in (401, 403)
