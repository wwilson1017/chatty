"""
Chatty — Provider management API endpoints.

GET  /api/providers          — get current provider status
POST /api/providers/anthropic/connect   — save API key
POST /api/providers/google/connect      — start OAuth flow / exchange code
POST /api/providers/openai/connect      — start OAuth flow / exchange code
POST /api/providers/{provider}/disconnect — remove credentials
PUT  /api/providers/active    — switch active provider + model
GET  /api/providers/{provider}/models   — list models for a provider
"""

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core.auth import get_current_user
from core.providers.credentials import CredentialStore
from core.providers.oauth import start_oauth_flow, refresh_google_token

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Status ────────────────────────────────────────────────────────────────────

@router.get("")
async def get_providers(user=Depends(get_current_user)):
    """Return current provider configuration (no raw keys)."""
    store = CredentialStore()
    return store.to_dict()


# ── Connect Anthropic (API key) ───────────────────────────────────────────────

class AnthropicConnectRequest(BaseModel):
    api_key: str
    model: str = "claude-opus-4-6"


@router.post("/anthropic/connect")
async def connect_anthropic(body: AnthropicConnectRequest, user=Depends(get_current_user)):
    """Validate and store an Anthropic API key."""
    from core.providers.anthropic_provider import AnthropicProvider
    provider = AnthropicProvider(api_key=body.api_key, model=body.model)
    if not await provider.validate():
        raise HTTPException(status_code=400, detail="Invalid Anthropic API key")

    store = CredentialStore()
    store.set_api_key("anthropic", body.api_key, model=body.model)
    return {"ok": True, "provider": "anthropic", "model": body.model}


# ── Connect Google / OpenAI (PKCE OAuth) ─────────────────────────────────────

class OAuthStartRequest(BaseModel):
    pass


@router.post("/google/connect")
async def connect_google(user=Depends(get_current_user)):
    """Start Google PKCE OAuth flow. Opens browser, waits for callback."""
    try:
        tokens = await start_oauth_flow("google")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    store = CredentialStore()
    store.set_oauth_tokens(
        provider="google",
        access_token=tokens["access_token"],
        refresh_token=tokens["refresh_token"],
        expires_in=tokens["expires_in"],
        model="gemini-2.0-flash-exp",
    )
    return {"ok": True, "provider": "google"}


@router.post("/openai/connect")
async def connect_openai(user=Depends(get_current_user)):
    """Start OpenAI PKCE OAuth flow. Opens browser, waits for callback."""
    try:
        tokens = await start_oauth_flow("openai")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    store = CredentialStore()
    store.set_oauth_tokens(
        provider="openai",
        access_token=tokens["access_token"],
        refresh_token=tokens.get("refresh_token", ""),
        expires_in=tokens.get("expires_in", 3600),
        model="gpt-4o",
    )
    return {"ok": True, "provider": "openai"}


# ── Disconnect ────────────────────────────────────────────────────────────────

@router.post("/{provider}/disconnect")
async def disconnect_provider(provider: str, user=Depends(get_current_user)):
    """Remove credentials for a provider."""
    if provider not in ("anthropic", "openai", "google"):
        raise HTTPException(status_code=404, detail="Unknown provider")

    store = CredentialStore()
    store.remove_provider(provider)
    return {"ok": True, "provider": provider}


# ── Set active provider / model ───────────────────────────────────────────────

class SetActiveRequest(BaseModel):
    provider: str
    model: str


@router.put("/active")
async def set_active(body: SetActiveRequest, user=Depends(get_current_user)):
    """Switch the active provider and model."""
    store = CredentialStore()
    _, profile = store.get_active_profile(provider_override=body.provider)
    if not profile:
        raise HTTPException(status_code=400, detail=f"No credentials for provider: {body.provider}")

    store.set_active_provider(body.provider)
    store.set_active_model(body.model)
    return {"ok": True, "provider": body.provider, "model": body.model}


# ── List models ───────────────────────────────────────────────────────────────

@router.get("/{provider}/models")
async def list_models(provider: str, user=Depends(get_current_user)):
    """Return available models for the given provider."""
    from core.providers import get_ai_provider
    p = get_ai_provider(agent_provider=provider)
    if not p:
        raise HTTPException(status_code=400, detail=f"Provider not configured: {provider}")
    models = await p.list_models()
    return {"provider": provider, "models": models}


# ── Token refresh ─────────────────────────────────────────────────────────────

@router.post("/google/refresh")
async def refresh_google(user=Depends(get_current_user)):
    """Refresh the Google OAuth access token using the stored refresh token."""
    store = CredentialStore()
    profile = store.data.get("profiles", {}).get("google:default", {})
    refresh_token = profile.get("refresh", "")
    if not refresh_token:
        raise HTTPException(status_code=400, detail="No Google refresh token stored")

    try:
        tokens = await refresh_google_token(refresh_token)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Token refresh failed: {e}")

    store.set_oauth_tokens(
        provider="google",
        access_token=tokens["access_token"],
        refresh_token=refresh_token,  # keep existing refresh token
        expires_in=tokens.get("expires_in", 3600),
    )
    return {"ok": True}
