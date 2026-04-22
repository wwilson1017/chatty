"""Chatty — Odoo database auto-discovery.

Discovers available databases on an Odoo instance using public (unauthenticated)
endpoints. Tries XML-RPC db.list(), then JSON-RPC /web/database/list, then URL
inference as a final fallback.
"""

import ipaddress
import logging
import socket
import xmlrpc.client
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)


def discover_databases(url: str) -> dict:
    """Discover available databases on an Odoo instance.

    Returns dict with keys: databases, method, error.
    """
    url = _normalize_url(url)
    if not url:
        return {"databases": [], "method": None, "error": "Invalid URL"}

    err = _check_ssrf(url)
    if err:
        return {"databases": [], "method": None, "error": err}

    # Tier 1: XML-RPC db.list()
    dbs = _try_xmlrpc_db_list(url)
    if dbs is not None:
        return {"databases": dbs, "method": "xmlrpc", "error": None}

    # Tier 2: JSON-RPC /web/database/list
    dbs = _try_jsonrpc_db_list(url)
    if dbs is not None:
        return {"databases": dbs, "method": "jsonrpc", "error": None}

    # Tier 3: URL inference
    dbs = _infer_from_url(url)
    if dbs:
        return {"databases": dbs, "method": "url_inference", "error": None}

    return {
        "databases": [],
        "method": None,
        "error": "Could not discover databases. The instance may have database listing disabled. Please enter the database name manually.",
    }


def _check_ssrf(url: str) -> str | None:
    """Reject URLs that resolve to private/internal IPs. Returns error message or None."""
    parsed = urlparse(url)
    host = parsed.hostname or ""
    return _validate_host(host)


def _validate_host(host: str) -> str | None:
    """Resolve host and reject private/internal IPs. Returns error or None."""
    try:
        addrs = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return f"Cannot resolve host: {host}"
    for info in addrs:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            return "Requests to internal addresses are not allowed"
    return None


def _normalize_url(url: str) -> str:
    """Strip trailing slashes, ensure https:// prefix."""
    url = url.strip()
    if not url:
        return ""
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"
    return url.rstrip("/")


class _TimeoutTransport(xmlrpc.client.Transport):
    def __init__(self, timeout: int):
        super().__init__()
        self._timeout = timeout

    def make_connection(self, host):
        conn = super().make_connection(host)
        conn.timeout = self._timeout
        return conn


class _TimeoutSafeTransport(xmlrpc.client.SafeTransport):
    def __init__(self, timeout: int):
        super().__init__()
        self._timeout = timeout

    def make_connection(self, host):
        conn = super().make_connection(host)
        conn.timeout = self._timeout
        return conn


def _try_xmlrpc_db_list(url: str) -> list[str] | None:
    """Returns None if unavailable."""
    try:
        host = urlparse(url).hostname or ""
        if _validate_host(host):
            return None
        transport = _TimeoutSafeTransport(5) if url.startswith("https") else _TimeoutTransport(5)
        proxy = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/db", transport=transport)
        result = proxy.list()
        if isinstance(result, list):
            return result
        return None
    except xmlrpc.client.Fault:
        return None
    except (OSError, socket.timeout, xmlrpc.client.ProtocolError):
        return None
    except Exception as e:
        logger.debug("XML-RPC db.list() failed for %s: %s", url, e)
        return None


def _try_jsonrpc_db_list(url: str) -> list[str] | None:
    """Returns None if unavailable."""
    try:
        host = urlparse(url).hostname or ""
        if _validate_host(host):
            return None
        resp = httpx.post(
            f"{url}/web/database/list",
            json={"jsonrpc": "2.0", "method": "call", "params": {}},
            timeout=5,
            follow_redirects=False,
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        result = data.get("result")
        if isinstance(result, list):
            return result
        return None
    except (httpx.HTTPError, httpx.InvalidURL, OSError, ValueError):
        return None


def _infer_from_url(url: str) -> list[str]:
    """Infer database name from URL pattern."""
    parsed = urlparse(url)
    host = parsed.hostname or ""

    # *.odoo.com — database is the subdomain
    if host.endswith(".odoo.com") and host != "www.odoo.com":
        subdomain = host.removesuffix(".odoo.com")
        if subdomain:
            return [subdomain]

    # *.odoo.sh — subdomain is a likely prefix
    if host.endswith(".odoo.sh"):
        subdomain = host.removesuffix(".odoo.sh")
        if subdomain:
            return [subdomain]

    return []
