"""
Chatty — Google integration setup flow.

Tokens for Gmail/Calendar/Drive are stored in data/integrations/google.json
(NOT in auth-profiles.json). This keeps the integration credentials separate
from the Gemini AI provider credentials, which live under google:default in
auth-profiles.json. Connecting/disconnecting the integration never touches
the AI provider slot.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

import httpx

from integrations.registry import get_credentials, save_credentials

logger = logging.getLogger(__name__)

_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"


async def _resolve_email(access_token: str) -> str:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                _USERINFO_URL,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            resp.raise_for_status()
            return resp.json().get("email", "")
    except Exception as e:
        logger.warning("Failed to resolve Google email: %s", e)
        return ""


async def _resolve_calendar_timezone(access_token: str) -> str:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                "https://www.googleapis.com/calendar/v3/users/me/settings/timezone",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            if resp.status_code == 200:
                return resp.json().get("value", "UTC")
    except Exception as e:
        logger.debug("Calendar timezone lookup failed: %s", e)
    return "UTC"


async def setup_from_oauth(
    access_token: str,
    refresh_token: str,
    expires_in: int,
    scope_grants: dict,
) -> dict:
    """Persist tokens + grants to google.json. Returns {ok, email, ...}."""
    email = await _resolve_email(access_token)
    timezone = "UTC"
    if scope_grants.get("calendar", "none") != "none":
        timezone = await _resolve_calendar_timezone(access_token)

    existing = get_credentials("google")
    existing.update({
        "enabled": True,
        "email": email,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_expires_at": time.time() + expires_in,
        "scope_grants": scope_grants,
        "calendar_timezone": timezone,
        "connection_status": "ok",
    })
    save_credentials("google", existing)

    logger.info("Google connected: email=%s scope_grants=%s", email, scope_grants)
    return {
        "ok": True,
        "email": email,
        "scope_grants": scope_grants,
        "timezone": timezone,
    }


async def disconnect() -> dict:
    """Revoke tokens with Google and clear google.json. Does NOT touch
    auth-profiles.json — the Gemini AI provider is unaffected."""
    creds = get_credentials("google")
    refresh = creds.get("refresh_token", "")
    access = creds.get("access_token", "")

    token_to_revoke = refresh or access
    if token_to_revoke:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    "https://oauth2.googleapis.com/revoke",
                    params={"token": token_to_revoke},
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                if resp.status_code == 200:
                    logger.info("Google tokens revoked successfully")
                else:
                    logger.warning("Google token revoke returned %d", resp.status_code)
        except Exception as e:
            logger.warning("Google token revoke failed: %s", e)

    preserved_app = creds.get("app")
    creds_path = Path(__file__).resolve().parent.parent.parent / "data" / "integrations" / "google.json"
    if creds_path.exists():
        creds_path.unlink()
        logger.info("Removed google.json")

    if preserved_app:
        save_credentials("google", {"app": preserved_app})

    return {"ok": True}
