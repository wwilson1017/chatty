"""Telegram integration — FastAPI router.

Handles inbound Telegram webhooks (unauthenticated, routed by agent slug)
and JWT-protected admin endpoints for bot token management and registration.
"""

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, Depends, HTTPException, Request

from core.auth import get_current_user
from agents import db as agent_db

from . import state, lifecycle, service
from .client import send_message
from .models import SetBotTokenRequest, ResetRegistrationRequest

logger = logging.getLogger(__name__)

router = APIRouter(tags=["telegram"])

_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="telegram-webhook")


# ---------------------------------------------------------------------------
# Telegram webhook — per-agent, no JWT, routed by slug
# ---------------------------------------------------------------------------

@router.post("/webhook/{agent_slug}", status_code=200)
async def telegram_webhook(agent_slug: str, request: Request):
    """Receive inbound Telegram messages for an agent's bot.

    Returns 200 immediately; processes message and sends reply in background.
    """
    try:
        raw = await request.json()
    except Exception:
        logger.warning("Telegram webhook (%s): unparseable body", agent_slug)
        return {"status": "ok"}

    # Telegram sends an Update object
    message = raw.get("message")
    if not message:
        return {"status": "ok"}

    text = message.get("text", "")
    if not text:
        return {"status": "ok"}

    chat = message.get("chat", {})
    chat_id = chat.get("id")
    from_user = message.get("from", {})
    user_id = str(from_user.get("id", ""))
    first_name = from_user.get("first_name", "")
    last_name = from_user.get("last_name", "")
    sender_name = f"{first_name} {last_name}".strip() or "Unknown"

    if not chat_id or not user_id:
        return {"status": "ok"}

    logger.info(
        "Telegram webhook: slug=%s user_id=%s name=%s chat_id=%s msg=%s",
        agent_slug, user_id, sender_name, chat_id, text[:100],
    )

    _executor.submit(
        _safe_process_telegram, agent_slug, user_id, sender_name, text, chat_id,
    )
    return {"status": "ok"}


def _safe_process_telegram(
    agent_slug: str, user_id: str, sender_name: str, message: str, chat_id: int,
) -> None:
    """Process a Telegram message in a background thread."""
    bot_token = ""
    try:
        # Resolve slug → agent
        agent = agent_db.get_agent_by_slug(agent_slug)
        if not agent:
            logger.warning("Telegram webhook: unknown slug %s", agent_slug)
            return

        bot_token = agent.get("telegram_bot_token", "")
        if not bot_token:
            return

        # Check if sender has a mapping
        mapping = state.get_mapping_by_sender("telegram", user_id)
        if not mapping:
            # Try auto-registration
            if lifecycle.try_auto_register(agent["id"], user_id, sender_name):
                logger.info("Auto-registered Telegram user %s for agent %s", user_id, agent["agent_name"])
            else:
                send_message(
                    chat_id,
                    "Registration window is closed. Please ask the admin to reset it in Chatty.",
                    bot_token,
                )
                return

        # Process the message via async service
        loop = asyncio.new_event_loop()
        try:
            response = loop.run_until_complete(
                service.process_message(user_id, sender_name, message)
            )
        finally:
            loop.close()

        send_message(chat_id, response, bot_token)
    except Exception:
        logger.exception("Telegram processing failed (slug=%s, user_id=%s)", agent_slug, user_id)
        try:
            if bot_token:
                send_message(
                    chat_id, "I had trouble processing that. Please try again.", bot_token,
                )
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Admin endpoints — JWT protected
# ---------------------------------------------------------------------------

@router.post("/bot-token")
def set_bot_token(
    req: SetBotTokenRequest, user: dict = Depends(get_current_user),
):
    """Validate and save a Telegram bot token for an agent.

    Registers the webhook and opens a 10-minute registration window.
    """
    try:
        result = lifecycle.validate_and_save_token(req.agent_id, req.bot_token)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/bot-token/{agent_id}")
def remove_bot_token(
    agent_id: str, user: dict = Depends(get_current_user),
):
    """Remove a Telegram bot token from an agent."""
    lifecycle.remove_token(agent_id)
    return {"ok": True}


@router.post("/reset-registration")
def reset_registration(
    req: ResetRegistrationRequest, user: dict = Depends(get_current_user),
):
    """Reset (re-open) the Telegram registration window for an agent."""
    try:
        window = lifecycle.reset_registration_window(req.agent_id)
        return window
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/registration-window/{agent_id}")
def get_registration_window(
    agent_id: str, user: dict = Depends(get_current_user),
):
    """Get the current Telegram registration window status for an agent."""
    window = state.get_registration_window(agent_id)
    if not window:
        return {"open": False, "window": None}
    return {
        "open": state.is_registration_open(agent_id),
        "window": window,
    }


@router.get("/status/{agent_id}")
def get_telegram_status(
    agent_id: str, user: dict = Depends(get_current_user),
):
    """Get the Telegram bot status for an agent."""
    agent = agent_db.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    bot_token = agent.get("telegram_bot_token", "")
    return {
        "connected": bool(bot_token),
        "enabled": bool(agent.get("telegram_enabled")),
        "bot_username": agent.get("telegram_bot_username", ""),
    }


@router.get("/mappings")
def list_mappings(user: dict = Depends(get_current_user)):
    """List all Telegram user mappings."""
    return {"mappings": state.get_user_mappings()}


@router.delete("/mappings/{mapping_id}")
def delete_mapping(mapping_id: str, user: dict = Depends(get_current_user)):
    """Delete a Telegram user mapping."""
    if state.delete_mapping(mapping_id):
        return {"ok": True}
    raise HTTPException(status_code=404, detail="Mapping not found")
