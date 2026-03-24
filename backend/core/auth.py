"""
Chatty — Authentication utilities.

Single-user password login with JWT. The login endpoint checks the
plaintext password from AUTH_PASSWORD env var and returns a signed JWT.

Multi-user Google OAuth is roughed in behind MULTI_USER_ENABLED=false
for Phase 2.
"""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Request, HTTPException, status
from fastapi.responses import JSONResponse
from jose import JWTError, jwt
from pydantic import BaseModel

from core.config import settings

router = APIRouter()


# ── JWT helpers ──────────────────────────────────────────────────────────────

def create_access_token(data: dict) -> str:
    """Create a signed JWT with the given claims and configured expiry."""
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt.expire_minutes)
    to_encode = {**data, "exp": expire}
    return jwt.encode(to_encode, settings.jwt.secret_key, algorithm=settings.jwt.algorithm)


def decode_access_token(token: str) -> dict:
    """Decode and validate a JWT. Raises JWTError on failure."""
    return jwt.decode(token, settings.jwt.secret_key, algorithms=[settings.jwt.algorithm])


async def get_current_user(request: Request) -> dict:
    """
    FastAPI dependency — extracts and validates the JWT from the
    Authorization: Bearer <token> header.

    Raises 401 if missing, invalid, or expired.
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

    return payload


# ── Login endpoint ────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    password: str


@router.post("/login")
async def login(body: LoginRequest):
    """Single-user password login. Returns a JWT on success."""
    if body.password != settings.auth.password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect password",
        )

    token = create_access_token({"sub": "user", "role": "admin"})
    return JSONResponse({"access_token": token, "token_type": "bearer"})


@router.get("/me")
async def get_me(user: dict = None):
    """Return current user info from token."""
    # Dependency injected in main.py
    return {"sub": user.get("sub"), "role": user.get("role")}
