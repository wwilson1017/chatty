"""Tests for core.auth — password verification, JWT lifecycle, rate limiting."""

import asyncio
import time
from unittest.mock import MagicMock

import bcrypt as _bcrypt
import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

TEST_PASSWORD = "correct-horse-battery-staple"
TEST_JWT_SECRET = "test-secret-key-for-jwt-signing"


@pytest.fixture()
def app_env(monkeypatch):
    """Patch core.config.settings with known test values for auth + JWT."""
    from core.config import settings

    monkeypatch.setattr(settings.auth, "password", TEST_PASSWORD)
    monkeypatch.setattr(settings.jwt, "secret_key", TEST_JWT_SECRET)
    monkeypatch.setattr(settings.jwt, "algorithm", "HS256")
    monkeypatch.setattr(settings.jwt, "expire_minutes", 480)

    # Clear rate-limit state so tests don't leak into each other
    from core.auth import _login_attempts
    _login_attempts.clear()

    yield settings


# ---------------------------------------------------------------------------
# Password verification
# ---------------------------------------------------------------------------

class TestVerifyPassword:
    def test_correct_plaintext(self, app_env):
        from core.auth import verify_password

        assert verify_password(TEST_PASSWORD) is True

    def test_wrong_plaintext(self, app_env):
        from core.auth import verify_password

        assert verify_password("wrong-password") is False

    def test_bcrypt_hash_match(self, app_env):
        from core.auth import verify_password

        hashed = _bcrypt.hashpw(TEST_PASSWORD.encode(), _bcrypt.gensalt()).decode()
        app_env.auth.password = hashed
        assert verify_password(TEST_PASSWORD) is True

    def test_bcrypt_hash_mismatch(self, app_env):
        from core.auth import verify_password

        hashed = _bcrypt.hashpw(b"some-other-password", _bcrypt.gensalt()).decode()
        app_env.auth.password = hashed
        assert verify_password(TEST_PASSWORD) is False


# ---------------------------------------------------------------------------
# JWT lifecycle
# ---------------------------------------------------------------------------

class TestJWTLifecycle:
    def test_create_decode_roundtrip(self, app_env):
        from core.auth import create_access_token, decode_access_token

        claims = {"sub": "user", "role": "admin"}
        token = create_access_token(claims)
        payload = decode_access_token(token)

        assert payload["sub"] == "user"
        assert payload["role"] == "admin"
        assert "exp" in payload

    def test_custom_expiry_honored(self, app_env):
        from core.auth import create_access_token, decode_access_token

        token_short = create_access_token({"sub": "user"}, expire_minutes=1)
        token_long = create_access_token({"sub": "user"}, expire_minutes=9999)

        short_exp = decode_access_token(token_short)["exp"]
        long_exp = decode_access_token(token_long)["exp"]
        assert long_exp > short_exp

    def test_expired_token_raises(self, app_env):
        from jose import JWTError
        from core.auth import create_access_token, decode_access_token

        token = create_access_token({"sub": "user"}, expire_minutes=-1)
        with pytest.raises(JWTError):
            decode_access_token(token)


# ---------------------------------------------------------------------------
# get_current_user dependency
# ---------------------------------------------------------------------------

def _make_request(headers: dict | None = None) -> MagicMock:
    """Build a mock FastAPI Request with the given headers."""
    req = MagicMock()
    req.headers = headers or {}
    return req


class TestGetCurrentUser:
    def test_valid_bearer_token(self, app_env):
        from core.auth import create_access_token, get_current_user

        token = create_access_token({"sub": "user", "role": "admin"})
        request = _make_request({"Authorization": f"Bearer {token}"})
        payload = asyncio.run(get_current_user(request))

        assert payload["sub"] == "user"
        assert payload["role"] == "admin"

    def test_missing_header_raises_401(self, app_env):
        from fastapi import HTTPException
        from core.auth import get_current_user

        request = _make_request({})
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(get_current_user(request))
        assert exc_info.value.status_code == 401

    def test_2fa_pending_raises_401(self, app_env):
        from fastapi import HTTPException
        from core.auth import create_access_token, get_current_user

        token = create_access_token({"sub": "user", "purpose": "2fa_pending"})
        request = _make_request({"Authorization": f"Bearer {token}"})

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(get_current_user(request))
        assert exc_info.value.status_code == 401
        assert "2FA" in exc_info.value.detail


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------

class TestRateLimiting:
    def test_allows_under_limit(self, app_env):
        from core.auth import _check_login_rate

        for _ in range(9):
            assert _check_login_rate("10.0.0.1") is True

    def test_blocks_at_limit(self, app_env):
        from core.auth import _check_login_rate

        for _ in range(10):
            _check_login_rate("10.0.0.2")
        assert _check_login_rate("10.0.0.2") is False

    def test_window_expires(self, app_env, monkeypatch):
        from core.auth import _check_login_rate

        fake_time = 1000.0
        monkeypatch.setattr(time, "time", lambda: fake_time)

        for _ in range(10):
            _check_login_rate("10.0.0.3")
        assert _check_login_rate("10.0.0.3") is False

        # Advance past the 5-minute window
        fake_time = 1301.0
        monkeypatch.setattr(time, "time", lambda: fake_time)
        assert _check_login_rate("10.0.0.3") is True
