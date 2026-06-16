"""Chatty — Printing Press API endpoints (browse, install, manage CLIs).

GET    /api/printing-press/catalog                  — library catalog (slimmed)
GET    /api/printing-press/installed                — installed CLIs + status
POST   /api/printing-press/install                  — start a build → {build_id}
GET    /api/printing-press/install/{build_id}/stream — live build progress (SSE)
POST   /api/printing-press/{slug}/enable|disable     — toggle a CLI
POST   /api/printing-press/{slug}/mode               — set tool_mode ceiling
DELETE /api/printing-press/{slug}                    — uninstall
"""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from starlette.responses import StreamingResponse

from core.auth import get_current_user

from . import build_jobs, device_flow, library_client, paths, store

logger = logging.getLogger(__name__)
router = APIRouter()


class InstallRequest(BaseModel):
    slug: str = Field(..., max_length=64)
    category: str = Field(..., max_length=64)
    ref: str = Field("main", max_length=64)


class ModeRequest(BaseModel):
    tool_mode: str = Field(..., max_length=16)


class AuthRequest(BaseModel):
    env: dict[str, str] = Field(default_factory=dict)


def _install_view(rec: store.Install) -> dict:
    needs_auth = bool(rec.auth.get("env_vars")) and not store.has_credentials(rec.slug)
    return {
        "slug": rec.slug, "category": rec.category, "api_name": rec.api_name,
        "description": rec.description, "tool_count": rec.tool_count,
        "enabled": rec.enabled, "tool_mode": rec.tool_mode,
        "build_status": rec.build_status, "build_error": rec.build_error,
        "auth_type": rec.auth.get("type"), "needs_auth": needs_auth,
        "installed_at": rec.installed_at,
    }


@router.get("/catalog")
def get_catalog(user=Depends(get_current_user)):
    """The published library catalog, slimmed (search_terms dropped for size)."""
    try:
        registry = library_client.fetch_registry()
    except Exception as exc:
        logger.warning("catalog fetch failed: %s", exc)
        raise HTTPException(status_code=502, detail="Could not reach the Printing Press library")
    entries = []
    for e in registry.get("entries", []):
        mcp = e.get("mcp", {}) or {}
        entries.append({
            "slug": e.get("name"), "category": e.get("category"),
            "api": e.get("api"), "description": e.get("description"),
            "path": e.get("path"),
            "tool_count": mcp.get("tool_count"), "auth_type": mcp.get("auth_type"),
            "env_vars": mcp.get("env_vars", []),
        })
    return {"count": len(entries), "entries": entries}


@router.get("/installed")
def get_installed(user=Depends(get_current_user)):
    return {"installed": [_install_view(r) for r in store.list_installed()]}


@router.post("/install")
def start_install(req: InstallRequest, user=Depends(get_current_user)):
    """Create a building install record + queue the build off the worker."""
    try:
        slug = paths.validate_slug(req.slug)
        category = paths.validate_category(req.category)
    except paths.InvalidIdentifier as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    existing = store.get_install(slug)
    record = existing or store.Install(slug=slug, category=category, ref=req.ref, sha="")
    record.category = category
    record.ref = req.ref
    record.build_status = store.BUILD_BUILDING
    record.build_error = None
    store.save_install(record)

    build_id = build_jobs.submit_build(slug, category, req.ref)
    return {"build_id": build_id, "slug": slug}


@router.get("/install/{build_id}/stream")
async def stream_install(build_id: str, user=Depends(get_current_user)):
    job = build_jobs.get_job(build_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown build")

    async def gen():
        sent = 0
        while True:
            log = job.log
            while sent < len(log):
                yield f"data: {json.dumps({'type': 'progress', **log[sent]})}\n\n"
                sent += 1
            if job.done and sent >= len(job.log):
                yield f"data: {json.dumps({'type': 'done', 'status': job.status, 'error': job.error})}\n\n"
                return
            await asyncio.sleep(0.2)

    return StreamingResponse(
        gen(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


@router.post("/{slug}/enable")
def enable_cli(slug: str, user=Depends(get_current_user)):
    if store.update_install(slug, enabled=True) is None:
        raise HTTPException(status_code=404, detail="CLI not installed")
    return {"ok": True}


@router.post("/{slug}/disable")
def disable_cli(slug: str, user=Depends(get_current_user)):
    if store.update_install(slug, enabled=False) is None:
        raise HTTPException(status_code=404, detail="CLI not installed")
    return {"ok": True}


@router.post("/{slug}/mode")
def set_mode(slug: str, req: ModeRequest, user=Depends(get_current_user)):
    if req.tool_mode not in store.VALID_TOOL_MODES:
        raise HTTPException(status_code=400, detail=f"Invalid tool_mode: {req.tool_mode}")
    if store.update_install(slug, tool_mode=req.tool_mode) is None:
        raise HTTPException(status_code=404, detail="CLI not installed")
    return {"ok": True}


@router.delete("/{slug}")
def uninstall_cli(slug: str, user=Depends(get_current_user)):
    if not store.remove_install(slug):
        raise HTTPException(status_code=404, detail="CLI not installed")
    return {"ok": True}


# ── auth ──────────────────────────────────────────────────────────────────

@router.get("/{slug}/auth")
def auth_requirements(slug: str, user=Depends(get_current_user)):
    """What this CLI needs to authenticate: env-var fields (paste) and whether it
    supports the device-code flow."""
    rec = store.get_install(slug)
    if rec is None:
        raise HTTPException(status_code=404, detail="CLI not installed")
    manifest = store.get_manifest(slug) or {}
    auth = manifest.get("auth", {}) or {}
    specs = auth.get("env_var_specs") or [{"name": n} for n in auth.get("env_vars", [])]
    env_vars = [
        {"name": s.get("name"), "description": s.get("description", ""),
         "sensitive": s.get("sensitive", True)}
        for s in specs if s.get("name")
    ]
    return {
        "slug": slug, "auth_type": auth.get("type"),
        "env_vars": env_vars, "key_url": auth.get("key_url", ""),
        "has_credentials": store.has_credentials(slug),
        "supports_device": device_flow.supports_device_flow(slug),
    }


@router.post("/{slug}/auth")
def save_auth(slug: str, req: AuthRequest, user=Depends(get_current_user)):
    """Save pasted credentials (api_key / bearer / PAT), encrypted at rest."""
    if store.get_install(slug) is None:
        raise HTTPException(status_code=404, detail="CLI not installed")
    cleaned = {k: v for k, v in req.env.items() if v}
    if not cleaned:
        raise HTTPException(status_code=400, detail="No credentials provided")
    store.save_cli_credentials(slug, cleaned)
    return {"ok": True}


@router.delete("/{slug}/auth")
def clear_auth(slug: str, user=Depends(get_current_user)):
    store.delete_cli_credentials(slug)
    return {"ok": True}


@router.post("/{slug}/auth/device")
def start_device(slug: str, user=Depends(get_current_user)):
    if store.get_install(slug) is None:
        raise HTTPException(status_code=404, detail="CLI not installed")
    if not device_flow.supports_device_flow(slug):
        raise HTTPException(status_code=400, detail="This CLI does not support device-code login")
    result = device_flow.start_device_flow(slug)
    if "error" in result:
        raise HTTPException(status_code=502, detail=result["error"])
    return result


@router.get("/{slug}/auth/device/{flow_id}")
def device_status(slug: str, flow_id: str, user=Depends(get_current_user)):
    flow = device_flow.get_flow(flow_id)
    if flow is None or flow.slug != slug:
        raise HTTPException(status_code=404, detail="Unknown device flow")
    return {"status": flow.status, "error": flow.error}
