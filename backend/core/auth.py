"""
Chatty — Authentication utilities.

Single-user password login with JWT. Optional TOTP two-factor authentication.
The login endpoint checks the password and, if 2FA is enabled, issues a
short-lived pending token requiring a TOTP code before granting access.

Multi-user Google OAuth is roughed in behind MULTI_USER_ENABLED=false
for Phase 2.
"""

import hmac
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request, HTTPException, status
from fastapi.responses import JSONResponse
import bcrypt as _bcrypt
from jose import JWTError, jwt
from pydantic import BaseModel

from core.config import settings

router = APIRouter()

PENDING_TOKEN_EXPIRE_MINUTES = 5

# ── Rate limiting (in-memory) ────────────────────────────────────────────────

_login_attempts: dict[str, list[float]] = defaultdict(list)


def _check_login_rate(ip: str) -> bool:
    now = time.time()
    window = 300  # 5 minutes
    _login_attempts[ip] = [t for t in _login_attempts[ip] if now - t < window]
    if len(_login_attempts[ip]) >= 10:
        return False
    _login_attempts[ip].append(now)
    return True


# ── JWT helpers ──────────────────────────────────────────────────────────────

def create_access_token(data: dict, expire_minutes: int | None = None) -> str:
    """Create a signed JWT with the given claims and configured expiry."""
    minutes = expire_minutes if expire_minutes is not None else settings.jwt.expire_minutes
    expire = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    to_encode = {**data, "exp": expire}
    return jwt.encode(to_encode, settings.jwt.secret_key, algorithm=settings.jwt.algorithm)


def decode_access_token(token: str) -> dict:
    """Decode and validate a JWT. Raises JWTError on failure."""
    return jwt.decode(token, settings.jwt.secret_key, algorithms=[settings.jwt.algorithm])


async def get_current_user(request: Request) -> dict:
    """
    FastAPI dependency — extracts and validates the JWT from the
    Authorization: Bearer <token> header.

    Raises 401 if missing, invalid, expired, or if the token is a
    2FA pending token (which cannot be used for API access).
    """
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = auth_header.removeprefix("Bearer ").strip()
    try:
        payload = decode_access_token(token)
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if payload.get("purpose") == "2fa_pending":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="2FA verification required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return payload


# ── Password verification ────────────────────────────────────────────────────

def verify_password(plain: str) -> bool:
    """Verify password against AUTH_PASSWORD. Supports bcrypt hashes or plaintext."""
    stored = settings.auth.password
    if stored.startswith("$2b$") or stored.startswith("$2a$"):
        return _bcrypt.checkpw(plain.encode(), stored.encode())
    return hmac.compare_digest(plain, stored)


# ── Login endpoint ────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    password: str


@router.post("/login")
async def login(body: LoginRequest, request: Request):
    """Single-user password login. Returns JWT or 2FA challenge."""
    client_ip = request.client.host if request.client else "unknown"
    if not _check_login_rate(client_ip):
        raise HTTPException(status_code=429, detail="Too many login attempts. Try again in a few minutes.")

    if not verify_password(body.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect password",
        )

    # Check if 2FA is enabled (lazy import to avoid circular dependency at module load)
    try:
        from core.auth_2fa import is_2fa_enabled, is_device_trusted, TRUST_COOKIE_NAME
    except ImportError:
        is_2fa_enabled = None
    if is_2fa_enabled and is_2fa_enabled():
        trust_token = request.cookies.get(TRUST_COOKIE_NAME, "")
        if not is_device_trusted(trust_token):
            pending = create_access_token(
                {"sub": "user", "purpose": "2fa_pending"},
                expire_minutes=PENDING_TOKEN_EXPIRE_MINUTES,
            )
            return JSONResponse({"requires_2fa": True, "pending_token": pending})

    token = create_access_token({"sub": "user", "role": "admin"})
    return JSONResponse({"access_token": token, "token_type": "bearer"})


@router.get("/me")
async def get_me(user: dict = Depends(get_current_user)):
    """Return current user info from token."""
    return {"sub": user.get("sub"), "role": user.get("role")}
