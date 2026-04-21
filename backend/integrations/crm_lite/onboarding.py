"""Chatty — CRM Lite onboarding (no credentials needed — built-in)."""

from .db import init_db
from .seed_data import seed_demo_data
from integrations.registry import get_credentials, save_credentials


def setup() -> dict:
    """Initialize CRM Lite database, seed example data, and mark as enabled."""
    init_db()
    seeded = seed_demo_data()
    creds = get_credentials("crm_lite")
    creds["enabled"] = True
    if seeded:
        creds["demo_mode"] = True
    save_credentials("crm_lite", creds)
    return {"ok": True}
