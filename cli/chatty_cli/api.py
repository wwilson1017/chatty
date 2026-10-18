"""HTTP client for a Chatty server: device token -> short-lived JWT, JSON calls, and the SSE chat stream."""

import json
import mimetypes

import httpx


class ApiError(Exception):
    """The server refused the request; the message carries its `detail`."""


class Revoked(ApiError):
    def __init__(self):
        super().__init__("This terminal was revoked. Run `chatty login`.")


def detail(r: httpx.Response) -> str:
    try:
        d = r.json().get("detail")
    except (ValueError, AttributeError):
        d = None
    return f"HTTP {r.status_code}: {d or r.text[:300] or r.reason_phrase}"


def parse_sse(line: str) -> dict | None:
    if not line.startswith("data: "):
        return None
    try:
        return json.loads(line[6:])
    except ValueError:
        return None


class Api:
    def __init__(self, url: str, device_token: str, transport: httpx.AsyncBaseTransport | None = None):
        # No read timeout: thinking and long tools leave silent gaps, and a dropped stream cancels the turn.
        self.http = httpx.AsyncClient(base_url=url, timeout=httpx.Timeout(10, read=None), transport=transport)
        self.device_token = device_token
        self.jwt: str | None = None

    async def _token(self, fresh: bool = False) -> str:
        if fresh or not self.jwt:
            r = await self.http.post("/api/terminal/token", headers={"Authorization": f"Bearer {self.device_token}"})
            if r.status_code == 401:
                raise Revoked()
            if r.is_error:
                raise ApiError(detail(r))
            self.jwt = r.json()["access_token"]
        return self.jwt

    async def _send(self, method: str, path: str, **kw) -> httpx.Response:
        """Send with the JWT. Only a 401 status, before any body is read, is retried: once, with a fresh swap.
        Transport errors are never replayed (the server may already be running the turn or the tool)."""
        for retry in (False, True):
            token = await self._token(fresh=retry)
            req = self.http.build_request(method, path, headers={"Authorization": f"Bearer {token}"}, **kw)
            r = await self.http.send(req, stream=True)
            if r.status_code != 401 or retry:
                break
            await r.aclose()
        if r.is_error:
            await r.aread()
            await r.aclose()
            raise ApiError(detail(r))
        return r

    async def call(self, method: str, path: str, **kw):
        r = await self._send(method, path, **kw)
        try:
            await r.aread()
        finally:
            await r.aclose()
        return r.json() if r.content else None

    async def chat(self, agent_id: str, text: str, conversation_id: str | None, tool_mode: str,
                   approved_tool: dict | None = None, files: list[tuple[str, bytes]] = ()):
        """Yield the reply's events. Only the new message is sent; the server keeps the history.
        With `files` it goes through /chat/upload, which streams the same way."""
        body = {"messages": [{"role": "user", "content": text}], "conversation_id": conversation_id,
                "tool_mode": tool_mode}
        if approved_tool:
            body["approved_tool"] = approved_tool
        if files:
            path = f"/api/agents/{agent_id}/chat/upload"
            kw = {"data": {"payload": json.dumps(body)},
                  "files": [("files", (name, data, mimetypes.guess_type(name)[0] or "application/octet-stream"))
                            for name, data in files]}
        else:
            path, kw = f"/api/agents/{agent_id}/chat", {"json": body}
        r = await self._send("POST", path, **kw)
        try:
            async for line in r.aiter_lines():
                if (event := parse_sse(line)) is not None:
                    yield event
        finally:
            await r.aclose()

    async def agents(self) -> list[dict]:
        return (await self.call("GET", "/api/agents"))["agents"]

    async def execute_tool(self, agent_id: str, tool: str, args: dict) -> dict:
        return await self.call("POST", f"/api/agents/{agent_id}/tool/execute", json={"tool": tool, "args": args})

    async def conversations(self, agent_id: str) -> list[dict]:
        """Most recently updated first (the server lists pinned ones first)."""
        convs = (await self.call("GET", f"/api/agents/{agent_id}/conversations", params={"limit": 50}))
        return sorted(convs["conversations"], key=lambda c: c.get("updated_at") or "", reverse=True)

    async def conversation(self, agent_id: str, conversation_id: str) -> dict:
        return await self.call("GET", f"/api/agents/{agent_id}/conversations/{conversation_id}")

    async def providers(self) -> dict:
        return await self.call("GET", "/api/providers")

    async def models(self, provider: str) -> list[str]:
        return (await self.call("GET", f"/api/providers/{provider}/models"))["models"]

    async def update_agent(self, agent_id: str, **fields) -> dict:
        return await self.call("PUT", f"/api/agents/{agent_id}", json=fields)
