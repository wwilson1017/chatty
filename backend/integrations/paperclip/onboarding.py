"""Chatty — Paperclip integration setup.

Logs into Paperclip with email/password, discovers companies, generates
a webhook secret, and auto-configures Paperclip agents to use Chatty's
webhook endpoint.
"""

import logging
import secrets

from .client import login, PaperclipClient

logger = logging.getLogger(__name__)


def _generate_webhook_secret() -> str:
    return secrets.token_urlsafe(32)


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
    webhook_secret = existing.get("webhook_secret") or _generate_webhook_secret()

    existing.update({
        "enabled": True,
        "url": url,
        "email": email,
        "company_id": company_id,
        "company_name": company_name,
        "session_cookie": result["session_cookie"],
        "user_name": user.get("name", ""),
        "webhook_secret": webhook_secret,
    })
    if "agent_mapping" not in existing:
        existing["agent_mapping"] = {}
    save_credentials("paperclip", existing)

    logger.info("Paperclip integration configured: %s (%s)", company_name, url)
    return {"ok": True, "company_name": company_name, "user_name": user.get("name", "")}


def configure_mapped_agents(chatty_base_url: str = "") -> dict:
    """Configure all mapped Paperclip agents to use Chatty's webhook with the shared secret.

    Called after agent mapping is saved. Updates each mapped Paperclip agent's
    adapter to HTTP with the webhook URL and secret header.
    """
    from integrations.registry import get_credentials

    creds = get_credentials("paperclip")
    if not creds.get("url") or not creds.get("session_cookie"):
        return {"error": "Paperclip not configured"}

    mapping = creds.get("agent_mapping", {})
    if not mapping:
        return {"ok": True, "configured": 0}

    webhook_secret = creds.get("webhook_secret", "")
    if not webhook_secret:
        return {"error": "No webhook secret configured"}

    webhook_url = chatty_base_url.rstrip("/") + "/api/integrations/paperclip/heartbeat" if chatty_base_url else ""
    if not webhook_url:
        return {"ok": True, "configured": 0, "note": "No Chatty base URL provided — skipping agent adapter config"}

    client = PaperclipClient(
        base_url=creds["url"],
        company_id=creds["company_id"],
        session_cookie=creds["session_cookie"],
    )

    configured = 0
    errors = []
    for paperclip_agent_id in mapping:
        result = client.configure_agent_webhook(paperclip_agent_id, webhook_url, webhook_secret)
        if "ok" in result:
            configured += 1
            logger.info("Configured Paperclip agent %s with Chatty webhook", paperclip_agent_id)
        else:
            errors.append(f"{paperclip_agent_id}: {result.get('error', 'unknown')}")
            logger.warning("Failed to configure agent %s: %s", paperclip_agent_id, result.get("error"))

    out: dict = {"ok": True, "configured": configured}
    if errors:
        out["errors"] = errors
    return out
