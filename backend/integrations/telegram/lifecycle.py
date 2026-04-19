"""Telegram bot lifecycle management.

Handles token validation, webhook registration/deregistration, and the
time-limited auto-registration window that lets a user self-onboard by
messaging their agent's Telegram bot within 10 minutes of setup.
"""

import logging
import threading
import time

from core.config import settings
from agents.db import get_agent, list_agents, update_agent

from . import state
from .client import validate_token, set_webhook, delete_webhook, get_updates

logger = logging.getLogger(__name__)

_polling_threads: dict[str, threading.Event] = {}


def _is_local() -> bool:
    """True if the backend URL points to localhost (webhooks won't work)."""
    return "localhost" in settings.backend_url or "127.0.0.1" in settings.backend_url


def validate_and_save_token(agent_id: str, bot_token: str) -> dict:
    """Validate a Telegram bot token and save it for an agent.

    1. Calls getMe to verify the token
    2. Checks no other agent uses the same token
    3. Deregisters the old webhook if replacing a token
    4. Saves to DB + registers webhook + opens registration window

    Returns dict with bot_username, webhook_url, registration info.
    Raises ValueError on validation failure.
    """
    bot_info = validate_token(bot_token)
    if not bot_info:
        raise ValueError("Invalid Telegram bot token — getMe failed")

    bot_username = bot_info.get("username", "")

    # Check for duplicate tokens across agents
    for agent in list_agents():
        if agent["id"] == agent_id:
            continue
        if agent.get("telegram_bot_token") == bot_token:
            raise ValueError(
                f"This token is already in use by {agent.get('agent_name', 'another agent')}"
            )

    # If agent already has a different token, deregister old webhook
    existing = get_agent(agent_id)
    if not existing:
        raise ValueError("Agent not found")

    if existing.get("telegram_bot_token") and existing["telegram_bot_token"] != bot_token:
        delete_webhook(existing["telegram_bot_token"])

    # Save token + username
    update_agent(agent_id, telegram_bot_token=bot_token, telegram_bot_username=bot_username)

    slug = existing["slug"]

    if _is_local():
        # Local mode: delete any webhook and start polling
        delete_webhook(bot_token)
        start_polling(agent_id, slug, bot_token)
        webhook_ok = True
        webhook_url = "(polling mode — local development)"
        logger.info("Telegram polling started for agent %s (local mode)", existing["agent_name"])
    else:
        # Production mode: register webhook
        secret = state.get_or_create_webhook_secret(agent_id)
        webhook_url = f"{settings.backend_url}/api/telegram/webhook/{slug}"
        webhook_result = set_webhook(webhook_url, bot_token, secret_token=secret)
        webhook_ok = webhook_result.get("ok", False)
        if not webhook_ok:
            logger.warning(
                "Webhook registration failed for agent %s: %s",
                agent_id, webhook_result.get("error", "unknown"),
            )

    if not webhook_ok:
        # Don't open registration or enable — webhook failed so messages can't arrive
        return {
            "bot_username": bot_username,
            "bot_id": bot_info.get("id"),
            "webhook_url": webhook_url,
            "webhook_ok": False,
            "error": "Webhook registration failed. Check BACKEND_URL is a public HTTPS URL reachable by Telegram.",
            "registration_expires_at": "",
        }

    # Open registration window
    window = state.open_registration_window(agent_id)

    # Auto-enable Telegram on first token setup
    if not existing.get("telegram_enabled"):
        update_agent(agent_id, telegram_enabled=1)

    return {
        "bot_username": bot_username,
        "bot_id": bot_info.get("id"),
        "webhook_url": webhook_url,
        "webhook_ok": True,
        "registration_expires_at": window["expires_at"],
    }


def remove_token(agent_id: str) -> None:
    """Remove a Telegram bot token from an agent.

    Deregisters the webhook/polling and clears the token from the DB.
    """
    agent = get_agent(agent_id)
    if not agent:
        return

    stop_polling(agent_id)
    token = agent.get("telegram_bot_token", "")
    if token:
        delete_webhook(token)

    update_agent(agent_id, telegram_bot_token="", telegram_bot_username="", telegram_enabled=0)
    state.delete_webhook_secret(agent_id)


def reset_registration_window(agent_id: str) -> dict:
    """Reset (re-open) the registration window for an agent.

    Returns the new window info.
    Raises ValueError if the agent has no token configured.
    """
    agent = get_agent(agent_id)
    if not agent or not agent.get("telegram_bot_token"):
        raise ValueError("Agent has no Telegram bot token configured")

    return state.open_registration_window(agent_id)


def start_polling(agent_id: str, slug: str, bot_token: str) -> None:
    """Start a long-polling thread for a Telegram bot (local dev mode)."""
    if agent_id in _polling_threads:
        _polling_threads[agent_id].set()

    stop_event = threading.Event()
    _polling_threads[agent_id] = stop_event

    def _poll_loop():
        from .router import _safe_process_telegram
        offset = None
        while not stop_event.is_set():
            try:
                updates = get_updates(bot_token, offset=offset, timeout=30)
                for update in updates:
                    offset = update["update_id"] + 1
                    message = update.get("message")
                    if not message or not message.get("text"):
                        continue
                    chat = message.get("chat", {})
                    from_user = message.get("from", {})
                    chat_id = chat.get("id")
                    user_id = str(from_user.get("id", ""))
                    first_name = from_user.get("first_name", "")
                    last_name = from_user.get("last_name", "")
                    sender_name = f"{first_name} {last_name}".strip() or "Unknown"
                    if chat_id and user_id:
                        _safe_process_telegram(slug, user_id, sender_name, message["text"], chat_id)
            except Exception:
                logger.exception("Telegram polling error for %s", slug)
                if not stop_event.is_set():
                    time.sleep(5)

    t = threading.Thread(target=_poll_loop, daemon=True, name=f"tg-poll-{slug}")
    t.start()


def stop_polling(agent_id: str) -> None:
    """Stop the polling thread for an agent."""
    event = _polling_threads.pop(agent_id, None)
    if event:
        event.set()


def register_all_webhooks() -> None:
    """Re-register webhooks (or start polling) for all agents with Telegram bot tokens.

    Called on startup to ensure message delivery works.
    """
    agents = list_agents()
    count = 0
    local = _is_local()

    for agent in agents:
        token = agent.get("telegram_bot_token", "")
        if not token:
            continue

        slug = agent["slug"]

        if local:
            delete_webhook(token)
            start_polling(agent["id"], slug, token)
            count += 1
        else:
            webhook_url = f"{settings.backend_url}/api/telegram/webhook/{slug}"
            secret = state.get_or_create_webhook_secret(agent["id"])
            try:
                result = set_webhook(webhook_url, token, secret_token=secret)
                if result.get("ok"):
                    count += 1
                else:
                    logger.warning(
                        "Startup webhook registration failed for %s: %s",
                        agent["agent_name"], result.get("error", "unknown"),
                    )
            except Exception as e:
                logger.warning("Startup webhook registration error for %s: %s", agent["agent_name"], e)

    if count:
        mode = "polling" if local else "webhook"
        logger.info("Registered Telegram %s for %d agent(s)", mode, count)


def try_auto_register(
    agent_id: str, telegram_user_id: str, sender_name: str,
) -> bool:
    """Try to auto-register a Telegram user during the registration window.

    Returns True if registration succeeded, False if the window is closed.
    """
    if not state.is_registration_open(agent_id):
        return False

    state.create_mapping("telegram", telegram_user_id, agent_id, sender_name)
    state.close_registration_window(agent_id, telegram_user_id)
    return True
