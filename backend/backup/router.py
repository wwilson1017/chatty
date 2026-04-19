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
import threading
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

_restore_lock = threading.Lock()


def _backup_sqlite(db_path: Path) -> bytes:
    """Create a consistent snapshot of a SQLite DB (handles WAL mode).

    Uses SQLite's built-in backup API which safely handles WAL mode
    and produces a single consistent .db file.  Runs an integrity
    check on the snapshot before returning it.
    """
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        tmp_path = tmp.name
    src = None
    dst = None
    try:
        src = sqlite3.connect(str(db_path))
        dst = sqlite3.connect(tmp_path)
        src.backup(dst)
        dst.close()
        dst = None

        check = sqlite3.connect(tmp_path)
        try:
            result = check.execute("PRAGMA integrity_check").fetchone()
            if not result or result[0] != "ok":
                logger.warning(
                    "Integrity check failed on backup snapshot of %s: %s",
                    db_path.name, result[0] if result else "no result",
                )
                raise sqlite3.DatabaseError(
                    f"Backup snapshot of {db_path.name} failed integrity check"
                )
        finally:
            check.close()

        return Path(tmp_path).read_bytes()
    finally:
        if dst:
            dst.close()
        if src:
            src.close()
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
                except sqlite3.DatabaseError:
                    logger.warning("Skipping %s — failed integrity check", rel)
                    continue
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
    if not _restore_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="A restore is already in progress")

    try:
        return _do_restore(file, await file.read())
    finally:
        _restore_lock.release()


def _do_restore(file: UploadFile, content: bytes) -> dict:
    # Validate file type
    if not file.filename or not file.filename.endswith(".zip"):
        raise HTTPException(status_code=400, detail="File must be a .zip archive")

    # Validate size
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

    # Reject path traversal — verify all resolved paths stay within DATA_DIR
    data_dir_resolved = DATA_DIR.resolve()
    for name in names:
        resolved = (DATA_DIR / name).resolve()
        if not resolved.is_relative_to(data_dir_resolved):
            raise HTTPException(status_code=400, detail=f"Invalid path in ZIP: {name}")

    # Close all database connections before overwriting files
    from agents.engine import close_all_agent_dbs
    from agents.db import close_db as close_agents_db
    from core.agents.reminders.db import close_db as close_reminders_db
    from core.agents.shared_context.db import close_db as close_shared_context_db
    from core.agents.tool_config_db import close_db as close_tool_config_db
    from integrations.crm_lite.db import close_db as close_crm_db
    from integrations.qb_csv.db import close_db as close_qb_csv_db
    from integrations.telegram.state import close_db as close_telegram_db
    from integrations.whatsapp.state import close_db as close_whatsapp_db

    close_all_agent_dbs()
    close_agents_db()
    close_reminders_db()
    close_shared_context_db()
    close_tool_config_db()
    close_crm_db()
    close_qb_csv_db()
    close_telegram_db()
    close_whatsapp_db()

    # Extract to a temp directory first, then swap — atomic restore
    tmp_dir = Path(tempfile.mkdtemp(prefix="chatty-restore-"))
    try:
        zf.extractall(tmp_dir)
        zf.close()

        # Swap: remove old data, move new data into place
        if DATA_DIR.exists():
            shutil.rmtree(DATA_DIR)
        shutil.move(str(tmp_dir), str(DATA_DIR))
    except Exception:
        # Clean up temp dir on failure; original data is intact if rmtree hasn't run
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise

    # Re-initialize all databases
    from agents.db import init_db as init_agents_db
    init_agents_db()

    from core.agents.reminders.db import init_db as init_reminders_db
    init_reminders_db()

    from core.agents.shared_context.db import init_db as init_shared_context_db
    init_shared_context_db()

    from core.agents.tool_config_db import init_db as init_tool_config_db
    init_tool_config_db()

    from integrations.telegram.state import init_db as init_telegram_db
    init_telegram_db()

    from integrations.registry import is_enabled
    if is_enabled("crm_lite"):
        from integrations.crm_lite.db import init_db as init_crm_db
        init_crm_db()

    if is_enabled("qb_csv"):
        from integrations.qb_csv.db import init_db as init_qb_csv_db
        init_qb_csv_db()

    try:
        from integrations.whatsapp.state import init_db as init_whatsapp_db
        init_whatsapp_db()
    except Exception:
        pass

    logger.info("Backup restored successfully from %s", file.filename)

    return {"ok": True, "message": "Restore complete. All data has been replaced."}
