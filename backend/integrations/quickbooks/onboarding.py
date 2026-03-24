"""Chatty — QuickBooks Online OAuth2 setup flow."""

import logging
from integrations.registry import save_credentials

logger = logging.getLogger(__name__)


def setup_from_oauth(
    company_id: str,
    access_token: str,
    refresh_token: str,
    client_id: str,
    client_secret: str,
    expires_in: int = 3600,
) -> dict:
    """Save QBO OAuth2 credentials after completing the OAuth flow."""
    import time
    save_credentials("quickbooks", {
        "company_id": company_id,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "client_id": client_id,
        "client_secret": client_secret,
        "token_expires_at": time.time() + expires_in,
        "enabled": True,
    })
    return {"ok": True}
