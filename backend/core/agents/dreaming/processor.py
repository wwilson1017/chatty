"""Dreaming processor — automated context consolidation.

Runs daily as a scheduled action. Pure Python (no Claude calls).
Archives dormant files and reorders context loading priority.
"""

import json
import logging
import time
from datetime import datetime, timezone

from core.agents.context_manager import ContextManager
from core.agents.reminders import db
from . import scorer

logger = logging.getLogger(__name__)

# Files that should never be archived
PROTECTED_FILES = {"soul.md", "MEMORY.md", "_training-progress.md"}


def process_dreaming(agent_name: str, ctx_manager: ContextManager) -> dict:
    """Run the dreaming cycle for an agent. Returns a summary."""
    start = time.monotonic()
    data_dir = ctx_manager.data_dir
    gcs_prefix = ctx_manager.gcs_prefix

    scores = scorer.score_context_files(agent_name, data_dir)
    archived = []
    load_order_changed = False

    # 1. Archive dormant files (score < 0.1, not protected)
    for item in scores:
        if item["classification"] != "dormant":
            continue
        fname = item["filename"]
        if fname in PROTECTED_FILES:
            continue
        src = data_dir / fname
        dst = data_dir / f"_archived-{fname}"
        if src.exists() and not dst.exists():
            try:
                src.rename(dst)
                # Sync: upload archived, delete original from GCS
                from core.storage import upload_file, delete_config
                upload_file(dst, f"{gcs_prefix}_archived-{fname}")
                delete_config(fname, prefix=gcs_prefix)
                archived.append(fname)
                logger.info("Dreaming archived %s/%s (score=%.3f)", agent_name, fname, item["score"])
            except Exception as e:
                logger.warning("Failed to archive %s/%s: %s", agent_name, fname, e)

    # 2. Update load order (_load-order.json)
    active_files = [
        item["filename"]
        for item in scores
        if item["classification"] in ("active", "stale")
        and item["filename"] not in archived
        and not item["filename"].startswith("_")
        and item["filename"] != "soul.md"
    ]

    order_file = data_dir / "_load-order.json"
    old_order = []
    if order_file.exists():
        try:
            old_order = json.loads(order_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, TypeError):
            pass

    if active_files != old_order:
        try:
            from core.storage import atomic_write_json, upload_file
            atomic_write_json(order_file, active_files)
            upload_file(order_file, f"{gcs_prefix}_load-order.json")
            load_order_changed = True
        except Exception as e:
            logger.warning("Failed to write _load-order.json for %s: %s", agent_name, e)

    # 3. Record the run
    duration_ms = int((time.monotonic() - start) * 1000)
    details = json.dumps({
        "scores": scores[:10],  # Top 10 for storage
        "archived": archived,
    })

    try:
        conn = db.get_db()
        with db.write_lock():
            conn.execute(
                """INSERT INTO dreaming_runs
                   (agent, files_scored, files_archived, load_order_changed, details, duration_ms)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (agent_name, len(scores), len(archived), 1 if load_order_changed else 0, details, duration_ms),
            )
            conn.commit()
    except Exception as e:
        logger.warning("Failed to record dreaming run for %s: %s", agent_name, e)

    summary = {
        "agent": agent_name,
        "files_scored": len(scores),
        "files_archived": len(archived),
        "archived": archived,
        "load_order_changed": load_order_changed,
        "duration_ms": duration_ms,
    }
    logger.info(
        "Dreaming %s: scored=%d, archived=%d, reorder=%s (%dms)",
        agent_name, len(scores), len(archived), load_order_changed, duration_ms,
    )
    return summary
