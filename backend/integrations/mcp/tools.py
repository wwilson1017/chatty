"""Chatty — MCP tools for agents, built from the tool lists cached in mcp.json.

Every tool is `writes: True` unless the user marked it read-only on the card; a
server's readOnlyHint is only a suggestion there. Definitions carry `context_aware`,
so ToolRegistry hands the executor the server-built `_ctx` and the executor re-checks
policy against the turn's origin on every call. `_ctx` never reaches the server.
Loading reads the file only, never the network.
"""

import json

from . import store
from .client import McpClient, McpError

MAX_RESULT_CHARS = 20000


def _enabled_tools():
    """(server_id, server, cached tool, provider tool name) for every tool an agent may see."""
    seen: set[str] = set()
    for sid, s in store.servers().items():
        if not s.get("enabled", True):
            continue
        for t in s.get("tools") or []:
            if store.tool_policy(s, t["name"])["enabled"]:
                yield sid, s, t, store.unique_tool_name(sid, t["name"], seen)


def MCP_TOOL_DEFS() -> list[dict]:
    return [{
        "name": name,
        "description": f"[{s['name']}] {t.get('description') or t['name']}"[:store.MAX_DESCRIPTION],
        "input_schema": store.clean_schema(t.get("input_schema") or {}),
        "kind": "integration",
        "writes": store.tool_policy(s, t["name"])["writes"],
        "context_aware": True,
    } for sid, s, t, name in _enabled_tools()]


def TOOL_EXECUTORS() -> dict:
    return {name: _executor(sid, t["name"], store.tool_policy(s, t["name"])["writes"])
            for sid, s, t, name in _enabled_tools()}


def _executor(server_id: str, tool: str, loaded_writes: bool):
    async def run(*, _ctx: dict, **arguments) -> dict:
        err = store.call_error(server_id, tool, loaded_writes, _ctx.get("origin") or "background")
        if err:
            return {"error": err}
        s = store.servers()[server_id]
        try:
            result = await McpClient(s["url"], s.get("api_key") or "", s.get("header") or "Authorization").call_tool(tool, arguments)
        except McpError as e:
            return {"error": f"MCP server '{s['name']}': {e}"}
        return _shape(result)
    return run


def _shape(result: dict) -> dict:
    content = [c for c in result.get("content") or [] if isinstance(c, dict)]
    text = "\n".join(str(c.get("text") or "") for c in content if c.get("type") == "text")
    out: dict = {"content": text[:MAX_RESULT_CHARS]}
    if len(text) > MAX_RESULT_CHARS:
        out["truncated"] = True
    if omitted := sorted({str(c.get("type")) for c in content if c.get("type") != "text"}):
        out["omitted_content_types"] = omitted
    if (structured := result.get("structuredContent")) is not None:
        if len(json.dumps(structured, default=str)) > MAX_RESULT_CHARS:  # the same bound as the text, or it floods the model
            out["structured_omitted"] = f"structuredContent over {MAX_RESULT_CHARS} characters"
        else:
            out["structured"] = structured
    if result.get("isError"):
        out["is_error"] = True
    return out
