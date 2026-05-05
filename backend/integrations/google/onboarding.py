"""
Chatty — Google integration setup flow (multi-account).

Tokens for each Google account are stored in data/integrations/google.json
under the accounts dict, keyed by a short UUID. The Gemini AI provider
credentials live separately in auth-profiles.json.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from pathlib import Path

import httpx

from integrations.registry import (
    get_google_account,
    save_google_account,
    delete_google_account,
    list_google_accounts,
)

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
    account_id: str = "",
) -> dict:
    """Persist tokens + grants to google.json accounts dict. Returns {ok, account_id, email, ...}."""
    email = await _resolve_email(access_token)
    if not email:
        return {
            "ok": False,
            "error": "Could not resolve Google account email. Please try again.",
        }

    if account_id:
        existing = get_google_account(account_id)
        if existing and existing.get("email") and existing["email"] != email:
            logger.warning("Google reconnect email mismatch: stored=%s returned=%s", existing["email"], email)
            return {
                "ok": False,
                "error": "Account email mismatch. Disconnect and add a new account instead.",
            }

    timezone = "UTC"
    if scope_grants.get("calendar", "none") != "none":
        timezone = await _resolve_calendar_timezone(access_token)

    if not account_id:
        existing_accounts = list_google_accounts()
        for aid, acct in existing_accounts.items():
            if acct.get("email") and acct["email"] == email:
                account_id = aid
                break
        if not account_id:
            account_id = uuid.uuid4().hex[:8]

    account_data = {
        "email": email,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_expires_at": time.time() + expires_in,
        "scope_grants": scope_grants,
        "calendar_timezone": timezone,
        "connection_status": "ok",
    }

    save_google_account(account_id, account_data, create=True)

    _clear_stale_assignments(account_id, scope_grants)

    logger.info("Google account connected: id=%s email=%s scope_grants=%s", account_id, email, scope_grants)
    return {
        "ok": True,
        "account_id": account_id,
        "email": email,
        "scope_grants": scope_grants,
        "timezone": timezone,
    }


def _clear_stale_assignments(account_id: str, scope_grants: dict) -> None:
    """Clear agent assignments for services that were downgraded to 'none'."""
    try:
        from agents.db import list_agents, update_agent
        svc_map = {"gmail": "gmail", "calendar": "calendar", "drive": "drive"}
        for agent in list_agents():
            ga = agent.get("google_accounts", {})
            if not isinstance(ga, dict):
                continue
            changed = False
            for svc, scope_key in svc_map.items():
                if ga.get(svc) == account_id and scope_grants.get(scope_key, "none") == "none":
                    ga[svc] = ""
                    changed = True
            if changed:
                update_agent(agent["id"], google_accounts=json.dumps(ga))
    except Exception as e:
        logger.warning("Failed to clear stale Google assignments: %s", e)


async def _revoke_token(acct: dict) -> None:
    """Revoke tokens for a single account."""
    refresh = acct.get("refresh_token", "")
    access = acct.get("access_token", "")
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
                    logger.info("Google tokens revoked for %s", acct.get("email", "?"))
                else:
                    logger.warning("Google token revoke returned %d for %s", resp.status_code, acct.get("email", "?"))
        except Exception as e:
            logger.warning("Google token revoke failed for %s: %s", acct.get("email", "?"), e)


def _clear_agent_references(account_id: str = "") -> None:
    """Clear google_accounts on agents that reference a removed account."""
    try:
        from agents.db import list_agents, update_agent
        for agent in list_agents():
            ga = agent.get("google_accounts", {})
            if not isinstance(ga, dict):
                continue
            changed = False
            if account_id:
                for svc, aid in list(ga.items()):
                    if aid == account_id:
                        ga[svc] = ""
                        changed = True
            else:
                if any(v for v in ga.values()):
                    ga = {"gmail": "", "calendar": "", "drive": ""}
                    changed = True
            if changed:
                update_agent(agent["id"], google_accounts=json.dumps(ga))
    except Exception as e:
        logger.warning("Failed to clear agent Google references: %s", e)


async def disconnect(account_id: str = "") -> dict:
    """Revoke tokens and remove account(s). Does NOT touch auth-profiles.json."""
    from integrations.registry import get_credentials, _GOOGLE_FILE_LOCK, _read_google_creds, _write_google_creds

    if account_id:
        acct = get_google_account(account_id)
        if acct:
            await _revoke_token(acct)
            delete_google_account(account_id)
        _clear_agent_references(account_id)
    else:
        accounts = list_google_accounts()
        for acct in accounts.values():
            await _revoke_token(acct)

        with _GOOGLE_FILE_LOCK:
            creds = _read_google_creds()
            preserved_app = creds.get("app")
            preserved_tool_mode = creds.get("tool_mode")
            creds_path = Path(__file__).resolve().parent.parent.parent / "data" / "integrations" / "google.json"
            if creds_path.exists():
                creds_path.unlink()
                logger.info("Removed google.json")
            if preserved_app or preserved_tool_mode:
                new_creds = {}
                if preserved_app:
                    new_creds["app"] = preserved_app
                if preserved_tool_mode:
                    new_creds["tool_mode"] = preserved_tool_mode
                _write_google_creds(new_creds)

        _clear_agent_references()

    return {"ok": True, "account_id": account_id}
