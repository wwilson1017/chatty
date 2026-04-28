"""Per-agent file cache for downloaded attachments.

Stores raw file bytes on disk so agents can forward/send them by
reference (``file_ref``) without the binary travelling through the
AI context window.  Cached files are ephemeral and auto-expire.
"""

import json
import logging
import os
import re
import time
import uuid

logger = logging.getLogger(__name__)

_TTL_HOURS = 4


def cache_file(cache_dir: str, raw: bytes, filename: str, mime_type: str) -> str:
    """Cache file bytes to disk and return a short reference string."""
    os.makedirs(cache_dir, exist_ok=True)

    file_ref = uuid.uuid4().hex[:12]
    bin_path = os.path.join(cache_dir, f"{file_ref}.bin")
    meta_path = os.path.join(cache_dir, f"{file_ref}.meta.json")

    with open(bin_path, "wb") as f:
        f.write(raw)

    meta = {
        "filename": filename,
        "mime_type": mime_type,
        "size_bytes": len(raw),
        "cached_at": time.time(),
    }
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f)

    try:
        cleanup_expired(cache_dir)
    except Exception:
        logger.debug("file_cache cleanup error (non-fatal)", exc_info=True)

    return file_ref


def load_cached_file(cache_dir: str, file_ref: str) -> dict | None:
    """Load a cached file by reference.

    Returns ``{"raw": bytes, "filename": str, "mime_type": str}`` or
    ``None`` if the ref is missing or expired.
    """
    if not cache_dir or not file_ref:
        return None

    if not re.fullmatch(r"[0-9a-f]{12}", file_ref):
        return None

    bin_path = os.path.join(cache_dir, f"{file_ref}.bin")
    meta_path = os.path.join(cache_dir, f"{file_ref}.meta.json")

    if not os.path.isfile(bin_path) or not os.path.isfile(meta_path):
        return None

    try:
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
    except Exception:
        return None

    cached_at = meta.get("cached_at", 0)
    if time.time() - cached_at > _TTL_HOURS * 3600:
        return None

    try:
        with open(bin_path, "rb") as f:
            raw = f.read()
    except Exception:
        return None

    return {
        "raw": raw,
        "filename": meta.get("filename", "file"),
        "mime_type": meta.get("mime_type", "application/octet-stream"),
    }


def cleanup_expired(cache_dir: str) -> int:
    """Delete cached files older than the TTL. Returns count deleted."""
    if not cache_dir or not os.path.isdir(cache_dir):
        return 0

    cutoff = time.time() - _TTL_HOURS * 3600
    deleted = 0

    for entry in os.scandir(cache_dir):
        if not entry.name.endswith(".meta.json"):
            continue
        try:
            with open(entry.path, encoding="utf-8") as f:
                meta = json.load(f)
            if meta.get("cached_at", 0) < cutoff:
                ref = entry.name.removesuffix(".meta.json")
                bin_path = os.path.join(cache_dir, f"{ref}.bin")
                if os.path.isfile(bin_path):
                    os.remove(bin_path)
                os.remove(entry.path)
                deleted += 1
        except Exception:
            continue

    return deleted
