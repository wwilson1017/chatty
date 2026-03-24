"""
Chatty — Cloud Storage adapter.

In Phase 2 (Cloud Run), syncs data files to/from a GCS bucket.
In Phase 1 (local), GCS_BUCKET is empty so all operations are no-ops.
"""

import logging
import os
from pathlib import Path

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
