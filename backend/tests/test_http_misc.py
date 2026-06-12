"""HTTP tests: health, login, usage, and the unauthenticated-route sweep."""

import re

import pytest

# Imported at collection time because _protected_routes() feeds parametrize.
# main is import-side-effect-free (all init lives in lifespan) — test_health
# asserts that holds.
import main


# ── Health ────────────────────────────────────────────────────────────────────

def test_health(anon_client):
    resp = anon_client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    # Lifespan never ran, so no DB statuses were recorded — this is the
    # sentinel that the HTTP tier runs without startup side effects.
    assert body["databases"] == {}


def test_health_live(anon_client):
    resp = anon_client.get("/api/health/live")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


# ── Login ─────────────────────────────────────────────────────────────────────

@pytest.fixture
def login_env(monkeypatch):
    """Known password, no 2FA, fresh rate-limiter state."""
    import core.auth as auth_mod
    from core.config import settings

    monkeypatch.setattr(settings.auth, "password", "test-password")
    monkeypatch.setattr("core.auth_2fa.is_2fa_enabled", lambda: False)
    auth_mod._login_attempts.clear()
    yield
    auth_mod._login_attempts.clear()


def test_login_wrong_password(anon_client, login_env):
    resp = anon_client.post("/api/login", json={"password": "nope"})
    assert resp.status_code == 401


def test_login_correct_password_token_round_trip(anon_client, login_env):
    resp = anon_client.post("/api/login", json={"password": "test-password"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["token_type"] == "bearer"

    me = anon_client.get(
        "/api/me", headers={"Authorization": f"Bearer {body['access_token']}"}
    )
    assert me.status_code == 200
    assert me.json() == {"sub": "user", "role": "admin"}


def test_login_rate_limited(anon_client, login_env):
    for _ in range(10):
        assert anon_client.post("/api/login", json={"password": "nope"}).status_code == 401
    resp = anon_client.post("/api/login", json={"password": "nope"})
    assert resp.status_code == 429


# ── Usage ─────────────────────────────────────────────────────────────────────

def test_usage_summary_empty(client):
    resp = client.get("/api/usage/summary")
    assert resp.status_code == 200
    totals = resp.json()["totals"]
    assert totals["events"] == 0
    assert totals["input_tokens"] == 0


def test_usage_summary_aggregates(client):
    from core.agents.activity_log import log_chat_event

    log_chat_event("helper", model_used="mock-model",
                   input_tokens=100, output_tokens=50)
    resp = client.get("/api/usage/summary", params={"days": 7})
    assert resp.status_code == 200
    totals = resp.json()["totals"]
    assert totals["events"] == 1
    assert totals["input_tokens"] == 100
    assert totals["output_tokens"] == 50


def test_usage_summary_bad_tz_falls_back(client):
    resp = client.get("/api/usage/summary", params={"tz": "Not/AZone"})
    assert resp.status_code == 200
    assert resp.json()["timezone"] == "UTC"


# ── Unauthenticated-route sweep ───────────────────────────────────────────────

# Routes that are intentionally reachable without a JWT.
SWEEP_ALLOWLIST = {
    ("POST", "/api/login"),                     # password login
    ("POST", "/api/login/verify-2fa"),          # pending-token + TOTP auth
    ("GET", "/api/health"),                     # public health
    ("GET", "/api/health/live"),                # liveness probe
    ("POST", "/api/telegram/webhook/{agent_slug}"),  # secret-token header auth; invalid secrets get 200 by design (stops Telegram retries)
    ("GET", "/api/oauth/callback"),             # OAuth provider redirect — no JWT possible
    ("GET", "/api/branding/logo"),              # served in <img>/CSS tags
    ("POST", "/api/messaging/whatsapp/webhook"),  # Baileys sidecar, X-Api-Key auth
    ("POST", "/api/integrations/paperclip/heartbeat"),  # X-Webhook-Secret auth
}


def _protected_routes():
    from fastapi.routing import APIRoute

    cases = []
    for route in main.app.routes:
        # Only APIRoutes are swept; Mount sub-apps (e.g. static files) are
        # intentionally excluded and must be audited manually if ever added.
        if not isinstance(route, APIRoute):
            continue
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            if (method, route.path) in SWEEP_ALLOWLIST:
                continue
            cases.append((method, route.path))
    return cases


@pytest.mark.parametrize("method,path", _protected_routes())
def test_route_rejects_unauthenticated(anon_client, method, path):
    """Every route outside the allowlist must 401 without a token.

    get_current_user raises 401 during dependency resolution, before body
    or path-param validation, so no payload is needed.
    """
    url = re.sub(r"\{[^}]+\}", "x", path)
    resp = anon_client.request(method, url)
    assert resp.status_code == 401, f"{method} {path} returned {resp.status_code}"


def test_no_sub_app_mounts_under_api():
    """The sweep can't see inside Mount sub-apps, so none may live under /api."""
    from starlette.routing import Mount

    mounts = [r for r in main.app.routes if isinstance(r, Mount)]
    assert not [m.path for m in mounts if m.path.startswith("/api")]


# ── Webhook auth (allowlisted non-JWT routes) ─────────────────────────────────

def test_paperclip_heartbeat_closed_when_unconfigured(anon_client):
    # No webhook secret in the (tmp, empty) registry → closed by default.
    resp = anon_client.post(
        "/api/integrations/paperclip/heartbeat", json={"agentId": "x"}
    )
    assert resp.status_code == 403


def test_whatsapp_webhook_rejects_bad_api_key(anon_client, monkeypatch):
    from core.config import settings

    monkeypatch.setattr(settings.whatsapp, "webhook_secret", "wh-secret")
    missing = anon_client.post("/api/messaging/whatsapp/webhook", json={})
    assert missing.status_code == 401
    wrong = anon_client.post(
        "/api/messaging/whatsapp/webhook", json={}, headers={"X-Api-Key": "nope"}
    )
    assert wrong.status_code == 401
