"""
Chatty — Shopify REST Admin API client.

Credentials loaded from data/integrations/shopify.json.
Uses Admin API access token authentication (no OAuth).
"""

import logging
import re
from urllib.parse import parse_qs, urlparse

import httpx

logger = logging.getLogger(__name__)

_LINK_RE = re.compile(r'<([^>]+)>;\s*rel="(\w+)"')


class ShopifyClient:
    """Client for Shopify REST Admin API."""

    API_VERSION = "2025-10"

    def __init__(self, shop_name: str, admin_token: str):
        self.shop_name = shop_name
        self.admin_token = admin_token
        self.base_url = f"https://{shop_name}.myshopify.com/admin/api/{self.API_VERSION}"

    def _headers(self) -> dict:
        return {
            "X-Shopify-Access-Token": self.admin_token,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def test_connection(self) -> bool:
        """Validate credentials by fetching shop info."""
        try:
            resp = httpx.get(
                f"{self.base_url}/shop.json",
                headers=self._headers(),
                timeout=10,
            )
            return resp.status_code == 200
        except Exception as e:
            logger.error("Shopify connection error: %s", e)
            return False

    def _parse_link_header(self, link_header: str | None) -> dict[str, str]:
        """Parse Shopify Link header for cursor pagination.

        Returns dict with 'next' and/or 'previous' page_info values.
        """
        if not link_header:
            return {}
        result = {}
        for match in _LINK_RE.finditer(link_header):
            url, rel = match.group(1), match.group(2)
            parsed = urlparse(url)
            qs = parse_qs(parsed.query)
            page_info = qs.get("page_info", [None])[0]
            if page_info:
                result[rel] = page_info
        return result

    def _request(
        self,
        method: str,
        path: str,
        params: dict | None = None,
        json_body: dict | None = None,
        timeout: int = 15,
    ) -> dict:
        """Execute a Shopify API request.

        Returns dict with 'ok', 'status_code', 'data', and 'next_page_info'.
        """
        url = f"{self.base_url}{path}"
        try:
            resp = httpx.request(
                method,
                url,
                headers=self._headers(),
                params=params,
                json=json_body,
                timeout=timeout,
            )

            limit_header = resp.headers.get("X-Shopify-Shop-Api-Call-Limit")
            if limit_header:
                logger.debug("Shopify rate limit: %s", limit_header)

            ok = 200 <= resp.status_code < 300
            try:
                data = resp.json()
            except Exception:
                data = resp.text

            if not ok:
                logger.warning("Shopify API %s %s returned %s", method, path, resp.status_code)

            pagination = self._parse_link_header(resp.headers.get("link"))
            return {
                "ok": ok,
                "status_code": resp.status_code,
                "data": data,
                "next_page_info": pagination.get("next"),
            }
        except Exception as e:
            logger.error("Shopify API request failed: %s %s — %s", method, path, e)
            return {"ok": False, "status_code": 0, "data": str(e), "next_page_info": None}

    def get(self, path: str, params: dict | None = None, timeout: int = 15) -> dict:
        return self._request("GET", path, params=params, timeout=timeout)

    def post(self, path: str, json_body: dict | None = None, timeout: int = 15) -> dict:
        return self._request("POST", path, json_body=json_body, timeout=timeout)

    def put(self, path: str, json_body: dict | None = None, timeout: int = 15) -> dict:
        return self._request("PUT", path, json_body=json_body, timeout=timeout)


def get_client() -> ShopifyClient | None:
    """Return a configured ShopifyClient from stored credentials, or None."""
    from integrations.registry import get_credentials, is_enabled

    if not is_enabled("shopify"):
        return None
    creds = get_credentials("shopify")
    return ShopifyClient(
        shop_name=creds.get("shop_name", ""),
        admin_token=creds.get("admin_token", ""),
    )
