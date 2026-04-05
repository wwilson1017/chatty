"""Telegram bot lifecycle management.

Handles token validation, webhook registration/deregistration, and the
time-limited auto-registration window that lets a user self-onboard by
messaging their agent's Telegram bot within 10 minutes of setup.
"""

import logging

from core.config import settings
from agents.db import get_agent, list_agents, update_agent

from . import state
from .client import validate_token, set_webhook, delete_webhook

logger = logging.getLogger(__name__)


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

    # Generate webhook secret and register webhook
    secret = state.get_or_create_webhook_secret(agent_id)
    slug = existing["slug"]
    webhook_url = f"{settings.backend_url}/api/telegram/webhook/{slug}"
    webhook_result = set_webhook(webhook_url, bot_token, secret_token=secret)

    if not webhook_result.get("ok"):
        logger.warning(
            "Webhook registration failed for agent %s: %s",
            agent_id, webhook_result.get("error", "unknown"),
        )

    # Open registration window
    window = state.open_registration_window(agent_id)

    # Auto-enable Telegram on first token setup
    if not existing.get("telegram_enabled"):
        update_agent(agent_id, telegram_enabled=1)

    return {
        "bot_username": bot_username,
        "bot_id": bot_info.get("id"),
        "webhook_url": webhook_url,
        "webhook_ok": webhook_result.get("ok", False),
        "registration_expires_at": window["expires_at"],
    }


def remove_token(agent_id: str) -> None:
    """Remove a Telegram bot token from an agent.

    Deregisters the webhook and clears the token from the DB.
    """
    agent = get_agent(agent_id)
    if not agent:
        return

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


def register_all_webhooks() -> None:
    """Re-register webhooks for all agents with Telegram bot tokens.

    Called on startup to ensure webhooks point to the current backend URL.
    """
    agents = list_agents()
    count = 0
    for agent in agents:
        token = agent.get("telegram_bot_token", "")
        if not token:
            continue

        slug = agent["slug"]
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
        logger.info("Registered Telegram webhooks for %d agent(s)", count)


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
