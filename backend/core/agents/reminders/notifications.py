"""Chatty — Reminder notifications.

Creates in-app alerts when reminders fire.
Optionally sends external notifications via Telegram or WhatsApp.
"""

import logging

logger = logging.getLogger(__name__)


def notify_reminder_fired(
    reminder: dict,
    result_text: str,
    agent_slug: str,
    error: bool = False,
) -> bool:
    """Create in-app alert and optionally send external notification.

    Returns True if an alert was created.
    """
    from core.agents.alerts.service import create_alert

    title = f"Reminder: {reminder['message'][:80]}"
    body = result_text[:300] if result_text else "(no result)"
    if error:
        body = f"Error: {body}"

    create_alert(
        agent=agent_slug,
        title=title,
        message=body,
        source="reminder",
        source_id=reminder["id"],
    )

    _send_external(agent_slug, reminder, result_text)
    return True


def _send_external(agent_slug: str, reminder: dict, result_text: str) -> None:
    """Try Telegram first, then WhatsApp. Fire-and-forget."""
    try:
        msg = f"{reminder['message']}\n\n{result_text[:200]}" if result_text else reminder["message"]
        if _try_telegram(agent_slug, msg):
            return
        if _try_whatsapp(agent_slug, msg):
            return
        logger.debug("No external notification channel configured for %s", agent_slug)
    except Exception as e:
        logger.warning("External notification failed for %s: %s", agent_slug, e)


def _try_telegram(agent_slug: str, message: str) -> bool:
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
        text = f"[Reminder] {agent['agent_name']}:\n{message[:300]}"
        send_message(chat_id, text, bot_token)
        logger.info("Reminder notification sent via Telegram for %s", agent_slug)
        return True
    except Exception as e:
        logger.debug("Telegram notification skipped for %s: %s", agent_slug, e)
        return False


def _try_whatsapp(agent_slug: str, message: str) -> bool:
    try:
        from agents.db import list_agents
        from integrations.whatsapp.client import send_message

        agents = list_agents()
        agent = next((a for a in agents if a["slug"] == agent_slug), None)
        if not agent or not agent.get("whatsapp_enabled") or not agent.get("whatsapp_phone"):
            return False

        phone = agent["whatsapp_phone"]
        text = f"[Reminder] {agent['agent_name']}:\n{message[:300]}"
        send_message(phone, text)
        logger.info("Reminder notification sent via WhatsApp for %s", agent_slug)
        return True
    except Exception as e:
        logger.debug("WhatsApp notification skipped for %s: %s", agent_slug, e)
        return False
