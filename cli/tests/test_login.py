"""chatty login (QR pairing and --password) and logout."""

import getpass
import json
import stat

import httpx
from chatty_cli import config
from chatty_cli.login import cmd_login, cmd_logout, qr_text
from conftest import FakeChatty

URL = "http://chatty.test"


def pairing_server(*statuses: dict):
    seen = []
    queue = list(statuses)

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append((request.url.path, body))
        if request.url.path == "/api/terminal/pair/start":
            assert set(body) == {"host", "platform"} and "authorization" not in request.headers
            return httpx.Response(200, json={"device_code": "dc-secret", "user_code": "ABCD-EFGH",
                                             "expires_in": 600, "interval": 0})
        if request.url.path == "/api/terminal/pair/poll":
            assert body == {"device_code": "dc-secret"}
            return httpx.Response(200, json=queue.pop(0))
        return httpx.Response(404)

    return httpx.MockTransport(handler), seen


def test_pair_pending_then_approved_saves_the_device_token(isolated_config, capsys):
    transport, seen = pairing_server({"status": "pending"}, {"status": "pending"},
                                     {"status": "approved", "token": "dev-tok", "device_id": 7})
    assert cmd_login(URL + "/", False, transport) == 0
    cfg = json.loads(isolated_config.read_text())
    assert cfg == {"url": URL, "device_token": "dev-tok", "device_id": 7}
    assert stat.S_IMODE(isolated_config.stat().st_mode) == 0o600
    assert [p for p, _ in seen].count("/api/terminal/pair/poll") == 3
    out = capsys.readouterr().out
    assert f"{URL}/?pair=ABCD-EFGH" in out and "\x1b[97;40m" in out


def test_pair_denied_or_expired_exits_nonzero(isolated_config):
    for status in ("denied", "expired"):
        transport, _ = pairing_server({"status": "pending"}, {"status": status})
        assert cmd_login(URL, False, transport) == 1
    assert not isolated_config.exists()


def test_pair_rate_limited(capsys):
    transport = httpx.MockTransport(lambda r: httpx.Response(429, json={"detail": "Too many requests"}))
    assert cmd_login(URL, False, transport) == 1
    assert "Wait a few minutes" in capsys.readouterr().err


def test_password_login_with_2fa_ends_with_a_device_token(isolated_config, monkeypatch):
    monkeypatch.setattr(getpass, "getpass", lambda prompt: "hunter2")
    monkeypatch.setattr("builtins.input", lambda prompt: " 123456 ")
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append(request.url.path)
        if request.url.path == "/api/login":
            assert body == {"password": "hunter2"}
            return httpx.Response(200, json={"requires_2fa": True, "pending_token": "pending"})
        if request.url.path == "/api/login/verify-2fa":
            assert body == {"pending_token": "pending", "code": "123456"}
            return httpx.Response(200, json={"access_token": "jwt-once", "token_type": "bearer"})
        if request.url.path == "/api/terminal/devices":
            assert request.headers["authorization"] == "Bearer jwt-once"
            assert set(body) == {"label", "host", "platform"}
            return httpx.Response(200, json={"token": "dev-tok", "device_id": 3})
        return httpx.Response(404)

    assert cmd_login(URL, True, httpx.MockTransport(handler)) == 0
    assert seen == ["/api/login", "/api/login/verify-2fa", "/api/terminal/devices"]
    saved = isolated_config.read_text()
    assert json.loads(saved)["device_token"] == "dev-tok"
    assert "jwt-once" not in saved and "hunter2" not in saved


def test_wrong_password_exits_nonzero(isolated_config, monkeypatch, capsys):
    monkeypatch.setattr(getpass, "getpass", lambda prompt: "nope")
    transport = httpx.MockTransport(lambda r: httpx.Response(401, json={"detail": "Incorrect password"}))
    assert cmd_login(URL, True, transport) == 1
    assert "Incorrect password" in capsys.readouterr().err
    assert not isolated_config.exists()


def test_login_to_another_server_forgets_the_agent(isolated_config):
    config.save({"url": "http://old.test", "device_token": "old", "last_agent_id": "x", "mode": "power"})
    transport, _ = pairing_server({"status": "approved", "token": "dev-tok", "device_id": 1})
    assert cmd_login(URL, False, transport) == 0
    assert json.loads(isolated_config.read_text()) == {"mode": "power", "url": URL, "device_token": "dev-tok",
                                                       "device_id": 1}


def test_logout_revokes_on_the_server_and_forgets(isolated_config):
    fake = FakeChatty()
    config.save({"url": URL, "device_token": "dev-tok", "device_id": 7, "mode": "power"})
    assert cmd_logout(httpx.MockTransport(fake.handler)) == 0
    assert ("DELETE", "/api/terminal/devices/7") in [(m, p) for m, p, _ in fake.requests]
    assert json.loads(isolated_config.read_text()) == {"url": URL, "mode": "power"}


def test_qr_round_trips_with_dark_modules_on_the_black_background():
    import qrcode

    qr = qrcode.QRCode(border=4)
    qr.add_data(f"{URL}/?pair=ABCD-EFGH")
    matrix = qr.get_matrix()
    lines = qr_text(f"{URL}/?pair=ABCD-EFGH").splitlines()
    cells = {"█": (False, False), "▀": (False, True), "▄": (True, False), " ": (True, True)}
    decoded = []
    for line in lines:
        assert line.startswith("\x1b[97;40m") and line.endswith("\x1b[0m")
        pairs = [cells[c] for c in line[len("\x1b[97;40m"):-len("\x1b[0m")]]
        decoded += [[t for t, _ in pairs], [b for _, b in pairs]]
    assert decoded[:len(matrix)] == matrix
    assert not any(decoded[0]) and not any(row[0] for row in decoded)  # light quiet zone
