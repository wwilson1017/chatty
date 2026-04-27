"""
Chatty — Shopify integration onboarding.

Validates credentials and saves them to data/integrations/shopify.json.
"""

import re

from integrations.registry import save_credentials

from .client import ShopifyClient

SHOP_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$")


def _normalize_shop_name(raw: str) -> str:
    """Normalize shop name from various input formats to just the slug."""
    name = raw.strip().lower()
    for prefix in ("https://", "http://"):
        if name.startswith(prefix):
            name = name[len(prefix):]
    name = name.rstrip("/")
    if name.endswith("/admin"):
        name = name[: -len("/admin")]
    if name.endswith(".myshopify.com"):
        name = name[: -len(".myshopify.com")]
    return name


def setup(shop_name: str, admin_token: str) -> dict:
    """Validate Shopify credentials and save them."""
    shop_name = _normalize_shop_name(shop_name)

    if not shop_name:
        return {"ok": False, "error": "Shop name is required"}
    if not SHOP_SLUG_RE.match(shop_name):
        return {
            "ok": False,
            "error": f"Invalid shop name '{shop_name}'. Use just the store slug (e.g. 'my-store' from my-store.myshopify.com).",
        }
    if not admin_token or not admin_token.strip():
        return {"ok": False, "error": "Admin API access token is required"}

    client = ShopifyClient(shop_name=shop_name, admin_token=admin_token.strip())
    if not client.test_connection():
        return {"ok": False, "error": "Connection failed — check your shop name and admin token"}

    save_credentials("shopify", {
        "shop_name": shop_name,
        "admin_token": admin_token.strip(),
        "enabled": True,
    })
    return {"ok": True}
