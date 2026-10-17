"""Chatty — OAuth sign-in for a remote MCP server (MCP authorization spec, 2025-06-18).

Discovery: the protected-resource metadata (RFC 9728, from the 401 challenge or the
well-known path) names the authorization server; its metadata (RFC 8414 / OpenID
discovery) names the endpoints and must carry the issuer it was fetched from; dynamic
client registration (RFC 7591) gives us a client, or the user pastes one on the card.
Every URL goes through ssrf.validate_url and the pinned client (redirects off). The flow
itself is core.providers.oauth with an immutable FlowConfig: PKCE S256, `resource` on the
authorization request and every token request, `iss` checked on the callback when the
server advertises it, and the flow bound to the server id and its config generation.

Per server in mcp.json (encrypt_dict covers access_token / refresh_token / client_secret):
    "oauth": {"resource_metadata": url | None,              # from the 401 challenge
              "client_id", "client_secret", "use_basic_auth", "registered": bool,
              "issuer", "authorization_endpoint", "token_endpoint", "scopes", "check_iss",
              "resource", "access_token", "refresh_token", "expires_at", "error"}
A token is only ever sent to the server whose canonical URL equals `resource`.
"""

import asyncio
import re
import time
from urllib.parse import urlsplit, urlunsplit

import httpx

from core.providers.oauth import FlowConfig, consume_flow, redirect_uri, refresh_tokens, start_flow
from core.security.ssrf import pinned_client, validate_url

from . import store
from .client import McpAuthError, McpClient, McpError

REFRESH_MARGIN = 60  # seconds before expiry a token counts as expired
MAX_METADATA = 1024 * 1024
SIGN_IN_AGAIN = "Sign in again on the MCP card"
_transport: httpx.AsyncBaseTransport | None = None  # tests only: bypasses the pinned transport
_locks: dict[tuple[int, str], asyncio.Lock] = {}


def canonical(url: str) -> str:
    """RFC 8707 resource form: lowercase scheme and host, no query, fragment or trailing slash."""
    p = urlsplit(url)
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path.rstrip("/"), "", ""))


def challenge_metadata_url(www_authenticate: str) -> str | None:
    m = re.search(r'resource_metadata="([^"]+)"', www_authenticate or "")
    return m.group(1) if m else None


def _http() -> httpx.AsyncClient:
    if _transport is not None:
        return httpx.AsyncClient(transport=_transport, timeout=15)
    return pinned_client(timeout=15)


def _checked(url) -> str:
    if not isinstance(url, str) or (err := validate_url(url)):
        raise McpError(f"{err if isinstance(url, str) else 'Invalid URL'}: {url}")
    return url


async def _json(http, method: str, url: str, **kw) -> dict | None:
    """The JSON object at `url`, or None for a non-2xx answer or a non-object body."""
    try:
        resp = await http.request(method, _checked(url), headers={"Accept": "application/json"}, **kw)
    except httpx.HTTPError as e:
        raise McpError(f"{type(e).__name__}: {e}") from e
    if not 200 <= resp.status_code < 300 or len(resp.content) > MAX_METADATA:
        return None
    try:
        data = resp.json()
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


# ── Discovery ──────────────────────────────────────────────────────────────────

async def discover(http, s: dict) -> dict:
    """What the server's authorization server is and offers. Raises McpError with the reason."""
    url = canonical(s["url"])
    p = urlsplit(url)
    origin = f"{p.scheme}://{p.netloc}"
    prm = None
    for cand in dict.fromkeys([(s.get("oauth") or {}).get("resource_metadata"),
                               f"{origin}/.well-known/oauth-protected-resource{p.path}",
                               f"{origin}/.well-known/oauth-protected-resource"]):
        if cand and (prm := await _json(http, "GET", cand)):
            break
    prm = prm or {}  # no metadata: the server is its own authorization server (2025-03-26 behaviour)
    resource = canonical(str(prm.get("resource") or url))
    if resource != url:
        raise McpError(f"The server's metadata protects {resource}, not {url}")
    servers = prm.get("authorization_servers")
    issuer = str((servers if isinstance(servers, list) and servers else [origin])[0]).rstrip("/")
    ip = urlsplit(issuer)
    as_origin = f"{ip.scheme}://{ip.netloc}"
    md_urls = [f"{as_origin}/.well-known/oauth-authorization-server{ip.path}",
               f"{as_origin}/.well-known/openid-configuration{ip.path}"]
    if ip.path:
        md_urls.append(f"{issuer}/.well-known/openid-configuration")
    md = None
    for cand in md_urls:
        if md := await _json(http, "GET", cand):
            break
    if not md:
        raise McpError(f"No authorization server metadata at {issuer}")
    if str(md.get("issuer") or "").rstrip("/") != issuer:
        raise McpError(f"Authorization server metadata at {issuer} names another issuer")
    methods = md.get("code_challenge_methods_supported")
    if isinstance(methods, list) and "S256" not in methods:
        raise McpError("Authorization server does not support PKCE S256")
    scopes = prm.get("scopes_supported")
    return {
        "issuer": issuer,
        "authorization_endpoint": _checked(md.get("authorization_endpoint")),
        "token_endpoint": _checked(md.get("token_endpoint")),
        "registration_endpoint": md.get("registration_endpoint"),
        "resource": resource,
        # simplification: every advertised scope; upgrade: the challenge's `scope` or a card field.
        "scopes": [x for x in scopes if isinstance(x, str)] if isinstance(scopes, list) else [],
        "check_iss": bool(md.get("authorization_response_iss_parameter_supported")),
        "token_auth_methods": md.get("token_endpoint_auth_methods_supported") or ["client_secret_basic"],
    }


async def _register(http, info: dict) -> dict:
    """Dynamic client registration (RFC 7591); the oauth fields describing the new client."""
    reg = info.get("registration_endpoint")
    if not isinstance(reg, str) or not reg:
        raise McpError("This server has no dynamic client registration. Paste a client id and secret on the MCP card.")
    resp = await _json(http, "POST", reg, json={
        "client_name": "Chatty", "redirect_uris": [redirect_uri()],
        "grant_types": ["authorization_code", "refresh_token"], "response_types": ["code"],
    })
    client_id = (resp or {}).get("client_id")
    if not isinstance(client_id, str) or not client_id:
        raise McpError("Client registration failed")
    secret = str(resp.get("client_secret") or "")
    method = str(resp.get("token_endpoint_auth_method") or ("client_secret_basic" if secret else "none"))
    return {"client_id": client_id, "client_secret": secret, "registered": True,
            "use_basic_auth": bool(secret) and method == "client_secret_basic"}


# ── Sign-in flow ───────────────────────────────────────────────────────────────

async def start(server_id: str) -> dict:
    """Discover, register if needed, and start the flow. Returns {flow_id, auth_url}."""
    s = store.servers().get(server_id)
    if not s:
        raise KeyError(server_id)
    o = dict(s.get("oauth") or {})
    async with _http() as http:
        info = await discover(http, s)
        if o.get("issuer") and o["issuer"] != info["issuer"]:  # a client belongs to one authorization server
            o = {"resource_metadata": o.get("resource_metadata")}
        o["issuer"] = info["issuer"]
        if not o.get("client_id"):
            o.update(await _register(http, info))
        elif not o.get("registered"):  # pasted on the card; RFC 8414's default method is Basic
            o["use_basic_auth"] = bool(o.get("client_secret")) and "client_secret_post" not in info["token_auth_methods"]
    generation = s.get("generation") or 0
    cfg = FlowConfig(
        provider="mcp", auth_url=info["authorization_endpoint"], token_url=info["token_endpoint"],
        client_id=o["client_id"], client_secret=o.get("client_secret") or "", scopes=tuple(info["scopes"]),
        redirect_uri=redirect_uri(), use_pkce=True, use_basic_auth=bool(o.get("use_basic_auth")),
        resource=info["resource"], issuer=info["issuer"], check_iss=info["check_iss"],
        server_id=server_id, generation=generation, pinned=True,
    )

    def apply(c):  # the registered client survives an abandoned flow; a new issuer starts from scratch
        cur = (c.get("servers") or {}).get(server_id)
        if cur is not None and (cur.get("generation") or 0) == generation:
            old = cur.get("oauth") or {}
            cur["oauth"] = {**old, **o} if old.get("issuer") in (None, o["issuer"]) else o
    store.update(apply)
    return start_flow(cfg)


def _expires_at(tokens: dict) -> float:
    try:
        return time.time() + float(tokens.get("expires_in") or 3600)
    except (TypeError, ValueError):
        return time.time() + 3600


def complete(server_id: str, flow_id: str) -> None:
    """Attach the flow's tokens to the server the flow was started for, at the same config generation."""
    flow = consume_flow(flow_id)
    if not flow:
        raise KeyError("flow")
    if flow.status != "ok" or not flow.tokens:
        raise ValueError(flow.error or "OAuth flow failed. Please try again.")
    cfg, t = flow.config, flow.tokens
    if str(t.get("token_type") or "Bearer").lower() != "bearer":
        raise ValueError(f"Unsupported token type {t.get('token_type')!r}")

    def apply(c):
        s = (c.get("servers") or {}).get(server_id)
        if (cfg.provider != "mcp" or cfg.server_id != server_id or s is None
                or (s.get("generation") or 0) != cfg.generation or canonical(s["url"]) != cfg.resource):
            raise ValueError("This sign-in was for a server that has since changed. Start again.")
        s["oauth"] = {
            **(s.get("oauth") or {}),
            "issuer": cfg.issuer, "authorization_endpoint": cfg.auth_url, "token_endpoint": cfg.token_url,
            "client_id": cfg.client_id, "client_secret": cfg.client_secret, "use_basic_auth": cfg.use_basic_auth,
            "scopes": list(cfg.scopes), "check_iss": cfg.check_iss, "resource": cfg.resource,
            "access_token": t["access_token"], "refresh_token": t.get("refresh_token") or "",
            "expires_at": _expires_at(t), "error": None,
        }
        s["last_error"] = None
    store.update(apply)


def set_client(server_id: str, client_id: str, client_secret: str) -> None:
    """A pasted OAuth client (servers without dynamic registration). Old tokens belong to the old client."""
    def apply(c):
        s = (c.get("servers") or {}).get(server_id)
        if s is None:
            raise KeyError(server_id)
        s["oauth"] = {"resource_metadata": (s.get("oauth") or {}).get("resource_metadata"),
                      "client_id": client_id.strip(), "client_secret": client_secret.strip(), "registered": False}
        s["generation"] = time.time_ns()
    store.update(apply)


# ── Tokens ─────────────────────────────────────────────────────────────────────

def view(s: dict) -> dict | None:
    """Card status for a server that needs a sign-in; None for a key server, a command server or a public one
    that loaded tools."""
    if s.get("api_key") or store.is_command(s) or (s.get("oauth") is None and s.get("tools")):
        return None
    o = s.get("oauth") or {}
    if not o.get("token_endpoint"):
        status = "none"
    elif o.get("error") or not (o.get("access_token") or o.get("refresh_token")):
        status = "sign_in_again"
    elif _fresh(o, None):
        status = "signed_in"
    else:
        status = "sign_in_again" if not o.get("refresh_token") else "expired"
    return {"status": status, "error": o.get("error"), "has_client": bool(o.get("client_id"))}


def _fresh(o: dict, rejected: str | None) -> bool:
    tok = o.get("access_token")
    return bool(tok) and tok != rejected and (o.get("expires_at") or 0) - REFRESH_MARGIN > time.time()


def _lock(server_id: str) -> asyncio.Lock:
    # simplification: keyed by (loop, server) because executors run on the request loop and
    # refresh_stale on its own asyncio.run(); upgrade: one loop for all MCP traffic.
    return _locks.setdefault((id(asyncio.get_running_loop()), server_id), asyncio.Lock())


def _record(server_id: str, **fields) -> None:
    def apply(c):
        s = (c.get("servers") or {}).get(server_id)
        if s is not None:
            s.setdefault("oauth", {}).update(fields)
    store.update(apply)


async def access_token(server_id: str, rejected: str | None = None) -> str | None:
    """The bearer for `server_id`, or None for a key server. Refreshed under a per-server lock when
    within REFRESH_MARGIN of expiry or when the caller's `rejected` token is the one still stored."""
    o = (store.servers().get(server_id) or {}).get("oauth") or {}
    if not o.get("token_endpoint"):
        return None
    if _fresh(o, rejected):
        return o["access_token"]
    async with _lock(server_id):
        s = store.servers().get(server_id) or {}
        o = s.get("oauth") or {}
        if _fresh(o, rejected):
            return o["access_token"]
        return await _refresh(server_id, s, o)


async def _refresh(server_id: str, s: dict, o: dict) -> str:
    if canonical(s["url"]) != o.get("resource"):
        raise McpAuthError(f"The stored token is for {o.get('resource')}, not this server. {SIGN_IN_AGAIN}.")
    rt = o.get("refresh_token")
    if not rt:
        raise McpAuthError(f"The session expired and the server gave no refresh token. {SIGN_IN_AGAIN}.")
    cfg = FlowConfig(provider="mcp", auth_url="", token_url=_checked(o.get("token_endpoint")),
                     client_id=o.get("client_id") or "", client_secret=o.get("client_secret") or "",
                     use_basic_auth=bool(o.get("use_basic_auth")), resource=o["resource"], pinned=True)
    try:
        t = await refresh_tokens(cfg, rt)
    except httpx.HTTPStatusError as e:
        if e.response.status_code not in (400, 401):
            raise McpError(f"Token refresh failed: HTTP {e.response.status_code}") from e
        # The lock is per loop, so a refresh on the scheduler's loop (refresh_stale) can race one
        # here with a single-use refresh token: the loser gets invalid_grant. If the stored refresh
        # token is no longer the one we sent, the other side won — use its tokens, clear nothing.
        cur = (store.servers().get(server_id) or {}).get("oauth") or {}
        if cur.get("refresh_token") and cur.get("refresh_token") != rt and cur.get("access_token"):
            return cur["access_token"]
        try:
            why = str(e.response.json().get("error") or e.response.status_code)
        except (ValueError, AttributeError):
            why = str(e.response.status_code)
        _record(server_id, access_token="", refresh_token="", error=f"Token refresh refused ({why})")
        raise McpAuthError(f"Token refresh refused ({why}). {SIGN_IN_AGAIN}.") from e
    except httpx.HTTPError as e:
        raise McpError(f"Token refresh failed: {type(e).__name__}: {e}") from e
    tok = t.get("access_token")
    if not isinstance(tok, str) or not tok:
        raise McpError("Token refresh returned no access token")
    # A rotated refresh token replaces the old one; a server that keeps it quiet keeps the old one valid.
    _record(server_id, access_token=tok, refresh_token=t.get("refresh_token") or rt, expires_at=_expires_at(t), error=None)
    return tok


def client_for(s: dict, token: str | None) -> McpClient:
    if token:
        return McpClient(s["url"], token)
    return McpClient(s["url"], s.get("api_key") or "", s.get("header") or "Authorization")


async def run(server_id: str, op):
    """await op(client) with the server's credential. After an HTTP 401 raised before the tool call
    ran, one refreshed token and one retry; a failure of the call itself is never retried."""
    s = store.servers()[server_id]
    token = await access_token(server_id)
    try:
        return await op(client_for(s, token))
    except McpAuthError as e:
        if token is None or not e.retry_safe:
            raise
        return await op(client_for(s, await access_token(server_id, rejected=token)))
