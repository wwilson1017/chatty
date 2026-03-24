"""Chatty — Odoo integration onboarding (credential validation)."""

import logging
from .client import OdooClient
from integrations.registry import save_credentials, enable

logger = logging.getLogger(__name__)


def setup(url: str, database: str, username: str, api_key: str) -> dict:
    """Validate Odoo credentials and save them. Returns {ok, error}."""
    client = OdooClient(url=url, database=database, username=username, api_key=api_key)
    version = client.test_connection()
    if not version:
        return {"ok": False, "error": "Cannot connect to Odoo — check URL"}
    if not client.authenticate():
        return {"ok": False, "error": "Authentication failed — check username and API key"}

    save_credentials("odoo", {
        "url": url,
        "database": database,
        "username": username,
        "api_key": api_key,
        "enabled": True,
        "version": version.get("server_version", ""),
    })
    return {"ok": True, "version": version.get("server_version", "")}
