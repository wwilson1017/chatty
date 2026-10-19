import asyncio
import json

import httpx
import pytest
from chatty_cli.api import Api
from chatty_cli.repl import Session

URL = "http://chatty.test"
AGENT = {"id": "a-uuid-1", "slug": "tom", "agent_name": "Tom", "provider_override": "", "model_override": "",
         "model_tier": "auto"}


def sse(*events: dict) -> bytes:
    return "".join(f"data: {json.dumps(e)}\n\n" for e in events).encode()


async def gated(first: list, gate: asyncio.Event, rest: list):
    """A reply stream that stops after `first` until the test sets `gate`."""
    yield sse(*first)
    await gate.wait()
    yield sse(*rest)


def answer(*replies: str):
    """A stand-in for render.ask that gives these replies in turn."""
    it = iter(replies)

    async def ask(_prompt):
        return next(it)
    return ask


async def until(cond, timeout: float = 2.0) -> None:
    for _ in range(int(timeout / 0.01)):
        if cond():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition never became true")


class FakeChatty:
    """Just enough of Chatty's API, recording every request it sees."""

    def __init__(self):
        self.requests: list[tuple[str, str, object]] = []
        self.swaps = 0
        self.revoked = False
        self.stale: set[str] = set()  # JWTs answered with 401
        self.reject_all = False
        self.agents = [AGENT]
        self.streams: list = []  # one per chat call: a list of events, or an async byte iterator
        self.execute: tuple | Exception = (200, {"ok": True})
        self.conversations: list[dict] = []
        self.messages: list[dict] = []

    def chats(self) -> list:
        return [body for _, path, body in self.requests if "/chat" in path]

    async def handler(self, request: httpx.Request) -> httpx.Response:
        await request.aread()
        path = request.url.path
        ctype = request.headers.get("content-type", "")
        body = json.loads(request.content) if ctype == "application/json" else request.content
        self.requests.append((request.method, path, body))
        if path == "/api/terminal/token":
            assert request.headers["authorization"] == "Bearer dev-tok"
            if self.revoked:
                return httpx.Response(401, json={"detail": "Unknown device"})
            self.swaps += 1
            return httpx.Response(200, json={"access_token": f"jwt-{self.swaps}", "expires_in": 900})
        auth = request.headers.get("authorization", "")
        if self.reject_all or auth.removeprefix("Bearer ") in self.stale or not auth.startswith("Bearer jwt-"):
            return httpx.Response(401, json={"detail": "Invalid token"})
        if path == "/api/agents":
            return httpx.Response(200, json={"agents": self.agents})
        if path.endswith(("/chat", "/chat/upload")):
            item = self.streams.pop(0)
            return httpx.Response(200, headers={"content-type": "text/event-stream"},
                                  content=sse(*item) if isinstance(item, list) else item)
        if path.endswith("/tool/execute"):
            if isinstance(self.execute, Exception):
                raise self.execute
            status, result = self.execute
            return httpx.Response(status, json=result)
        if path.endswith("/conversations"):
            return httpx.Response(200, json={"conversations": self.conversations})
        if "/conversations/" in path:
            cid = path.rsplit("/", 1)[1]
            return httpx.Response(200, json={"id": cid, "title": f"title {cid}", "messages": self.messages})
        return httpx.Response(404, json={"detail": "Not Found"})


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("CHATTY_CONFIG", str(tmp_path / "config.json"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    return tmp_path / "config.json"


@pytest.fixture
def fake():
    return FakeChatty()


def make_session(fake: FakeChatty, **cfg) -> Session:
    api = Api(URL, "dev-tok", httpx.MockTransport(fake.handler))
    return Session(api, {"url": URL, "device_token": "dev-tok", **cfg}, dict(AGENT))
