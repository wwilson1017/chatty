"""Chatty — Paperclip integration setup.

Validates the Paperclip connection and persists credentials.
"""

import logging

from .client import PaperclipClient

logger = logging.getLogger(__name__)


def setup(url: str, company_id: str, api_key: str = "") -> dict:
    """Validate connection and save Paperclip credentials.

    Returns {"ok": True} on success or {"error": "..."} on failure.
    """
    from integrations.registry import get_credentials, save_credentials

    client = PaperclipClient(
        base_url=url,
        company_id=company_id,
        bearer_token=api_key,
    )
    result = client.get_company()
    if "error" in result:
        return {"error": f"Cannot reach Paperclip: {result['error']}"}

    company_name = result.get("name", "Unknown")

    existing = get_credentials("paperclip")
    existing.update({
        "enabled": True,
        "url": url,
        "company_id": company_id,
        "api_key": api_key,
        "company_name": company_name,
    })
    if "agent_mapping" not in existing:
        existing["agent_mapping"] = {}
    if "webhook_secret" not in existing:
        existing["webhook_secret"] = ""
    save_credentials("paperclip", existing)

    logger.info("Paperclip integration configured: %s (%s)", company_name, url)
    return {"ok": True, "company_name": company_name}
