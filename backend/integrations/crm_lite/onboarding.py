"""Chatty — CRM Lite onboarding (no credentials needed — built-in)."""

from .db import init_db
from integrations.registry import save_credentials


def setup() -> dict:
    """Initialize CRM Lite database (with schema migrations) and mark as enabled."""
    init_db()  # Creates tables + applies migrations for upgrades
    save_credentials("crm_lite", {"enabled": True})
    return {"ok": True}
