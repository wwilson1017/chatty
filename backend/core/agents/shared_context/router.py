"""Shared context — Admin API endpoints.

Endpoints for managing shared knowledge files and reviewing agent-contributed
entries.  All endpoints require authentication. Chatty is single-user, so
the authenticated user has full admin access.
"""

import logging

from fastapi import APIRouter, Body, Depends, HTTPException

from core.auth import get_current_user

from . import db, service

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/shared-context",
    dependencies=[Depends(get_current_user)],
    tags=["shared-context"],
)


# ── Files ──────────────────────────────────────────────────────────


@router.get("/files")
def list_files():
    return {"files": service.list_files()}


@router.get("/files/{filename}")
def read_file(filename: str):
    content = service.read_file(filename)
    if content is None:
        raise HTTPException(status_code=404, detail="File not found")
    return {"filename": filename, "content": content}


@router.put("/files/{filename}")
def write_file(filename: str, body: dict = Body(...)):
    content = body.get("content", "")
    if not filename.endswith(".md"):
        raise HTTPException(status_code=400, detail="Filename must end with .md")
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    service.write_file(filename, content)
    return {"filename": filename, "ok": True}


@router.delete("/files/{filename}")
def delete_file(filename: str):
    if not service.delete_file(filename):
        raise HTTPException(status_code=404, detail="File not found")
    return {"filename": filename, "deleted": True}


# ── Entries ────────────────────────────────────────────────────────


@router.get("/entries")
def list_entries(agent: str | None = None, category: str | None = None, limit: int = 100, offset: int = 0):
    entries = db.list_entries(agent_name=agent, category=category, limit=limit, offset=offset)
    return {"entries": entries, "count": len(entries)}


@router.patch("/entries/{entry_id}")
def update_entry(entry_id: str, body: dict = Body(...)):
    updated = db.update_entry(
        entry_id,
        title=body.get("title"),
        content=body.get("content"),
        category=body.get("category"),
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Entry not found")
    try:
        db.backup_to_gcs()
    except Exception:
        pass
    return updated


@router.delete("/entries/{entry_id}")
def delete_entry(entry_id: str):
    if not db.delete_entry(entry_id):
        raise HTTPException(status_code=404, detail="Entry not found")
    try:
        db.backup_to_gcs()
    except Exception:
        pass
    return {"id": entry_id, "deleted": True}


# ── Bootstrap ─────────────────────────────────────────────────────


@router.post("/bootstrap")
async def bootstrap_shared_knowledge(force: bool = False):
    """Analyze all agents' knowledge files and populate shared context.

    Extracts universally useful facts (user profile, company info, contacts,
    preferences) via AI and writes them as shared entries. Runs automatically
    when the second agent is created; this endpoint allows manual re-runs.
    """
    from .bootstrap import run_bootstrap
    return await run_bootstrap(force=force)
