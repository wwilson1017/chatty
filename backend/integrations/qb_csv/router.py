"""
Chatty — QuickBooks CSV Analysis REST API.

Endpoints for direct CSV upload, import management, and financial dashboard.
"""

import csv
import io
import logging

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from core.auth import get_current_user
from integrations.registry import is_enabled
from . import client as qb
from .parser import parse_csv_file

logger = logging.getLogger(__name__)
router = APIRouter()


def _require_qb_csv(user=Depends(get_current_user)):
    """Dependency: ensure QB CSV integration is enabled."""
    if not is_enabled("qb_csv"):
        raise HTTPException(status_code=400, detail="QuickBooks CSV integration is not enabled")
    return user


# ── CSV Import ───────────────────────────────────────────────────────────────

@router.post("/import")
async def import_csv(
    files: list[UploadFile] = File(default=[]),
    user=Depends(_require_qb_csv),
):
    """Import one or more QuickBooks CSV files.

    Each file is auto-detected for entity type and imported into the database.
    Returns per-file results.
    """
    if not files:
        raise HTTPException(status_code=400, detail="No files provided")

    results = []
    for f in files[:10]:  # Max 10 files per request
        filename = f.filename or "unknown.csv"
        if not filename.lower().endswith(".csv"):
            results.append({"filename": filename, "error": "Not a .csv file"})
            continue

        content = await f.read()
        if len(content) > 10 * 1024 * 1024:
            results.append({"filename": filename, "error": "File exceeds 10 MB limit"})
            continue

        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            try:
                text = content.decode("latin-1")
            except UnicodeDecodeError:
                results.append({"filename": filename, "error": "Cannot decode file"})
                continue

        result = qb.import_csv_text(text, filename)
        result["filename"] = filename
        results.append(result)

    total_imported = sum(r.get("imported", 0) for r in results)
    return {"results": results, "total_imported": total_imported}


# ── Import Management ────────────────────────────────────────────────────────

@router.get("/imports")
async def list_imports(user=Depends(_require_qb_csv)):
    """List all imported CSV files."""
    imports = qb.list_imports()
    return {"imports": imports, "count": len(imports)}


@router.delete("/imports/{import_id}")
async def delete_import(import_id: int, user=Depends(_require_qb_csv)):
    """Delete an import and all its data."""
    if qb.delete_import(import_id):
        return {"deleted": True, "import_id": import_id}
    raise HTTPException(status_code=404, detail=f"Import {import_id} not found")


# ── Dashboard ────────────────────────────────────────────────────────────────

@router.get("/dashboard")
async def dashboard(user=Depends(_require_qb_csv)):
    """Get a financial summary dashboard from imported data."""
    return qb.get_financial_summary()
