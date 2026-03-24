"""
Chatty — Branding API endpoints.

GET  /api/branding           — get current branding config
PUT  /api/branding           — update company name and/or accent color
POST /api/branding/logo      — upload logo image (multipart)
DELETE /api/branding/logo    — remove logo
GET  /api/branding/logo      — serve logo image
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import FileResponse
from pydantic import BaseModel

from core.auth import get_current_user
from . import storage

logger = logging.getLogger(__name__)
router = APIRouter()

ALLOWED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp", "image/svg+xml"}
MAX_LOGO_BYTES = 2 * 1024 * 1024  # 2 MB


class BrandingUpdateRequest(BaseModel):
    company_name: str | None = None
    accent_color: str | None = None


@router.get("")
async def get_branding(user=Depends(get_current_user)):
    """Return current branding configuration."""
    return storage.load_config()


@router.put("")
async def update_branding(body: BrandingUpdateRequest, user=Depends(get_current_user)):
    """Update company name and/or accent color."""
    if body.accent_color and not body.accent_color.startswith("#"):
        raise HTTPException(status_code=400, detail="accent_color must be a hex color (e.g. #6366f1)")
    return storage.save_config(
        company_name=body.company_name,
        accent_color=body.accent_color,
    )


@router.post("/logo")
async def upload_logo(
    file: UploadFile = File(...),
    user=Depends(get_current_user),
):
    """Upload a logo image (PNG, JPEG, GIF, WebP, SVG). Max 2 MB."""
    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported image type: {file.content_type}. Allowed: PNG, JPEG, GIF, WebP, SVG",
        )
    data = await file.read()
    if len(data) > MAX_LOGO_BYTES:
        raise HTTPException(status_code=400, detail="Logo must be under 2 MB")
    if not storage.save_logo(data):
        raise HTTPException(status_code=500, detail="Failed to save logo")
    return {"ok": True, "has_logo": True}


@router.delete("/logo")
async def delete_logo(user=Depends(get_current_user)):
    """Remove the logo."""
    storage.delete_logo()
    return {"ok": True, "has_logo": False}


@router.get("/logo")
async def get_logo():
    """Serve the logo image (no auth — used in CSS/img tags)."""
    path = storage.get_logo_path()
    if not path:
        raise HTTPException(status_code=404, detail="No logo uploaded")
    return FileResponse(str(path))
