"""Command MCP servers on the computer: the URL built from a validated id with the computer origin as
the one SSRF exemption, env values encrypted on disk and absent from routes and logs, restart on 404
with a retry only for retry-safe requests, stop on disable/remove, the computer-off refusals, and the
card routes. A fake computer (control API + MCP bridge) over httpx MockTransport; no network."""

import asyncio
import json
import logging

import httpx
import pytest

from core.security import ssrf
from integrations.mcp import command, service, store
from integrations.mcp import tools as mcp_tools
from integrations.mcp.client import McpClient, McpError
from integrations.registry import disable, enable, get_credentials, save_credentials

ORIGIN = "http://computer.railway.internal:8080"
SECRET = "s3cret-s3cret-s3cret-s3cret-s3cret"
TOKEN = "ghp_veryS3cretValue"
USER = {"origin": "user", "agent_slug": "tom"}
BACKGROUND = {"origin": "background", "agent_slug": "tom"}


class FakeComputer:
    """PUT/GET/DELETE /mcp/servers and the /mcp/{name}/mcp proxy. `running` is the set of live processes."""

    def __init__(self):
        self.calls: list[tuple[str, str, dict | None]] = []  # control-API calls (method, path, body)
        self.rpc: list[str] = []  # JSON-RPC methods that reached a running server
        self.running: set[str] = set()
        self.envs: dict[str, dict] = {}
        self.start_fail = False
        self.die_before_call = False  # the process vanishes right before tools/call arrives
        self.unreachable = False
        self.tools = [{"name": "echo", "description": "Echo", "inputSchema": {"type": "object", "properties": {}},
                       "annotations": {"readOnlyHint": True}}]

    def handle(self, request: httpx.Request) -> httpx.Response:
        if self.unreachable:
            raise httpx.ConnectError("refused", request=request)
        assert request.headers["Authorization"] == f"Bearer {SECRET}"
        path = request.url.path
        body = json.loads(request.content) if request.content else None
        if path.startswith("/mcp/servers"):
            self.calls.append((request.method, path, body))
            name = path.rsplit("/", 1)[-1]
            if request.method == "PUT":
                if self.start_fail:
                    return httpx.Response(502, json={"error": "mcp_start_failed", "detail": "mcp-proxy did not come up",
                                                     "log": f"npm ERR! 404 not found; env TOKEN={body['env'].get('TOKEN', '')}"})
                self.running.add(name)
                self.envs[name] = body["env"]
                return httpx.Response(200, json={"name": name, "running": True, "url": f"/mcp/{name}/mcp"})
            if request.method == "DELETE":
                return httpx.Response(200, json={"stopped": bool(self.running.discard(name) or True)})
            return httpx.Response(200, json={"servers": [{"name": n, "running": True} for n in sorted(self.running)]})
        name = path.split("/")[2]
        if name not in self.running:
            return httpx.Response(404, json={"error": "mcp_server_not_running", "detail": "no such server on this computer"})
        if body.get("method") == "tools/call" and self.die_before_call:
            self.running.discard(name)
            return httpx.Response(404, json={"error": "mcp_server_not_running", "detail": "no such server on this computer"})
        self.rpc.append(body["method"])
        if "id" not in body:
            return httpx.Response(202)
        result = {"initialize": {"protocolVersion": "2025-06-18", "capabilities": {}},
                  "tools/list": {"tools": self.tools},
                  "tools/call": {"content": [{"type": "text", "text": "echoed"}]}}[body["method"]]
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": result})


@pytest.fixture
def env(tmp_path, monkeypatch, encryption_env):
    """mcp.json and computer.json in tmp, the computer configured by env and switched on, the fake wired in."""
    import integrations.registry as reg
    monkeypatch.setattr(reg, "DATA_DIR", tmp_path / "integrations")
    monkeypatch.setenv("COMPUTER_URL", ORIGIN)
    monkeypatch.setenv("COMPUTER_SECRET", SECRET)
    save_credentials("computer", {"enabled": True})
    save_credentials("mcp", {"enabled": True, "servers": {}})
    fake = FakeComputer()
    monkeypatch.setattr(command, "_transport", httpx.MockTransport(fake.handle))
    return fake


def _run(coro):
    return asyncio.run(coro)


def _add(name="Everything", cmd="npx -y @modelcontextprotocol/server-everything", env=None) -> dict:
    return _run(service.add_command_server(name, cmd, {"TOKEN": TOKEN} if env is None else env))


def _puts(fake):
    return [c for c in fake.calls if c[0] == "PUT"]


def _deletes(fake):
    return [c for c in fake.calls if c[0] == "DELETE"]


class TestUrl:
    def test_built_from_a_validated_id(self, env):
        assert command.url("everything_2") == f"{ORIGIN}/mcp/everything_2/mcp"
        for bad in ("../x", "a/b", "A", "", "x" * 65, "x y", "x?y", "..", "x#"):
            with pytest.raises(McpError, match="Invalid server id"):
                command.url(bad)

    def test_only_the_computer_origin_is_exempt(self, env, monkeypatch):
        c = command.client("everything")
        assert c.url == f"{ORIGIN}/mcp/everything/mcp" and c._allow_origins == (ORIGIN,)
        assert c._headers["Authorization"] == f"Bearer {SECRET}"
        monkeypatch.setattr(ssrf, "resolve", lambda h: ["10.0.0.5"])
        assert ssrf.validate_url(c.url, allow_origins=c._allow_origins) is None
        # The same host on another port, any other private host, and plain http elsewhere stay refused.
        assert ssrf.validate_url(f"{ORIGIN[:-1]}1/mcp/x/mcp", allow_origins=c._allow_origins) == "URL must use https"
        assert ssrf.validate_url("https://other.internal/mcp/x/mcp", allow_origins=c._allow_origins) == ssrf.INTERNAL_ADDRESS
        # A remote server pointed at the computer gets no exemption: the user URL path never reaches it.
        monkeypatch.setattr(McpClient, "list_tools", lambda self: pytest.fail("connected"))
        with pytest.raises(ValueError, match="https"):
            _run(service.add_server("Sneaky", f"{ORIGIN}/mcp/everything/mcp", "k", "Authorization"))
        with pytest.raises(ValueError, match="internal addresses"):
            _run(service.add_server("Sneaky", "https://computer.railway.internal/mcp/x/mcp", "k", "Authorization"))


class TestAdd:
    def test_starts_lists_tools_and_saves_the_env_encrypted(self, env, tmp_path, caplog):
        caplog.set_level(logging.DEBUG)
        status = _add()
        assert _puts(env) == [("PUT", "/mcp/servers/everything", {"command": "npx -y @modelcontextprotocol/server-everything",
                                                                   "env": {"TOKEN": TOKEN}})]
        assert env.rpc == ["initialize", "notifications/initialized", "tools/list"]
        s = status["servers"][0]
        assert s["kind"] == "command" and s["command"].startswith("npx") and s["env_names"] == ["TOKEN"]
        assert s["url"] == "" and s["has_key"] is False and s["oauth"] is None and s["last_error"] is None
        assert [t["name"] for t in s["tools"]] == ["echo"] and s["tools"][0]["read_only_hint"] is True
        assert s["tools"][0]["writes"] is True  # the hint is a suggestion; command servers are writes by default too
        # The value is in no route response, no log line, and only encrypted on disk.
        assert TOKEN not in json.dumps(status) and TOKEN not in caplog.text
        raw = (tmp_path / "integrations" / "mcp.json").read_text()
        assert TOKEN not in raw and raw.count("enc:v1:") == 1
        assert store.env_values(get_credentials("mcp")["servers"]["everything"]) == {"TOKEN": TOKEN}
        assert get_credentials("mcp")["enabled"] is True and get_credentials("mcp")["tool_mode"] == "normal"

    def test_start_failure_is_readable_redacted_and_not_saved(self, env, caplog):
        caplog.set_level(logging.DEBUG)
        env.start_fail = True
        with pytest.raises(McpError, match="Start failed on the computer: mcp-proxy did not come up") as ei:
            _add()
        assert "npm ERR! 404" in str(ei.value) and "[redacted]" in str(ei.value) and TOKEN not in str(ei.value)
        assert TOKEN not in caplog.text and store.servers() == {}

    def test_a_server_that_starts_but_does_not_answer_is_stopped_and_not_saved(self, env, monkeypatch):
        async def boom(self):
            raise McpError("HTTP 500: broken", status=500)
        monkeypatch.setattr(McpClient, "list_tools", boom)
        with pytest.raises(McpError, match="HTTP 500"):
            _add()
        assert len(_puts(env)) == 1 and _deletes(env) == [("DELETE", "/mcp/servers/everything", None)]
        assert store.servers() == {}

    def test_refused_when_the_computer_is_unconfigured_or_off(self, env, monkeypatch):
        disable("computer")
        with pytest.raises(ValueError, match="turned off"):
            _add()
        enable("computer")
        monkeypatch.delenv("COMPUTER_URL")
        monkeypatch.delenv("COMPUTER_SECRET")
        with pytest.raises(ValueError, match="no computer is set up"):
            _add()
        assert env.calls == []

    def test_bad_command_and_env(self, env):
        with pytest.raises(ValueError, match="variable name"):
            _add(env={"bad name": "x"})
        with pytest.raises(ValueError, match="control characters"):
            _add(env={"A": "x\ny"})
        with pytest.raises(ValueError, match="Command is empty"):
            _add(cmd="   ")
        assert env.calls == []

    def test_ids_suffix_collisions_like_remote_servers(self, env):
        _add()
        status = _add()
        assert [s["id"] for s in status["servers"]] == ["everything", "everything_2"]
        assert env.running == {"everything", "everything_2"}


class TestRestart:
    def test_404_on_a_listing_starts_the_server_again_and_retries(self, env):
        _add()
        env.running.clear()  # the computer restarted
        env.tools = [{"name": "echo2"}]
        status = _run(service.refresh_server("everything"))
        assert len(_puts(env)) == 2 and env.envs["everything"] == {"TOKEN": TOKEN}  # the env is sent again, from the file
        assert [t["name"] for t in status["servers"][0]["tools"]] == ["echo2"] and status["servers"][0]["last_error"] is None

    def test_404_on_the_tool_call_restarts_but_never_replays(self, env):
        _add()
        env.die_before_call = True
        ex = mcp_tools.TOOL_EXECUTORS()["mcp_everything__echo"]
        r = _run(ex(_ctx=USER))
        assert "was not replayed" in r["error"] and "unknown" in r["error"] and r["error"].startswith("MCP server 'Everything'")
        assert len(_puts(env)) == 2  # started again for the next call
        assert env.rpc.count("tools/call") == 0  # the first attempt never ran; nothing was replayed
        env.die_before_call = False
        assert _run(ex(_ctx=USER)) == {"content": "echoed"} and env.rpc.count("tools/call") == 1

    def test_other_failures_are_not_retried(self, env, monkeypatch):
        _add()
        calls = []

        async def boom(self, name, arguments):
            calls.append(name)
            raise McpError("HTTP 500: broken", status=500, retry_safe=False)
        monkeypatch.setattr(McpClient, "call_tool", boom)
        ex = mcp_tools.TOOL_EXECUTORS()["mcp_everything__echo"]
        assert _run(ex(_ctx=USER)) == {"error": "MCP server 'Everything': HTTP 500: broken"}
        assert calls == ["echo"] and len(_puts(env)) == 1

    def test_unreachable_computer_is_a_clear_message(self, env):
        _add()
        env.unreachable = True
        ex = mcp_tools.TOOL_EXECUTORS()["mcp_everything__echo"]
        r = _run(ex(_ctx=USER))
        assert r["error"] == f"MCP server 'Everything': Can't reach the computer at {ORIGIN} (ConnectError). Is it running?"


class TestPolicy:
    def test_store_call_error_applies_and_the_computer_is_checked(self, env):
        _add()
        ex = mcp_tools.TOOL_EXECUTORS()["mcp_everything__echo"]
        assert "not allowed to do that in background" in _run(ex(_ctx=BACKGROUND))["error"]
        service.update_server("everything", allow_in_background=True)
        assert _run(ex(_ctx=BACKGROUND)) == {"content": "echoed"}
        service.set_tool("everything", "echo", enabled=False)
        assert "turned off" in _run(ex(_ctx=USER))["error"]
        service.set_tool("everything", "echo", enabled=True)
        n = env.rpc.count("tools/call")
        disable("computer")
        assert _run(ex(_ctx=USER)) == {"error": "Command MCP servers run on the computer, which is turned off (see the Computer card)."}
        assert env.rpc.count("tools/call") == n
        assert store.call_error("everything", "echo", True, "user").endswith("(see the Computer card).")

    def test_refresh_stale_skips_command_servers_while_the_computer_is_off(self, env, monkeypatch):
        _add()
        store.update(lambda c: c["servers"]["everything"].__setitem__("tools_refreshed_at", 0))
        disable("computer")
        n = len(env.calls)
        service.refresh_stale()
        assert len(env.calls) == n and store.servers()["everything"]["last_error"] is None
        enable("computer")
        service.refresh_stale()
        assert store.servers()["everything"]["tools_refreshed_at"] > 0

    def test_tools_are_loaded_like_remote_ones(self, env):
        _add()
        d = {d["name"]: d for d in mcp_tools.MCP_TOOL_DEFS()}["mcp_everything__echo"]
        assert d["kind"] == "integration" and d["writes"] is True and d["context_aware"] is True
        assert d["description"].startswith("[Everything] Echo")


class TestRoutes:
    def test_add_status_restart_disable_remove(self, client, env):
        r = client.post("/api/integrations/mcp/servers/command",
                        json={"name": "Everything", "command": "npx -y @modelcontextprotocol/server-everything",
                              "env": {"TOKEN": TOKEN}})
        assert r.status_code == 200 and TOKEN not in r.text and r.json()["servers"][0]["env_names"] == ["TOKEN"]
        assert TOKEN not in client.get("/api/integrations/mcp/status").text
        assert client.get("/api/integrations/mcp/computer").json() == {"error": None, "running": ["everything"]}

        r = client.post("/api/integrations/mcp/servers/everything/restart")
        assert r.status_code == 200 and len(_puts(env)) == 2 and r.json()["servers"][0]["last_error"] is None
        assert client.post("/api/integrations/mcp/servers/nope/restart").status_code == 404

        # Disabling the server stops the process; enabling again starts it on the next call.
        r = client.put("/api/integrations/mcp/servers/everything", json={"enabled": False})
        assert r.status_code == 200 and _deletes(env) == [("DELETE", "/mcp/servers/everything", None)]
        assert client.get("/api/integrations/mcp/computer").json()["running"] == []
        client.put("/api/integrations/mcp/servers/everything", json={"enabled": True})
        assert len(_deletes(env)) == 1

        # Disabling the MCP integration or the computer stops every command server.
        assert client.post("/api/integrations/mcp/disable").status_code == 200
        assert len(_deletes(env)) == 2
        enable("mcp")
        assert client.post("/api/integrations/computer/disable").status_code == 200
        assert len(_deletes(env)) == 3
        assert client.get("/api/integrations/mcp/computer").json()["running"] == []
        assert "turned off" in client.get("/api/integrations/mcp/computer").json()["error"]
        enable("computer")

        # Removing deletes the process too.
        r = client.delete("/api/integrations/mcp/servers/everything")
        assert r.status_code == 200 and r.json()["servers"] == [] and len(_deletes(env)) == 4
        assert client.get("/api/integrations/mcp/computer").json() == {"error": None, "running": []}

    def test_add_errors_are_400s_without_the_value(self, client, env):
        env.start_fail = True
        r = client.post("/api/integrations/mcp/servers/command", json={"name": "X", "command": "npx nope", "env": {"TOKEN": TOKEN}})
        assert r.status_code == 400 and "Start failed on the computer" in r.json()["detail"] and TOKEN not in r.text
        r = client.post("/api/integrations/mcp/servers/command", json={"name": "X", "command": "npx nope", "env": {"1BAD": "v"}})
        assert r.status_code == 400 and "variable name" in r.json()["detail"]
        assert client.post("/api/integrations/mcp/servers/command", json={"name": "X", "command": ""}).status_code == 422

    def test_remote_servers_never_touch_the_computer(self, client, env, monkeypatch):
        monkeypatch.setattr(ssrf, "resolve", lambda h: ["93.184.216.34"])

        async def list_tools(self):
            return [{"name": "t"}]
        monkeypatch.setattr(McpClient, "list_tools", list_tools)
        assert client.post("/api/integrations/mcp/servers", json={"name": "Remote", "url": "https://s.test/mcp", "api_key": "k"}).status_code == 200
        assert client.put("/api/integrations/mcp/servers/remote", json={"enabled": False}).status_code == 200
        assert client.post("/api/integrations/mcp/servers/remote/restart").status_code == 404
        assert client.delete("/api/integrations/mcp/servers/remote").status_code == 200
        assert env.calls == []
        assert client.get("/api/integrations/mcp/computer").json() == {"error": None, "running": []}
