"""
Chatty — Integrations API endpoints.

GET  /api/integrations                          — list all integrations + status
POST /api/integrations/{name}/enable            — enable an integration
POST /api/integrations/{name}/disable           — disable an integration
POST /api/integrations/{name}/setup             — configure credentials
GET  /api/integrations/{name}/tool-defs         — get tool definitions for an integration
"""

import logging
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core.auth import get_current_user
from .registry import list_integrations, enable, disable, is_enabled

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Setup request models ──────────────────────────────────────────────────────

class OdooDiscoverRequest(BaseModel):
    url: str = Field(..., max_length=2048)


class OdooSetupRequest(BaseModel):
    url: str
    database: str
    username: str
    api_key: str


class BambooHRSetupRequest(BaseModel):
    subdomain: str
    api_key: str


class ToolModeRequest(BaseModel):
    tool_mode: str


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("")
async def get_integrations(user=Depends(get_current_user)):
    """List all integrations with their status."""
    return {"integrations": list_integrations()}


@router.post("/{name}/enable")
async def enable_integration(name: str, user=Depends(get_current_user)):
    """Enable an integration (must be configured first)."""
    integrations = {i["id"]: i for i in list_integrations()}
    if name not in integrations:
        raise HTTPException(status_code=404, detail=f"Unknown integration: {name}")
    if not integrations[name]["configured"]:
        raise HTTPException(status_code=400, detail="Integration must be configured before enabling")
    enable(name)
    return {"ok": True, "integration": name, "enabled": True}


@router.post("/{name}/disable")
async def disable_integration(name: str, user=Depends(get_current_user)):
    """Disable an integration (credentials preserved)."""
    integrations = {i["id"]: i for i in list_integrations()}
    if name not in integrations:
        raise HTTPException(status_code=404, detail=f"Unknown integration: {name}")
    disable(name)
    return {"ok": True, "integration": name, "enabled": False}


@router.post("/{name}/tool-mode")
async def set_integration_tool_mode(name: str, body: ToolModeRequest, user=Depends(get_current_user)):
    """Set the tool_mode permission ceiling for an integration."""
    if name not in ("odoo", "quickbooks"):
        raise HTTPException(status_code=400, detail="Tool mode is only supported for Odoo and QuickBooks")
    if body.tool_mode not in ("read-only", "normal", "power"):
        raise HTTPException(status_code=400, detail=f"Invalid tool_mode: {body.tool_mode}")
    integrations = {i["id"]: i for i in list_integrations()}
    if not integrations.get(name, {}).get("configured"):
        raise HTTPException(status_code=400, detail="Integration must be configured before setting tool mode")
    from .registry import set_tool_mode
    set_tool_mode(name, body.tool_mode)
    return {"ok": True, "integration": name, "tool_mode": body.tool_mode}


@router.post("/odoo/discover-databases")
def discover_odoo_databases(body: OdooDiscoverRequest, user=Depends(get_current_user)):
    """Discover available databases on an Odoo instance (no credentials needed)."""
    from .odoo.discovery import discover_databases
    return discover_databases(url=body.url)


@router.post("/odoo/setup")
async def setup_odoo(body: OdooSetupRequest, user=Depends(get_current_user)):
    """Configure and validate Odoo credentials."""
    from .odoo.onboarding import setup
    result = setup(
        url=body.url,
        database=body.database,
        username=body.username,
        api_key=body.api_key,
    )
    if not result["ok"]:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/bamboohr/setup")
async def setup_bamboohr(body: BambooHRSetupRequest, user=Depends(get_current_user)):
    """Configure and validate BambooHR credentials."""
    from .bamboohr.onboarding import setup
    result = setup(subdomain=body.subdomain, api_key=body.api_key)
    if not result["ok"]:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/quickbooks/setup")
async def setup_quickbooks(user=Depends(get_current_user)):
    """Start QuickBooks OAuth flow. Returns {flow_id, auth_url} for the
    frontend to open in a popup and poll until /quickbooks/setup/complete."""
    from core.providers.oauth import start_oauth_flow

    try:
        return start_oauth_flow("quickbooks")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


class CompleteSetupRequest(BaseModel):
    flow_id: str


@router.post("/quickbooks/setup/complete")
async def setup_quickbooks_complete(body: CompleteSetupRequest, user=Depends(get_current_user)):
    """Finalize QuickBooks setup after the OAuth callback stashes tokens."""
    from core.providers.oauth import consume_flow

    flow = consume_flow(body.flow_id)
    if not flow:
        raise HTTPException(status_code=404, detail="OAuth flow not found or expired")
    if flow.status != "ok" or not flow.tokens:
        raise HTTPException(status_code=400, detail=flow.error or "OAuth flow incomplete")

    tokens = flow.tokens
    realm_id = tokens.get("realmId", "")
    if not realm_id:
        raise HTTPException(status_code=400, detail="QuickBooks did not return a company ID (realmId)")

    from .quickbooks.onboarding import setup_from_oauth
    result = setup_from_oauth(
        company_id=realm_id,
        access_token=tokens["access_token"],
        refresh_token=tokens["refresh_token"],
        expires_in=tokens.get("expires_in", 3600),
    )
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "Setup failed"))
    return result


@router.post("/quickbooks/disconnect")
async def disconnect_quickbooks(user=Depends(get_current_user)):
    """Disconnect QuickBooks: revoke tokens with Intuit and remove stored credentials."""
    from core.config import settings
    from .registry import get_credentials
    from .quickbooks.client import QBO_REVOKE_URL

    creds = get_credentials("quickbooks")
    refresh_token = creds.get("refresh_token", "")

    # Revoke token with Intuit
    if refresh_token:
        try:
            resp = httpx.post(
                QBO_REVOKE_URL,
                json={"token": refresh_token},
                auth=(settings.quickbooks_oauth.client_id, settings.quickbooks_oauth.client_secret),
                timeout=10,
            )
            if resp.status_code == 200:
                logger.info("QBO tokens revoked successfully")
            else:
                logger.warning("QBO token revoke returned %d", resp.status_code)
        except Exception as e:
            logger.warning("QBO token revoke failed: %s", e)

    # Remove stored credentials
    creds_path = Path(__file__).resolve().parent.parent / "data" / "integrations" / "quickbooks.json"
    if creds_path.exists():
        creds_path.unlink()
        logger.info("Removed quickbooks.json credentials")

    return {"ok": True}


from typing import Literal


class GoogleSetupRequest(BaseModel):
    gmail_level: Literal["none", "read", "send"] = "none"
    calendar_level: Literal["none", "read", "full"] = "none"
    drive_level: Literal["none", "file", "readonly", "full"] = "none"


@router.post("/google/setup")
async def setup_google(body: GoogleSetupRequest, user=Depends(get_current_user)):
    """Start Google OAuth flow with user-chosen scope levels.

    Returns {flow_id, auth_url}. The frontend opens auth_url in a popup,
    polls /api/oauth/flows/{flow_id}/status, then calls
    /api/integrations/google/setup/complete with {flow_id}.
    """
    from core.providers.oauth import start_oauth_flow
    from core.config import build_google_scopes

    # Reject "all none" — user must grant at least one capability
    if body.gmail_level == "none" and body.calendar_level == "none" and body.drive_level == "none":
        raise HTTPException(
            status_code=400,
            detail="At least one of Gmail, Calendar, or Drive must be enabled",
        )

    # Include Gemini AI scope if Google is already the active AI provider, so
    # we don't break Gemini when the user connects Gmail/Calendar/Drive.
    from core.providers.credentials import CredentialStore
    store = CredentialStore()
    include_ai = store.data.get("active_provider") == "google"

    scopes = build_google_scopes(
        gmail_level=body.gmail_level,
        calendar_level=body.calendar_level,
        drive_level=body.drive_level,
        include_ai=include_ai,
    )

    try:
        return start_oauth_flow(
            "google",
            scopes=scopes,
            metadata={
                "gmail_level": body.gmail_level,
                "calendar_level": body.calendar_level,
                "drive_level": body.drive_level,
                "include_ai": include_ai,
            },
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


class GoogleCompleteRequest(BaseModel):
    flow_id: str


@router.post("/google/setup/complete")
async def setup_google_complete(body: GoogleCompleteRequest, user=Depends(get_current_user)):
    """Finalize Google setup after the OAuth callback stashes tokens."""
    from core.providers.oauth import consume_flow
    from .google.onboarding import setup_from_oauth

    flow = consume_flow(body.flow_id)
    if not flow:
        raise HTTPException(status_code=404, detail="OAuth flow not found or expired")
    if flow.status != "ok" or not flow.tokens:
        raise HTTPException(status_code=400, detail=flow.error or "OAuth flow incomplete")

    tokens = flow.tokens
    if not tokens.get("access_token"):
        raise HTTPException(status_code=400, detail="Google did not return an access token")
    if not tokens.get("refresh_token"):
        raise HTTPException(
            status_code=400,
            detail="Google did not return a refresh token. Try disconnecting at "
                   "https://myaccount.google.com/permissions then reconnect.",
        )

    meta = flow.metadata or {}
    scope_grants = {
        "gmail": meta.get("gmail_level", "none"),
        "calendar": meta.get("calendar_level", "none"),
        "drive": meta.get("drive_level", "none"),
    }

    result = await setup_from_oauth(
        access_token=tokens["access_token"],
        refresh_token=tokens["refresh_token"],
        expires_in=tokens.get("expires_in", 3600),
        scope_grants=scope_grants,
    )
    return result


@router.post("/google/disconnect")
async def disconnect_google(user=Depends(get_current_user)):
    """Revoke Google OAuth + clear stored credentials."""
    from .google.onboarding import disconnect
    return await disconnect()


@router.post("/qb_csv/setup")
async def setup_qb_csv(user=Depends(get_current_user)):
    """Initialize QuickBooks CSV Analysis (no credentials needed)."""
    from .qb_csv.onboarding import setup
    return setup()


@router.post("/crm_lite/setup")
async def setup_crm_lite(user=Depends(get_current_user)):
    """Initialize CRM Lite (no credentials needed)."""
    from .crm_lite.onboarding import setup
    return setup()


class PendingSetupRequest(BaseModel):
    messaging: list[str] = []
    integrations: list[str] = []


@router.post("/pending-setup")
async def save_pending_setup(body: PendingSetupRequest, user=Depends(get_current_user)):
    """Save onboarding integration selections for the first agent to pick up."""
    from .pending_setup import save_pending
    return save_pending(body.messaging, body.integrations)


@router.get("/pending-setup")
async def get_pending_setup(user=Depends(get_current_user)):
    """Get pending integration setup selections."""
    from .pending_setup import load_pending
    data = load_pending()
    return data or {"messaging": [], "integrations": []}


@router.get("/{name}/tool-defs")
async def get_tool_defs(name: str, user=Depends(get_current_user)):
    """Return tool definitions for an enabled integration."""
    if not is_enabled(name):
        raise HTTPException(status_code=400, detail=f"Integration not enabled: {name}")

    if name == "odoo":
        from .odoo.tools import ODOO_TOOL_DEFS
        return {"tools": ODOO_TOOL_DEFS}
    elif name == "bamboohr":
        from .bamboohr.tools import BAMBOOHR_TOOL_DEFS
        return {"tools": BAMBOOHR_TOOL_DEFS}
    elif name == "quickbooks":
        from .quickbooks.tools import QB_TOOL_DEFS
        return {"tools": QB_TOOL_DEFS}
    elif name == "crm_lite":
        from .crm_lite.tools import CRM_LITE_TOOL_DEFS
        return {"tools": CRM_LITE_TOOL_DEFS}
    elif name == "qb_csv":
        from .qb_csv.tools import QB_CSV_TOOL_DEFS
        return {"tools": QB_CSV_TOOL_DEFS}
    else:
        return {"tools": []}
