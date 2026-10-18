"""
Chatty — pair a terminal (`chatty login`) by device code (/api/terminal/*).

The inverse of the Claude Code connector's pairing: here the web is the side
that has already proven itself (password + TOTP), so the terminal asks and
the logged-in web approves. `chatty login` starts a pairing and shows its
user_code as text and as a QR for `<origin>/?pair=<code>`; the phone opens
Settings → Terminal with the code filled in; Approve lets the terminal's next
poll claim a long-lived device token (stored hashed, revocable per device).
The CLI trades that token for a short JWT at /token, so every other endpoint
keeps its normal auth.
"""

import hashlib
import logging
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from core.auth import create_access_token, get_current_user
from core.todo.ratelimit import IPRateLimiter

from . import db

logger = logging.getLogger(__name__)

router = APIRouter()

PAIR_TTL = timedelta(minutes=10)
POLL_INTERVAL_S = 2
MAX_LIVE_PAIRINGS = 20  # /pair/start is public, so cap what it can pile up
# simplification: a revoke takes effect within one JWT life (15 min); upgrade: check the `device` claim in get_current_user
TOKEN_MINUTES = 15
CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTWXYZ"  # no 0/O, 1/I/L, U/V — easy to read off a screen

start_limiter = IPRateLimiter(window=300, max_hits=10)
poll_limiter = IPRateLimiter(window=300, max_hits=400)  # the CLI polls every 2 s for up to 10 min


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _norm(code: str) -> str:
    return code.replace("-", "").replace(" ", "").upper()


def _show(code: str) -> str:
    return f"{code[:4]}-{code[4:]}"


def _insert_device(conn: sqlite3.Connection, label: str, host: str, platform: str) -> dict:
    """Add a device row (caller commits) and return its one-time plaintext token."""
    token = secrets.token_urlsafe(32)
    cur = conn.execute(
        "INSERT INTO devices (label, host, platform, token_hash, created_at) VALUES (?, ?, ?, ?, ?)",
        (label or host, host, platform, _sha256(token), _now()),
    )
    return {"token": token, "device_id": cur.lastrowid}


# ── Terminal side (no login yet) ─────────────────────────────────────────────

class StartRequest(BaseModel):
    host: str = Field("", max_length=200)
    platform: str = Field("", max_length=50)


@router.post("/pair/start")
def pair_start(body: StartRequest, request: Request):
    ip = _client_ip(request)
    if not start_limiter.allow(ip):
        raise HTTPException(status_code=429, detail="Too many pairing attempts — try again in a few minutes")
    device_code = secrets.token_urlsafe(32)
    user_code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))
    now = datetime.now(timezone.utc)
    with db.write_lock():
        conn = db.get_db()
        conn.execute("DELETE FROM pairings WHERE expires_at <= ?", (_now(),))
        live = conn.execute(
            "SELECT COUNT(*) FROM pairings WHERE status IN ('pending', 'approved')").fetchone()[0]
        if live >= MAX_LIVE_PAIRINGS:
            conn.commit()
            raise HTTPException(status_code=429, detail="Too many pairings waiting — try again in a few minutes")
        conn.execute(
            "INSERT INTO pairings (user_code, device_code_hash, host, platform, ip, created_at, expires_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user_code, _sha256(device_code), body.host, body.platform, ip,
             now.isoformat(timespec="seconds"), (now + PAIR_TTL).isoformat(timespec="seconds")),
        )
        conn.commit()
    return {"device_code": device_code, "user_code": _show(user_code),
            "expires_in": int(PAIR_TTL.total_seconds()), "interval": POLL_INTERVAL_S}


class PollRequest(BaseModel):
    device_code: str = Field(..., min_length=1, max_length=200)


@router.post("/pair/poll")
def pair_poll(body: PollRequest, request: Request):
    """pending | denied | expired (final: unknown, timed out or already claimed) | approved + token."""
    if not poll_limiter.allow(_client_ip(request)):
        raise HTTPException(status_code=429, detail="Polling too fast")
    code_hash, now = _sha256(body.device_code), _now()
    with db.write_lock():
        conn = db.get_db()
        row = conn.execute(
            "SELECT * FROM pairings WHERE device_code_hash = ? AND expires_at > ?", (code_hash, now)).fetchone()
        if not row or row["status"] == "claimed":
            return {"status": "expired"}
        if row["status"] != "approved":
            return {"status": row["status"]}
        # Claim and mint in one transaction, so two racing polls can't both get a token.
        claimed = conn.execute(
            "UPDATE pairings SET status = 'claimed'"
            " WHERE device_code_hash = ? AND status = 'approved' AND expires_at > ?", (code_hash, now))
        if claimed.rowcount != 1:
            conn.rollback()
            return {"status": "expired"}
        device = _insert_device(conn, row["label"], row["host"], row["platform"])
        conn.commit()
    logger.info("Terminal paired: %s (device %s)", row["label"], device["device_id"])
    return {"status": "approved", **device}


@router.post("/token")
def device_token(authorization: str = Header("")):
    """Trade a device token for a short JWT the rest of the API accepts."""
    token = authorization[7:].strip() if authorization[:7].lower() == "bearer " else ""
    row = None
    with db.write_lock():
        conn = db.get_db()
        if token:
            row = conn.execute("SELECT id FROM devices WHERE token_hash = ?", (_sha256(token),)).fetchone()
        if row:
            conn.execute("UPDATE devices SET last_seen_at = ? WHERE id = ?", (_now(), row["id"]))
            conn.commit()
    if not row:
        raise HTTPException(status_code=401, detail="This terminal isn't paired, or was revoked — run `chatty login`")
    access = create_access_token({"sub": "user", "role": "admin", "device": row["id"]},
                                 expire_minutes=TOKEN_MINUTES)
    return {"access_token": access, "expires_in": TOKEN_MINUTES * 60}


# ── Web side (logged in) ─────────────────────────────────────────────────────

@router.get("/pair/{user_code}")
def pair_lookup(user_code: str, user=Depends(get_current_user)):
    with db.write_lock():
        row = db.get_db().execute(
            "SELECT user_code, host, platform, ip, created_at, expires_at, status FROM pairings"
            " WHERE user_code = ? AND expires_at > ?", (_norm(user_code), _now())).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="No pairing with that code — it may have expired")
    return {**dict(row), "user_code": _show(row["user_code"])}


class DecideRequest(BaseModel):
    approve: bool
    label: str = Field("", max_length=100)


@router.post("/pair/{user_code}/decide")
def pair_decide(user_code: str, body: DecideRequest, user=Depends(get_current_user)):
    with db.write_lock():
        conn = db.get_db()
        cur = conn.execute(
            "UPDATE pairings SET status = ?, label = COALESCE(NULLIF(?, ''), host)"
            " WHERE user_code = ? AND status = 'pending' AND expires_at > ?",
            ("approved" if body.approve else "denied", body.label.strip(), _norm(user_code), _now()))
        conn.commit()
    if cur.rowcount != 1:
        raise HTTPException(status_code=409, detail="This pairing is no longer waiting — run `chatty login` again")
    return {"ok": True}


class DeviceRequest(BaseModel):
    label: str = Field("", max_length=100)
    host: str = Field("", max_length=200)
    platform: str = Field("", max_length=50)


@router.post("/devices")
def create_device(body: DeviceRequest, user=Depends(get_current_user)):
    """Enroll a terminal that logged in with the password (`chatty login --password`)."""
    with db.write_lock():
        conn = db.get_db()
        device = _insert_device(conn, body.label.strip(), body.host, body.platform)
        conn.commit()
    return device


@router.get("/devices")
def list_devices(user=Depends(get_current_user)):
    with db.write_lock():
        rows = db.get_db().execute(
            "SELECT id, label, host, platform, created_at, last_seen_at FROM devices ORDER BY id").fetchall()
    return {"devices": [dict(r) for r in rows]}


@router.delete("/devices/{device_id}")
def revoke_device(device_id: int, user=Depends(get_current_user)):
    with db.write_lock():
        conn = db.get_db()
        cur = conn.execute("DELETE FROM devices WHERE id = ?", (device_id,))
        conn.commit()
    if cur.rowcount != 1:
        raise HTTPException(status_code=404, detail="No such terminal")
    return {"ok": True}
