"""core.providers.oauth — the built-in providers behave as before the per-flow config: Google's extra
authorization params, QuickBooks' Basic auth and realmId, OpenAI, both callback modes, and the
config frozen at start."""

import base64
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from core.providers import oauth

CREDS = {"google": ("g-id", "g-secret"), "openai": ("o-id", ""), "quickbooks": ("q-id", "q-secret")}


@pytest.fixture
def token_server(monkeypatch):
    """Creds resolved from CREDS, no proxy override, and a token endpoint that records every request."""
    records = []
    monkeypatch.setattr(oauth, "_resolve_cred", lambda integ, field: CREDS[integ][0 if field == "client_id" else 1])
    monkeypatch.delenv("OAUTH_REDIRECT_URI", raising=False)

    def handler(request: httpx.Request) -> httpx.Response:
        records.append(request)
        return httpx.Response(200, json={"access_token": "at", "refresh_token": "rt", "expires_in": 1234, "token_type": "Bearer"})
    monkeypatch.setattr(oauth, "_http", lambda cfg: httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    return records


def _params(url: str) -> dict:
    return {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}


def _form(request: httpx.Request) -> dict:
    return {k: v[0] for k, v in parse_qs(request.content.decode(), keep_blank_values=True).items()}


class TestGoogle:
    def test_auth_url_has_pkce_offline_access_prompt_and_proxy_state(self, token_server):
        out = oauth.start_oauth_flow("google", scopes=["s1", "s2"], prompt="consent select_account", metadata={"k": 1})
        p = _params(out["auth_url"])
        assert out["auth_url"].startswith("https://accounts.google.com/o/oauth2/v2/auth?")
        assert p["client_id"] == "g-id" and p["redirect_uri"] == "https://auth.mechatty.com/callback"
        assert p["response_type"] == "code" and p["scope"] == "s1 s2"
        assert p["access_type"] == "offline" and p["prompt"] == "consent select_account"
        assert p["code_challenge_method"] == "S256" and len(p["code_challenge"]) == 43
        assert "resource" not in p
        flow_id, encoded = p["state"].split(":")
        assert flow_id == out["flow_id"]
        assert base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)) == b"http://localhost:8000/api/oauth/callback"
        assert oauth._OAUTH_FLOWS[flow_id].metadata == {"k": 1}

    def test_default_scopes_and_prompt(self, token_server):
        p = _params(oauth.start_oauth_flow("google")["auth_url"])
        assert p["prompt"] == "consent" and p["scope"]

    async def test_exchange_sends_client_secret_verifier_and_redirect_in_the_body(self, token_server):
        out = oauth.start_oauth_flow("google")
        flow = await oauth.complete_oauth_flow("the-code", out["flow_id"], {})
        req = token_server[-1]
        assert str(req.url) == "https://oauth2.googleapis.com/token" and "authorization" not in req.headers
        body = _form(req)
        assert body == {"grant_type": "authorization_code", "redirect_uri": "https://auth.mechatty.com/callback",
                        "code": "the-code", "client_id": "g-id", "client_secret": "g-secret",
                        "code_verifier": oauth._OAUTH_FLOWS[out["flow_id"]].code_verifier}
        assert flow.status == "ok" and flow.tokens == {"access_token": "at", "refresh_token": "rt", "expires_in": 1234, "token_type": "Bearer"}
        assert oauth.consume_flow(out["flow_id"]) is flow and oauth.consume_flow(out["flow_id"]) is None

    async def test_refresh_google_token_body(self, token_server):
        assert (await oauth.refresh_google_token("old-rt"))["access_token"] == "at"
        assert _form(token_server[-1]) == {"grant_type": "refresh_token", "client_id": "g-id",
                                           "client_secret": "g-secret", "refresh_token": "old-rt"}

    def test_missing_client_id_and_unknown_provider(self, token_server, monkeypatch):
        monkeypatch.setattr(oauth, "_resolve_cred", lambda integ, field: "")
        with pytest.raises(ValueError, match="GOOGLE_CLIENT_ID"):
            oauth.start_oauth_flow("google")
        with pytest.raises(ValueError, match="Unknown provider"):
            oauth.start_oauth_flow("github")


class TestQuickBooks:
    async def test_no_pkce_basic_auth_and_realm_id(self, token_server):
        out = oauth.start_oauth_flow("quickbooks")
        p = _params(out["auth_url"])
        assert out["auth_url"].startswith("https://appcenter.intuit.com/connect/oauth2?")
        assert p["scope"] == "com.intuit.quickbooks.accounting" and "code_challenge" not in p and "prompt" not in p
        flow = await oauth.complete_oauth_flow("c", out["flow_id"], {"realmId": "4620", "other": "x"})
        req = token_server[-1]
        assert str(req.url) == "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
        assert req.headers["authorization"] == "Basic " + base64.b64encode(b"q-id:q-secret").decode()
        assert _form(req) == {"grant_type": "authorization_code", "redirect_uri": "https://auth.mechatty.com/callback", "code": "c"}
        assert flow.tokens["realmId"] == "4620" and "other" not in flow.tokens


class TestOpenAI:
    async def test_pkce_and_the_empty_secret_still_sent(self, token_server):
        out = oauth.start_oauth_flow("openai")
        p = _params(out["auth_url"])
        assert out["auth_url"].startswith("https://auth.openai.com/authorize?")
        assert p["scope"] == "openid email profile model.request" and p["code_challenge_method"] == "S256"
        await oauth.complete_oauth_flow("c", out["flow_id"], {})
        body = _form(token_server[-1])
        assert str(token_server[-1].url) == "https://auth.openai.com/oauth/token"
        assert body["client_id"] == "o-id" and body["client_secret"] == "" and body["code_verifier"]


class TestCallbackModes:
    def test_direct_mode_uses_the_env_redirect_and_a_bare_state(self, token_server, monkeypatch):
        monkeypatch.setenv("OAUTH_REDIRECT_URI", "https://me.example/api/oauth/callback")
        out = oauth.start_oauth_flow("google")
        p = _params(out["auth_url"])
        assert p["state"] == out["flow_id"] and p["redirect_uri"] == "https://me.example/api/oauth/callback"
        assert oauth._OAUTH_FLOWS[out["flow_id"]].config.redirect_uri == "https://me.example/api/oauth/callback"

    async def test_proxy_mode_callback_arrives_with_the_bare_flow_id(self, token_server):
        out = oauth.start_oauth_flow("google")
        assert ":" in _params(out["auth_url"])["state"]
        flow = await oauth.complete_oauth_flow("c", out["flow_id"], {})  # the proxy strips ":<callback>"
        assert flow.status == "ok"
        with pytest.raises(ValueError, match="Unknown or expired"):
            await oauth.complete_oauth_flow("c", "nope", {})


class TestFlowConfig:
    async def test_config_is_frozen_at_start(self, token_server, monkeypatch):
        out = oauth.start_oauth_flow("google")
        monkeypatch.setattr(oauth, "_resolve_cred", lambda integ, field: "changed")
        monkeypatch.setenv("OAUTH_REDIRECT_URI", "https://elsewhere.example/cb")
        await oauth.complete_oauth_flow("c", out["flow_id"], {})
        body = _form(token_server[-1])
        assert body["client_id"] == "g-id" and body["redirect_uri"] == "https://auth.mechatty.com/callback"
        with pytest.raises(Exception):
            oauth._OAUTH_FLOWS[out["flow_id"]].config.client_id = "x"

    async def test_iss_checked_only_when_the_config_asks(self, token_server):
        cfg = oauth.FlowConfig(provider="mcp", auth_url="https://as.test/authorize", token_url="https://as.test/token",
                               client_id="c", issuer="https://as.test", check_iss=True, resource="https://mcp.test/mcp")
        out = oauth.start_flow(cfg)
        with pytest.raises(ValueError, match="wrong issuer"):
            await oauth.complete_oauth_flow("c", out["flow_id"], {"iss": "https://evil.test"})
        assert oauth.get_flow_status(out["flow_id"]) == {"status": "error", "error": "Authorization response came from the wrong issuer"}
        assert token_server == []

        out = oauth.start_flow(cfg)
        with pytest.raises(ValueError, match="wrong issuer"):
            await oauth.complete_oauth_flow("c", out["flow_id"], {})  # missing iss is a mismatch too
        out = oauth.start_flow(cfg)
        flow = await oauth.complete_oauth_flow("c", out["flow_id"], {"iss": "https://as.test"})
        assert flow.status == "ok"
        body = _form(token_server[-1])
        assert body["resource"] == "https://mcp.test/mcp" and "client_secret" not in body  # public MCP client
        assert _params(out["auth_url"])["resource"] == "https://mcp.test/mcp"

    def test_an_authorization_endpoint_with_a_query_keeps_it(self, token_server):
        cfg = oauth.FlowConfig(provider="mcp", auth_url="https://as.test/authorize?tenant=t1", token_url="https://as.test/token", client_id="c")
        url = oauth.start_flow(cfg)["auth_url"]
        assert url.startswith("https://as.test/authorize?tenant=t1&client_id=c&") and url.count("?") == 1
        assert _params(url)["tenant"] == "t1" and _params(url)["response_type"] == "code"

    def test_failed_exchange_marks_the_flow(self, token_server, monkeypatch):
        def handler(request):
            return httpx.Response(400, json={"error": "invalid_grant"})
        monkeypatch.setattr(oauth, "_http", lambda cfg: httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        import asyncio
        out = oauth.start_oauth_flow("google")
        with pytest.raises(httpx.HTTPStatusError):
            asyncio.run(oauth.complete_oauth_flow("c", out["flow_id"], {}))
        assert oauth.get_flow_status(out["flow_id"])["status"] == "error"
