"""MCP integration — naming, write-by-default policy, call-time checks, the client protocol, the card routes."""

import asyncio
import json
import re

import httpx
import pytest

from integrations.mcp import service, store
from integrations.mcp import tools as mcp_tools
from integrations.mcp.client import McpClient, McpError
from integrations.registry import get_credentials, save_credentials

PUBLIC = "93.184.216.34"
SERVER = {
    "name": "GitHub", "url": "https://mcp.github.test/mcp", "api_key": "k1", "header": "Authorization",
    "enabled": True, "allow_in_background": False, "tools_refreshed_at": 0, "last_error": None, "overrides": {},
    "tools": [
        {"name": "create_issue", "description": "Open an issue",
         "input_schema": {"type": "object", "properties": {"title": {"type": "string"}}}, "read_only_hint": False},
        {"name": "get_issue", "description": "Read one issue", "input_schema": {}, "read_only_hint": True},
    ],
}


@pytest.fixture
def mcp_env(tmp_path, monkeypatch, encryption_env):
    import integrations.registry as reg
    monkeypatch.setattr(reg, "DATA_DIR", tmp_path / "integrations")
    save_credentials("mcp", {"enabled": True, "servers": {"github": json.loads(json.dumps(SERVER))}})
    return tmp_path


@pytest.fixture
def fake_call(monkeypatch):
    """Replace the network call; records (url, auth header, tool, arguments)."""
    calls = []

    async def call_tool(self, name, arguments):
        calls.append((self.url, self._headers.get("Authorization"), name, arguments))
        return {"content": [{"type": "text", "text": f"did {name}"}]}
    monkeypatch.setattr(McpClient, "call_tool", call_tool)
    return calls


def _defs() -> dict:
    return {d["name"]: d for d in mcp_tools.MCP_TOOL_DEFS()}


def _run(coro):
    return asyncio.run(coro)


USER = {"origin": "user", "agent_slug": "tom"}
BACKGROUND = {"origin": "background", "agent_slug": "tom"}


class TestNaming:
    def test_names_are_prefixed_and_provider_safe(self, mcp_env):
        names = set(_defs())
        assert names == {"mcp_github__create_issue", "mcp_github__get_issue"}
        assert all(re.fullmatch(r"[A-Za-z0-9_-]{1,64}", n) for n in names)

    def test_collision_and_overflow_get_a_hash_suffix(self):
        seen: set[str] = set()
        a = store.unique_tool_name("s", "a.b", seen)
        b = store.unique_tool_name("s", "a_b", seen)
        assert a == "mcp_s__a_b" and b != a and b.startswith("mcp_s__a_b_") and len(b) <= 64
        long = store.unique_tool_name("s", "x" * 100, seen)
        assert len(long) == 64 and re.fullmatch(r"[A-Za-z0-9_-]+", long)
        assert long != store.unique_tool_name("s", "x" * 101, set())

    def test_description_prefixed_with_server_and_capped(self, mcp_env):
        assert _defs()["mcp_github__create_issue"]["description"] == "[GitHub] Open an issue"
        store.update(lambda c: c["servers"]["github"]["tools"][0].__setitem__("description", "d" * 5000))
        assert len(_defs()["mcp_github__create_issue"]["description"]) == store.MAX_DESCRIPTION


class TestPolicy:
    def test_every_tool_is_a_write_by_default(self, mcp_env):
        defs = _defs()
        assert all(d["writes"] and d["context_aware"] and d["kind"] == "integration" for d in defs.values())
        assert defs["mcp_github__get_issue"]["writes"] is True  # readOnlyHint is only a suggestion

    def test_user_read_only_override(self, mcp_env):
        service.set_tool("github", "get_issue", read_only=True)
        assert _defs()["mcp_github__get_issue"]["writes"] is False
        assert _defs()["mcp_github__create_issue"]["writes"] is True

    def test_disabled_tool_and_server_vanish(self, mcp_env):
        service.set_tool("github", "get_issue", enabled=False)
        assert set(_defs()) == {"mcp_github__create_issue"}
        service.update_server("github", enabled=False)
        assert _defs() == {} and mcp_tools.TOOL_EXECUTORS() == {}


class TestCallTime:
    def test_background_write_refused_unless_allowed_and_rechecked_each_call(self, mcp_env, fake_call):
        ex = mcp_tools.TOOL_EXECUTORS()["mcp_github__create_issue"]
        r = _run(ex(title="x", _ctx=BACKGROUND))
        assert "background" in r["error"] and fake_call == []

        service.update_server("github", allow_in_background=True)
        assert _run(ex(title="x", _ctx=BACKGROUND)) == {"content": "did create_issue"}
        assert fake_call[-1] == ("https://mcp.github.test/mcp", "Bearer k1", "create_issue", {"title": "x"})

        service.update_server("github", allow_in_background=False)  # same loaded executor, policy re-read
        assert "background" in _run(ex(title="x", _ctx=BACKGROUND))["error"] and len(fake_call) == 1

    def test_user_turn_write_runs(self, mcp_env, fake_call):
        ex = mcp_tools.TOOL_EXECUTORS()["mcp_github__create_issue"]
        assert _run(ex(title="x", _ctx=USER)) == {"content": "did create_issue"}

    def test_read_only_then_write_refused_until_reloaded(self, mcp_env, fake_call):
        service.set_tool("github", "get_issue", read_only=True)
        ex = mcp_tools.TOOL_EXECUTORS()["mcp_github__get_issue"]  # loaded as read-only
        assert _run(ex(_ctx=BACKGROUND)) == {"content": "did get_issue"}  # reads run anywhere
        service.set_tool("github", "get_issue", read_only=False)
        assert _run(ex(_ctx=USER)) == {"error": "This tool's permissions changed; ask again."}
        assert _run(mcp_tools.TOOL_EXECUTORS()["mcp_github__get_issue"](_ctx=USER)) == {"content": "did get_issue"}

    def test_integration_mode_read_only_refuses_a_loaded_write(self, mcp_env, fake_call):
        from integrations.registry import set_tool_mode
        ex = mcp_tools.TOOL_EXECUTORS()["mcp_github__create_issue"]
        set_tool_mode("mcp", "read-only")
        assert _run(ex(title="x", _ctx=USER)) == {"error": "This tool's permissions changed; ask again."}

    def test_switched_off_after_load(self, mcp_env, fake_call):
        from integrations.registry import disable
        ex = mcp_tools.TOOL_EXECUTORS()["mcp_github__create_issue"]
        service.set_tool("github", "create_issue", enabled=False)
        assert "turned off" in _run(ex(title="x", _ctx=USER))["error"]
        service.set_tool("github", "create_issue", enabled=True)
        service.update_server("github", enabled=False)
        assert _run(ex(title="x", _ctx=USER))["error"] == "MCP server 'github' is turned off."
        service.update_server("github", enabled=True)
        disable("mcp")
        assert _run(ex(title="x", _ctx=USER))["error"] == "MCP servers are turned off."
        assert fake_call == []

    def test_registry_injects_the_server_ctx_and_never_forwards_it(self, mcp_env, fake_call):
        from agents.tool_loader import load_integration_tools, tool_flags
        from core.agents.tool_registry import ToolRegistry
        defs, execs = load_integration_tools()
        assert {d["integration"] for d in defs} == {"mcp"} and asyncio.iscoroutinefunction(execs["mcp_github__create_issue"])
        reg = ToolRegistry(context_dir=str(mcp_env / "ctx"), gcs_prefix="",
                           integration_executors=execs, integration_tool_flags=tool_flags(defs))
        # A model-supplied _ctx is stripped; the registry's own origin (background) decides.
        r = _run(reg.execute_tool("mcp_github__create_issue", {"title": "x", "_ctx": {"origin": "user"}}, "integration"))
        assert "background" in r["error"] and fake_call == []
        reg._turn_origin = "user"
        r = _run(reg.execute_tool("mcp_github__create_issue", {"title": "x"}, "integration"))
        assert r == {"content": "did create_issue"} and fake_call[-1][3] == {"title": "x"}

    def test_server_failure_is_a_readable_error(self, mcp_env, monkeypatch):
        async def boom(self, name, arguments):
            raise McpError("HTTP 401: bad key")
        monkeypatch.setattr(McpClient, "call_tool", boom)
        ex = mcp_tools.TOOL_EXECUTORS()["mcp_github__create_issue"]
        assert _run(ex(title="x", _ctx=USER)) == {"error": "MCP server 'GitHub': HTTP 401: bad key"}

    def test_result_shape(self):
        out = mcp_tools._shape({"content": [{"type": "text", "text": "a"}, {"type": "image", "data": "..."},
                                            {"type": "text", "text": "b"}],
                                "isError": True, "structuredContent": {"n": 1}})
        assert out == {"content": "a\nb", "omitted_content_types": ["image"], "structured": {"n": 1}, "is_error": True}
        big = mcp_tools._shape({"content": [{"type": "text", "text": "x" * (mcp_tools.MAX_RESULT_CHARS + 5)}]})
        assert len(big["content"]) == mcp_tools.MAX_RESULT_CHARS and big["truncated"] is True


class TestWrappingAndDiscovery:
    def test_results_are_wrapped_as_untrusted(self):
        from core.agents.security.delimiters import should_wrap, wrap_result
        assert should_wrap("mcp_github__create_issue", "integration") is True
        assert wrap_result("mcp_github__create_issue", "hi").startswith('<untrusted_tool_result id="')

    def test_find_tools_matches_the_server_prefix_and_the_mcp_alias(self, mcp_env):
        from core.agents.deferred_tools import build_provider_tools, execute_find_tools
        defs = [{**d, "integration": "mcp"} for d in mcp_tools.MCP_TOOL_DEFS()]
        both = {"mcp_github__create_issue", "mcp_github__get_issue"}
        assert set(execute_find_tools("github", defs)["loaded_names"]) == both
        assert set(execute_find_tools("mcp", defs)["loaded_names"]) == both
        assert "context_aware" not in build_provider_tools(defs)[0]


class TestSchema:
    def test_refs_inlined_nullables_collapsed_defs_dropped(self):
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object",
            "properties": {
                "repo": {"$ref": "#/$defs/Repo"},
                "label": {"anyOf": [{"type": "string"}, {"type": "null"}], "description": "d"},
                "n": {"type": ["integer", "null"]},
                "many": {"oneOf": [{"type": "string"}, {"type": "integer"}]},
            },
            "$defs": {"Repo": {"type": "object", "properties": {"owner": {"type": "string"}}}},
        }
        out = store.clean_schema(schema)
        assert out["properties"]["repo"] == {"type": "object", "properties": {"owner": {"type": "string"}}}
        assert out["properties"]["label"] == {"type": "string", "description": "d"}
        assert out["properties"]["n"] == {"type": "integer"}
        assert out["properties"]["many"] == {"oneOf": [{"type": "string"}, {"type": "integer"}]}
        assert "$defs" not in out and "$schema" not in out

    def test_empty_and_cyclic_schemas(self):
        assert store.clean_schema({}) == {"type": "object", "properties": {}}
        cyclic = {"$defs": {"N": {"type": "object", "properties": {"next": {"$ref": "#/$defs/N"}}}},
                  "properties": {"root": {"$ref": "#/$defs/N"}}}
        assert store.clean_schema(cyclic)["properties"]["root"]["type"] == "object"


def _fake_server(records: list, *, call_result=None, call_error=None, status=200, first_page=None):
    """A streamable-HTTP MCP server as an httpx MockTransport: JSON initialize, SSE tools/list in two pages."""
    sse = {"content-type": "text/event-stream"}
    first_page = first_page or {"tools": [{"name": "search", "inputSchema": {"type": "object"}}], "nextCursor": "p2"}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        records.append((request.method, dict(request.headers), body))
        if status != 200:
            return httpx.Response(status, text="nope")
        if request.method == "DELETE":
            return httpx.Response(200)
        method = body["method"]
        if method == "initialize":
            return httpx.Response(200, headers={"mcp-session-id": "sess-1"},
                                  json={"jsonrpc": "2.0", "id": body["id"], "result": {"protocolVersion": "2025-03-26"}})
        if method == "notifications/initialized":
            return httpx.Response(202)
        if method == "tools/list":
            page = first_page if not body["params"].get("cursor") else {"tools": [{"name": "fetch"}]}
            # An unrelated notification first, then the response as two data: lines (joined with \n per the SSE spec).
            head, tail = json.dumps({"jsonrpc": "2.0", "id": body["id"], "result": page}).split(",", 1)
            return httpx.Response(200, headers=sse, text=(
                'data: {"jsonrpc": "2.0", "method": "notifications/progress", "params": {}}\n\n'
                f"event: message\ndata: {head},\ndata: {tail}\n\n"))
        if method == "tools/call":
            if call_error:
                return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "error": call_error})
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": call_result})
        return httpx.Response(404)
    return httpx.MockTransport(handler)


class TestClientProtocol:
    async def test_session_headers_bearer_and_paginated_sse_list(self):
        records = []
        client = McpClient("https://s.test/mcp", "k", "Authorization", transport=_fake_server(records))
        assert [t["name"] for t in await client.list_tools()] == ["search", "fetch"]
        methods = [r[2]["method"] if r[2] else r[0] for r in records]
        assert methods == ["initialize", "notifications/initialized", "tools/list", "tools/list", "DELETE"]
        assert all(h["authorization"] == "Bearer k" for _, h, _ in records)
        assert all(h.get("mcp-session-id") == "sess-1" for _, h, _ in records[1:])
        assert all(h.get("mcp-protocol-version") == "2025-03-26" for _, h, _ in records[1:])
        assert records[3][2]["params"] == {"cursor": "p2"}

    async def test_custom_header_and_prefixed_key_go_through_verbatim(self):
        records = []
        await McpClient("https://s.test/mcp", "k", "X-API-Key", transport=_fake_server(records)).list_tools()
        assert records[0][1]["x-api-key"] == "k" and "authorization" not in records[0][1]
        records.clear()
        await McpClient("https://s.test/mcp", "Basic abc", transport=_fake_server(records)).list_tools()
        assert records[0][1]["authorization"] == "Basic abc"

    async def test_call_tool_json_result_and_errors(self):
        client = McpClient("https://s.test/mcp", transport=_fake_server([], call_result={"content": [{"type": "text", "text": "ok"}]}))
        assert await client.call_tool("search", {"q": "x"}) == {"content": [{"type": "text", "text": "ok"}]}
        with pytest.raises(McpError, match="bad args"):
            await McpClient("https://s.test/mcp", transport=_fake_server([], call_error={"code": -32602, "message": "bad args"})).call_tool("search", {})
        with pytest.raises(McpError, match="HTTP 401"):
            await McpClient("https://s.test/mcp", transport=_fake_server([], status=401)).list_tools()

    async def test_session_is_closed_even_when_the_call_fails(self):
        records = []
        with pytest.raises(McpError):
            await McpClient("https://s.test/mcp", transport=_fake_server(records, call_error={"code": -1, "message": "x"})).call_tool("search", {})
        assert records[-1][0] == "DELETE" and records[-1][1]["mcp-session-id"] == "sess-1"

    async def test_tool_cap_applies_within_one_page(self):
        from integrations.mcp.client import MAX_TOOLS
        big = {"tools": [{"name": f"t{i}"} for i in range(MAX_TOOLS + 7)]}
        tools = await McpClient("https://s.test/mcp", transport=_fake_server([], first_page=big)).list_tools()
        assert len(tools) == MAX_TOOLS


class TestService:
    def test_add_server_refuses_private_or_plain_http_urls(self, mcp_env, monkeypatch):
        from core.security import ssrf
        monkeypatch.setattr(ssrf, "resolve", lambda h: ["10.0.0.1"])
        monkeypatch.setattr(McpClient, "list_tools", lambda self: pytest.fail("connected"))
        with pytest.raises(ValueError, match="internal addresses"):
            _run(service.add_server("Local", "https://local.test/mcp", "k", "Authorization"))
        with pytest.raises(ValueError, match="https"):
            _run(service.add_server("Local", "http://example.test/mcp", "k", "Authorization"))
        monkeypatch.setattr(ssrf, "resolve", lambda h: [PUBLIC])
        with pytest.raises(ValueError, match="control characters"):
            _run(service.add_server("X", "https://example.test/mcp", "sek\nret", "Authorization"))

    def test_add_server_fetches_saves_encrypted_and_suffixes_collisions(self, mcp_env, monkeypatch):
        from core.security import ssrf
        monkeypatch.setattr(ssrf, "resolve", lambda h: [PUBLIC])

        async def list_tools(self):
            return [{"name": "search", "description": "d", "inputSchema": {"type": "object"}, "annotations": {"readOnlyHint": True}}]
        monkeypatch.setattr(McpClient, "list_tools", list_tools)

        st = _run(service.add_server("My Server!", "https://s.test/mcp", "k2", "X-API-Key"))
        s = {v["id"]: v for v in st["servers"]}["my_server"]
        assert s["has_key"] and "k2" not in json.dumps(st) and "api_key" not in json.dumps(st)
        assert s["tools"] == [{"name": "search", "description": "d", "read_only_hint": True, "enabled": True, "writes": True}]
        on_disk = json.loads((mcp_env / "integrations" / "mcp.json").read_text())
        assert on_disk["servers"]["my_server"]["api_key"].startswith("enc:v1:")
        assert store.servers()["my_server"]["api_key"] == "k2"

        st = _run(service.add_server("GitHub", "https://s.test/mcp", "", "Authorization"))
        assert {v["id"] for v in st["servers"]} == {"github", "my_server", "github_2"}

    def test_first_server_switches_the_integration_on_unless_the_user_turned_it_off(self, mcp_env, monkeypatch):
        from core.security import ssrf
        from integrations.registry import is_enabled
        monkeypatch.setattr(ssrf, "resolve", lambda h: [PUBLIC])

        async def list_tools(self):
            return []
        monkeypatch.setattr(McpClient, "list_tools", list_tools)
        save_credentials("mcp", {})
        _run(service.add_server("A", "https://a.test/", "", "Authorization"))
        assert is_enabled("mcp")
        # Telegram/WhatsApp cap only integrations whose file names a tool_mode (they strip
        # write tools below "power"); the first server must leave one behind.
        assert get_credentials("mcp")["tool_mode"] == "normal"
        save_credentials("mcp", {"enabled": False, "tool_mode": "power"})
        _run(service.add_server("B", "https://b.test/", "", "Authorization"))
        assert not is_enabled("mcp") and get_credentials("mcp")["tool_mode"] == "power"

    def test_refresh_keeps_the_old_list_and_records_the_error(self, mcp_env, monkeypatch):
        from core.security import ssrf
        monkeypatch.setattr(ssrf, "resolve", lambda h: [PUBLIC])

        async def boom(self):
            raise McpError("HTTP 500")
        monkeypatch.setattr(McpClient, "list_tools", boom)
        st = _run(service.refresh_server("github"))
        assert st["servers"][0]["last_error"] == "HTTP 500" and len(st["servers"][0]["tools"]) == 2
        with pytest.raises(KeyError):
            _run(service.refresh_server("nope"))

    def test_refresh_stale_only_touches_old_lists(self, mcp_env, monkeypatch):
        refreshed = []

        async def refresh_server(sid):
            refreshed.append(sid)
        monkeypatch.setattr(service, "refresh_server", refresh_server)
        service.refresh_stale()
        assert refreshed == ["github"]
        store.update(lambda c: c["servers"]["github"].__setitem__("tools_refreshed_at", 10 ** 12))
        service.refresh_stale()
        assert refreshed == ["github"]

    def test_cached_tool_name_is_verbatim_description_capped(self):
        entry = service._cache_entry({"name": "n" * 300, "description": "d" * 5000})
        assert entry["name"] == "n" * 300 and len(entry["description"]) == store.MAX_DESCRIPTION

    def test_remove_and_unknown_tool(self, mcp_env):
        with pytest.raises(KeyError):
            service.set_tool("github", "nope", read_only=True)
        assert service.remove_server("github")["servers"] == []


class TestApprovePath:
    def test_the_approve_click_runs_a_write_as_a_user_turn(self, client, mcp_env, fake_call):
        """/tool/execute builds its own registry; a write the model asked for in chat and the owner
        approved must not be refused as a background turn."""
        from tests.test_http_agents import make_agent
        agent = make_agent(client)
        r = client.post(f"/api/agents/{agent['id']}/tool/execute",
                        json={"tool": "mcp_github__create_issue", "args": {"title": "x"}})
        assert r.status_code == 200 and r.json() == {"content": "did create_issue"}
        assert fake_call[-1][2:] == ("create_issue", {"title": "x"})


class TestRoutes:
    def test_add_list_toggle_refresh_remove(self, client, monkeypatch):
        from core.security import ssrf
        monkeypatch.setattr(ssrf, "resolve", lambda h: [PUBLIC])

        async def list_tools(self):
            return [{"name": "create_issue", "description": "d", "inputSchema": {}}]
        monkeypatch.setattr(McpClient, "list_tools", list_tools)

        r = client.post("/api/integrations/mcp/servers", json={"name": "GitHub", "url": "https://s.test/mcp", "api_key": "k"})
        assert r.status_code == 200 and "api_key" not in r.text and r.json()["servers"][0]["id"] == "github"
        entry = {i["id"]: i for i in client.get("/api/integrations").json()["integrations"]}["mcp"]
        assert entry["configured"] is True and entry["enabled"] is True

        r = client.put("/api/integrations/mcp/servers/github/tools/create_issue", json={"read_only": True})
        assert r.json()["servers"][0]["tools"][0]["writes"] is False
        r = client.put("/api/integrations/mcp/servers/github", json={"allow_in_background": True})
        assert r.json()["servers"][0]["allow_in_background"] is True
        assert client.post("/api/integrations/mcp/servers/github/refresh").status_code == 200
        assert client.get("/api/integrations/mcp/status").json()["servers"][0]["last_error"] is None
        assert client.delete("/api/integrations/mcp/servers/github").json()["servers"] == []

    def test_bad_inputs(self, client, monkeypatch):
        from core.security import ssrf
        monkeypatch.setattr(ssrf, "resolve", lambda h: ["127.0.0.1"])
        r = client.post("/api/integrations/mcp/servers", json={"name": "X", "url": "https://x.test/", "api_key": "k"})
        assert r.status_code == 400 and "internal addresses" in r.json()["detail"]
        r = client.post("/api/integrations/mcp/servers", json={"name": "X", "url": "https://x.test/", "header": "X Key"})
        assert r.status_code == 422
        assert client.put("/api/integrations/mcp/servers/nope", json={"enabled": False}).status_code == 404
        assert client.post("/api/integrations/mcp/servers/nope/refresh").status_code == 404
