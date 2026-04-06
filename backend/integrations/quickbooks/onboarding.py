"""Chatty — QuickBooks Online OAuth2 setup flow."""

import logging
from integrations.registry import save_credentials

logger = logging.getLogger(__name__)


def setup_from_oauth(
    company_id: str,
    access_token: str,
    refresh_token: str,
    expires_in: int = 3600,
) -> dict:
    """Save QBO OAuth2 credentials after completing the OAuth flow."""
    import time
    save_credentials("quickbooks", {
        "company_id": company_id,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_expires_at": time.time() + expires_in,
        "connection_status": "ok",
        "enabled": True,
    })
    return {"ok": True}
