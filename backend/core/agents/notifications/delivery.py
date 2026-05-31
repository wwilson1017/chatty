"""Unified notification delivery to all enabled channels."""

import json
import logging
import uuid

logger = logging.getLogger(__name__)


def deliver_notification(agent_slug: str, title: str, message: str) -> dict:
    """Deliver notification to all enabled channels. Returns delivery report."""
    from core.admin_settings import load_admin_settings

    from . import service, subscriptions
    from .vapid import get_vapid_claims, get_vapid_private_key, get_vapid_public_key

    notification_id = str(uuid.uuid4())
    settings = load_admin_settings()
    channels_sent: list[str] = []

    # Web Push
    if settings.get("notifications_web_push", True):
        subs = subscriptions.list_subscriptions()
        if subs and _send_web_push(
            subs, agent_slug, title, message, notification_id,
            get_vapid_private_key(), get_vapid_claims(),
        ):
            channels_sent.append("web_push")

    # Telegram
    if settings.get("notifications_telegram", True):
        if _send_telegram(agent_slug, title, message):
            channels_sent.append("telegram")

    # WhatsApp
    if settings.get("notifications_whatsapp", True):
        if _send_whatsapp(agent_slug, title, message):
            channels_sent.append("whatsapp")

    service.create_notification(
        agent=agent_slug,
        title=title,
        message=message,
        channels_sent=channels_sent,
        notification_id=notification_id,
    )

    return {"ok": True, "notification_id": notification_id, "channels_sent": channels_sent}


def _send_web_push(
    subs: list[dict],
    agent_slug: str,
    title: str,
    message: str,
    notification_id: str,
    private_key: str,
    vapid_claims: dict,
) -> bool:
    try:
        from pywebpush import WebPushException, webpush
    except ImportError:
        logger.warning("pywebpush not installed, skipping web push")
        return False

    from . import subscriptions as sub_module

    # Resolve agent name for push title
    agent_name = agent_slug
    try:
        from agents.db import list_agents
        agents = list_agents()
        agent = next((a for a in agents if a["slug"] == agent_slug), None)
        if agent:
            agent_name = agent.get("name", agent_slug)
    except Exception:
        pass

    payload = json.dumps({
        "title": agent_name,
        "body": title,
        "agent": agent_slug,
        "url": f"/agent/{agent_slug}?tab=chat",
        "notification_id": notification_id,
    })

    # Web Push payload limit is 4KB
    if len(payload.encode()) > 4096:
        payload = json.dumps({
            "title": agent_name,
            "body": title[:100],
            "agent": agent_slug,
            "url": f"/agent/{agent_slug}?tab=chat",
            "notification_id": notification_id,
        })

    sent = 0
    for sub in subs:
        subscription_info = {
            "endpoint": sub["endpoint"],
            "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]},
        }
        try:
            webpush(
                subscription_info=subscription_info,
                data=payload,
                vapid_private_key=private_key,
                vapid_claims=vapid_claims.copy(),
            )
            sent += 1
        except WebPushException as e:
            if "410" in str(e) or "Gone" in str(e):
                logger.info("Removing expired push subscription: %s", sub["endpoint"][:60])
                sub_module.remove_subscription(sub["endpoint"])
            else:
                logger.warning("Web push failed for %s: %s", sub["endpoint"][:60], e)
        except Exception as e:
            logger.warning("Web push error: %s", e)

    return sent > 0


def _send_telegram(agent_slug: str, title: str, message: str) -> bool:
    try:
        from core.agents.scheduled_actions.notifications import _try_telegram

        formatted = f"**{title}**\n\n{message[:3500]}"
        return _try_telegram(agent_slug, f"{title}: {message[:3500]}", formatted_text=formatted)
    except Exception as e:
        logger.warning("Telegram delivery failed for %s: %s", agent_slug, e)
        return False


def _send_whatsapp(agent_slug: str, title: str, message: str) -> bool:
    try:
        from core.agents.scheduled_actions.notifications import _try_whatsapp

        formatted = f"**{title}**\n\n{message[:3500]}"
        return _try_whatsapp(agent_slug, f"{title}: {message[:3500]}", formatted_text=formatted)
    except Exception as e:
        logger.warning("WhatsApp delivery failed for %s: %s", agent_slug, e)
        return False
