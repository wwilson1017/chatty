"""
Chatty — Integrations API endpoints.

GET  /api/integrations                          — list all integrations + status
POST /api/integrations/{name}/enable            — enable an integration
POST /api/integrations/{name}/disable           — disable an integration
POST /api/integrations/{name}/setup             — configure credentials
GET  /api/integrations/{name}/tool-defs         — get tool definitions for an integration
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core.auth import get_current_user
from .registry import list_integrations, enable, disable, is_enabled

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Setup request models ──────────────────────────────────────────────────────

class OdooSetupRequest(BaseModel):
    url: str
    database: str
    username: str
    api_key: str


class BambooHRSetupRequest(BaseModel):
    subdomain: str
    api_key: str


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


@router.post("/crm_lite/setup")
async def setup_crm_lite(user=Depends(get_current_user)):
    """Initialize CRM Lite (no credentials needed)."""
    from .crm_lite.onboarding import setup
    return setup()


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
    else:
        return {"tools": []}
