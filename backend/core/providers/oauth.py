"""
Chatty — OAuth flow for Google, OpenAI, QuickBooks and remote MCP servers.

All OAuth flows route through the auth.mechatty.com proxy by default.
The proxy receives the callback from the OAuth provider (Google, Intuit,
OpenAI), then 302-redirects the auth code to the originating Chatty
instance. This lets every deployment — local dev, Railway, custom host —
share a single registered redirect URI without ngrok or per-instance
callback URLs.

Two-step pattern:
    1. `start_oauth_flow(provider, scopes=..., metadata=...)` returns
       {flow_id, auth_url}. The caller opens auth_url in a popup; the user
       authorizes with the provider.
    2. The provider redirects to auth.mechatty.com/callback, which decodes
       the instance callback URL from the state parameter and 302-redirects
       to `{backend_url}/api/oauth/callback?code=...&state=<flow_id>` (every
       other callback parameter — realmId, iss — is forwarded as is).
       That FastAPI route calls `complete_oauth_flow(...)` which exchanges
       the code for tokens and stashes them on the OAuthFlow object.
    3. The frontend polls `/api/oauth/flows/{flow_id}/status`; once it
       reports `status: "ok"`, the frontend calls the integration-specific
       `/setup/complete` endpoint (e.g. `/api/integrations/quickbooks/setup/complete`)
       which reads the tokens via `consume_flow(flow_id)` and persists them.

Every flow carries a FlowConfig fixed when it starts: endpoints, client,
scopes, redirect URI, resource and issuer. Nothing read later can change
where the code is exchanged. The built-in providers build theirs from
OAUTH_CONFIG; MCP servers build theirs from discovery (integrations.mcp.oauth).

Set OAUTH_REDIRECT_URI to bypass the proxy (direct mode) or use a
different proxy.
"""

import base64
import hashlib
import logging
import os
import secrets
import time
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx

from core.config import settings

logger = logging.getLogger(__name__)


# ── Credential resolver ──────────────────────────────────────────────────────

def _resolve_cred(integration: str, field: str) -> str:
    """Read a BYO app credential, falling back to env vars."""
    from integrations.app_credentials import get_app_credentials
    return get_app_credentials(integration).get(field, "")


# ── Provider OAuth config ─────────────────────────────────────────────────────

OAUTH_CONFIG = {
    "google": {
        "auth_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url": "https://oauth2.googleapis.com/token",
        "client_id": lambda: _resolve_cred("google", "client_id"),
        "client_secret": lambda: _resolve_cred("google", "client_secret"),
        "scopes": lambda: settings.google_oauth.scopes,
        "use_pkce": True,
        "use_basic_auth": False,
        "extra_callback_params": [],
    },
    "openai": {
        "auth_url": "https://auth.openai.com/authorize",
        "token_url": "https://auth.openai.com/oauth/token",
        "client_id": lambda: _resolve_cred("openai", "client_id"),
        "client_secret": lambda: _resolve_cred("openai", "client_secret"),
        "scopes": lambda: ["openid", "email", "profile", "model.request"],
        "use_pkce": True,
        "use_basic_auth": False,
        "extra_callback_params": [],
    },
    "quickbooks": {
        "auth_url": "https://appcenter.intuit.com/connect/oauth2",
        "token_url": "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer",
        "client_id": lambda: _resolve_cred("quickbooks", "client_id"),
        "client_secret": lambda: _resolve_cred("quickbooks", "client_secret"),
        "scopes": lambda: ["com.intuit.quickbooks.accounting"],
        "use_pkce": False,
        "use_basic_auth": True,
        "extra_callback_params": ["realmId"],
    },
}

CALLBACK_PATH = "/api/oauth/callback"


@dataclass(frozen=True)
class FlowConfig:
    """Everything one flow needs, fixed when it starts."""
    provider: str
    auth_url: str
    token_url: str
    client_id: str
    client_secret: str = ""
    scopes: tuple[str, ...] = ()
    redirect_uri: str = ""
    use_pkce: bool = True
    use_basic_auth: bool = False
    extra_auth_params: tuple[tuple[str, str], ...] = ()  # Google: access_type, prompt
    extra_callback_params: tuple[str, ...] = ()  # QuickBooks: realmId
    # MCP (RFC 8707 / MCP authorization spec)
    resource: str = ""  # sent on the authorization request and every token request
    issuer: str = ""  # the authorization server its metadata was found at
    check_iss: bool = False  # the server advertises authorization_response_iss_parameter_supported
    server_id: str = ""
    generation: int = 0  # the server's config generation when the flow started
    pinned: bool = False  # token requests go over the SSRF-pinned client (redirects off)


def provider_config(provider: str, scopes: list[str] | None = None, prompt: str | None = None) -> FlowConfig:
    """The FlowConfig for a built-in provider, read from OAUTH_CONFIG right now."""
    cfg = OAUTH_CONFIG[provider]
    if scopes is None:
        scopes_spec = cfg["scopes"]
        scopes = scopes_spec() if callable(scopes_spec) else scopes_spec
    extra = (("access_type", "offline"), ("prompt", prompt or "consent")) if provider == "google" else ()
    return FlowConfig(
        provider=provider,
        auth_url=cfg["auth_url"],
        token_url=cfg["token_url"],
        client_id=cfg["client_id"](),
        client_secret=cfg["client_secret"](),
        scopes=tuple(scopes),
        redirect_uri=redirect_uri(),
        use_pkce=cfg.get("use_pkce", True),
        use_basic_auth=cfg.get("use_basic_auth", False),
        extra_auth_params=extra,
        extra_callback_params=tuple(cfg.get("extra_callback_params", [])),
    )


# ── Flow state ────────────────────────────────────────────────────────────────

_OAUTH_FLOWS: dict[str, "OAuthFlow"] = {}
_FLOW_TTL_SECONDS = 600  # 10 minutes


class OAuthFlow:
    """Tracks a single in-flight OAuth authorization flow."""

    def __init__(
        self,
        flow_id: str,
        config: FlowConfig,
        code_verifier: str | None,
        metadata: dict | None = None,
    ):
        self.flow_id = flow_id
        self.config = config
        self.provider = config.provider
        self.code_verifier = code_verifier
        self.metadata = metadata or {}
        self.created_at = time.time()
        self.status = "pending"  # pending | ok | error
        self.tokens: dict | None = None
        self.error: str | None = None


def _cleanup_expired_flows() -> None:
    """Remove flows older than TTL. Called on every start/complete/status."""
    now = time.time()
    expired = [
        fid for fid, flow in _OAUTH_FLOWS.items()
        if now - flow.created_at > _FLOW_TTL_SECONDS
    ]
    for fid in expired:
        _OAUTH_FLOWS.pop(fid, None)


# ── Redirect URI ──────────────────────────────────────────────────────────────

_DEFAULT_REDIRECT_URI = "https://auth.mechatty.com/callback"


def redirect_uri() -> str:
    return os.getenv("OAUTH_REDIRECT_URI", "") or _DEFAULT_REDIRECT_URI


# ── PKCE helpers ──────────────────────────────────────────────────────────────

def _generate_pkce() -> tuple[str, str]:
    """Generate (code_verifier, code_challenge) for PKCE."""
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    return verifier, challenge


def _build_auth_url(cfg: FlowConfig, code_challenge: str | None, state: str) -> str:
    """Build the OAuth authorization URL, with optional PKCE parameters."""
    params = {
        "client_id": cfg.client_id,
        "redirect_uri": cfg.redirect_uri,
        "response_type": "code",
    }
    if cfg.scopes:
        params["scope"] = " ".join(cfg.scopes)
    params["state"] = state
    if code_challenge:
        params["code_challenge"] = code_challenge
        params["code_challenge_method"] = "S256"
    params.update(cfg.extra_auth_params)
    if cfg.resource:
        params["resource"] = cfg.resource
    return f"{cfg.auth_url}?{urlencode(params)}"


# ── Public API ────────────────────────────────────────────────────────────────

def start_oauth_flow(
    provider: str,
    scopes: list[str] | None = None,
    metadata: dict | None = None,
    prompt: str | None = None,
) -> dict:
    """
    Start an OAuth flow for a built-in provider.

    Args:
        provider: "google" | "openai" | "quickbooks"
        scopes: Optional scope override (used for Google where user picks
                access levels at connect time).
        metadata: Arbitrary caller-owned data attached to the flow. The
                  /setup/complete endpoint reads this via consume_flow() to
                  remember e.g. which scope levels the user requested.

    Returns:
        {"flow_id": str, "auth_url": str}
    """
    if provider not in OAUTH_CONFIG:
        raise ValueError(f"Unknown provider: {provider}")
    cfg = provider_config(provider, scopes, prompt)
    if not cfg.client_id:
        raise ValueError(
            f"OAuth not configured for {provider}: missing {provider.upper()}_CLIENT_ID"
        )
    return start_flow(cfg, metadata)


def start_flow(cfg: FlowConfig, metadata: dict | None = None) -> dict:
    """Start a flow from a ready FlowConfig. Returns {"flow_id", "auth_url"}."""
    _cleanup_expired_flows()

    verifier, challenge = _generate_pkce() if cfg.use_pkce else (None, None)
    flow_id = secrets.token_urlsafe(32)

    if not os.getenv("OAUTH_REDIRECT_URI", ""):
        # Proxy mode (default): encode the instance callback in state so the
        # proxy knows where to forward the auth code.
        instance_callback = f"{settings.backend_url}{CALLBACK_PATH}"
        encoded = base64.urlsafe_b64encode(instance_callback.encode()).rstrip(b"=").decode()
        state = f"{flow_id}:{encoded}"
    else:
        state = flow_id

    auth_url = _build_auth_url(cfg, challenge, state=state)

    _OAUTH_FLOWS[flow_id] = OAuthFlow(
        flow_id=flow_id,
        config=cfg,
        code_verifier=verifier,
        metadata=metadata,
    )

    logger.info("Started OAuth flow: provider=%s flow_id=%s...", cfg.provider, flow_id[:8])
    return {"flow_id": flow_id, "auth_url": auth_url}


async def complete_oauth_flow(code: str, state: str, callback_params: dict) -> OAuthFlow:
    """Exchange the authorization code for tokens. Called by /api/oauth/callback."""
    _cleanup_expired_flows()

    flow = _OAUTH_FLOWS.get(state)
    if not flow:
        raise ValueError("Unknown or expired OAuth state")

    cfg = flow.config
    try:
        # RFC 9207: a server that says it sends `iss` must send ours (the proxy forwards it).
        if cfg.check_iss and callback_params.get("iss") != cfg.issuer:
            raise ValueError("Authorization response came from the wrong issuer")
        tokens = await _exchange_code(cfg, code, flow.code_verifier)
        response = {
            "access_token": tokens.get("access_token", ""),
            "refresh_token": tokens.get("refresh_token", ""),
            "expires_in": tokens.get("expires_in", 3600),
            "token_type": tokens.get("token_type", "Bearer"),
        }
        for param in cfg.extra_callback_params:
            if param in callback_params:
                response[param] = callback_params[param]

        flow.tokens = response
        flow.status = "ok"
        return flow
    except Exception as e:
        logger.error("OAuth token exchange failed for %s: %s", cfg.provider, e)
        flow.error = str(e)
        flow.status = "error"
        raise


def _client_auth(cfg: FlowConfig, data: dict) -> tuple[str, str] | None:
    """Put the client credentials where the server wants them: Basic auth, or the body."""
    if cfg.use_basic_auth:
        return (cfg.client_id, cfg.client_secret)
    data["client_id"] = cfg.client_id
    # Built-in providers always got the field (OpenAI's is empty); a public MCP client must not send one.
    if cfg.client_secret or cfg.provider in OAUTH_CONFIG:
        data["client_secret"] = cfg.client_secret
    return None


async def _exchange_code(cfg: FlowConfig, code: str, code_verifier: str | None) -> dict:
    """Exchange authorization code for access + refresh tokens."""
    data = {
        "grant_type": "authorization_code",
        "redirect_uri": cfg.redirect_uri,
        "code": code,
    }
    auth = _client_auth(cfg, data)
    if code_verifier:
        data["code_verifier"] = code_verifier
    if cfg.resource:
        data["resource"] = cfg.resource
    return await _token_request(cfg, data, auth)


async def refresh_tokens(cfg: FlowConfig, refresh_token: str) -> dict:
    """Use a refresh token to get a new access token (and maybe a rotated refresh token)."""
    data = {"grant_type": "refresh_token", "refresh_token": refresh_token}
    auth = _client_auth(cfg, data)
    if cfg.resource:
        data["resource"] = cfg.resource
    return await _token_request(cfg, data, auth)


def _http(cfg: FlowConfig) -> httpx.AsyncClient:
    if cfg.pinned:
        from core.security.ssrf import pinned_client
        return pinned_client(timeout=15)
    return httpx.AsyncClient(timeout=15)


async def _token_request(cfg: FlowConfig, data: dict, auth) -> dict:
    async with _http(cfg) as client:
        resp = await client.post(cfg.token_url, data=data, auth=auth)
        resp.raise_for_status()
        return resp.json()


def get_flow_status(flow_id: str) -> dict:
    """Return the current status of an OAuth flow for polling.

    Tokens are NEVER included in this response — they stay server-side and
    are consumed by the integration's /setup/complete route via consume_flow().
    """
    _cleanup_expired_flows()
    flow = _OAUTH_FLOWS.get(flow_id)
    if not flow:
        return {"status": "not_found"}
    return {
        "status": flow.status,
        "error": flow.error if flow.status == "error" else None,
    }


def consume_flow(flow_id: str) -> OAuthFlow | None:
    """Pop and return an OAuth flow. Use this in /setup/complete handlers."""
    _cleanup_expired_flows()
    return _OAUTH_FLOWS.pop(flow_id, None)


# ── Token refresh helpers ─────────────────────────────────────────────────────

async def refresh_google_token(refresh_token: str) -> dict:
    """Use a Google refresh token to get a new access token."""
    return await refresh_tokens(provider_config("google"), refresh_token)
