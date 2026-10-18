"""Computer integration (PR 2): settings discovery, the card's actions, viewer
tickets and the VNC relay — against a fake computer (httpx MockTransport for the
control API, a real `websockets` echo server for the screen stream)."""

import asyncio
import json
import threading
from http import HTTPStatus
from urllib.parse import urlparse

import httpx
import pytest
from fastapi import HTTPException
from starlette.websockets import WebSocketDisconnect
from websockets.sync.server import serve

from integrations.computer import card, client as client_mod, viewer
from integrations.registry import save_credentials


# ── fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def clean_viewer_state():
    viewer._tickets.clear()
    viewer._open.clear()
    yield
    viewer._tickets.clear()
    viewer._open.clear()


class FakeComputer:
    """Control API over MockTransport + a VNC-ish WebSocket echo server on localhost."""

    def __init__(self):
        self.calls: list[tuple[str, str, dict | None]] = []
        self.api_version = "1.0"
        self.busy = False
        self.unreachable = False
        self.idle_minutes = 30
        self.refuse_ws = False  # the computer refuses /vnc before the upgrade (asleep, dead control session)
        self.on_ws_request = None  # hook run while the relay's upstream handshake is in flight
        self.ended_sessions: set[str] = set()
        self.ws_requests: list[tuple[str, str, str]] = []  # (path, authorization, offered subprotocols)

    def handle(self, request: httpx.Request) -> httpx.Response:
        if self.unreachable:
            raise httpx.ConnectError("refused", request=request)
        body = json.loads(request.content) if request.content else None
        self.calls.append((request.method, request.url.path, body))
        assert request.headers["Authorization"] == "Bearer s3cret-s3cret-s3cret-s3cret-s3cret"
        path = request.url.path
        if path == "/health":
            return httpx.Response(200, json={"api_version": self.api_version, "chromium_version": "131.0",
                                             "active_agent": None, "human_in_control": False,
                                             "idle_minutes": self.idle_minutes})
        if path == "/settings":
            self.idle_minutes = body["idle_minutes"]
            return httpx.Response(200, json={"idle_minutes": self.idle_minutes})
        if path == "/control/start":
            if self.busy:
                return httpx.Response(409, json={"error": "busy", "detail": "Someone else has the screen."})
            return httpx.Response(200, json={"control_session_id": "cs-1", "expires_in": 900})
        if path == "/control/end":
            if body["control_session_id"] in self.ended_sessions:
                return httpx.Response(404, json={"error": "no_such_session", "detail": "That control session already ended."})
            self.ended_sessions.add(body["control_session_id"])
            return httpx.Response(200, json={"ended": True})
        if path == "/profiles/tom/sites" and request.method == "GET":
            return httpx.Response(200, json={"sites": [{"domain": "github.com", "cookies": 4}]})
        return httpx.Response(200, json={"ok": True})

    def ws_process_request(self, conn, request):
        if self.on_ws_request:
            self.on_ws_request()
        if self.refuse_ws:
            return conn.respond(HTTPStatus.FORBIDDEN, '{"error": "desktop_stopped"}')
        return None

    def ws_handler(self, conn):
        self.ws_requests.append((conn.request.path, conn.request.headers.get("Authorization", ""),
                                 conn.request.headers.get("Sec-WebSocket-Protocol", "")))
        conn.send(b"RFB 003.008\n")  # a VNC server speaks first
        for msg in conn:
            if msg == b"bye":
                conn.close(1000, "desktop stopped")  # the computer hangs up, with a reason
                return
            conn.send(b"echo:" + (msg if isinstance(msg, bytes) else msg.encode()))


@pytest.fixture
def fake(client, monkeypatch):
    fc = FakeComputer()
    server = serve(fc.ws_handler, "127.0.0.1", 0, process_request=fc.ws_process_request)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.socket.getsockname()[1]
    monkeypatch.setenv("COMPUTER_URL", f"http://127.0.0.1:{port}")
    monkeypatch.setenv("COMPUTER_SECRET", "s3cret-s3cret-s3cret-s3cret-s3cret")
    monkeypatch.setattr(client_mod, "get_client", lambda: client_mod.ComputerClient(
        f"http://127.0.0.1:{port}", "s3cret-s3cret-s3cret-s3cret-s3cret", transport=httpx.MockTransport(fc.handle)))
    monkeypatch.setattr(card, "get_client", client_mod.get_client)
    monkeypatch.setattr(viewer, "get_client", client_mod.get_client)
    fc.client = client
    yield fc
    server.shutdown()


def _enable(**extra):
    save_credentials("computer", {"enabled": True, **extra})


def _ticket(fake, mode="view", agent="tom", **kw):
    r = fake.client.post("/api/computer/viewer-ticket", json={"mode": mode, "agent": agent, **kw})
    assert r.status_code == 200, r.text
    return r.json()["ticket"]


# ── settings discovery ───────────────────────────────────────────────────────

class TestSettings:
    def test_env_wins_then_creds_then_nothing(self, client, monkeypatch):
        from core.config import settings
        monkeypatch.delenv("COMPUTER_URL", raising=False)
        monkeypatch.delenv("COMPUTER_SECRET", raising=False)
        assert not settings.computer.is_configured
        save_credentials("computer", {"url": "http://creds:8080/", "api_key": "k" * 40})
        assert settings.computer.url == "http://creds:8080"
        assert settings.computer.secret == "k" * 40
        assert settings.computer.is_configured
        monkeypatch.setenv("COMPUTER_URL", "http://env:8080/")
        monkeypatch.setenv("COMPUTER_SECRET", "e" * 40)
        assert (settings.computer.url, settings.computer.secret) == ("http://env:8080", "e" * 40)
        # Half an env pair is a misconfiguration, never a mix with the saved pair (the saved secret
        # must not travel to the env-named host, nor an env secret to the saved host).
        monkeypatch.delenv("COMPUTER_SECRET")
        assert not settings.computer.is_configured and (settings.computer.url, settings.computer.secret) == ("", "")
        monkeypatch.delenv("COMPUTER_URL")
        monkeypatch.setenv("COMPUTER_SECRET", "e" * 40)
        assert not settings.computer.is_configured and settings.computer.url == ""

    def test_listed_and_configured_follows_settings(self, client, monkeypatch):
        monkeypatch.delenv("COMPUTER_URL", raising=False)
        monkeypatch.delenv("COMPUTER_SECRET", raising=False)
        entry = next(i for i in client.get("/api/integrations").json()["integrations"] if i["id"] == "computer")
        assert entry["configured"] is False and entry["enabled"] is False
        monkeypatch.setenv("COMPUTER_URL", "http://env:8080")
        monkeypatch.setenv("COMPUTER_SECRET", "e" * 40)
        entry = next(i for i in client.get("/api/integrations").json()["integrations"] if i["id"] == "computer")
        assert entry["configured"] is True

    def test_get_client_refuses_unconfigured(self, client, monkeypatch):
        monkeypatch.delenv("COMPUTER_URL", raising=False)
        monkeypatch.delenv("COMPUTER_SECRET", raising=False)
        with pytest.raises(client_mod.ComputerError) as ei:
            client_mod.get_client()
        assert ei.value.status == 0

    def test_vnc_url(self):
        c = client_mod.ComputerClient("https://computer.railway.internal:8080/", "x")
        assert c.vnc_url("view") == "wss://computer.railway.internal:8080/vnc?mode=view"
        assert c.vnc_url("control", "cs-1") == "wss://computer.railway.internal:8080/vnc?mode=control&control_session_id=cs-1"


# ── card ─────────────────────────────────────────────────────────────────────

class TestCard:
    def test_status_and_enable(self, fake):
        s = fake.client.get("/api/integrations/computer/status").json()
        assert s["configured"] and not s["enabled"] and s["online"] and s["error"] is None
        assert s["health"]["chromium_version"] == "131.0" and s["idle_minutes"] == 30
        assert fake.client.post("/api/integrations/computer/enable").status_code == 200
        assert card.policy_error("tom") is None

    def test_api_version_mismatch_refused(self, fake):
        fake.api_version = "2.0"
        r = fake.client.post("/api/integrations/computer/enable")
        assert r.status_code == 400 and "v2.0" in r.json()["detail"] and "v1.x" in r.json()["detail"]
        s = fake.client.get("/api/integrations/computer/status").json()
        assert s["online"] and "v2.0" in s["error"] and not s["enabled"]
        assert client_mod.api_version_error({"api_version": "1.4.2"}) is None
        assert client_mod.api_version_error({"api_version": 1}) is None
        assert client_mod.api_version_error({}) is not None

    def test_unreachable_refused_without_401(self, fake):
        fake.unreachable = True
        r = fake.client.post("/api/integrations/computer/enable")
        assert r.status_code == 400 and "Can't reach" in r.json()["detail"]
        s = fake.client.get("/api/integrations/computer/status").json()
        assert not s["online"] and "Can't reach" in s["error"]

    def test_computer_401_is_never_forwarded(self, fake):
        # A wrong secret must not log the owner out of Chatty (the frontend treats any 401 as its own).
        fake.handle = lambda req: httpx.Response(401, json={"error": "unauthorized", "detail": "Bad bearer token."})
        r = fake.client.get("/api/integrations/computer/profiles/tom/sites")
        assert r.status_code == 502 and r.json()["detail"] == "Bad bearer token."

    def test_error_code_and_detail_are_both_kept(self, fake):
        fake.handle = lambda req: httpx.Response(409, json={"error": "human_in_control", "detail": "Someone has the screen."})
        with pytest.raises(client_mod.ComputerError) as ei:
            asyncio.run(client_mod.get_client().health())
        assert (ei.value.status, ei.value.code, ei.value.detail) == (409, "human_in_control", "Someone has the screen.")
        fake.handle = lambda req: httpx.Response(422, json={"detail": [{"loc": ["body"], "msg": "bad"}]})
        with pytest.raises(client_mod.ComputerError) as ei:
            asyncio.run(client_mod.get_client().health())
        assert ei.value.code == "" and "bad" in ei.value.detail

    def test_keep_running_passes_through(self, fake):
        r = fake.client.put("/api/integrations/computer/settings", json={"always_on": True})
        assert r.status_code == 200 and r.json()["idle_minutes"] == 0
        assert ("PUT", "/settings", {"idle_minutes": 0}) in fake.calls
        assert fake.client.get("/api/integrations/computer/status").json()["idle_minutes"] == 0
        fake.client.put("/api/integrations/computer/settings", json={"always_on": False})
        assert ("PUT", "/settings", {"idle_minutes": 30}) in fake.calls
        fake.idle_minutes = 0  # the computer's persisted value (e.g. set before a Chatty redeploy) wins over the card's copy
        assert fake.client.get("/api/integrations/computer/status").json()["idle_minutes"] == 0

    def test_sites_sign_out_and_reset(self, fake):
        r = fake.client.get("/api/integrations/computer/profiles/tom/sites")
        assert r.json() == {"sites": [{"domain": "github.com", "cookies": 4}]}
        assert fake.client.delete("/api/integrations/computer/profiles/tom/sites/github.com").status_code == 200
        assert ("DELETE", "/profiles/tom/sites/github.com", None) in fake.calls
        assert fake.client.delete("/api/integrations/computer/profiles/tom").status_code == 200
        assert ("DELETE", "/profiles/tom", None) in fake.calls
        assert fake.client.get("/api/integrations/computer/profiles/Bad_Slug/sites").status_code == 400
        for bad in ("a/../b", "..", ".", "..github.com", "a..b", "github.com."):  # httpx would fold ".." into DELETE /profiles/tom
            with pytest.raises(HTTPException):
                card._check(card.DOMAIN_RE, bad, "domain")
        assert card._check(card.DOMAIN_RE, "accounts.google.com", "domain")
        assert card._check(card.DOMAIN_RE, ".github.com", "domain")  # Chromium's host_key for a domain cookie

    def test_unconfigured_is_a_readable_502_not_a_500(self, client, monkeypatch):
        monkeypatch.delenv("COMPUTER_URL", raising=False)
        monkeypatch.delenv("COMPUTER_SECRET", raising=False)
        for r in (client.put("/api/integrations/computer/settings", json={"always_on": True}),
                  client.get("/api/integrations/computer/profiles/tom/sites"),
                  client.delete("/api/integrations/computer/profiles/tom"),
                  client.post("/api/computer/control/end", json={"control_session_id": "cs-1"})):
            assert r.status_code == 502 and "No computer is configured" in r.json()["detail"], r.text

    def test_agent_exclude_list(self, fake):
        _enable()
        r = fake.client.put("/api/integrations/computer/agents", json={"disabled_agents": ["sam", "sam"]})
        assert r.json()["disabled_agents"] == ["sam"]
        assert card.policy_error("sam") == "The computer is turned off for this agent."
        assert card.policy_error("tom") is None
        fake.client.post("/api/integrations/computer/disable")
        assert card.policy_error("tom") == "The computer is not set up or is turned off."


# ── tickets ──────────────────────────────────────────────────────────────────

class TestTickets:
    def test_single_use_and_binding(self, fake):
        _enable()
        tok = _ticket(fake, mode="control", agent="tom", task_id="t1")
        t = viewer.redeem_ticket(tok)
        assert (t["mode"], t["agent"], t["task_id"], t["reattach"]) == ("control", "tom", "t1", None)
        assert viewer.redeem_ticket(tok) is None
        assert viewer.redeem_ticket("") is None and viewer.redeem_ticket("nope") is None

    def test_expiry(self, fake, monkeypatch):
        now = [1000.0]
        monkeypatch.setattr(viewer.time, "monotonic", lambda: now[0])
        tok = viewer.issue_ticket("view", "tom")
        now[0] += viewer.TICKET_TTL_S + 1
        assert viewer.redeem_ticket(tok) is None
        viewer.issue_ticket("view", "tom")  # issuing prunes the stale one
        assert tok not in viewer._tickets

    def test_policy_checked_at_issue(self, fake):
        r = fake.client.post("/api/computer/viewer-ticket", json={"mode": "view", "agent": "tom"})
        assert r.status_code == 409  # not enabled
        _enable(disabled_agents=["tom"])
        r = fake.client.post("/api/computer/viewer-ticket", json={"mode": "view", "agent": "tom"})
        assert r.status_code == 409 and "this agent" in r.json()["detail"]
        assert fake.client.post("/api/computer/viewer-ticket", json={"mode": "view", "agent": "Bad!"}).status_code == 422


# ── relay ────────────────────────────────────────────────────────────────────

class TestRelay:
    def test_no_or_bad_ticket_refused(self, fake):
        _enable()
        for q in ("", "?ticket=bogus"):
            with pytest.raises(WebSocketDisconnect):
                with fake.client.websocket_connect("/api/computer/vnc" + q):
                    pass
        assert fake.ws_requests == []

    def test_view_relays_both_ways_and_never_starts_control(self, fake):
        _enable()
        tok = _ticket(fake, mode="view", agent="tom")
        with fake.client.websocket_connect(f"/api/computer/vnc?ticket={tok}") as ws:
            assert ws.receive_bytes() == b"RFB 003.008\n"
            ws.send_bytes(b"\x01\x02")
            assert ws.receive_bytes() == b"echo:\x01\x02"
            assert fake.client.get("/api/computer/control/status").json() == {"control": None}
            assert fake.client.get("/api/integrations/computer/status").json()["viewers"] == 1
            ws.send_bytes(b"bye")
            with pytest.raises(WebSocketDisconnect) as ei:
                ws.receive_bytes()
            # The computer's own reason reaches the page instead of a bare "Disconnected".
            assert (ei.value.code, ei.value.reason) == (4000, "The computer ended the stream: desktop stopped")
        path, auth, protocols = fake.ws_requests[0]
        assert urlparse(path).query == "mode=view" and auth == "Bearer s3cret-s3cret-s3cret-s3cret-s3cret"
        assert "binary" in protocols  # noVNC's subprotocol, offered upstream like the browser would
        assert not [c for c in fake.calls if c[1] == "/control/start"]
        assert viewer.open_count() == 0

    def test_control_starts_with_the_tickets_agent_and_task(self, fake):
        _enable()
        tok = _ticket(fake, mode="control", agent="tom", task_id="t1")
        with fake.client.websocket_connect(f"/api/computer/vnc?ticket={tok}") as ws:
            assert ws.receive_bytes() == b"RFB 003.008\n"
            assert ("POST", "/control/start", {"agent": "tom", "task_id": "t1"}) in fake.calls
            assert fake.client.get("/api/computer/control/status").json() == {
                "control": {"control_session_id": "cs-1", "agent": "tom", "task_id": "t1"}}
            r = fake.client.post("/api/computer/control/end", json={"control_session_id": "cs-1"})
            assert r.status_code == 200
            assert ("POST", "/control/end", {"control_session_id": "cs-1"}) in fake.calls
        assert urlparse(fake.ws_requests[0][0]).query == "mode=control&control_session_id=cs-1"

    def test_reattach_skips_control_start(self, fake):
        _enable()
        tok = _ticket(fake, mode="control", agent="tom", reattach="cs-9")
        with fake.client.websocket_connect(f"/api/computer/vnc?ticket={tok}") as ws:
            assert ws.receive_bytes() == b"RFB 003.008\n"
        assert not [c for c in fake.calls if c[1] == "/control/start"]
        assert urlparse(fake.ws_requests[0][0]).query == "mode=control&control_session_id=cs-9"

    def test_busy_control_closes_with_reason(self, fake):
        _enable()
        fake.busy = True
        tok = _ticket(fake, mode="control", agent="tom")
        with fake.client.websocket_connect(f"/api/computer/vnc?ticket={tok}") as ws:
            with pytest.raises(WebSocketDisconnect) as ei:
                ws.receive_bytes()
        assert (ei.value.code, ei.value.reason) == (4409, "Someone else has the screen.")
        assert fake.ws_requests == []

    def test_control_end_after_the_session_already_ended_is_ok(self, fake):
        _enable()
        assert fake.client.post("/api/computer/control/end", json={"control_session_id": "cs-1"}).status_code == 200
        assert fake.client.post("/api/computer/control/end", json={"control_session_id": "cs-1"}).status_code == 200

    def test_computer_refusing_the_handshake_closes_with_4403(self, fake):
        _enable()
        fake.refuse_ws = True
        tok = _ticket(fake, mode="view", agent="tom")
        with fake.client.websocket_connect(f"/api/computer/vnc?ticket={tok}") as ws:
            with pytest.raises(WebSocketDisconnect) as ei:
                ws.receive_bytes()
        assert ei.value.code == 4403 and "HTTP 403" in ei.value.reason and "asleep" in ei.value.reason

    def test_disable_during_the_upstream_handshake_still_closes(self, fake):
        _enable()
        fake.on_ws_request = lambda: save_credentials("computer", {"enabled": False})
        tok = _ticket(fake, mode="view", agent="tom")
        with fake.client.websocket_connect(f"/api/computer/vnc?ticket={tok}") as ws:
            with pytest.raises(WebSocketDisconnect) as ei:
                ws.receive_bytes()
        assert (ei.value.code, ei.value.reason) == (4000, "The computer was turned off.")
        assert viewer.open_count() == 0

    def test_ticket_is_burned_even_if_policy_now_forbids(self, fake):
        _enable()
        tok = _ticket(fake, mode="view", agent="tom")
        save_credentials("computer", {"enabled": True, "disabled_agents": ["tom"]})
        with pytest.raises(WebSocketDisconnect):
            with fake.client.websocket_connect(f"/api/computer/vnc?ticket={tok}"):
                pass
        assert viewer.redeem_ticket(tok) is None

    def test_disable_closes_open_viewers(self, fake):
        _enable()
        tok = _ticket(fake, mode="view", agent="tom")
        with fake.client.websocket_connect(f"/api/computer/vnc?ticket={tok}") as ws:
            assert ws.receive_bytes() == b"RFB 003.008\n"
            assert fake.client.post("/api/integrations/computer/disable").status_code == 200
            with pytest.raises(WebSocketDisconnect) as ei:
                ws.receive_bytes()
            assert (ei.value.code, ei.value.reason) == (4000, "The computer was turned off.")
        assert viewer.open_count() == 0

    def test_stream_failure_closes_with_4502(self, fake, monkeypatch):
        _enable()
        monkeypatch.setattr(client_mod.ComputerClient, "vnc_url", lambda self, *a: "ws://127.0.0.1:9/vnc")
        tok = _ticket(fake, mode="view", agent="tom")
        with fake.client.websocket_connect(f"/api/computer/vnc?ticket={tok}") as ws:
            with pytest.raises(WebSocketDisconnect) as ei:
                ws.receive_bytes()
        assert ei.value.code == 4502


# ── the page ─────────────────────────────────────────────────────────────────

class TestPage:
    def test_serves_shell_or_503(self, anon_client, monkeypatch):
        monkeypatch.setattr(viewer, "_index_html", lambda: "<html><head></head><body>shell</body></html>")
        r = anon_client.get("/computer")
        assert r.status_code == 200 and "shell" in r.text and r.headers["cache-control"] == "no-store"
        monkeypatch.setattr(viewer, "_index_html", lambda: "")
        assert anon_client.get("/computer").status_code == 503
