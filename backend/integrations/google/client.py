"""
Chatty — Google API client factory with auto-refresh.

All Gmail / Calendar / Drive operations route through here. The wrapper
transparently refreshes the access token when it's near expiry or when
an API call returns 401, and persists the refreshed tokens back to
auth-profiles.json.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time

from core.providers.oauth import refresh_google_token

logger = logging.getLogger(__name__)

# One global lock — we only have a single Google connection at any time,
# so serializing refresh attempts across Gmail/Calendar/Drive callers is fine.
_REFRESH_LOCK = threading.Lock()


class GoogleAuthError(Exception):
    """Raised when Google OAuth is irrecoverable (refresh token revoked)."""


# ── Token management ─────────────────────────────────────────────────────────

def _load_integration_tokens() -> dict:
    """Read tokens from data/integrations/google.json (NOT auth-profiles.json)."""
    try:
        from integrations.registry import get_credentials
        return get_credentials("google")
    except Exception:
        return {}


def _save_refreshed_tokens(access: str, refresh: str, expires_in: int) -> None:
    """Write refreshed tokens back to google.json."""
    from integrations.registry import get_credentials, save_credentials
    creds = get_credentials("google")
    creds["access_token"] = access
    creds["refresh_token"] = refresh
    creds["token_expires_at"] = time.time() + expires_in
    save_credentials("google", creds)


def _ensure_fresh_token(force: bool = False) -> str:
    """Return a valid access token from google.json. Refreshes if expired.

    Raises GoogleAuthError if no tokens are stored or refresh fails.
    """
    with _REFRESH_LOCK:
        creds = _load_integration_tokens()
        access = creds.get("access_token", "")
        refresh = creds.get("refresh_token", "")
        expires = creds.get("token_expires_at", 0)

        if not access and not refresh:
            raise GoogleAuthError(
                "Google not connected. Connect at Settings → Integrations → Google."
            )

        needs_refresh = force or not expires or time.time() >= (expires - 60)
        if not needs_refresh:
            return access

        if not refresh:
            raise GoogleAuthError(
                "Google access expired and no refresh token is stored. Reconnect Google."
            )

        try:
            tokens = _run_sync(refresh_google_token(refresh))
        except Exception as e:
            logger.error("Google token refresh failed: %s", e)
            _mark_broken()
            raise GoogleAuthError(
                "Google connection expired. Reconnect at Settings → Integrations → Google."
            ) from e

        new_access = tokens.get("access_token", "")
        new_expires = tokens.get("expires_in", 3600)
        new_refresh = tokens.get("refresh_token", refresh)

        _save_refreshed_tokens(new_access, new_refresh, new_expires)
        return new_access


def _run_sync(coro):
    """Run an async coroutine from sync code.

    If we're inside an async context (FastAPI request handler), we cannot
    call asyncio.run directly — it would conflict with the running loop.
    We run the coroutine in a background thread with its own loop. In a
    purely-sync context, we just spin up a one-shot loop here.
    """
    import concurrent.futures
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        # No running loop — safe to run directly
        return asyncio.run(coro)

    # Inside an async context — offload to a thread
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


def _mark_broken() -> None:
    """Set connection_status=broken in data/integrations/google.json."""
    try:
        from integrations.registry import get_credentials, save_credentials
        creds = get_credentials("google")
        if creds:
            creds["connection_status"] = "broken"
            save_credentials("google", creds)
    except Exception as e:
        logger.warning("Failed to mark Google connection broken: %s", e)


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


def get_gmail_service():
    """Return an authenticated Gmail v1 service."""
    access = _ensure_fresh_token()
    return _build_service("gmail", "v1", access)


def get_calendar_service():
    """Return an authenticated Calendar v3 service."""
    access = _ensure_fresh_token()
    return _build_service("calendar", "v3", access)


def get_drive_service():
    """Return an authenticated Drive v3 service."""
    access = _ensure_fresh_token()
    return _build_service("drive", "v3", access)


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


def call_with_refresh(service_factory, operation, *args, **kwargs):
    """Run `operation(service, *args, **kwargs)` with one automatic 401 retry.

    On 401, force-refresh the token, rebuild the service, retry once.
    Wraps Google library HttpError into GoogleAuthError with actionable text
    when refresh itself fails.

    Args:
        service_factory: Callable that returns a fresh Google API service
                         (e.g. get_gmail_service).
        operation: Callable taking (service, *args, **kwargs) and performing the API call.
    """
    try:
        from googleapiclient.errors import HttpError
    except ImportError:
        HttpError = Exception  # type: ignore

    service = service_factory()
    try:
        return operation(service, *args, **kwargs)
    except HttpError as e:
        status = getattr(getattr(e, "resp", None), "status", None)
        if status == 401:
            logger.info("Google 401 — forcing token refresh and retrying once")
            _ensure_fresh_token(force=True)
            service = service_factory()
            try:
                return operation(service, *args, **kwargs)
            except HttpError as retry_err:
                retry_status = getattr(getattr(retry_err, "resp", None), "status", None)
                if retry_status == 401:
                    _mark_broken()
                    raise GoogleAuthError(
                        "Google connection expired. Reconnect at Settings → Integrations → Google."
                    ) from retry_err
                if retry_status == 403:
                    _maybe_raise_scope_error(retry_err)
                raise
        if status == 403:
            _maybe_raise_scope_error(e)
        raise
