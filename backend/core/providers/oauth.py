"""
Chatty — PKCE OAuth flow for Google, OpenAI, and QuickBooks.

Two-step pattern (Railway-compatible):
    1. `start_oauth_flow(provider, scopes=..., metadata=...)` returns
       {flow_id, auth_url}. The caller opens auth_url in a popup; the user
       authorizes with Google/Intuit/OpenAI.
    2. The provider redirects the user's browser to
       `{backend_url}/api/oauth/callback?code=...&state=<flow_id>`.
       That FastAPI route calls `complete_oauth_flow(...)` which exchanges
       the code for tokens and stashes them on the OAuthFlow object.
    3. The frontend polls `/api/oauth/flows/{flow_id}/status`; once it
       reports `status: "ok"`, the frontend calls the integration-specific
       `/setup/complete` endpoint (e.g. `/api/integrations/quickbooks/setup/complete`)
       which reads the tokens via `consume_flow(flow_id)` and persists them.

This replaces the old "localhost:9876 HTTP server" pattern, which only
worked when the backend ran on the same machine as the user's browser
(i.e. local dev, not Railway).
"""

import base64
import hashlib
import logging
import os
import secrets
import time
from urllib.parse import urlencode

import httpx

from core.config import settings

logger = logging.getLogger(__name__)

# ── Provider OAuth config ─────────────────────────────────────────────────────

OAUTH_CONFIG = {
    "google": {
        "auth_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url": "https://oauth2.googleapis.com/token",
        "client_id": lambda: settings.google_oauth.client_id,
        "client_secret": lambda: settings.google_oauth.client_secret,
        "scopes": lambda: settings.google_oauth.scopes,
        "use_pkce": True,
        "use_basic_auth": False,
        "extra_callback_params": [],
    },
    "openai": {
        "auth_url": "https://auth.openai.com/authorize",
        "token_url": "https://auth.openai.com/oauth/token",
        "client_id": lambda: settings.openai_oauth.client_id,
        "client_secret": lambda: settings.openai_oauth.client_secret,
        "scopes": lambda: ["openid", "email", "profile", "model.request"],
        "use_pkce": True,
        "use_basic_auth": False,
        "extra_callback_params": [],
    },
    "quickbooks": {
        "auth_url": "https://appcenter.intuit.com/connect/oauth2",
        "token_url": "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer",
        "client_id": lambda: settings.quickbooks_oauth.client_id,
        "client_secret": lambda: settings.quickbooks_oauth.client_secret,
        "scopes": lambda: ["com.intuit.quickbooks.accounting"],
        "use_pkce": False,
        "use_basic_auth": True,
        "extra_callback_params": ["realmId"],
    },
}

CALLBACK_PATH = "/api/oauth/callback"

# ── Flow state ────────────────────────────────────────────────────────────────

_OAUTH_FLOWS: dict[str, "OAuthFlow"] = {}
_FLOW_TTL_SECONDS = 600  # 10 minutes


class OAuthFlow:
    """Tracks a single in-flight OAuth authorization flow."""

    def __init__(
        self,
        flow_id: str,
        provider: str,
        code_verifier: str | None,
        metadata: dict | None = None,
    ):
        self.flow_id = flow_id
        self.provider = provider
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

def redirect_uri() -> str:
    """Compute the OAuth callback URL — works for both local and Railway."""
    override = os.getenv("OAUTH_REDIRECT_URI", "")
    if override:
        return override
    return f"{settings.backend_url}{CALLBACK_PATH}"


# ── PKCE helpers ──────────────────────────────────────────────────────────────

def _generate_pkce() -> tuple[str, str]:
    """Generate (code_verifier, code_challenge) for PKCE."""
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    return verifier, challenge


def _build_auth_url(
    provider: str,
    code_challenge: str | None,
    state: str,
    scopes: list[str] | None = None,
) -> str:
    """Build the OAuth authorization URL, with optional PKCE parameters."""
    cfg = OAUTH_CONFIG[provider]
    client_id = cfg["client_id"]()

    use_scopes = scopes
    if use_scopes is None:
        scopes_spec = cfg["scopes"]
        use_scopes = scopes_spec() if callable(scopes_spec) else scopes_spec

    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri(),
        "response_type": "code",
        "scope": " ".join(use_scopes),
        "state": state,
    }
    if code_challenge:
        params["code_challenge"] = code_challenge
        params["code_challenge_method"] = "S256"
    if provider == "google":
        params["access_type"] = "offline"
        params["prompt"] = "consent"  # ensure refresh_token on every connect
    return f"{cfg['auth_url']}?{urlencode(params)}"


# ── Public API ────────────────────────────────────────────────────────────────

def start_oauth_flow(
    provider: str,
    scopes: list[str] | None = None,
    metadata: dict | None = None,
) -> dict:
    """
    Start an OAuth flow.

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
    _cleanup_expired_flows()

    if provider not in OAUTH_CONFIG:
        raise ValueError(f"Unknown provider: {provider}")

    cfg = OAUTH_CONFIG[provider]
    if not cfg["client_id"]():
        raise ValueError(
            f"OAuth not configured for {provider}: missing {provider.upper()}_CLIENT_ID"
        )

    use_pkce = cfg.get("use_pkce", True)
    verifier, challenge = _generate_pkce() if use_pkce else (None, None)
    flow_id = secrets.token_urlsafe(32)

    auth_url = _build_auth_url(provider, challenge, state=flow_id, scopes=scopes)

    _OAUTH_FLOWS[flow_id] = OAuthFlow(
        flow_id=flow_id,
        provider=provider,
        code_verifier=verifier,
        metadata=metadata,
    )

    logger.info("Started OAuth flow: provider=%s flow_id=%s...", provider, flow_id[:8])
    return {"flow_id": flow_id, "auth_url": auth_url}


async def complete_oauth_flow(code: str, state: str, callback_params: dict) -> OAuthFlow:
    """Exchange the authorization code for tokens. Called by /api/oauth/callback."""
    _cleanup_expired_flows()

    flow = _OAUTH_FLOWS.get(state)
    if not flow:
        raise ValueError("Unknown or expired OAuth state")

    try:
        tokens = await _exchange_code(flow.provider, code, flow.code_verifier)
        cfg = OAUTH_CONFIG[flow.provider]
        response = {
            "access_token": tokens.get("access_token", ""),
            "refresh_token": tokens.get("refresh_token", ""),
            "expires_in": tokens.get("expires_in", 3600),
            "token_type": tokens.get("token_type", "Bearer"),
        }
        for param in cfg.get("extra_callback_params", []):
            if param in callback_params:
                response[param] = callback_params[param]

        flow.tokens = response
        flow.status = "ok"
        return flow
    except Exception as e:
        logger.error("OAuth token exchange failed for %s: %s", flow.provider, e)
        flow.error = str(e)
        flow.status = "error"
        raise


async def _exchange_code(provider: str, code: str, code_verifier: str | None) -> dict:
    """Exchange authorization code for access + refresh tokens."""
    cfg = OAUTH_CONFIG[provider]
    data = {
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri(),
        "code": code,
    }
    auth = None
    if cfg.get("use_basic_auth", False):
        auth = (cfg["client_id"](), cfg["client_secret"]())
    else:
        data["client_id"] = cfg["client_id"]()
        data["client_secret"] = cfg["client_secret"]()

    if code_verifier:
        data["code_verifier"] = code_verifier

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(cfg["token_url"], data=data, auth=auth)
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
    cfg = OAUTH_CONFIG["google"]
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            cfg["token_url"],
            data={
                "grant_type": "refresh_token",
                "client_id": cfg["client_id"](),
                "client_secret": cfg["client_secret"](),
                "refresh_token": refresh_token,
            },
        )
        resp.raise_for_status()
        return resp.json()
