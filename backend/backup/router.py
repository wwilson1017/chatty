"""
Chatty — Backup and restore endpoints.

GET  /api/backup/download — download all data as a ZIP file.
POST /api/backup/restore  — upload a backup ZIP to restore data.
"""

import io
import logging
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse

from core.auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter()

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

MAX_RESTORE_SIZE = 100 * 1024 * 1024  # 100 MB


def _backup_sqlite(db_path: Path) -> bytes:
    """Create a consistent snapshot of a SQLite DB (handles WAL mode).

    Uses SQLite's built-in backup API which safely handles WAL mode
    and produces a single consistent .db file.
    """
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        src = sqlite3.connect(str(db_path))
        dst = sqlite3.connect(tmp_path)
        src.backup(dst)
        dst.close()
        src.close()
        return Path(tmp_path).read_bytes()
    finally:
        Path(tmp_path).unlink(missing_ok=True)


@router.get("/download")
async def download_backup(user=Depends(get_current_user)):
    """Download all Chatty data as a ZIP file."""
    if not DATA_DIR.exists():
        raise HTTPException(status_code=404, detail="No data directory found")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for file_path in sorted(DATA_DIR.rglob("*")):
            if not file_path.is_file():
                continue
            # Skip WAL and SHM journal files — the backup API handles them
            if file_path.suffix in (".db-wal", ".db-shm"):
                continue

            rel = file_path.relative_to(DATA_DIR)
            arc_name = str(rel)

            if file_path.suffix == ".db":
                try:
                    data = _backup_sqlite(file_path)
                except Exception as e:
                    logger.warning("Failed to backup %s via SQLite API, copying raw: %s", rel, e)
                    data = file_path.read_bytes()
            else:
                data = file_path.read_bytes()

            zf.writestr(arc_name, data)

    buf.seek(0)
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    filename = f"chatty-backup-{timestamp}.zip"

    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/restore")
async def restore_backup(
    file: UploadFile = File(...),
    user=Depends(get_current_user),
):
    """Restore Chatty data from a backup ZIP file.

    Replaces all current data. This cannot be undone.
    """
    # Validate file type
    if not file.filename or not file.filename.endswith(".zip"):
        raise HTTPException(status_code=400, detail="File must be a .zip archive")

    # Read and validate size
    content = await file.read()
    if len(content) > MAX_RESTORE_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"File too large. Maximum size is {MAX_RESTORE_SIZE // (1024 * 1024)} MB",
        )

    # Validate ZIP structure
    try:
        zf = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail="Invalid ZIP file")

    names = zf.namelist()

    # Must contain agents.db
    if "agents.db" not in names:
        raise HTTPException(
            status_code=400,
            detail="Invalid backup: missing agents.db. This doesn't appear to be a Chatty backup.",
        )

    # Reject path traversal
    for name in names:
        if ".." in name or name.startswith("/"):
            raise HTTPException(status_code=400, detail=f"Invalid path in ZIP: {name}")

    # Close all database connections before overwriting files
    from agents.engine import close_all_agent_dbs
    from agents.db import close_db as close_agents_db
    from core.agents.reminders.db import close_db as close_reminders_db

    close_all_agent_dbs()
    close_agents_db()
    close_reminders_db()

    try:
        from integrations.crm_lite.db import close_db as close_crm_db
        close_crm_db()
    except Exception:
        pass

    # Clear existing data and extract backup
    if DATA_DIR.exists():
        shutil.rmtree(DATA_DIR)
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    zf.extractall(DATA_DIR)
    zf.close()

    # Re-initialize all databases
    from agents.db import init_db as init_agents_db
    init_agents_db()

    from core.agents.reminders.db import init_db as init_reminders_db
    init_reminders_db()

    try:
        from integrations.registry import is_enabled
        if is_enabled("crm_lite"):
            from integrations.crm_lite.db import init_db as init_crm_db
            init_crm_db()
    except Exception:
        pass

    logger.info("Backup restored successfully from %s", file.filename)

    return {"ok": True, "message": "Restore complete. All data has been replaced."}
