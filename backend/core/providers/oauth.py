"""
Chatty — PKCE OAuth flow for OpenAI and Google.

Opens a browser for the user to authorize, starts a local callback server,
captures the auth code, exchanges it for tokens, and stores them.

Google OAuth also covers Gmail + Google Calendar scopes — one connection
covers AI (Gemini), Gmail, and Calendar access. No admin/service account needed.

Usage:
    result = await start_oauth_flow("google")
    # Opens browser, waits for user to authorize, returns tokens
"""

import asyncio
import base64
import hashlib
import json
import logging
import os
import secrets
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from urllib.parse import parse_qs, urlencode, urlparse

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
        "scopes": settings.google_oauth.scopes,
        "use_pkce": True,
        "use_basic_auth": False,
        "extra_callback_params": [],
    },
    "openai": {
        "auth_url": "https://auth.openai.com/authorize",
        "token_url": "https://auth.openai.com/oauth/token",
        "client_id": lambda: settings.openai_oauth.client_id,
        "client_secret": lambda: settings.openai_oauth.client_secret,
        "scopes": ["openid", "email", "profile", "model.request"],
        "use_pkce": True,
        "use_basic_auth": False,
        "extra_callback_params": [],
    },
    "quickbooks": {
        "auth_url": "https://appcenter.intuit.com/connect/oauth2",
        "token_url": "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer",
        "client_id": lambda: settings.quickbooks_oauth.client_id,
        "client_secret": lambda: settings.quickbooks_oauth.client_secret,
        "scopes": ["com.intuit.quickbooks.accounting"],
        "use_pkce": False,
        "use_basic_auth": True,
        "extra_callback_params": ["realmId"],
    },
}

CALLBACK_PORT = 9876
CALLBACK_PATH = "/oauth/callback"
REDIRECT_URI = f"http://localhost:{CALLBACK_PORT}{CALLBACK_PATH}"


# ── PKCE helpers ──────────────────────────────────────────────────────────────

def _generate_pkce() -> tuple[str, str]:
    """Generate (code_verifier, code_challenge) for PKCE."""
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    return verifier, challenge


def _build_auth_url(provider: str, code_challenge: str | None, state: str) -> str:
    """Build the OAuth authorization URL, with optional PKCE parameters."""
    cfg = OAUTH_CONFIG[provider]
    client_id = cfg["client_id"]()
    scopes = cfg["scopes"]

    params = {
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": " ".join(scopes),
        "state": state,
    }
    if code_challenge:
        params["code_challenge"] = code_challenge
        params["code_challenge_method"] = "S256"
        params["access_type"] = "offline"   # Google: request refresh token
        params["prompt"] = "consent"        # Google: always show consent to get refresh token
    return f"{cfg['auth_url']}?{urlencode(params)}"


# ── Local callback server ─────────────────────────────────────────────────────

class _CallbackHandler(BaseHTTPRequestHandler):
    """Minimal HTTP handler to capture the OAuth callback."""

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == CALLBACK_PATH:
            params = parse_qs(parsed.query)
            self.server.auth_code = params.get("code", [None])[0]
            self.server.auth_error = params.get("error", [None])[0]
            self.server.auth_state = params.get("state", [None])[0]
            self.server.callback_params = {k: v[0] for k, v in params.items()}

            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            if self.server.auth_code:
                msg = "<h2>✓ Connected! You can close this tab and return to Chatty.</h2>"
            else:
                msg = f"<h2>Authorization failed: {self.server.auth_error}</h2>"
            self.wfile.write(msg.encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args):
        pass  # Suppress access logs


async def _wait_for_callback(state: str, timeout: int = 120) -> dict | None:
    """Start local server and wait for the OAuth callback.

    Returns {"code": str, "params": dict} on success, or None on failure.
    """
    server = HTTPServer(("localhost", CALLBACK_PORT), _CallbackHandler)
    server.auth_code = None
    server.auth_error = None
    server.auth_state = None
    server.callback_params = {}
    server.timeout = 1

    loop = asyncio.get_event_loop()

    def serve():
        deadline = asyncio.get_event_loop().time() if False else None
        for _ in range(timeout):
            server.handle_request()
            if server.auth_code or server.auth_error:
                break
        server.server_close()

    await loop.run_in_executor(None, serve)

    if server.auth_state != state:
        logger.warning("OAuth state mismatch — possible CSRF")
        return None

    if not server.auth_code:
        return None

    return {"code": server.auth_code, "params": server.callback_params}


# ── Token exchange ────────────────────────────────────────────────────────────

async def _exchange_code(provider: str, code: str, code_verifier: str | None = None) -> dict:
    """Exchange authorization code for access + refresh tokens."""
    cfg = OAUTH_CONFIG[provider]
    data = {
        "grant_type": "authorization_code",
        "redirect_uri": REDIRECT_URI,
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

    async with httpx.AsyncClient() as client:
        resp = await client.post(cfg["token_url"], data=data, auth=auth)
        resp.raise_for_status()
        return resp.json()


async def refresh_google_token(refresh_token: str) -> dict:
    """Use refresh token to get a new Google access token."""
    cfg = OAUTH_CONFIG["google"]
    async with httpx.AsyncClient() as client:
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


# ── Public API ────────────────────────────────────────────────────────────────

async def start_oauth_flow(provider: str) -> dict:
    """
    Run the full OAuth flow for a provider (PKCE or standard).

    Opens the user's browser, waits for the callback, exchanges the code.

    Returns:
        {
            "access_token": str,
            "refresh_token": str,  # may be empty for OpenAI
            "expires_in": int,     # seconds
            "token_type": str,
            ...extra_callback_params  # e.g. "realmId" for QuickBooks
        }

    Raises:
        ValueError if provider is not configured or user denies.
    """
    if provider not in OAUTH_CONFIG:
        raise ValueError(f"Unknown provider: {provider}")

    cfg = OAUTH_CONFIG[provider]
    if not cfg["client_id"]():
        raise ValueError(f"OAuth not configured for {provider}: missing client_id in .env")

    use_pkce = cfg.get("use_pkce", True)
    verifier, challenge = _generate_pkce() if use_pkce else (None, None)
    state = secrets.token_urlsafe(16)
    auth_url = _build_auth_url(provider, challenge, state)

    logger.info("Opening browser for %s OAuth: %s", provider, auth_url)
    webbrowser.open(auth_url)

    result = await _wait_for_callback(state, timeout=120)
    if not result:
        raise ValueError(f"OAuth flow failed or timed out for {provider}")

    tokens = await _exchange_code(provider, result["code"], verifier)

    response = {
        "access_token": tokens.get("access_token", ""),
        "refresh_token": tokens.get("refresh_token", ""),
        "expires_in": tokens.get("expires_in", 3600),
        "token_type": tokens.get("token_type", "Bearer"),
    }

    # Pass through extra callback params (e.g. realmId for QuickBooks)
    for param in cfg.get("extra_callback_params", []):
        if param in result["params"]:
            response[param] = result["params"][param]

    return response


def build_auth_url_for_frontend(provider: str) -> dict:
    """
    Build the OAuth URL and return it with state + verifier for polling flow.
    Used when the frontend needs to open the URL and poll for completion.
    """
    if provider not in OAUTH_CONFIG:
        raise ValueError(f"Unknown provider: {provider}")

    cfg = OAUTH_CONFIG[provider]
    use_pkce = cfg.get("use_pkce", True)
    verifier, challenge = _generate_pkce() if use_pkce else (None, None)
    state = secrets.token_urlsafe(16)
    auth_url = _build_auth_url(provider, challenge, state)

    return {
        "url": auth_url,
        "state": state,
        "code_verifier": verifier,
    }
