"""Chatty — QuickBooks CSV Analysis onboarding (no credentials needed)."""

from .db import init_db
from integrations.registry import save_credentials


def setup() -> dict:
    """Initialize QB CSV Analysis database and mark as enabled."""
    init_db()
    save_credentials("qb_csv", {"enabled": True})
    return {"ok": True}
