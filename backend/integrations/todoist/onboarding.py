"""Chatty — Todoist integration onboarding (credential validation)."""

from .client import test_connection
from integrations.registry import save_credentials


def setup(api_token: str) -> dict:
    """Validate Todoist API token and save credentials."""
    if not test_connection(api_token):
        return {"ok": False, "error": "Connection failed — check your API token"}
    save_credentials("todoist", {
        "api_key": api_token,
        "enabled": True,
    })
    return {"ok": True}
