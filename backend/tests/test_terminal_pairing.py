"""Terminal pairing (`chatty login`): device-code start → web approve → poll
claims a device token once → /token trades it for a JWT; deny, expiry, revoke,
password enrollment and the public endpoints' limits."""

import pytest
from core.auth import create_access_token
from core.terminal import db, router


@pytest.fixture
def tc(anon_client):
    """Real auth throughout: the terminal side has no JWT, the web side has one."""
    router.start_limiter.clear()
    router.poll_limiter.clear()
    anon_client.web = {"Authorization": f"Bearer {create_access_token({'sub': 'user', 'role': 'admin'})}"}
    return anon_client


def _start(c, host="skydiver"):
    r = c.post("/api/terminal/pair/start", json={"host": host, "platform": "Linux"})
    assert r.status_code == 200, r.text
    return r.json()


def _poll(c, device_code):
    r = c.post("/api/terminal/pair/poll", json={"device_code": device_code})
    assert r.status_code == 200, r.text
    return r.json()


def _decide(c, user_code, approve=True, label=""):
    return c.post(f"/api/terminal/pair/{user_code}/decide", headers=c.web,
                  json={"approve": approve, "label": label})


def _expire_all():
    db.get_db().execute("UPDATE pairings SET expires_at = '2000-01-01T00:00:00+00:00'")
    db.get_db().commit()


def _jwt(c, token):
    return c.post("/api/terminal/token", headers={"Authorization": f"Bearer {token}"})


def test_pair_approve_claims_token_once(tc):
    p = _start(tc)
    assert len(p["user_code"]) == 9 and p["user_code"][4] == "-"
    assert _poll(tc, p["device_code"]) == {"status": "pending"}

    # The QR's code arrives however the phone typed it.
    looked = tc.get(f"/api/terminal/pair/{p['user_code'].replace('-', '').lower()}", headers=tc.web)
    assert looked.status_code == 200
    assert looked.json()["host"] == "skydiver" and looked.json()["user_code"] == p["user_code"]

    assert _decide(tc, p["user_code"], label="Will's laptop").status_code == 200
    claimed = _poll(tc, p["device_code"])
    assert claimed["status"] == "approved" and claimed["token"]
    assert _poll(tc, p["device_code"]) == {"status": "expired"}  # single-use

    r = _jwt(tc, claimed["token"])
    assert r.status_code == 200 and r.json()["expires_in"] == 900
    agents = tc.get("/api/agents", headers={"Authorization": f"Bearer {r.json()['access_token']}"})
    assert agents.status_code == 200

    devices = tc.get("/api/terminal/devices", headers=tc.web).json()["devices"]
    assert [d["label"] for d in devices] == ["Will's laptop"]
    assert devices[0]["last_seen_at"]


def test_deny_is_final(tc):
    p = _start(tc)
    assert _decide(tc, p["user_code"], approve=False).status_code == 200
    assert _poll(tc, p["device_code"]) == {"status": "denied"}
    assert _decide(tc, p["user_code"]).status_code == 409


def test_expired_pairing_cannot_be_approved_or_claimed(tc):
    p = _start(tc)
    _expire_all()
    assert tc.get(f"/api/terminal/pair/{p['user_code']}", headers=tc.web).status_code == 404
    assert _decide(tc, p["user_code"]).status_code == 409
    assert _poll(tc, p["device_code"]) == {"status": "expired"}


def test_approved_then_expired_is_not_claimed(tc):
    p = _start(tc)
    assert _decide(tc, p["user_code"]).status_code == 200
    _expire_all()
    assert _poll(tc, p["device_code"]) == {"status": "expired"}
    assert tc.get("/api/terminal/devices", headers=tc.web).json()["devices"] == []


def test_unknown_codes(tc):
    assert tc.get("/api/terminal/pair/ABCD-EFGH", headers=tc.web).status_code == 404
    assert _poll(tc, "not-a-real-code") == {"status": "expired"}


def test_revoke_stops_token_swap(tc):
    p = _start(tc)
    _decide(tc, p["user_code"])
    claimed = _poll(tc, p["device_code"])
    assert tc.delete(f"/api/terminal/devices/{claimed['device_id']}", headers=tc.web).status_code == 200
    assert _jwt(tc, claimed["token"]).status_code == 401
    assert tc.delete(f"/api/terminal/devices/{claimed['device_id']}", headers=tc.web).status_code == 404


def test_password_login_enrolls_a_device(tc):
    r = tc.post("/api/terminal/devices", headers=tc.web, json={"host": "fred", "platform": "Darwin"})
    assert r.status_code == 200
    assert _jwt(tc, r.json()["token"]).status_code == 200
    assert tc.get("/api/terminal/devices", headers=tc.web).json()["devices"][0]["label"] == "fred"


def test_token_needs_a_device_bearer(tc):
    assert tc.post("/api/terminal/token").status_code == 401
    assert _jwt(tc, "garbage").status_code == 401
    # A web JWT is not a device token.
    assert tc.post("/api/terminal/token", headers=tc.web).status_code == 401


def test_start_is_rate_limited_and_capped(tc, monkeypatch):
    for _ in range(10):
        _start(tc)
    assert tc.post("/api/terminal/pair/start", json={}).status_code == 429

    router.start_limiter.clear()
    monkeypatch.setattr(router, "MAX_LIVE_PAIRINGS", 11)
    _start(tc)  # the 11th live pairing
    assert tc.post("/api/terminal/pair/start", json={}).status_code == 429
    _expire_all()
    _start(tc)  # expired rows are swept, freeing the cap
