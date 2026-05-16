"""Chatty — Heartbeat notifications.

Creates in-app alerts for every action_taken heartbeat result.
Optionally sends external notifications via Telegram or WhatsApp.
Failure alerts fire when consecutive errors hit a threshold.
"""

import logging
from datetime import datetime, timezone

from core.agents.reminders import db

logger = logging.getLogger(__name__)

FAILURE_ALERT_THRESHOLD = 3
_FAILURE_ALERT_COOLDOWN_SECONDS = 3600


def evaluate_and_notify(
    action: dict,
    status: str,
    result_summary: str,
    agent_slug: str,
) -> bool:
    """Create in-app alert and optionally send external notification.

    For heartbeats, only notifies on "action_taken".
    For cron jobs, notifies on any successful completion ("ok" or "action_taken")
    since the whole point of a cron job is to produce output.

    Returns True if an external notification was actually sent.
    """
    action_type = action.get("action_type", "heartbeat")
    is_cron = action_type == "cron"

    if is_cron:
        if status not in ("ok", "action_taken"):
            return False
    else:
        if status != "action_taken":
            return False

    from core.agents.alerts.service import create_alert
    create_alert(
        agent=agent_slug,
        title=f"{action.get('name', 'check')}",
        message=result_summary[:500],
        source="cron" if is_cron else "heartbeat",
        source_id=action["id"],
    )

    if not action.get("notify_on_action"):
        return False

    return _send_external(agent_slug, action, result_summary)


def _send_external(agent_slug: str, action: dict, result_summary: str) -> bool:
    """Try Telegram first, then WhatsApp. Returns True if any channel succeeded."""
    try:
        if _try_telegram(agent_slug, result_summary, action=action):
            return True
        if _try_whatsapp(agent_slug, result_summary, action=action):
            return True
        logger.debug("No external notification channel configured for %s", agent_slug)
        return False
    except Exception as e:
        logger.warning("External notification failed for %s: %s", agent_slug, e)
        return False


def _try_telegram(agent_slug: str, message: str, action: dict | None = None) -> bool:
    try:
        from agents.db import list_agents
        from integrations.telegram.client import send_message
        from integrations.telegram.state import get_db as get_tg_db

        agents = list_agents()
        agent = next((a for a in agents if a["slug"] == agent_slug), None)
        if not agent or not agent.get("telegram_enabled") or not agent.get("telegram_bot_token"):
            return False

        bot_token = agent["telegram_bot_token"]

        tg_conn = get_tg_db()
        row = tg_conn.execute(
            "SELECT platform_user_id FROM user_mappings WHERE agent_id = ? AND platform = 'telegram' LIMIT 1",
            (agent["id"],),
        ).fetchone()
        if not row:
            return False

        chat_id = row["platform_user_id"]
        action_type = (action or {}).get("action_type", "heartbeat")
        action_name = (action or {}).get("name", "")

        if action_type == "cron" and action_name:
            text = f"**{action_name}**\n\n{message[:3500]}"
        else:
            text = f"[Heartbeat] {agent['agent_name']}:\n{message[:3500]}"

        send_message(chat_id, text, bot_token)
        logger.info("Notification sent via Telegram for %s (%s)", agent_slug, action_type)
        return True
    except Exception as e:
        logger.warning("Telegram notification failed for %s: %s", agent_slug, e)
        return False


def evaluate_failure_alert(
    action: dict,
    consecutive_errors: int,
    last_error: str,
    agent_slug: str,
) -> bool:
    """Create in-app alert when consecutive errors hit threshold. 1-hour cooldown."""
    if consecutive_errors < FAILURE_ALERT_THRESHOLD:
        return False

    last_alert = action.get("last_failure_alert_at")
    if last_alert:
        try:
            alert_dt = datetime.fromisoformat(last_alert).replace(tzinfo=timezone.utc)
            if (datetime.now(timezone.utc) - alert_dt).total_seconds() < _FAILURE_ALERT_COOLDOWN_SECONDS:
                return False
        except (ValueError, TypeError):
            pass

    action_name = action.get("name") or action.get("action_type", "unknown")

    from core.agents.alerts.service import create_alert
    create_alert(
        agent=agent_slug,
        title=f"Repeated failures: {action_name}",
        message=f"Failed {consecutive_errors} times. Last error: {last_error[:300]}",
        source="heartbeat_failure",
        source_id=action["id"],
    )

    conn = db.get_db()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    with db.write_lock():
        conn.execute(
            "UPDATE scheduled_actions SET last_failure_alert_at = ? WHERE id = ?",
            (now, action["id"]),
        )
        conn.commit()

    if action.get("notify_on_action"):
        _send_external(agent_slug, action, f"Action '{action_name}' has failed {consecutive_errors} times. Last: {last_error[:200]}")

    logger.info("Failure alert sent for %s/%s (%d errors)", agent_slug, action["id"][:8], consecutive_errors)
    return True


def _try_whatsapp(agent_slug: str, message: str, action: dict | None = None) -> bool:
    try:
        from agents.db import list_agents
        from integrations.whatsapp.client import send_message

        agents = list_agents()
        agent = next((a for a in agents if a["slug"] == agent_slug), None)
        if not agent or not agent.get("whatsapp_enabled") or not agent.get("whatsapp_phone"):
            return False

        phone = agent["whatsapp_phone"]
        text = f"[Heartbeat] {agent['agent_name']}:\n{message[:300]}"
        send_message(phone, text)
        logger.info("Heartbeat notification sent via WhatsApp for %s", agent_slug)
        return True
    except Exception as e:
        logger.debug("WhatsApp notification skipped for %s: %s", agent_slug, e)
        return False
