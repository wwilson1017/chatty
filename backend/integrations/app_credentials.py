"""
Chatty — BYO OAuth app credentials.

Manages user-supplied OAuth client_id / client_secret for self-hosted
deployments. Stored in the existing per-integration JSON files under an
"app" sub-dict, encrypted at rest via the standard encrypt_dict() path.

Falls back to env vars (QUICKBOOKS_CLIENT_ID, GOOGLE_CLIENT_ID, etc.)
for dev/CI environments that pre-set them.
"""

import logging

from core.config import settings
from .registry import get_credentials, save_credentials

logger = logging.getLogger(__name__)

_ENV_FALLBACKS = {
    "quickbooks": lambda: (settings.quickbooks_oauth.client_id, settings.quickbooks_oauth.client_secret),
    "google": lambda: (settings.google_oauth.client_id, settings.google_oauth.client_secret),
    "openai": lambda: (settings.openai_oauth.client_id, settings.openai_oauth.client_secret),
}


def get_app_credentials(integration: str) -> dict:
    """Read stored BYO app credentials, falling back to env vars.

    Returns {"client_id": str, "client_secret": str, "environment"?: str}
    or {} if nothing is configured.
    """
    creds = get_credentials(integration)
    app = creds.get("app")
    if isinstance(app, dict) and app.get("client_id") and app.get("client_secret"):
        return app

    fallback = _ENV_FALLBACKS.get(integration)
    if fallback:
        cid, csec = fallback()
        if cid and csec:
            return {"client_id": cid, "client_secret": csec}

    return {}


def save_app_credentials(
    integration: str,
    client_id: str,
    client_secret: str,
    environment: str | None = None,
) -> None:
    """Store BYO app credentials (encrypted at rest)."""
    creds = get_credentials(integration)
    app: dict = {"client_id": client_id, "client_secret": client_secret}
    if environment:
        app["environment"] = environment
    creds["app"] = app
    save_credentials(integration, creds)
    logger.info("Saved app credentials for %s", integration)


def clear_app_credentials(integration: str) -> None:
    """Remove the app sub-dict. Preserves tokens if connected."""
    creds = get_credentials(integration)
    if "app" in creds:
        del creds["app"]
        save_credentials(integration, creds)
        logger.info("Cleared app credentials for %s", integration)


def has_app_credentials(integration: str) -> bool:
    """True if stored creds or env vars provide a client_id + client_secret."""
    return bool(get_app_credentials(integration))
