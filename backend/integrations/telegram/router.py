"""Telegram integration — FastAPI router.

Handles inbound Telegram webhooks (unauthenticated, routed by agent slug)
and JWT-protected admin endpoints for bot token management and registration.
"""

import asyncio
import hmac
import logging
import threading
import time
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

# Per-chat busy tracking: maps (agent_slug, chat_id) → start timestamp.
# Entries older than _BUSY_TTL are treated as stale (hung request).
_busy_chats: dict[tuple[str, int], float] = {}
_busy_lock = threading.Lock()
_BUSY_TTL = 300  # 5 minutes

from pathlib import Path as _Path
_AGENTS_DIR = _Path(__file__).resolve().parent.parent.parent / "data" / "agents"


def _mark_telegram_configured(agent_slug: str) -> None:
    """Auto-update the agent's _pending-setup.md after first Telegram message."""
    from integrations.pending_setup import mark_integration_complete
    context_dir = _AGENTS_DIR / agent_slug / "context"
    mark_integration_complete(context_dir, "Telegram Bot")


# ---------------------------------------------------------------------------
# Telegram webhook — per-agent, no JWT, routed by slug
# ---------------------------------------------------------------------------

@router.post("/webhook/{agent_slug}", status_code=200)
async def telegram_webhook(agent_slug: str, request: Request):
    """Receive inbound Telegram messages for an agent's bot.

    Returns 200 immediately; processes message and sends reply in background.
    Verifies the X-Telegram-Bot-Api-Secret-Token header against the stored secret.
    """
    # Verify webhook secret token
    agent = agent_db.get_agent_by_slug(agent_slug)
    if agent:
        expected_secret = state.get_webhook_secret(agent["id"])
        if expected_secret:
            received_secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
            if not hmac.compare_digest(received_secret, expected_secret):
                logger.warning("Telegram webhook (%s): invalid secret token", agent_slug)
                return {"status": "ok"}  # Return 200 to avoid Telegram retries

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
    chat_type = chat.get("type", "private")
    from_user = message.get("from", {})
    user_id = str(from_user.get("id", ""))
    is_bot = from_user.get("is_bot", False)
    from_username = from_user.get("username", "")
    first_name = from_user.get("first_name", "")
    last_name = from_user.get("last_name", "")
    sender_name = f"{first_name} {last_name}".strip() or "Unknown"
    group_name = chat.get("title", "")

    # For group mention/reply detection
    entities = message.get("entities", [])
    reply_to = message.get("reply_to_message")
    reply_to_bot_username = ""
    if reply_to and reply_to.get("from", {}).get("is_bot"):
        reply_to_bot_username = reply_to.get("from", {}).get("username", "")

    if not chat_id or not user_id:
        return {"status": "ok"}

    logger.info(
        "Telegram webhook: slug=%s user_id=%s name=%s chat_id=%s type=%s msg=%s",
        agent_slug, user_id, sender_name, chat_id, chat_type, text[:100],
    )

    _executor.submit(
        _safe_process_telegram, agent_slug, user_id, sender_name, text, chat_id,
        chat_type, is_bot, from_username, group_name, entities, reply_to_bot_username,
    )
    return {"status": "ok"}


def _safe_process_telegram(
    agent_slug: str, user_id: str, sender_name: str, message: str, chat_id: int,
    chat_type: str = "private", is_bot: bool = False,
    from_username: str = "", group_name: str = "",
    entities: list | None = None, reply_to_bot_username: str = "",
) -> None:
    """Process a Telegram message in a background thread."""
    from . import group

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

        # Check Telegram is enabled before any processing
        if not agent.get("telegram_enabled"):
            return

        # ── Group chat path ──────────────────────────────────────────
        if group.is_group_chat(chat_type):
            if not is_bot:
                group.record_human_message(chat_id)

            bot_username = agent.get("telegram_bot_username", "")
            is_addressed = group.is_addressed_to_bot(
                message, entities or [], reply_to_bot_username, bot_username,
            )
            ok, reason = group.should_respond(chat_id, is_bot, from_username, agent, is_addressed)
            if not ok:
                logger.debug("Group skip: chat=%s agent=%s reason=%s", chat_id, agent_slug, reason)
                return

            if is_bot:
                group.record_bot_message(chat_id)

            # Busy check — save message to history but skip AI if already processing
            busy_key = (agent_slug, chat_id)
            busy_started = time.monotonic()
            with _busy_lock:
                existing = _busy_chats.get(busy_key)
                if existing is not None and (busy_started - existing) < _BUSY_TTL:
                    is_busy = True
                else:
                    _busy_chats[busy_key] = busy_started
                    is_busy = False

            if is_busy:
                logger.info("Telegram busy (group): agent=%s chat=%s — saving without reply", agent_slug, chat_id)
                prefix = group.build_group_prefix(group_name, sender_name, is_bot)
                loop = asyncio.new_event_loop()
                try:
                    loop.run_until_complete(service.save_message_only(
                        agent_id=agent["id"],
                        agent_slug=agent_slug,
                        sender_id=f"group:{chat_id}",
                        content=prefix + message,
                        source="telegram-group",
                    ))
                except Exception:
                    logger.warning("Failed to save busy-skipped group message for chat=%s", chat_id, exc_info=True)
                finally:
                    loop.close()
                return

            try:
                loop = asyncio.new_event_loop()
                try:
                    response = loop.run_until_complete(
                        service.process_group_message(
                            chat_id=chat_id,
                            agent_id=agent["id"],
                            sender_name=sender_name,
                            sender_is_bot=is_bot,
                            group_name=group_name,
                            message_text=message,
                        )
                    )
                finally:
                    loop.close()

                try:
                    send_message(chat_id, response, bot_token)
                finally:
                    group.record_response(chat_id, agent["id"])
            finally:
                with _busy_lock:
                    if _busy_chats.get(busy_key) == busy_started:
                        del _busy_chats[busy_key]
            return

        # ── Private chat path ────────────────────────────────────────
        agent_id = agent["id"]
        mapping = state.get_mapping_by_sender("telegram", user_id, agent_id)
        if not mapping:
            if lifecycle.try_auto_register(agent_id, user_id, sender_name):
                logger.info("Auto-registered Telegram user %s for agent %s", user_id, agent["agent_name"])
                _mark_telegram_configured(agent["slug"])
            else:
                send_message(
                    chat_id,
                    "Registration window is closed. Please ask the admin to reset it in Chatty.",
                    bot_token,
                )
                return

        # Busy check — save message to history but skip AI if already processing
        busy_key = (agent_slug, chat_id)
        busy_started = time.monotonic()
        with _busy_lock:
            existing = _busy_chats.get(busy_key)
            if existing is not None and (busy_started - existing) < _BUSY_TTL:
                is_busy = True
            else:
                _busy_chats[busy_key] = busy_started
                is_busy = False

        if is_busy:
            logger.info("Telegram busy (private): agent=%s chat=%s — saving without reply", agent_slug, chat_id)
            prefix = f"[via Telegram from {sender_name}] "
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(service.save_message_only(
                    agent_id=agent_id,
                    agent_slug=agent_slug,
                    sender_id=user_id,
                    content=prefix + message,
                ))
            except Exception:
                logger.warning("Failed to save busy-skipped message for chat=%s", chat_id, exc_info=True)
            finally:
                loop.close()
            return

        # Process the message via async service
        try:
            loop = asyncio.new_event_loop()
            try:
                response = loop.run_until_complete(
                    service.process_message(user_id, sender_name, message, agent_id)
                )
            finally:
                loop.close()

            send_message(chat_id, response, bot_token)
        finally:
            with _busy_lock:
                if _busy_chats.get(busy_key) == busy_started:
                    del _busy_chats[busy_key]
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
        "group_enabled": bool(agent.get("telegram_group_enabled")),
        "respond_to_bots": bool(agent.get("telegram_respond_to_bots")),
        "max_bot_turns": agent.get("telegram_max_bot_turns", 3),
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
