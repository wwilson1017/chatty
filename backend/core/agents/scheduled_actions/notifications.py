"""Chatty — Heartbeat notifications.

External delivery helpers (Telegram, WhatsApp) used by delivery.py and
post_message. Failure alerts fire when consecutive errors hit a threshold.
"""

import logging
from datetime import datetime, timezone

from core.agents.reminders import db

logger = logging.getLogger(__name__)

FAILURE_ALERT_THRESHOLD = 3
_FAILURE_ALERT_COOLDOWN_SECONDS = 3600


def send_external_for_agent(agent_slug: str, message: str, title: str = "") -> bool:
    """Send an external notification on behalf of an agent.

    Used by the post_message tool. Bypasses notify_on_action checks
    since the agent is explicitly requesting delivery.
    """
    formatted = f"**{title}**\n\n{message[:3500]}" if title else message[:3500]
    try:
        if _try_telegram(agent_slug, message, formatted_text=formatted):
            return True
        if _try_whatsapp(agent_slug, message, formatted_text=formatted):
            return True
        logger.debug("No external channel configured for %s", agent_slug)
        return False
    except Exception as e:
        logger.warning("External send for %s failed: %s", agent_slug, e)
        return False


def _try_telegram(agent_slug: str, message: str, action: dict | None = None, formatted_text: str | None = None) -> bool:
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

        if formatted_text:
            text = formatted_text
        elif action_type == "cron" and action_name:
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

    try:
        from core.agents.notifications.delivery import deliver_notification
        deliver_notification(
            agent_slug,
            f"Repeated failures: {action_name}",
            f"Failed {consecutive_errors} times. Last error: {last_error[:300]}",
        )
    except Exception as e:
        logger.warning("Failure notification delivery failed for %s: %s", agent_slug, e)

    logger.info("Failure alert sent for %s/%s (%d errors)", agent_slug, action["id"][:8], consecutive_errors)
    return True


def _try_whatsapp(agent_slug: str, message: str, action: dict | None = None, formatted_text: str | None = None) -> bool:
    try:
        from agents.db import list_agents
        from integrations.whatsapp.client import send_message

        agents = list_agents()
        agent = next((a for a in agents if a["slug"] == agent_slug), None)
        if not agent or not agent.get("whatsapp_enabled") or not agent.get("whatsapp_phone"):
            return False

        phone = agent["whatsapp_phone"]
        text = formatted_text if formatted_text else f"[Heartbeat] {agent['agent_name']}:\n{message[:3500]}"
        send_message(phone, text)
        logger.info("Notification sent via WhatsApp for %s", agent_slug)
        return True
    except Exception as e:
        logger.debug("WhatsApp notification skipped for %s: %s", agent_slug, e)
        return False
