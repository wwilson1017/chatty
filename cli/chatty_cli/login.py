"""chatty login / logout. Pair by QR with the phone where you're logged in to Chatty, or enroll with the
password. Both end with the same revocable device token; no password or JWT is ever stored."""

import asyncio
import getpass
import platform
import socket
import sys
import time

import httpx
import qrcode

from . import config
from .api import Api, ApiError, Revoked, detail


def device() -> dict:
    return {"host": socket.gethostname(), "platform": platform.system()}


def _ok(r: httpx.Response) -> dict:
    if r.is_error:
        raise ApiError(detail(r))
    return r.json()


def qr_text(data: str) -> str:
    """Half blocks in explicit white on black with a 4-module quiet zone, so it scans on light terminals too."""
    qr = qrcode.QRCode(border=4)
    qr.add_data(data)
    m = qr.get_matrix()  # True = dark module, border included
    if len(m) % 2:
        m.append([False] * len(m[0]))
    # White foreground draws the light modules; the black background shows through as the dark ones.
    cells = {(False, False): "█", (False, True): "▀", (True, False): "▄", (True, True): " "}
    return "\n".join("\x1b[97;40m" + "".join(cells[t, b] for t, b in zip(top, bottom)) + "\x1b[0m"
                     for top, bottom in zip(m[::2], m[1::2]))


def pair(http: httpx.Client, url: str) -> dict | None:
    r = http.post("/api/terminal/pair/start", json=device())
    if r.status_code == 429:
        raise ApiError("too many pairing requests right now. Wait a few minutes and try again.")
    start = _ok(r)
    link = f"{url}/?pair={start['user_code']}"
    print("\nScan this with the phone where you're logged in to Chatty, or open the link there:\n")
    print(qr_text(link))
    print(f"\n{link}\n\nThis terminal's code: {start['user_code']}\n"
          "Approve it only if Chatty shows the same code. Waiting (Ctrl+C to stop)...")
    deadline = time.monotonic() + start["expires_in"]
    while time.monotonic() < deadline:
        time.sleep(start["interval"])
        poll = _ok(http.post("/api/terminal/pair/poll", json={"device_code": start["device_code"]}))
        if poll["status"] == "approved":
            return poll
        if poll["status"] == "denied":
            print("Chatty denied this terminal.", file=sys.stderr)
            return None
        if poll["status"] == "expired":
            break
    print("The code expired. Run chatty login again.", file=sys.stderr)
    return None


def password_login(http: httpx.Client) -> dict:
    body = _ok(http.post("/api/login", json={"password": getpass.getpass("Chatty password: ")}))
    if body.get("requires_2fa"):
        code = input("Two-factor code: ").strip()
        body = _ok(http.post("/api/login/verify-2fa", json={"pending_token": body["pending_token"], "code": code}))
    # The JWT is used once, to enroll this terminal; only the device token is kept.
    return _ok(http.post("/api/terminal/devices", json={"label": socket.gethostname(), **device()},
                         headers={"Authorization": f"Bearer {body['access_token']}"}))


def cmd_login(url: str | None, password: bool, transport: httpx.BaseTransport | None = None) -> int:
    cfg = config.load()
    url = (url or cfg.get("url") or "").rstrip("/")
    if not url:
        print("Usage: chatty login <your Chatty URL>, e.g. chatty login https://chatty.example.com", file=sys.stderr)
        return 2
    try:
        with httpx.Client(base_url=url, timeout=30, transport=transport) as http:
            got = password_login(http) if password else pair(http, url)
    except (ApiError, httpx.HTTPError) as e:
        print(f"Login failed: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nStopped.", file=sys.stderr)
        return 130
    if not got:
        return 1
    if url != cfg.get("url"):  # the remembered agent belongs to the old server
        cfg = {k: v for k, v in cfg.items() if k in ("mode", "verbose")}
    cfg.update(url=url, device_token=got["token"], device_id=got["device_id"])
    config.save(cfg)
    print(f"Logged in to {url}. Start chatting with: chatty")
    return 0


async def _revoke(cfg: dict, transport) -> None:
    api = Api(cfg["url"], cfg["device_token"], transport)
    try:
        await api.call("DELETE", f"/api/terminal/devices/{cfg['device_id']}")
    finally:
        await api.http.aclose()


def cmd_logout(transport: httpx.AsyncBaseTransport | None = None) -> int:
    cfg = config.load()
    if not cfg.get("device_token"):
        print("Not logged in.")
        return 0
    try:
        asyncio.run(_revoke(cfg, transport))
        print(f"Logged out. This terminal is revoked on {cfg['url']}.")
    except Revoked:
        print("Logged out (this terminal was already revoked).")
    except (ApiError, httpx.HTTPError, KeyError) as e:
        print(f"Logged out here, but couldn't revoke it on the server ({e}). Revoke it in Settings → Terminal.")
    cfg.pop("device_token", None)
    cfg.pop("device_id", None)
    config.save(cfg)
    return 0
