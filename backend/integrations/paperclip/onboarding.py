"""Chatty — Paperclip integration setup.

Logs into Paperclip with email/password, discovers companies, and persists session.
"""

import logging

from .client import login

logger = logging.getLogger(__name__)


def setup(url: str, email: str, password: str, company_id: str = "") -> dict:
    """Login to Paperclip, discover companies, and save credentials."""
    from integrations.registry import get_credentials, save_credentials

    result = login(url, email, password)
    if "error" in result:
        return result

    companies = result.get("companies", [])
    user = result.get("user", {})

    if not company_id and len(companies) == 1:
        company_id = companies[0]["id"]
    elif not company_id and len(companies) > 1:
        return {
            "ok": True,
            "needs_company_selection": True,
            "companies": [{"id": c["id"], "name": c["name"]} for c in companies],
            "session_cookie": result["session_cookie"],
            "user_name": user.get("name", ""),
        }
    elif not company_id:
        return {"error": "No companies found in your Paperclip account. Create one in the Paperclip UI first."}

    company_name = company_id
    for c in companies:
        if c["id"] == company_id:
            company_name = c.get("name", company_id)
            break

    existing = get_credentials("paperclip")
    existing.update({
        "enabled": True,
        "url": url,
        "email": email,
        "company_id": company_id,
        "company_name": company_name,
        "session_cookie": result["session_cookie"],
        "user_name": user.get("name", ""),
    })
    if "agent_mapping" not in existing:
        existing["agent_mapping"] = {}
    if "webhook_secret" not in existing:
        existing["webhook_secret"] = ""
    save_credentials("paperclip", existing)

    logger.info("Paperclip integration configured: %s (%s)", company_name, url)
    return {"ok": True, "company_name": company_name, "user_name": user.get("name", "")}
