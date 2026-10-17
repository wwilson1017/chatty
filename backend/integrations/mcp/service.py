"""Chatty — card-facing MCP operations: add, remove and change servers, refresh their
tool lists. The only MCP module besides the executors that talks to a server.
Every operation returns status(), which never includes an api_key.
"""

import asyncio
import logging
import time

from core.security.ssrf import validate_url

from . import store
from .client import McpClient, McpError

logger = logging.getLogger(__name__)


def status() -> dict:
    c = store.creds()
    return {"enabled": bool(c.get("enabled")),
            "servers": [_view(sid, s) for sid, s in (c.get("servers") or {}).items()]}


def _view(sid: str, s: dict) -> dict:
    return {
        "id": sid, "name": s["name"], "url": s["url"], "header": s.get("header") or "Authorization",
        "has_key": bool(s.get("api_key")), "enabled": s.get("enabled", True),
        "allow_in_background": bool(s.get("allow_in_background")),
        "tools_refreshed_at": s.get("tools_refreshed_at"), "last_error": s.get("last_error"),
        "tools": [{"name": t["name"], "description": (t.get("description") or "")[:300],
                   "read_only_hint": t.get("read_only_hint"), **store.tool_policy(s, t["name"])}
                  for t in s.get("tools") or []],
    }


def _cache_entry(t: dict) -> dict:
    ann = t.get("annotations") if isinstance(t.get("annotations"), dict) else {}
    return {
        "name": str(t["name"])[:128],
        "description": str(t.get("description") or "")[:store.MAX_DESCRIPTION],
        "input_schema": t.get("inputSchema") if isinstance(t.get("inputSchema"), dict) else {},
        "read_only_hint": bool(ann["readOnlyHint"]) if "readOnlyHint" in ann else None,
    }


async def _fetch_tools(url: str, api_key: str, header: str) -> list[dict]:
    return [_cache_entry(t) for t in await McpClient(url, api_key, header).list_tools()]


async def add_server(name: str, url: str, api_key: str, header: str) -> dict:
    """Validate the URL, fetch the tool list (the connection test) and save. Raises ValueError / McpError."""
    name, url, api_key = name.strip(), url.strip(), api_key.strip()
    if err := validate_url(url):
        raise ValueError(err)
    if not api_key.isprintable():  # httpx would echo an illegal header value, key included, in its error
        raise ValueError("API key contains control characters")
    tools = await _fetch_tools(url, api_key, header)

    def apply(c):
        servers = c.setdefault("servers", {})
        sid = base = store.slug(name)
        n = 2
        while sid in servers:
            sid, n = f"{base}_{n}", n + 1
        servers[sid] = {"name": name, "url": url, "api_key": api_key, "header": header or "Authorization",
                        "enabled": True, "allow_in_background": False, "tools": tools,
                        "tools_refreshed_at": time.time(), "last_error": None, "overrides": {}}
        c.setdefault("enabled", True)  # the first server switches the integration on
    store.update(apply)
    return status()


async def refresh_server(server_id: str) -> dict:
    """Re-fetch one server's tool list; a failure is recorded as last_error and the old list kept."""
    s = store.servers().get(server_id)
    if not s:
        raise KeyError(server_id)
    tools, error = None, validate_url(s["url"])
    if not error:
        try:
            tools = await _fetch_tools(s["url"], s.get("api_key") or "", s.get("header") or "Authorization")
        except McpError as e:
            error = str(e)

    def apply(c):
        cur = (c.get("servers") or {}).get(server_id)
        if cur is None:
            return
        if tools is not None:
            cur["tools"], cur["tools_refreshed_at"] = tools, time.time()
        cur["last_error"] = error
    store.update(apply)
    return status()


def refresh_stale() -> None:
    """Scheduler job (sync, APScheduler thread): re-fetch tool lists older than REFRESH_SECONDS."""
    if not store.is_enabled(store.NAME):
        return
    now = time.time()
    for sid, s in store.servers().items():
        if s.get("enabled", True) and now - (s.get("tools_refreshed_at") or 0) > store.REFRESH_SECONDS:
            try:
                asyncio.run(refresh_server(sid))
            except Exception:
                logger.warning("MCP tool refresh failed for %s", sid, exc_info=True)


def remove_server(server_id: str) -> dict:
    store.update(lambda c: (c.get("servers") or {}).pop(server_id, None))
    return status()


def update_server(server_id: str, enabled: bool | None = None, allow_in_background: bool | None = None) -> dict:
    def apply(c):
        s = (c.get("servers") or {}).get(server_id)
        if s is None:
            raise KeyError(server_id)
        if enabled is not None:
            s["enabled"] = enabled
        if allow_in_background is not None:
            s["allow_in_background"] = allow_in_background
    store.update(apply)
    return status()


def set_tool(server_id: str, tool: str, enabled: bool | None = None, read_only: bool | None = None) -> dict:
    def apply(c):
        s = (c.get("servers") or {}).get(server_id)
        if s is None or tool not in {t["name"] for t in s.get("tools") or []}:
            raise KeyError(tool)
        ov = s.setdefault("overrides", {}).setdefault(tool, {})
        if enabled is not None:
            ov["enabled"] = enabled
        if read_only is not None:
            ov["read_only"] = read_only
    store.update(apply)
    return status()
