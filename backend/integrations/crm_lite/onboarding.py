"""Chatty — CRM Lite onboarding (no credentials needed — built-in)."""

from .db import init_db
from integrations.registry import save_credentials


def setup() -> dict:
    """Initialize CRM Lite database and mark as enabled."""
    init_db()
    save_credentials("crm_lite", {"enabled": True})
    return {"ok": True}
