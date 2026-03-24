"""Chatty — BambooHR integration onboarding (credential validation)."""

from .client import BambooHRClient
from integrations.registry import save_credentials


def setup(subdomain: str, api_key: str) -> dict:
    """Validate BambooHR credentials and save them."""
    client = BambooHRClient(api_key=api_key, subdomain=subdomain)
    if not client.test_connection():
        return {"ok": False, "error": "Connection failed — check subdomain and API key"}
    save_credentials("bamboohr", {
        "subdomain": subdomain,
        "api_key": api_key,
        "enabled": True,
    })
    return {"ok": True}
