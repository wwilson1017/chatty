"""MCP OAuth — discovery, client registration, the flow bound to a server and its generation, token
storage, refresh and rotation under the per-server lock, the single 401 retry, SSRF on every URL,
and the card routes. Everything over httpx MockTransport; no network."""

import asyncio
import base64
import json
import time
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from core.providers import oauth as core_oauth
from core.security import ssrf
from integrations.mcp import oauth, service, store
from integrations.mcp import tools as mcp_tools
from integrations.mcp.client import McpAuthError, McpClient, McpError
from integrations.registry import save_credentials

PUBLIC = "93.184.216.34"
URL = "https://mcp.cal.test/mcp"
ISSUER = "https://auth.cal.test"
SERVER = {"name": "Cal", "url": URL, "api_key": "", "header": "Authorization", "enabled": True,
          "allow_in_background": False, "tools": [], "tools_refreshed_at": 0, "last_error": service.NOT_SIGNED_IN,
          "overrides": {}, "generation": 1, "oauth": None}
PRM = {"resource": URL, "authorization_servers": [ISSUER], "scopes_supported": ["calendar"]}
MD = {"issuer": ISSUER, "authorization_endpoint": f"{ISSUER}/authorize", "token_endpoint": f"{ISSUER}/token",
      "registration_endpoint": f"{ISSUER}/register", "code_challenge_methods_supported": ["S256"],
      "authorization_response_iss_parameter_supported": True}
REG = {"client_id": "cid", "client_secret": "csec", "token_endpoint_auth_method": "client_secret_basic"}


class AuthServer:
    """Protected-resource + authorization-server metadata, registration and token endpoints as one transport."""

    def __init__(self, prm=PRM, md=MD, reg=REG, md_path="/.well-known/oauth-authorization-server", token_delay=0.0,
                 issuer=ISSUER):
        self.prm, self.md, self.reg, self.md_path, self.token_delay = prm, md, reg, md_path, token_delay
        self.issuer = issuer
        self.requests: list[httpx.Request] = []
        self.tokens = 0

    def token_requests(self):
        return [r for r in self.requests if r.url.path == "/token"]

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        url = f"{request.url.scheme}://{request.url.host}{request.url.path}"
        if url == "https://mcp.cal.test/.well-known/oauth-protected-resource/mcp" and self.prm is not None:
            return httpx.Response(200, json=self.prm)
        if url == self.issuer + self.md_path:
            return httpx.Response(200, json=self.md)
        if url == f"{self.issuer}/register" and request.method == "POST":
            return httpx.Response(201, json=self.reg)
        if url == f"{self.issuer}/token" and request.method == "POST":
            await asyncio.sleep(self.token_delay)
            self.tokens += 1
            grant = parse_qs(request.content.decode())["grant_type"][0]
            n = self.tokens
            body = {"access_token": f"at{n}", "expires_in": 3600, "token_type": "Bearer"}
            if grant == "authorization_code" or n % 2 == 0:  # the AS rotates the refresh token every other refresh
                body["refresh_token"] = f"rt{n}"
            return httpx.Response(200, json=body)
        return httpx.Response(404)

    def transport(self):
        return httpx.MockTransport(self)


@pytest.fixture
def env(tmp_path, monkeypatch, encryption_env):
    import integrations.registry as reg
    monkeypatch.setattr(reg, "DATA_DIR", tmp_path / "integrations")
    save_credentials("mcp", {"enabled": True, "tool_mode": "normal", "servers": {"cal": json.loads(json.dumps(SERVER))}})
    monkeypatch.setattr(ssrf, "resolve", lambda h: ["10.0.0.1"] if h == "internal.test" else [PUBLIC])
    monkeypatch.delenv("OAUTH_REDIRECT_URI", raising=False)
    oauth._locks.clear()
    return tmp_path


@pytest.fixture
def auth_server(monkeypatch):
    def use(srv: AuthServer):
        monkeypatch.setattr(oauth, "_transport", srv.transport())
        monkeypatch.setattr(core_oauth, "_http", lambda cfg: httpx.AsyncClient(transport=srv.transport()))
        return srv
    return use


def _params(url: str) -> dict:
    return {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}


def _form(request: httpx.Request) -> dict:
    return {k: v[0] for k, v in parse_qs(request.content.decode(), keep_blank_values=True).items()}


def _server() -> dict:
    return store.servers()["cal"]


def _on_disk(tmp_path) -> dict:
    return json.loads((tmp_path / "integrations" / "mcp.json").read_text())["servers"]["cal"]


async def _sign_in(srv, callback=None) -> dict:
    out = await oauth.start("cal")
    await core_oauth.complete_oauth_flow("the-code", out["flow_id"], callback if callback is not None else {"iss": ISSUER})
    oauth.complete("cal", out["flow_id"])
    return out


def _set_tokens(**fields):
    oauth._record("cal", **fields)


class TestDiscoveryAndRegistration:
    async def test_discovery_registers_a_client_and_builds_the_authorization_url(self, env, auth_server):
        srv = auth_server(AuthServer())
        out = await oauth.start("cal")
        p = _params(out["auth_url"])
        assert out["auth_url"].startswith(f"{ISSUER}/authorize?")
        assert p["client_id"] == "cid" and p["resource"] == URL and p["scope"] == "calendar"
        assert p["code_challenge_method"] == "S256" and p["redirect_uri"] == "https://auth.mechatty.com/callback"
        assert p["state"].startswith(out["flow_id"] + ":")
        paths = [(r.method, r.url.path) for r in srv.requests]
        assert paths == [("GET", "/.well-known/oauth-protected-resource/mcp"), ("GET", "/.well-known/oauth-authorization-server"),
                         ("POST", "/register")]
        reg = json.loads(srv.requests[-1].content)
        assert reg["redirect_uris"] == ["https://auth.mechatty.com/callback"] and "refresh_token" in reg["grant_types"]
        o = _server()["oauth"]
        assert o["client_id"] == "cid" and o["client_secret"] == "csec" and o["registered"] and o["use_basic_auth"]
        assert _on_disk(env)["oauth"]["client_secret"].startswith("enc:v1:")
        cfg = core_oauth._OAUTH_FLOWS[out["flow_id"]].config
        assert (cfg.server_id, cfg.generation, cfg.issuer, cfg.check_iss, cfg.pinned) == ("cal", 1, ISSUER, True, True)

        await oauth.start("cal")  # the registered client is reused
        assert sum(r.url.path == "/register" for r in srv.requests) == 1

    async def test_challenge_metadata_url_is_tried_first_and_the_registered_client_survives_an_abandoned_flow(self, env, auth_server):
        srv = auth_server(AuthServer())
        store.update(lambda c: c["servers"]["cal"].__setitem__(
            "oauth", {"resource_metadata": "https://mcp.cal.test/.well-known/oauth-protected-resource/mcp"}))
        await oauth.start("cal")
        assert srv.requests[0].url.path == "/.well-known/oauth-protected-resource/mcp"
        assert _server()["oauth"]["client_id"] == "cid" and _server()["oauth"]["resource_metadata"]

    async def test_a_client_is_dropped_when_the_server_names_another_authorization_server(self, env, auth_server):
        srv = auth_server(AuthServer())
        await _sign_in(srv)
        as2 = "https://auth2.cal.test"
        srv2 = auth_server(AuthServer(issuer=as2, prm={**PRM, "authorization_servers": [as2]},
                                      md={**MD, "issuer": as2, "authorization_endpoint": f"{as2}/authorize",
                                          "token_endpoint": f"{as2}/token", "registration_endpoint": f"{as2}/register"},
                                      reg={"client_id": "cid2"}))
        out = await oauth.start("cal")
        assert [r.url.path for r in srv2.requests if r.method == "POST"] == ["/register"]
        assert _params(out["auth_url"])["client_id"] == "cid2"
        o = _server()["oauth"]
        assert o["issuer"] == as2 and o["client_id"] == "cid2" and not o.get("client_secret") and not o.get("access_token")

    async def test_no_metadata_falls_back_to_the_server_origin(self, env, auth_server):
        class Own(AuthServer):
            async def __call__(self, request):
                self.requests.append(request)
                if request.url.host == "mcp.cal.test" and request.url.path == "/.well-known/oauth-authorization-server":
                    return httpx.Response(200, json={**MD, "issuer": "https://mcp.cal.test",
                                                     "token_endpoint": "https://mcp.cal.test/token",
                                                     "authorization_endpoint": "https://mcp.cal.test/authorize",
                                                     "registration_endpoint": "https://mcp.cal.test/register"})
                if request.url.path == "/register":
                    return httpx.Response(201, json={"client_id": "pub"})  # public client, no secret
                return httpx.Response(404)
        srv = auth_server(Own())
        out = await oauth.start("cal")
        assert [r.url.path for r in srv.requests[:3]] == ["/.well-known/oauth-protected-resource/mcp",
                                                          "/.well-known/oauth-protected-resource",
                                                          "/.well-known/oauth-authorization-server"]
        assert _params(out["auth_url"])["client_id"] == "pub" and "scope" not in _params(out["auth_url"])
        assert _server()["oauth"]["use_basic_auth"] is False

    async def test_issuer_with_a_path_and_issuer_mismatch(self, env, auth_server):
        tenant = f"{ISSUER}/t1"
        srv = auth_server(AuthServer(prm={**PRM, "authorization_servers": [tenant]}, md={**MD, "issuer": tenant},
                                     md_path="/.well-known/oauth-authorization-server/t1"))
        out = await oauth.start("cal")
        assert core_oauth._OAUTH_FLOWS[out["flow_id"]].config.issuer == tenant
        assert srv.requests[1].url.path == "/.well-known/oauth-authorization-server/t1"
        auth_server(AuthServer(md={**MD, "issuer": "https://other.test"}))
        with pytest.raises(McpError, match="another issuer"):
            await oauth.start("cal")

    async def test_resource_mismatch_no_s256_and_missing_metadata_are_refused(self, env, auth_server):
        auth_server(AuthServer(prm={**PRM, "resource": "https://mcp.cal.test/other"}))
        with pytest.raises(McpError, match="protects https://mcp.cal.test/other"):
            await oauth.start("cal")
        auth_server(AuthServer(md={**MD, "code_challenge_methods_supported": ["plain"]}))
        with pytest.raises(McpError, match="S256"):
            await oauth.start("cal")
        auth_server(AuthServer(md_path="/elsewhere"))
        with pytest.raises(McpError, match="No authorization server metadata"):
            await oauth.start("cal")
        with pytest.raises(KeyError):
            await oauth.start("nope")

    async def test_ssrf_guard_on_metadata_registration_and_token_urls(self, env, auth_server):
        srv = auth_server(AuthServer(prm={**PRM, "authorization_servers": ["https://internal.test"]}))
        with pytest.raises(McpError, match="internal addresses"):
            await oauth.start("cal")
        assert all(r.url.host != "internal.test" for r in srv.requests)
        auth_server(AuthServer(md={**MD, "token_endpoint": "http://auth.cal.test/token"}))
        with pytest.raises(McpError, match="https"):
            await oauth.start("cal")
        auth_server(AuthServer(md={**MD, "registration_endpoint": "https://internal.test/register"}))
        with pytest.raises(McpError, match="internal addresses"):
            await oauth.start("cal")
        store.update(lambda c: c["servers"]["cal"].__setitem__("oauth", {"resource_metadata": "http://mcp.cal.test/prm"}))
        with pytest.raises(McpError, match="https"):
            await oauth.start("cal")

    async def test_no_dcr_needs_a_pasted_client(self, env, auth_server):
        md = {k: v for k, v in MD.items() if k != "registration_endpoint"}
        srv = auth_server(AuthServer(md={**md, "token_endpoint_auth_methods_supported": ["client_secret_post"]}))
        with pytest.raises(McpError, match="Paste a client id"):
            await oauth.start("cal")
        before = _server()["generation"]
        oauth.set_client("cal", " my-id ", "my-secret")
        assert _server()["generation"] != before and _server()["oauth"]["registered"] is False
        out = await _sign_in(srv)
        assert _params(out["auth_url"])["client_id"] == "my-id"
        body = _form(srv.token_requests()[-1])
        assert body["client_id"] == "my-id" and body["client_secret"] == "my-secret" and "authorization" not in srv.token_requests()[-1].headers
        with pytest.raises(KeyError):
            oauth.set_client("nope", "a", "b")


class TestFlowBinding:
    async def test_exchange_sends_resource_verifier_and_basic_auth_then_stores_tokens(self, env, auth_server):
        srv = auth_server(AuthServer())
        out = await _sign_in(srv)
        req = srv.token_requests()[-1]
        body = _form(req)
        assert req.headers["authorization"] == "Basic " + base64.b64encode(b"cid:csec").decode()
        assert body["grant_type"] == "authorization_code" and body["resource"] == URL and body["code_verifier"]
        assert "client_secret" not in body and body["redirect_uri"] == "https://auth.mechatty.com/callback"
        o = _server()["oauth"]
        assert (o["access_token"], o["refresh_token"], o["resource"], o["token_endpoint"]) == ("at1", "rt1", URL, f"{ISSUER}/token")
        assert o["expires_at"] > 0 and _server()["last_error"] is None
        disk = _on_disk(env)["oauth"]
        assert disk["access_token"].startswith("enc:v1:") and disk["refresh_token"].startswith("enc:v1:")
        assert core_oauth.consume_flow(out["flow_id"]) is None
        assert oauth.view(_server()) == {"status": "signed_in", "error": None, "has_client": True}

    async def test_iss_is_validated_on_the_callback(self, env, auth_server):
        srv = auth_server(AuthServer())
        out = await oauth.start("cal")
        with pytest.raises(ValueError, match="wrong issuer"):
            await core_oauth.complete_oauth_flow("c", out["flow_id"], {"iss": "https://evil.test"})
        with pytest.raises(ValueError, match="wrong issuer"):
            oauth.complete("cal", out["flow_id"])
        assert srv.token_requests() == [] and not _server()["oauth"].get("access_token")

        auth_server(AuthServer(md={**MD, "authorization_response_iss_parameter_supported": False}))
        await _sign_in(srv, callback={})  # a server that does not send iss is not held to it
        assert _server()["oauth"]["access_token"] == "at1"

    async def test_a_replaced_server_rejects_a_late_complete(self, env, auth_server):
        srv = auth_server(AuthServer())
        out = await oauth.start("cal")
        await core_oauth.complete_oauth_flow("c", out["flow_id"], {"iss": ISSUER})
        service.remove_server("cal")
        store.update(lambda c: c["servers"].__setitem__("cal", {**json.loads(json.dumps(SERVER)), "generation": 2}))
        with pytest.raises(ValueError, match="since changed"):
            oauth.complete("cal", out["flow_id"])
        assert _server()["oauth"] is None

        out = await oauth.start("cal")
        await core_oauth.complete_oauth_flow("c", out["flow_id"], {"iss": ISSUER})
        with pytest.raises(ValueError, match="since changed"):
            oauth.complete("other", out["flow_id"])
        with pytest.raises(KeyError):
            oauth.complete("cal", "never-started")
        assert srv.tokens == 2

    async def test_a_failed_flow_and_a_non_bearer_token_are_refused(self, env, auth_server):
        auth_server(AuthServer())
        out = await oauth.start("cal")
        with pytest.raises(ValueError, match="OAuth flow failed"):
            oauth.complete("cal", out["flow_id"])
        out = await oauth.start("cal")
        flow = await core_oauth.complete_oauth_flow("c", out["flow_id"], {"iss": ISSUER})
        flow.tokens["token_type"] = "MAC"
        with pytest.raises(ValueError, match="token type"):
            oauth.complete("cal", out["flow_id"])


class TestTokens:
    async def test_fresh_token_is_used_without_a_request(self, env, auth_server):
        srv = auth_server(AuthServer())
        await _sign_in(srv)
        assert await oauth.access_token("cal") == "at1" and srv.tokens == 1
        assert await oauth.access_token("nope") is None  # a key server (or none) has no bearer

    async def test_refresh_within_the_margin_rotates_or_keeps_the_refresh_token(self, env, auth_server):
        srv = auth_server(AuthServer())
        await _sign_in(srv)
        _set_tokens(expires_at=time.time() + 30)
        assert await oauth.access_token("cal") == "at2"
        req = srv.token_requests()[-1]
        assert _form(req) == {"grant_type": "refresh_token", "refresh_token": "rt1", "resource": URL}
        assert req.headers["authorization"].startswith("Basic ")
        o = _server()["oauth"]
        assert o["refresh_token"] == "rt2" and o["expires_at"] > time.time() + 3000  # rotated
        _set_tokens(expires_at=0)
        assert await oauth.access_token("cal") == "at3"
        assert _server()["oauth"]["refresh_token"] == "rt2"  # the AS kept quiet: the old one stays

    async def test_concurrent_callers_share_one_refresh(self, env, auth_server):
        srv = auth_server(AuthServer(token_delay=0.05))
        await _sign_in(srv)
        _set_tokens(expires_at=0)
        got = await asyncio.gather(*(oauth.access_token("cal") for _ in range(5)))
        assert got == ["at2"] * 5 and srv.tokens == 2

    async def test_no_refresh_token_or_a_refused_refresh_means_sign_in_again(self, env, auth_server, monkeypatch):
        srv = auth_server(AuthServer())
        await _sign_in(srv)
        _set_tokens(expires_at=0, refresh_token="")
        assert oauth.view(_server())["status"] == "sign_in_again"
        with pytest.raises(McpAuthError, match="Sign in again"):
            await oauth.access_token("cal")

        _set_tokens(refresh_token="dead")

        async def refuse(request):
            return httpx.Response(400, json={"error": "invalid_grant"})
        monkeypatch.setattr(core_oauth, "_http", lambda cfg: httpx.AsyncClient(transport=httpx.MockTransport(refuse)))
        with pytest.raises(McpAuthError, match="invalid_grant"):
            await oauth.access_token("cal")
        o = _server()["oauth"]
        assert o["access_token"] == "" and o["refresh_token"] == "" and "invalid_grant" in o["error"]
        assert oauth.view(_server()) == {"status": "sign_in_again", "error": o["error"], "has_client": True}

        _set_tokens(refresh_token="alive", error=None)

        async def flaky(request):
            return httpx.Response(503)
        monkeypatch.setattr(core_oauth, "_http", lambda cfg: httpx.AsyncClient(transport=httpx.MockTransport(flaky)))
        with pytest.raises(McpError, match="HTTP 503"):
            await oauth.access_token("cal")
        assert _server()["oauth"]["refresh_token"] == "alive"  # a transient failure keeps the session

    async def test_a_lost_cross_loop_refresh_race_keeps_the_winners_tokens(self, env, auth_server, monkeypatch):
        """refresh_stale() refreshes on its own loop with its own lock. When both loops send the same
        single-use refresh token, the loser's invalid_grant must not wipe what the winner stored."""
        srv = auth_server(AuthServer())
        await _sign_in(srv)
        _set_tokens(expires_at=0)

        async def lose(request):  # the other loop's refresh landed first
            _set_tokens(access_token="at-other", refresh_token="rt-other", expires_at=time.time() + 3600, error=None)
            return httpx.Response(400, json={"error": "invalid_grant"})
        monkeypatch.setattr(core_oauth, "_http", lambda cfg: httpx.AsyncClient(transport=httpx.MockTransport(lose)))
        assert await oauth.access_token("cal") == "at-other"
        o = _server()["oauth"]
        assert o["refresh_token"] == "rt-other" and o["error"] is None
        assert oauth.view(_server())["status"] == "signed_in"

    async def test_token_refused_for_another_resource(self, env, auth_server):
        srv = auth_server(AuthServer())
        await _sign_in(srv)
        _set_tokens(expires_at=0, resource="https://mcp.cal.test/other")
        with pytest.raises(McpAuthError, match="not this server"):
            await oauth.access_token("cal")

    def test_view_states(self, env):
        s = _server()
        assert oauth.view({**s, "api_key": "k"}) is None
        assert oauth.view(s)["status"] == "none"
        base = {"token_endpoint": "t", "access_token": "a", "refresh_token": "r", "expires_at": time.time() + 3600}
        assert oauth.view({**s, "oauth": base})["status"] == "signed_in"
        assert oauth.view({**s, "oauth": {**base, "expires_at": 0}})["status"] == "expired"
        assert oauth.view({**s, "oauth": {**base, "expires_at": 0, "refresh_token": ""}})["status"] == "sign_in_again"
        assert oauth.view({**s, "oauth": {**base, "error": "x"}})["status"] == "sign_in_again"


def _mcp_server(records: list, *, reject: set[str], fail_call=False):
    """A streamable-HTTP MCP server that answers 401 to the bearer tokens in `reject`."""
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        records.append((request.headers.get("authorization"), body["method"] if body else request.method))
        if request.method == "DELETE":
            return httpx.Response(200)
        if request.headers.get("authorization") in reject:
            return httpx.Response(401, headers={"www-authenticate": 'Bearer resource_metadata="https://mcp.cal.test/.well-known/oauth-protected-resource/mcp"'})
        if body["method"] == "initialize":
            return httpx.Response(200, headers={"mcp-session-id": "s"}, json={"jsonrpc": "2.0", "id": 1, "result": {}})
        if body["method"] == "notifications/initialized":
            return httpx.Response(202)
        if body["method"] == "tools/call" and fail_call:
            return httpx.Response(401)
        if body["method"] == "tools/call":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 2, "result": {"content": [{"type": "text", "text": "ok"}]}})
        if body["method"] == "tools/list":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 2, "result": {"tools": [{"name": "today"}]}})
        return httpx.Response(404)
    return httpx.MockTransport(handler)


class TestRetry:
    async def test_401_before_the_call_gets_one_refresh_and_one_retry(self, env, auth_server, monkeypatch):
        srv = auth_server(AuthServer())
        await _sign_in(srv)
        records = []
        monkeypatch.setattr(McpClient, "_http", lambda self: httpx.AsyncClient(transport=_mcp_server(records, reject={"Bearer at1"})))
        store.update(lambda c: c["servers"]["cal"].__setitem__("tools", [{"name": "today", "description": "", "input_schema": {}, "read_only_hint": None}]))
        ex = mcp_tools.TOOL_EXECUTORS()["mcp_cal__today"]
        assert await ex(_ctx={"origin": "user"}) == {"content": "ok"}
        assert srv.tokens == 2 and _server()["oauth"]["access_token"] == "at2"
        assert [r for r in records if r[1] == "tools/call"] == [("Bearer at2", "tools/call")]
        assert records[0] == ("Bearer at1", "initialize")

        # Still 401 with the refreshed token: no second refresh, a readable error.
        monkeypatch.setattr(McpClient, "_http", lambda self: httpx.AsyncClient(transport=_mcp_server(records, reject={"Bearer at2", "Bearer at3"})))
        r = await ex(_ctx={"origin": "user"})
        assert r["error"].startswith("MCP server 'Cal': HTTP 401") and srv.tokens == 3

    async def test_a_401_on_the_tool_call_itself_is_never_retried(self, env, auth_server, monkeypatch):
        srv = auth_server(AuthServer())
        await _sign_in(srv)
        records = []
        monkeypatch.setattr(McpClient, "_http", lambda self: httpx.AsyncClient(transport=_mcp_server(records, reject=set(), fail_call=True)))
        store.update(lambda c: c["servers"]["cal"].__setitem__("tools", [{"name": "today", "description": "", "input_schema": {}, "read_only_hint": None}]))
        r = await mcp_tools.TOOL_EXECUTORS()["mcp_cal__today"](_ctx={"origin": "user"})
        assert "HTTP 401" in r["error"] and srv.tokens == 1
        assert sum(r[1] == "tools/call" for r in records) == 1

    async def test_a_key_server_401_is_not_refreshed(self, env, monkeypatch):
        store.update(lambda c: c["servers"]["cal"].update({"api_key": "k", "oauth": None}))
        records = []
        monkeypatch.setattr(McpClient, "_http", lambda self: httpx.AsyncClient(transport=_mcp_server(records, reject={"Bearer k"})))
        with pytest.raises(McpAuthError):
            await oauth.run("cal", lambda c: c.list_tools())
        assert len(records) == 1

    async def test_refresh_server_uses_the_token_and_records_sign_in_again(self, env, auth_server, monkeypatch):
        srv = auth_server(AuthServer())
        await _sign_in(srv)
        records = []
        monkeypatch.setattr(McpClient, "_http", lambda self: httpx.AsyncClient(transport=_mcp_server(records, reject=set())))
        st = await service.refresh_server("cal")
        assert [t["name"] for t in st["servers"][0]["tools"]] == ["today"] and records[0][0] == "Bearer at1"
        _set_tokens(expires_at=0, refresh_token="")
        st = await service.refresh_server("cal")
        assert "Sign in again" in st["servers"][0]["last_error"] and st["servers"][0]["oauth"]["status"] == "sign_in_again"


class TestAddServer:
    async def test_a_401_without_a_key_saves_the_server_for_sign_in(self, env, monkeypatch):
        async def list_tools(self):
            raise McpAuthError("HTTP 401", 'Bearer resource_metadata="https://mcp.cal.test/.well-known/oauth-protected-resource", scope="x"')
        monkeypatch.setattr(McpClient, "list_tools", list_tools)
        st = await service.add_server("Cal 2", URL, "", "Authorization")
        s = {v["id"]: v for v in st["servers"]}["cal_2"]
        assert s["tools"] == [] and s["last_error"] == service.NOT_SIGNED_IN
        assert s["oauth"] == {"status": "none", "error": None, "has_client": False}
        raw = store.servers()["cal_2"]
        assert raw["oauth"] == {"resource_metadata": "https://mcp.cal.test/.well-known/oauth-protected-resource"}
        assert isinstance(raw["generation"], int) and raw["generation"] > 1
        with pytest.raises(McpAuthError):  # with a key, a 401 is a bad key
            await service.add_server("Cal 3", URL, "k", "Authorization")
        assert {v["id"]: v["oauth"] for v in st["servers"]}["cal"]["status"] == "none"

    async def test_a_public_server_that_loaded_tools_without_a_key_offers_no_sign_in(self, env, monkeypatch):
        async def list_tools(self):
            return [{"name": "t"}]
        monkeypatch.setattr(McpClient, "list_tools", list_tools)
        st = await service.add_server("Open", "https://open.test/mcp", "", "Authorization")
        assert {v["id"]: v for v in st["servers"]}["open"]["oauth"] is None


class TestRoutes:
    def test_start_complete_and_client_routes(self, client, monkeypatch, auth_server):
        srv = auth_server(AuthServer())
        monkeypatch.setattr(ssrf, "resolve", lambda h: [PUBLIC])
        monkeypatch.delenv("OAUTH_REDIRECT_URI", raising=False)
        oauth._locks.clear()

        async def list_tools(self):
            raise McpAuthError("HTTP 401")
        monkeypatch.setattr(McpClient, "list_tools", list_tools)
        r = client.post("/api/integrations/mcp/servers", json={"name": "Cal", "url": URL})
        assert r.status_code == 200 and r.json()["servers"][0]["oauth"]["status"] == "none"

        r = client.post("/api/integrations/mcp/servers/cal/oauth/start")
        assert r.status_code == 200 and set(r.json()) == {"flow_id", "auth_url"}
        flow_id = r.json()["flow_id"]
        # The proxy strips ":<callback>" from state and forwards iss; the callback route needs no JWT.
        cb = client.get("/api/oauth/callback", params={"code": "c", "state": flow_id, "iss": ISSUER})
        assert cb.status_code == 200 and "Connected" in cb.text
        assert client.get(f"/api/oauth/flows/{flow_id}/status").json() == {"status": "ok", "error": None}

        async def list_tools_ok(self):
            assert self._headers["Authorization"] == "Bearer at1"
            return [{"name": "today", "inputSchema": {}}]
        monkeypatch.setattr(McpClient, "list_tools", list_tools_ok)
        r = client.post("/api/integrations/mcp/servers/cal/oauth/complete", json={"flow_id": flow_id})
        s = r.json()["servers"][0]
        assert r.status_code == 200 and s["oauth"]["status"] == "signed_in" and [t["name"] for t in s["tools"]] == ["today"]
        assert "access_token" not in r.text and "csec" not in r.text and srv.tokens == 1

        assert client.post("/api/integrations/mcp/servers/cal/oauth/complete", json={"flow_id": flow_id}).status_code == 404
        assert client.post("/api/integrations/mcp/servers/nope/oauth/start").status_code == 404
        r = client.put("/api/integrations/mcp/servers/cal/oauth/client", json={"client_id": "x", "client_secret": "y"})
        assert r.status_code == 200 and r.json()["servers"][0]["oauth"] == {"status": "none", "error": None, "has_client": True}
        assert client.put("/api/integrations/mcp/servers/nope/oauth/client", json={"client_id": "x"}).status_code == 404

        auth_server(AuthServer(prm={**PRM, "resource": "https://mcp.cal.test/other"}))
        r = client.post("/api/integrations/mcp/servers/cal/oauth/start")
        assert r.status_code == 400 and "protects" in r.json()["detail"]
