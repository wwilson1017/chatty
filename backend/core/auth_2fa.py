"""
Chatty — Two-factor authentication (TOTP).

Opt-in TOTP via authenticator apps (Google Authenticator, Authy, 1Password).
Includes backup codes, trusted device cookies, and rate limiting.

Database: data/auth.db (SQLite, same pattern as agents/db.py).
"""

import base64
import hashlib
import io
import json
import logging
import secrets
import sqlite3
import string
import threading
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pyotp
import qrcode
import bcrypt as _bcrypt
from fastapi import APIRouter, Depends, Request, HTTPException, Response, status
from jose import JWTError
from pydantic import BaseModel

from core.auth import create_access_token, decode_access_token, get_current_user, verify_password
from core.config import settings
from core.encryption import encrypt_value, decrypt_value
from core.storage import safe_init_sqlite

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DB_PATH = DATA_DIR / "auth.db"
GCS_KEY = "auth.db"

_connection: sqlite3.Connection | None = None
_write_lock = threading.Lock()

TOTP_ISSUER = "Chatty"
TRUST_COOKIE_NAME = "chatty_2fa_trust"
TRUST_COOKIE_MAX_AGE = 30 * 24 * 60 * 60  # 30 days in seconds
BACKUP_CODE_COUNT = 10

router = APIRouter()


# ── Rate limiting (in-memory) ────────────────────────────────────────────────

_rate_limits: dict[str, list[float]] = defaultdict(list)


def _check_rate_limit(key: str, max_attempts: int, window_seconds: int) -> bool:
    now = time.time()
    _rate_limits[key] = [t for t in _rate_limits[key] if now - t < window_seconds]
    if len(_rate_limits[key]) >= max_attempts:
        return False
    _rate_limits[key].append(now)
    return True


# ── Database layer ───────────────────────────────────────────────────────────

def _get_db() -> sqlite3.Connection:
    if _connection is None:
        raise RuntimeError("Auth 2FA DB not initialized — call init_db() first")
    return _connection


def _setup_connection() -> None:
    global _connection
    _connection = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    _connection.row_factory = sqlite3.Row
    _connection.execute("PRAGMA journal_mode=WAL")
    _connection.execute("PRAGMA foreign_keys=ON")
    _connection.execute("PRAGMA busy_timeout=5000")

    _connection.executescript("""
        CREATE TABLE IF NOT EXISTS totp_config (
            id           INTEGER PRIMARY KEY CHECK (id = 1),
            enabled      INTEGER NOT NULL DEFAULT 0,
            secret_enc   TEXT NOT NULL DEFAULT '',
            backup_codes TEXT NOT NULL DEFAULT '[]',
            last_used_at TEXT NOT NULL DEFAULT '',
            created_at   TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at   TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS trusted_devices (
            token_hash  TEXT PRIMARY KEY,
            label       TEXT NOT NULL DEFAULT '',
            expires_at  TEXT NOT NULL,
            created_at  TEXT NOT NULL DEFAULT (datetime('now'))
        );
    """)
    _connection.commit()
    logger.info("Auth 2FA DB initialized at %s", DB_PATH)


def init_db() -> dict:
    return safe_init_sqlite(DB_PATH, GCS_KEY, init_fn=_setup_connection)


def get_totp_config() -> dict | None:
    row = _get_db().execute("SELECT * FROM totp_config WHERE id = 1").fetchone()
    return dict(row) if row else None


def is_2fa_enabled() -> bool:
    config = get_totp_config()
    return bool(config and config["enabled"])


def save_totp_config(secret_enc: str, backup_codes_json: str) -> None:
    with _write_lock:
        _get_db().execute(
            """INSERT INTO totp_config (id, enabled, secret_enc, backup_codes, updated_at)
               VALUES (1, 1, ?, ?, datetime('now'))
               ON CONFLICT(id) DO UPDATE SET
                   enabled = 1, secret_enc = excluded.secret_enc,
                   backup_codes = excluded.backup_codes,
                   updated_at = datetime('now')""",
            (secret_enc, backup_codes_json),
        )
        _get_db().commit()


def disable_totp() -> None:
    with _write_lock:
        _get_db().execute(
            """UPDATE totp_config SET enabled = 0, secret_enc = '', backup_codes = '[]',
               last_used_at = '', updated_at = datetime('now') WHERE id = 1"""
        )
        _get_db().commit()
    revoke_all_trusted_devices()


def update_last_used(timestamp: str) -> None:
    with _write_lock:
        _get_db().execute(
            "UPDATE totp_config SET last_used_at = ?, updated_at = datetime('now') WHERE id = 1",
            (timestamp,),
        )
        _get_db().commit()


def consume_backup_code(code: str) -> bool:
    normalized = code.strip().upper().replace("-", "").encode()
    with _write_lock:
        config = get_totp_config()
        if not config:
            return False
        hashes: list[str] = json.loads(config["backup_codes"])
        for i, h in enumerate(hashes):
            if _bcrypt.checkpw(normalized, h.encode()):
                hashes.pop(i)
                _get_db().execute(
                    "UPDATE totp_config SET backup_codes = ?, updated_at = datetime('now') WHERE id = 1",
                    (json.dumps(hashes),),
                )
                _get_db().commit()
                return True
    return False


def _hash_device_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def add_trusted_device(token: str, label: str, expires_at: str) -> None:
    token_hash = _hash_device_token(token)
    with _write_lock:
        _get_db().execute(
            "INSERT OR REPLACE INTO trusted_devices (token_hash, label, expires_at) VALUES (?, ?, ?)",
            (token_hash, label, expires_at),
        )
        _get_db().commit()


def is_device_trusted(token: str) -> bool:
    if not token:
        return False
    token_hash = _hash_device_token(token)
    row = _get_db().execute(
        "SELECT expires_at FROM trusted_devices WHERE token_hash = ?", (token_hash,)
    ).fetchone()
    if not row:
        return False
    expires = datetime.fromisoformat(row["expires_at"])
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) < expires


def revoke_all_trusted_devices() -> None:
    with _write_lock:
        _get_db().execute("DELETE FROM trusted_devices")
        _get_db().commit()


def cleanup_expired_devices() -> None:
    now = datetime.now(timezone.utc).isoformat()
    with _write_lock:
        _get_db().execute("DELETE FROM trusted_devices WHERE expires_at < ?", (now,))
        _get_db().commit()


# ── Helpers ──────────────────────────────────────────────────────────────────

def _generate_backup_codes() -> tuple[list[str], list[str]]:
    """Generate backup codes. Returns (plaintext_codes, bcrypt_hashes)."""
    charset = string.ascii_uppercase + string.digits
    codes = []
    hashes = []
    for _ in range(BACKUP_CODE_COUNT):
        raw = "".join(secrets.choice(charset) for _ in range(8))
        display = f"{raw[:4]}-{raw[4:]}"
        codes.append(display)
        hashes.append(_bcrypt.hashpw(raw.encode(), _bcrypt.gensalt()).decode())
    return codes, hashes


def _generate_qr_data_uri(provisioning_uri: str) -> str:
    img = qrcode.make(provisioning_uri, box_size=6, border=2)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()
    return f"data:image/png;base64,{b64}"


def verify_totp_code(code: str) -> bool:
    """Verify a TOTP code against the stored secret. Returns True on valid code."""
    with _write_lock:
        config = get_totp_config()
        if not config or not config["secret_enc"]:
            return False

        secret = decrypt_value(config["secret_enc"])
        if not secret:
            return False

        totp = pyotp.TOTP(secret)
        code_stripped = code.strip()
        if not totp.verify(code_stripped, valid_window=1):
            return False

        # Find which timeslot the code actually belongs to (could be T-1, T, or T+1)
        now_ts = totp.timecode(datetime.now(timezone.utc))
        matched_slot = now_ts
        for offset in (-1, 0, 1):
            candidate = now_ts + offset
            if totp.generate_otp(candidate) == code_stripped:
                matched_slot = candidate
                break

        # Replay prevention: reject if this or a later timeslot was already used
        if config["last_used_at"] and int(config["last_used_at"]) >= matched_slot:
            return False

        _get_db().execute(
            "UPDATE totp_config SET last_used_at = ?, updated_at = datetime('now') WHERE id = 1",
            (str(matched_slot),),
        )
        _get_db().commit()
        return True


# ── API request/response models ──────────────────────────────────────────────

class VerifySetupRequest(BaseModel):
    secret: str
    code: str
    password: str


class Verify2FARequest(BaseModel):
    pending_token: str
    code: str
    trust_device: bool = False


class PasswordConfirmRequest(BaseModel):
    password: str


# ── API endpoints ────────────────────────────────────────────────────────────

@router.get("/auth/2fa/status")
async def get_2fa_status(user: dict = Depends(get_current_user)):
    config = get_totp_config()
    if not config:
        return {"enabled": False, "has_backup_codes": False, "trusted_device_count": 0}

    backup_hashes = json.loads(config["backup_codes"])
    device_count = _get_db().execute(
        "SELECT COUNT(*) as cnt FROM trusted_devices WHERE expires_at > ?",
        (datetime.now(timezone.utc).isoformat(),),
    ).fetchone()["cnt"]

    return {
        "enabled": bool(config["enabled"]),
        "has_backup_codes": len(backup_hashes) > 0,
        "backup_code_count": len(backup_hashes),
        "trusted_device_count": device_count,
    }


@router.post("/auth/2fa/setup")
async def setup_2fa(user: dict = Depends(get_current_user)):
    secret = pyotp.random_base32()
    totp = pyotp.TOTP(secret)
    provisioning_uri = totp.provisioning_uri(name="user", issuer_name=TOTP_ISSUER)
    qr_data_uri = _generate_qr_data_uri(provisioning_uri)

    return {
        "secret": secret,
        "qr_code_data_uri": qr_data_uri,
        "provisioning_uri": provisioning_uri,
    }


@router.post("/auth/2fa/verify-setup")
async def verify_setup(body: VerifySetupRequest, user: dict = Depends(get_current_user)):
    if not verify_password(body.password):
        raise HTTPException(status_code=401, detail="Incorrect password")

    totp = pyotp.TOTP(body.secret)
    if not totp.verify(body.code.strip(), valid_window=1):
        raise HTTPException(status_code=400, detail="Invalid code. Check your authenticator app and try again.")

    encrypted_secret = encrypt_value(body.secret)
    plaintext_codes, hashed_codes = _generate_backup_codes()
    save_totp_config(encrypted_secret, json.dumps(hashed_codes))

    return {"enabled": True, "backup_codes": plaintext_codes}


@router.post("/auth/2fa/disable")
async def disable_2fa(body: PasswordConfirmRequest, user: dict = Depends(get_current_user)):
    if not verify_password(body.password):
        raise HTTPException(status_code=401, detail="Incorrect password")
    disable_totp()
    return {"disabled": True}


@router.post("/auth/2fa/backup-codes/regenerate")
async def regenerate_backup_codes(body: PasswordConfirmRequest, user: dict = Depends(get_current_user)):
    if not verify_password(body.password):
        raise HTTPException(status_code=401, detail="Incorrect password")
    if not is_2fa_enabled():
        raise HTTPException(status_code=400, detail="2FA is not enabled")

    plaintext_codes, hashed_codes = _generate_backup_codes()
    with _write_lock:
        _get_db().execute(
            "UPDATE totp_config SET backup_codes = ?, updated_at = datetime('now') WHERE id = 1",
            (json.dumps(hashed_codes),),
        )
        _get_db().commit()

    return {"backup_codes": plaintext_codes}


@router.post("/login/verify-2fa")
async def verify_2fa_login(body: Verify2FARequest, request: Request, response: Response):
    client_ip = request.client.host if request.client else "unknown"
    rate_key = f"2fa:{client_ip}"
    if not _check_rate_limit(rate_key, max_attempts=5, window_seconds=300):
        raise HTTPException(status_code=429, detail="Too many attempts. Please log in again.")

    # Validate pending token
    try:
        payload = decode_access_token(body.pending_token)
    except JWTError:
        raise HTTPException(status_code=401, detail="Expired or invalid session. Please log in again.")

    if payload.get("purpose") != "2fa_pending":
        raise HTTPException(status_code=401, detail="Invalid token")

    # Try TOTP code first, then backup code
    code = body.code.strip()
    valid = False
    if len(code.replace("-", "")) == 6 and code.replace("-", "").isdigit():
        valid = verify_totp_code(code)
    if not valid:
        valid = consume_backup_code(code)
    if not valid:
        raise HTTPException(status_code=401, detail="Invalid code")

    # Issue real access token
    token = create_access_token({"sub": "user", "role": "admin"})

    # Set trusted device cookie if requested
    if body.trust_device:
        device_token = secrets.token_hex(32)
        expires_at = (datetime.now(timezone.utc) + timedelta(seconds=TRUST_COOKIE_MAX_AGE)).isoformat()
        ua = request.headers.get("user-agent", "")
        label = ua[:100] if ua else "Unknown device"
        add_trusted_device(device_token, label, expires_at)
        response.set_cookie(
            key=TRUST_COOKIE_NAME,
            value=device_token,
            max_age=TRUST_COOKIE_MAX_AGE,
            httponly=True,
            secure=request.url.scheme == "https",
            samesite="lax",
        )

    return {"access_token": token, "token_type": "bearer"}
