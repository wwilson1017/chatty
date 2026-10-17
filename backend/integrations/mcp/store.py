"""Chatty — MCP server storage and call policy. Nothing here touches the network.

data/integrations/mcp.json, through registry.save_credentials (nested dicts are
encrypted by field name, so `api_key` is; lists are left alone, so the tool cache is):

    {"enabled": bool, "tool_mode": "normal",
     "servers": {"<id>": {
         "name", "url", "api_key", "header", "enabled", "allow_in_background",
         "generation": int,            # changes with the auth config; an OAuth flow is bound to it
         "oauth": dict | None,         # see oauth.py; None for a server with an API key
         "tools": [{"name", "description", "input_schema", "read_only_hint"}],  # cached
         "tools_refreshed_at": epoch, "last_error": str | None,
         "overrides": {"<tool>": {"enabled": bool, "read_only": bool}}}}}

The server id is a slug of its name and the first half of every tool name.
"""

import hashlib
import re
import threading

from integrations.registry import get_credentials, get_tool_mode, is_enabled, save_credentials

NAME = "mcp"
MAX_TOOL_NAME = 64
MAX_DESCRIPTION = 1000
REFRESH_SECONDS = 6 * 3600
_lock = threading.RLock()


def creds() -> dict:
    return get_credentials(NAME)


def servers() -> dict:
    return creds().get("servers") or {}


def update(fn):
    """Read-modify-write mcp.json under a lock; returns what `fn` returns."""
    with _lock:
        c = creds()
        out = fn(c)
        save_credentials(NAME, c)
        return out


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:24] or "server"


def unique_tool_name(server_id: str, tool: str, seen: set[str]) -> str:
    """mcp_<server>__<tool>, provider-safe ([A-Za-z0-9_-], 64 chars); a hash suffix on overflow or collision."""
    raw = f"mcp_{server_id}__{tool}"
    name = re.sub(r"[^A-Za-z0-9_-]", "_", raw)
    if len(name) > MAX_TOOL_NAME or name in seen:
        name = f"{name[:MAX_TOOL_NAME - 9]}_{hashlib.sha1(raw.encode()).hexdigest()[:8]}"
    seen.add(name)
    return name


def tool_policy(server: dict, tool: str) -> dict:
    """The user's settings for one tool: every tool is enabled and a write until they say otherwise."""
    ov = (server.get("overrides") or {}).get(tool) or {}
    return {"enabled": bool(ov.get("enabled", True)), "writes": not ov.get("read_only", False)}


def call_error(server_id: str, tool: str, loaded_writes: bool, origin: str) -> str | None:
    """Why a call to `tool` on `server_id` may not run right now, or None.

    Read from the file on every call, so a change on the card applies to tools already
    loaded in a conversation. `loaded_writes` is the writes flag of the definition the
    model was given: a tool that has since become a write (or whose integration mode now
    forbids writes) is refused so the next turn reloads it and goes through confirmation.
    PR 11 (command servers) adds its checks here.
    """
    if not is_enabled(NAME):
        return "MCP servers are turned off."
    s = servers().get(server_id)
    if not s or not s.get("enabled", True):
        return f"MCP server '{server_id}' is turned off."
    pol = tool_policy(s, tool)
    if not pol["enabled"]:
        return f"Tool '{tool}' is turned off for this server."
    if pol["writes"] and (not loaded_writes or get_tool_mode(NAME) == "read-only"):
        return "This tool's permissions changed; ask again."
    if pol["writes"] and origin != "user" and not s.get("allow_in_background"):
        return (f"'{tool}' changes things, and '{s['name']}' is not allowed to do that in background "
                "turns. Turn on 'allow in background' for the server on the MCP card, or ask in chat.")
    return None


def clean_schema(schema: dict) -> dict:
    """A provider-safe input schema: local $refs inlined, nullable unions collapsed, $defs dropped (Gemini rejects both)."""
    defs = {**(schema.get("$defs") or {}), **(schema.get("definitions") or {})}

    def walk(node, depth=0):
        if depth > 32:
            return {}
        if isinstance(node, list):
            return [walk(n, depth + 1) for n in node]
        if not isinstance(node, dict):
            return node
        node = dict(node)
        ref = node.pop("$ref", None)
        if isinstance(ref, str) and ref.startswith("#/"):
            node = {**defs.get(ref.rsplit("/", 1)[-1], {}), **node}
        for key in ("anyOf", "oneOf"):
            variants = node.get(key)
            if isinstance(variants, list):
                real = [v for v in variants if not (isinstance(v, dict) and v.get("type") == "null")]
                if len(real) == 1 and len(variants) > 1:
                    node.pop(key)
                    node = {**real[0], **node}
        if isinstance(node.get("type"), list):
            real = [t for t in node["type"] if t != "null"]
            node["type"] = real[0] if len(real) == 1 else real
        return {k: walk(v, depth + 1) for k, v in node.items() if k not in ("$defs", "definitions", "$schema")}

    out = walk(schema or {})
    out.setdefault("type", "object")
    out.setdefault("properties", {})
    return out
