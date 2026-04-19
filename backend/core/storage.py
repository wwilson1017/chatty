"""
Chatty — Cloud Storage adapter + database safety helpers.

GCS sync: when CONFIG_BUCKET is set, syncs data files to/from a GCS bucket.
When empty (local dev, Railway), all GCS operations are no-ops.

Database helpers:
  safe_backup_sqlite()  — consistent online backup via Connection.backup()
  safe_init_sqlite()    — integrity-checked init with corruption recovery
  atomic_write_json()   — crash-safe JSON file writes
"""

import json
import logging
import os
import sqlite3
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

GCS_BUCKET = os.getenv("CONFIG_BUCKET", "")

_storage_client = None


def _get_client():
    global _storage_client
    if _storage_client is not None:
        return _storage_client
    if not GCS_BUCKET:
        return None
    try:
        from google.cloud import storage
        _storage_client = storage.Client()
        return _storage_client
    except Exception as e:
        logger.warning("GCS client init failed: %s", e)
        return None


def download_configs(local_dir: Path, prefix: str):
    """On startup, download config files from GCS to local filesystem."""
    client = _get_client()
    if not client:
        return
    try:
        bucket = client.bucket(GCS_BUCKET)
        blobs = bucket.list_blobs(prefix=prefix)
        for blob in blobs:
            filename = blob.name.removeprefix(prefix)
            if not filename:
                continue
            local_path = local_dir / filename
            local_path.parent.mkdir(parents=True, exist_ok=True)
            blob.download_to_filename(str(local_path))
            logger.info("Downloaded %s from GCS", filename)
    except Exception as e:
        logger.error("GCS config download failed: %s", e)


def upload_config(local_path: Path, filename: str, prefix: str):
    """After a config file write, upload it to GCS."""
    client = _get_client()
    if not client:
        return
    try:
        bucket = client.bucket(GCS_BUCKET)
        blob = bucket.blob(f"{prefix}{filename}")
        blob.upload_from_filename(str(local_path))
        logger.info("Uploaded %s to GCS", filename)
    except Exception as e:
        logger.error("GCS upload of %s failed: %s", filename, e)


def delete_config(filename: str, prefix: str):
    """Delete a file from GCS."""
    client = _get_client()
    if not client:
        return
    try:
        bucket = client.bucket(GCS_BUCKET)
        blob = bucket.blob(f"{prefix}{filename}")
        if blob.exists():
            blob.delete()
            logger.info("Deleted %s from GCS", filename)
    except Exception as e:
        logger.error("GCS delete of %s failed: %s", filename, e)


def download_file(local_path: Path, blob_name: str):
    """Download a single file from GCS by blob name."""
    client = _get_client()
    if not client:
        return
    try:
        bucket = client.bucket(GCS_BUCKET)
        blob = bucket.blob(blob_name)
        if not blob.exists():
            return
        local_path.parent.mkdir(parents=True, exist_ok=True)
        blob.download_to_filename(str(local_path))
        logger.info("Downloaded %s from GCS", blob_name)
    except Exception as e:
        logger.error("GCS download of %s failed: %s", blob_name, e)


def upload_file(local_path: Path, blob_name: str):
    """Upload a single file to GCS by blob name."""
    client = _get_client()
    if not client:
        return
    try:
        bucket = client.bucket(GCS_BUCKET)
        blob = bucket.blob(blob_name)
        blob.upload_from_filename(str(local_path))
        logger.info("Uploaded %s to GCS", blob_name)
    except Exception as e:
        logger.error("GCS upload of %s failed: %s", blob_name, e)


# ---------------------------------------------------------------------------
# Database safety helpers
# ---------------------------------------------------------------------------


def safe_backup_sqlite(
    source_conn: sqlite3.Connection | None,
    local_db_path: Path,
    blob_name: str,
    *,
    backup_mutex: threading.Lock,
) -> None:
    """Create a consistent SQLite snapshot and upload it to GCS.

    Uses the online backup API which is safe under concurrent writers.
    Runs an integrity check on the snapshot before uploading — a corrupt
    snapshot is logged and discarded, never uploaded.

    Never raises.  A failed backup must not crash a request.
    """
    if source_conn is None:
        return

    if not backup_mutex.acquire(blocking=False):
        logger.debug("Backup already in progress for %s, skipping", blob_name)
        return

    tmp_path: Path | None = None
    try:
        fd, tmp_name = tempfile.mkstemp(
            suffix=".db", dir=str(local_db_path.parent),
        )
        os.close(fd)
        tmp_path = Path(tmp_name)

        dst = sqlite3.connect(str(tmp_path))
        try:
            source_conn.backup(dst)
        finally:
            dst.close()

        # Verify the snapshot before uploading
        check_conn = sqlite3.connect(str(tmp_path))
        try:
            result = check_conn.execute("PRAGMA integrity_check").fetchone()
            if not result or result[0] != "ok":
                logger.error(
                    "Integrity check failed on backup snapshot of %s: %s",
                    blob_name, result[0] if result else "no result",
                )
                return
        finally:
            check_conn.close()

        upload_file(tmp_path, blob_name)
    except Exception:
        logger.exception("Backup failed for %s", blob_name)
    finally:
        backup_mutex.release()
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)


def safe_init_sqlite(
    db_path: Path,
    blob_name: str,
    *,
    init_fn: Callable[[], None],
) -> dict:
    """Integrity-checked database initialization with corruption recovery.

    1. If the db file is missing, try to download it from GCS.
    2. If it still doesn't exist, call init_fn() to create a fresh database.
    3. If it exists, run PRAGMA integrity_check:
       - OK → call init_fn() to open connection / apply migrations.
       - Corrupt → quarantine the file and call init_fn() for a fresh start.

    Returns a status dict: {"db": blob_name, "status": "ok"|"fresh"|"quarantined"|"error"}.
    Never raises.
    """
    try:
        db_path.parent.mkdir(parents=True, exist_ok=True)

        if not db_path.exists():
            download_file(db_path, blob_name)

        if not db_path.exists():
            init_fn()
            return {"db": blob_name, "status": "fresh"}

        # Integrity check on the existing file
        try:
            check_conn = sqlite3.connect(str(db_path))
            try:
                result = check_conn.execute("PRAGMA integrity_check").fetchone()
                healthy = result[0] == "ok"
            finally:
                check_conn.close()
        except sqlite3.DatabaseError:
            healthy = False

        if healthy:
            init_fn()
            return {"db": blob_name, "status": "ok"}

        # Quarantine the corrupt file — preserve it for manual inspection
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        quarantine_path = db_path.with_suffix(f".corrupt.{ts}")
        db_path.rename(quarantine_path)
        logger.warning(
            "Database %s failed integrity check — quarantined to %s, creating fresh",
            db_path, quarantine_path,
        )
        # Also quarantine WAL/SHM if present
        for ext in ("-wal", "-shm"):
            wal = db_path.with_name(db_path.name + ext)
            if wal.exists():
                wal.rename(quarantine_path.with_name(quarantine_path.name + ext))

        init_fn()
        return {"db": blob_name, "status": "quarantined"}

    except Exception:
        logger.exception("safe_init_sqlite failed for %s", blob_name)
        return {"db": blob_name, "status": "error"}


def atomic_write_json(path: Path, data: Any, *, indent: int = 2) -> None:
    """Write JSON atomically via tempfile + fsync + os.replace.

    The temp file is created in the same directory as the target to
    guarantee same-filesystem semantics for os.replace (atomic on POSIX).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        suffix=".tmp", dir=str(path.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=indent, ensure_ascii=False)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, str(path))
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise
