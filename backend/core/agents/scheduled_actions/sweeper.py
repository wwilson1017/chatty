"""Chatty — Scheduled actions maintenance sweeper.

Runs every 5 minutes via APScheduler to enforce retention, correct
next_run drift after downtime, and release expired leases.
"""

import logging
from datetime import datetime, timedelta, timezone

from core.agents.reminders import db

logger = logging.getLogger(__name__)


def sweep() -> None:
    """Run all maintenance tasks. Called by APScheduler every 5 minutes."""
    try:
        from core.agents.scheduled_actions import history as history_mod
        from core.agents.scheduled_actions import service
        from core.agents.alerts import service as alerts_service

        cleaned_history = history_mod.cleanup_old(retention_days=7)
        cleaned_alerts = alerts_service.cleanup_old(retention_days=30)
        cleaned_usage = _cleanup_context_usage(retention_days=90)
        fixed_drift = _fix_next_run_drift()
        released_leases = service.release_expired_leases()

        service.ensure_default_actions_all()

        if cleaned_history or cleaned_alerts or cleaned_usage or fixed_drift or released_leases:
            logger.info(
                "Sweeper: cleaned %d history, %d alerts, %d usage, fixed %d drifted, released %d leases",
                cleaned_history, cleaned_alerts, cleaned_usage, fixed_drift, released_leases,
            )
    except Exception as e:
        logger.error("Sweeper failed: %s", e)


def _cleanup_context_usage(retention_days: int = 90) -> int:
    try:
        from core.agents.dreaming.tracker import cleanup_old
        return cleanup_old(retention_days=retention_days)
    except Exception as e:
        logger.debug("Context usage cleanup skipped: %s", e)
        return 0


def _fix_next_run_drift() -> int:
    conn = db.get_db()
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S")
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

    with db.write_lock():
        rows = conn.execute(
            """SELECT id, interval_minutes FROM scheduled_actions
               WHERE enabled = 1 AND next_run IS NOT NULL AND next_run < ?
               AND schedule_type = 'interval'""",
            (cutoff,),
        ).fetchall()

        fixed = 0
        for row in rows:
            interval = row["interval_minutes"] or 30
            new_next = (datetime.now(timezone.utc) + timedelta(minutes=interval)).strftime("%Y-%m-%dT%H:%M:%S")
            conn.execute(
                "UPDATE scheduled_actions SET next_run = ?, updated_at = ? WHERE id = ?",
                (new_next, now, row["id"]),
            )
            fixed += 1

        if fixed:
            conn.commit()

    return fixed
