"""Chatty — minimal MCP client: JSON-RPC over streamable HTTP.

# simplification: hand-rolled instead of the official `mcp` SDK. The SDK (2.x) is built on
# a parallel HTTP stack (httpx2/httpcore2, plus ten more packages) and cannot carry the
# pinned-IP transport in core.security.ssrf; upgrade: the SDK once it takes an httpx 0.28
# client, or when we need resources, prompts or sampling.
# simplification: one short-lived session per call (initialize, request, delete);
# upgrade: one session per server on a loop thread.
"""

import json

import httpx

from core.security.ssrf import pinned_client

PROTOCOL_VERSION = "2025-06-18"
MAX_BODY = 4 * 1024 * 1024
MAX_TOOLS = 500
TIMEOUT = 60.0


class McpError(Exception):
    """A transport or protocol failure, worded for the card and the agent."""


class McpClient:
    def __init__(self, url: str, api_key: str = "", header: str = "Authorization", *,
                 allow_origins=(), transport: httpx.AsyncBaseTransport | None = None):
        self.url = url
        self._headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
        if api_key:
            header = header or "Authorization"
            # A bare key in Authorization gets the Bearer scheme; a key that already names a
            # scheme ("Bearer x", "Basic y") or any other header goes through verbatim.
            bearer = header.lower() == "authorization" and " " not in api_key
            self._headers[header] = f"Bearer {api_key}" if bearer else api_key
        self._allow_origins = allow_origins
        self._transport = transport  # tests only: bypasses the pinned transport

    def _http(self) -> httpx.AsyncClient:
        if self._transport is not None:
            return httpx.AsyncClient(transport=self._transport, timeout=TIMEOUT)
        return pinned_client(allow_origins=self._allow_origins, timeout=TIMEOUT)

    async def list_tools(self) -> list[dict]:
        async with self._http() as http:
            headers = await self._initialize(http)
            tools, cursor = [], None
            while True:
                result = await self._request(http, headers, "tools/list", {"cursor": cursor} if cursor else {})
                tools.extend(t for t in result.get("tools") or [] if isinstance(t, dict) and t.get("name"))
                cursor = result.get("nextCursor")
                if not cursor or len(tools) >= MAX_TOOLS:
                    break
            await self._close(http, headers)
            return tools

    async def call_tool(self, name: str, arguments: dict) -> dict:
        async with self._http() as http:
            headers = await self._initialize(http)
            result = await self._request(http, headers, "tools/call", {"name": name, "arguments": arguments or {}})
            await self._close(http, headers)
            return result

    async def _initialize(self, http) -> dict:
        headers = dict(self._headers)
        resp, result = await self._post(http, headers, 1, "initialize", {
            "protocolVersion": PROTOCOL_VERSION, "capabilities": {},
            "clientInfo": {"name": "chatty", "version": "1"},
        })
        if sid := resp.headers.get("mcp-session-id"):
            headers["Mcp-Session-Id"] = sid
        headers["MCP-Protocol-Version"] = str(result.get("protocolVersion") or PROTOCOL_VERSION)
        await self._post(http, headers, None, "notifications/initialized", None)
        return headers

    async def _request(self, http, headers, method, params) -> dict:
        return (await self._post(http, headers, 2, method, params))[1]

    async def _close(self, http, headers) -> None:
        if "Mcp-Session-Id" in headers:
            try:
                await http.delete(self.url, headers=headers)
            except httpx.HTTPError:
                pass

    async def _post(self, http, headers, want_id, method, params) -> tuple[httpx.Response, dict]:
        """POST one JSON-RPC message; return the response whose id matches, or {} for a notification."""
        message = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        if want_id is not None:
            message["id"] = want_id
        try:
            async with http.stream("POST", self.url, json=message, headers=headers) as resp:
                if resp.status_code >= 400:
                    detail = (await resp.aread())[:300].decode(errors="replace").strip()
                    raise McpError(f"HTTP {resp.status_code}" + (f": {detail}" if detail else ""))
                if want_id is None:
                    return resp, {}
                if resp.headers.get("content-type", "").startswith("text/event-stream"):
                    messages = await _read_sse(resp, want_id)
                else:
                    body = await resp.aread()
                    if len(body) > MAX_BODY:
                        raise McpError("Response too large")
                    data = json.loads(body or "null")
                    messages = data if isinstance(data, list) else [data]
        except httpx.HTTPError as e:
            raise McpError(f"{type(e).__name__}: {e}") from e
        except ValueError as e:
            raise McpError(f"Invalid JSON from server: {e}") from e
        for m in messages:
            if isinstance(m, dict) and m.get("id") == want_id:
                if "error" in m:
                    err = m["error"] if isinstance(m["error"], dict) else {}
                    raise McpError(f"{err.get('message') or 'Server error'} (code {err.get('code')})")
                return resp, m.get("result") if isinstance(m.get("result"), dict) else {}
        raise McpError(f"No response to {method}")


async def _read_sse(resp: httpx.Response, want_id) -> list[dict]:
    """Collect JSON-RPC messages from an SSE body until the one with `want_id` arrives."""
    messages, data, size = [], [], 0
    async for line in resp.aiter_lines():
        size += len(line)
        if size > MAX_BODY:
            raise McpError("Response too large")
        if line.startswith("data:"):
            data.append(line[5:].lstrip())
        elif line == "" and data:
            msg = json.loads("\n".join(data))
            data = []
            messages.append(msg)
            if isinstance(msg, dict) and msg.get("id") == want_id:
                break
    return messages
