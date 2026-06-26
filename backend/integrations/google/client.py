"""
Chatty — Google API client factory with auto-refresh (multi-account).

All Gmail / Calendar / Drive operations route through here. The wrapper
transparently refreshes the access token when it's near expiry or when
an API call returns 401, and persists the refreshed tokens back to
google.json under the correct account entry.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time

import httpx

from core.providers.oauth import refresh_google_token

logger = logging.getLogger(__name__)

_ACCOUNT_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_LOCK = threading.Lock()


def _get_account_lock(account_id: str) -> threading.Lock:
    with _LOCKS_LOCK:
        if account_id not in _ACCOUNT_LOCKS:
            _ACCOUNT_LOCKS[account_id] = threading.Lock()
        return _ACCOUNT_LOCKS[account_id]


class GoogleAuthError(Exception):
    """Raised when Google OAuth is irrecoverable (refresh token revoked)."""


# ── Token management ─────────────────────────────────────────────────────────

def _load_integration_tokens(account_id: str) -> dict:
    """Read tokens for a specific account from google.json."""
    try:
        from integrations.registry import get_google_account
        return get_google_account(account_id)
    except Exception:
        return {}


def _save_refreshed_tokens(account_id: str, access: str, refresh: str, expires_in: int) -> None:
    """Merge refreshed token fields into the account entry atomically."""
    from integrations.registry import _GOOGLE_FILE_LOCK, _read_google_creds, _write_google_creds
    with _GOOGLE_FILE_LOCK:
        creds = _read_google_creds()
        accounts = creds.get("accounts", {})
        if account_id not in accounts:
            return
        accounts[account_id]["access_token"] = access
        accounts[account_id]["refresh_token"] = refresh
        accounts[account_id]["token_expires_at"] = time.time() + expires_in
        _write_google_creds(creds)


def _ensure_fresh_token(account_id: str, force: bool = False) -> str:
    """Return a valid access token for the given account. Refreshes if expired.

    Raises GoogleAuthError if no tokens are stored or refresh fails.
    """
    lock = _get_account_lock(account_id)
    with lock:
        creds = _load_integration_tokens(account_id)
        access = creds.get("access_token", "")
        refresh = creds.get("refresh_token", "")
        expires = creds.get("token_expires_at", 0)

        if not access and not refresh:
            raise GoogleAuthError(
                "Google account not connected. Connect at Settings → Integrations → Google."
            )

        needs_refresh = force or not expires or time.time() >= (expires - 60)
        if not needs_refresh:
            return access

        if not refresh:
            _mark_broken(account_id)
            raise GoogleAuthError(
                "Google access expired and no refresh token is stored. Reconnect Google."
            )

        try:
            tokens = _run_sync(refresh_google_token(refresh))
        except httpx.HTTPStatusError as e:
            is_permanent = (
                e.response.status_code == 400
                and "invalid_grant" in e.response.text
            )
            if is_permanent:
                logger.error("Google refresh token revoked for account %s", account_id)
                _mark_broken(account_id)
                raise GoogleAuthError(
                    "Google refresh token revoked. Reconnect at Settings → Integrations → Google."
                ) from e
            logger.warning("Transient Google refresh error for account %s (HTTP %d): %s",
                           account_id, e.response.status_code, e)
            raise GoogleAuthError(
                "Temporary Google error. Will retry on next request."
            ) from e
        except Exception as e:
            logger.warning("Transient Google refresh error for account %s: %s", account_id, e)
            raise GoogleAuthError(
                "Temporary Google error. Will retry on next request."
            ) from e

        new_access = tokens.get("access_token", "")
        new_expires = tokens.get("expires_in", 3600)
        new_refresh = tokens.get("refresh_token", refresh)

        _save_refreshed_tokens(account_id, new_access, new_refresh, new_expires)
        _mark_ok(account_id)
        return new_access


def _run_sync(coro):
    """Run an async coroutine from sync code."""
    import concurrent.futures
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


def _mark_broken(account_id: str) -> None:
    """Set connection_status=broken for a specific account and alert assigned agents."""
    try:
        from integrations.registry import get_google_account, save_google_account
        acct = get_google_account(account_id)
        if acct:
            acct["connection_status"] = "broken"
            first_break = not acct.get("broken_at")
            if first_break:
                acct["broken_at"] = time.time()
            save_google_account(account_id, acct)
            if first_break:
                _fire_broken_alerts(account_id, acct.get("email", account_id))
    except Exception as e:
        logger.warning("Failed to mark Google account %s broken: %s", account_id, e)


def _mark_ok(account_id: str) -> None:
    """Restore connection_status=ok and resolve alerts if previously broken."""
    try:
        from integrations.registry import get_google_account, save_google_account
        acct = get_google_account(account_id)
        if not acct:
            return
        was_broken = acct.get("connection_status") == "broken"
        if not was_broken:
            return
        acct["connection_status"] = "ok"
        acct.pop("broken_at", None)
        save_google_account(account_id, acct)
        try:
            from core.agents.alerts.service import resolve_by_source
            resolve_by_source("google_connection", f"google:{account_id}")
        except Exception as e:
            logger.warning("Failed to resolve alerts for Google account %s: %s", account_id, e)
        logger.info("Google account %s (%s) restored to ok", account_id, acct.get("email", "?"))
    except Exception as e:
        logger.warning("Failed to mark Google account %s ok: %s", account_id, e)


def _fire_broken_alerts(account_id: str, email: str) -> None:
    """Create a google_connection alert for each agent assigned to this account."""
    try:
        from agents.db import list_agents
        from core.agents.alerts.service import create_alert
        from integrations.google.policy import GOOGLE_SERVICES
        for agent in list_agents():
            ga = agent.get("google_accounts", {})
            if not isinstance(ga, dict):
                continue
            uses_account = any(
                account_id in (ga.get(svc) or [])
                for svc in GOOGLE_SERVICES
            )
            if uses_account:
                create_alert(
                    agent=agent["slug"],
                    title=f"Google connection broken: {email}",
                    message=(
                        f"The Google account {email} has lost its connection. "
                        f"Email, calendar, drive, and workspace tools for this account are disabled. "
                        f"Reconnect at Settings → Integrations → Google."
                    ),
                    source="google_connection",
                    source_id=f"google:{account_id}",
                )
    except Exception as e:
        logger.warning("Failed to create broken connection alerts: %s", e)


def try_heal_broken_accounts() -> list[str]:
    """Retry refresh for legacy broken accounts (no broken_at). Returns healed IDs."""
    from integrations.registry import list_google_accounts
    healed = []
    for account_id, acct in list_google_accounts().items():
        if acct.get("connection_status") != "broken":
            continue
        if acct.get("broken_at"):
            continue
        refresh_token = acct.get("refresh_token", "")
        if not refresh_token:
            continue
        try:
            tokens = _run_sync(refresh_google_token(refresh_token))
            _save_refreshed_tokens(
                account_id,
                tokens.get("access_token", ""),
                tokens.get("refresh_token", refresh_token),
                tokens.get("expires_in", 3600),
            )
            _mark_ok(account_id)
            healed.append(account_id)
            logger.info("Self-healed legacy broken Google account %s (%s)",
                         account_id, acct.get("email", "?"))
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 400 and "invalid_grant" in e.response.text:
                _mark_broken(account_id)
                logger.info("Legacy broken account %s confirmed revoked", account_id)
            else:
                logger.debug("Legacy heal retry failed for %s (HTTP %d)", account_id, e.response.status_code)
        except Exception as e:
            logger.debug("Legacy heal retry failed for %s: %s", account_id, e)
    return healed


# ── Service factories ────────────────────────────────────────────────────────

def _build_service(api_name: str, version: str, access_token: str):
    """Construct a googleapiclient service from an access token."""
    try:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
    except ImportError as e:
        raise GoogleAuthError(
            "Google API libraries not installed. Run: pip install google-api-python-client google-auth"
        ) from e

    credentials = Credentials(token=access_token)
    return build(api_name, version, credentials=credentials, cache_discovery=False)


def get_gmail_service(account_id: str):
    """Return an authenticated Gmail v1 service for the given account."""
    access = _ensure_fresh_token(account_id)
    return _build_service("gmail", "v1", access)


def get_calendar_service(account_id: str):
    """Return an authenticated Calendar v3 service for the given account."""
    access = _ensure_fresh_token(account_id)
    return _build_service("calendar", "v3", access)


def get_drive_service(account_id: str):
    """Return an authenticated Drive v3 service for the given account."""
    access = _ensure_fresh_token(account_id)
    return _build_service("drive", "v3", access)


def get_docs_service(account_id: str):
    """Return an authenticated Docs v1 service for the given account."""
    access = _ensure_fresh_token(account_id)
    return _build_service("docs", "v1", access)


def get_sheets_service(account_id: str):
    """Return an authenticated Sheets v4 service for the given account."""
    access = _ensure_fresh_token(account_id)
    return _build_service("sheets", "v4", access)


def get_slides_service(account_id: str):
    """Return an authenticated Slides v1 service for the given account."""
    access = _ensure_fresh_token(account_id)
    return _build_service("slides", "v1", access)


# ── Retry wrapper for tool handlers ──────────────────────────────────────────

_SCOPE_ERROR_REASONS = {"insufficientpermissions", "forbidden", "insufficient permission"}


def _maybe_raise_scope_error(err):
    """Raise GoogleAuthError for 403s caused by missing scopes; re-raise others."""
    reason = getattr(err, "reason", "") or ""
    if reason.lower().strip() in _SCOPE_ERROR_REASONS:
        raise GoogleAuthError(
            "Insufficient Google permissions. Disconnect and reconnect Google "
            "at Settings → Integrations → Google to grant the required scopes."
        ) from err
    raise err


def call_with_refresh(account_id: str, service_factory, operation, *args, **kwargs):
    """Run `operation(service, *args, **kwargs)` with one automatic 401 retry.

    On 401, force-refresh the token, rebuild the service, retry once.
    """
    try:
        from googleapiclient.errors import HttpError
    except ImportError:
        HttpError = Exception  # type: ignore

    service = service_factory(account_id)
    try:
        return operation(service, *args, **kwargs)
    except HttpError as e:
        status = getattr(getattr(e, "resp", None), "status", None)
        if status == 401:
            logger.info("Google 401 for account %s — forcing token refresh and retrying once", account_id)
            _ensure_fresh_token(account_id, force=True)
            service = service_factory(account_id)
            try:
                return operation(service, *args, **kwargs)
            except HttpError as retry_err:
                retry_status = getattr(getattr(retry_err, "resp", None), "status", None)
                if retry_status == 401:
                    _mark_broken(account_id)
                    raise GoogleAuthError(
                        "Google connection expired. Reconnect at Settings → Integrations → Google."
                    ) from retry_err
                if retry_status == 403:
                    _maybe_raise_scope_error(retry_err)
                raise
        if status == 403:
            _maybe_raise_scope_error(e)
        raise
