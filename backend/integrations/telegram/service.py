"""Telegram integration — Message processing service.

Routes inbound Telegram messages to the appropriate Chatty agent,
runs the agent (non-streaming), and returns the response text.
The router handles sending the response back via the Telegram client.
"""

import logging
import uuid

from agents import db as agent_db
from agents.engine import (
    build_agent_config,
    get_context_manager,
    get_chat_service,
)
from agents.tool_loader import INTEGRATION_MODULES, load_integration_tools, build_agent_handlers, tool_flags
from core.providers import get_ai_provider
from core.agents.tool_registry import ToolRegistry
from core.agents import ai_service

from . import state
from .group import build_group_prefix

logger = logging.getLogger(__name__)


async def save_message_only(
    agent_id: str,
    agent_slug: str,
    sender_id: str,
    content: str,
    source: str = "telegram",
) -> None:
    """Save a user message to chat history without running the AI.

    Used when the agent is already busy processing a message for this chat.
    The message is preserved so it appears in context for the next AI turn.
    Never raises — logs failures internally.
    """
    try:
        chat_service = get_chat_service(agent_slug)
        if not chat_service:
            logger.warning("save_message_only: no chat service for %s", agent_slug)
            return

        conv = state.get_or_create_conversation(sender_id, agent_id)
        chatty_conv_id = conv.get("chatty_conversation_id")
        if not chatty_conv_id:
            # Don't create a new conversation here — the active request will
            # create it.  Skip saving to avoid a race on conversation creation.
            return

        chat_service.save_message(
            conversation_id=chatty_conv_id,
            msg_id=str(uuid.uuid4()),
            role="user",
            content=content,
        )
        logger.info("save_message_only: saved busy-skipped message for %s", agent_slug)
    except Exception:
        logger.warning("save_message_only: failed for agent=%s sender=%s", agent_slug, sender_id, exc_info=True)


async def process_message(
    sender_id: str,
    sender_name: str,
    message_text: str,
    agent_id: str,
) -> str:
    """Route an inbound Telegram message to the appropriate agent and return the response.

    Args:
        sender_id: Telegram user ID (string)
        sender_name: Display name from Telegram
        message_text: The message content
        agent_id: The agent ID (resolved by the webhook handler from the URL slug)

    Returns:
        The agent's response text.
    """
    if not state.get_mapping_by_sender("telegram", sender_id, agent_id):
        return (
            "I don't recognize your account yet. "
            "Please ask the admin to reset the registration window."
        )

    agent = agent_db.get_agent(agent_id)
    if not agent:
        return "This agent is no longer available."

    if not agent.get("telegram_enabled"):
        return "Telegram messaging is currently disabled for this agent."

    slug = agent["slug"]
    config = build_agent_config(agent)
    ctx_manager = get_context_manager(slug)
    chat_service = get_chat_service(slug)

    provider = get_ai_provider(
        agent_provider=config.provider_override or None,
        agent_model=config.model_override or None,
        agent_model_tier=config.model_tier,
    )
    if not provider:
        return "No AI provider is configured. Please set up an AI provider in Settings."

    ga = config.google_accounts
    gmail_ids = ga.get("gmail", [])
    calendar_ids = ga.get("calendar", [])
    drive_ids = ga.get("drive", [])
    google_connected = bool(gmail_ids or calendar_ids or drive_ids)

    from integrations.registry import list_google_accounts as _list_ga
    all_ga = _list_ga()
    account_info_map = {
        aid: {"email": a.get("email", ""), "scope_grants": a.get("scope_grants", {}), "connection_status": a.get("connection_status", "ok")}
        for aid, a in all_ga.items()
    }

    integration_tool_defs, integration_executors = load_integration_tools()

    from integrations.registry import get_tool_mode, get_credentials
    integration_tool_modes = {
        name: get_tool_mode(name)
        for name in INTEGRATION_MODULES
        if "tool_mode" in get_credentials(name)
    }

    reminder_handlers, sa_handlers = build_agent_handlers(slug)
    registry = ToolRegistry(
        context_dir=config.context_dir,
        google_connected=google_connected,
        integration_executors=integration_executors,
        integration_tool_flags=tool_flags(integration_tool_defs),
        agent_slug=slug,
        reminder_handlers=reminder_handlers,
        scheduled_action_handlers=sa_handlers,
        gmail_account_ids=gmail_ids,
        calendar_account_ids=calendar_ids,
        drive_account_ids=drive_ids,
        account_info_map=account_info_map,
    )
    # Private chat with a mapped user: chat id == user id.
    registry._turn_origin = "user"
    registry._turn_route = {"channel": "telegram", "chat_id": sender_id}

    # 5. Get/create Telegram conversation for multi-turn context
    conv = state.get_or_create_conversation(sender_id, agent_id)

    # 6. Resolve or create Chatty chat history conversation
    chatty_conv_id = conv.get("chatty_conversation_id")
    if not chatty_conv_id and chat_service:
        try:
            new_conv = chat_service.create_conversation(source="telegram")
            chatty_conv_id = new_conv["id"]
            state.set_chatty_conversation_id(conv["id"], chatty_conv_id)
        except Exception as e:
            logger.warning("Failed to create chat history conversation: %s", e)

    # 7. run_sync reconstructs the full conversation from chat_history.db by
    # conversation_id (with compaction + full tool results), so pass ONLY the
    # new inbound message. Prior turns — including any busy-skipped messages
    # saved via save_message_only — are assembled server-side.
    platform_prefix = f"[via Telegram from {sender_name}] "
    messages = [{"role": "user", "content": platform_prefix + message_text}]

    # 8. Run the agent (non-streaming)
    response = await ai_service.run_sync(
        config=config,
        provider=provider,
        registry=registry,
        ctx_manager=ctx_manager,
        messages=messages,
        chat_service=chat_service,
        conversation_id=chatty_conv_id,
        integration_tool_defs=integration_tool_defs or None,
        integration_tool_modes=integration_tool_modes,
        source="telegram",
    )

    return response or "I had trouble generating a response. Please try again."


async def process_group_message(
    chat_id: int,
    agent_id: str,
    sender_name: str,
    sender_is_bot: bool,
    group_name: str,
    message_text: str,
    sender_id: str = "",
) -> str:
    """Process a group chat message for a specific agent. `sender_id` is the Telegram user who wrote it."""

    agent = agent_db.get_agent(agent_id)
    if not agent:
        return "This agent is no longer available."
    if not agent.get("telegram_enabled"):
        return "Telegram messaging is currently disabled for this agent."

    slug = agent["slug"]

    config = build_agent_config(agent)
    ctx_manager = get_context_manager(slug)
    chat_service = get_chat_service(slug)

    provider = get_ai_provider(
        agent_provider=config.provider_override or None,
        agent_model=config.model_override or None,
        agent_model_tier=config.model_tier,
    )
    if not provider:
        return "No AI provider is configured. Please set up an AI provider in Settings."

    ga = config.google_accounts
    gmail_ids = ga.get("gmail", [])
    calendar_ids = ga.get("calendar", [])
    drive_ids = ga.get("drive", [])
    google_connected = bool(gmail_ids or calendar_ids or drive_ids)

    from integrations.registry import list_google_accounts as _list_ga
    all_ga = _list_ga()
    account_info_map = {
        aid: {"email": a.get("email", ""), "scope_grants": a.get("scope_grants", {}), "connection_status": a.get("connection_status", "ok")}
        for aid, a in all_ga.items()
    }

    integration_tool_defs, integration_executors = load_integration_tools()

    from integrations.registry import get_tool_mode, get_credentials
    integration_tool_modes = {
        name: get_tool_mode(name)
        for name in INTEGRATION_MODULES
        if "tool_mode" in get_credentials(name)
    }

    reminder_handlers, sa_handlers = build_agent_handlers(slug)
    registry = ToolRegistry(
        context_dir=config.context_dir,
        google_connected=google_connected,
        integration_executors=integration_executors,
        integration_tool_flags=tool_flags(integration_tool_defs),
        agent_slug=slug,
        reminder_handlers=reminder_handlers,
        scheduled_action_handlers=sa_handlers,
        gmail_account_ids=gmail_ids,
        calendar_account_ids=calendar_ids,
        drive_account_ids=drive_ids,
        account_info_map=account_info_map,
    )
    # A group member asked, not the owner: never user-originated (no full access,
    # no approvals), but anything the turn delegates reports back to the group.
    # The route says it's a group so approval cards and takeover links go to the
    # owner's private chat instead. Only the owner's linked account (the dashboard
    # pairing, the same check that decides who may approve) may use the computer.
    registry._turn_origin = "group"
    registry._turn_route = {"channel": "telegram", "chat_id": str(chat_id), "group": True}
    registry._turn_group_owner = bool(
        sender_id and not sender_is_bot and state.get_mapping_by_sender("telegram", sender_id, agent_id))

    group_sender_id = f"group:{chat_id}"
    conv = state.get_or_create_conversation(group_sender_id, agent_id)

    chatty_conv_id = conv.get("chatty_conversation_id")
    if not chatty_conv_id and chat_service:
        try:
            new_conv = chat_service.create_conversation(source="telegram-group")
            chatty_conv_id = new_conv["id"]
            state.set_chatty_conversation_id(conv["id"], chatty_conv_id)
        except Exception as e:
            logger.warning("Failed to create group chat conversation: %s", e)

    # run_sync rebuilds the full conversation from the DB — pass only the new
    # message (prior turns are assembled server-side).
    prefix = build_group_prefix(group_name, sender_name, sender_is_bot)
    messages = [{"role": "user", "content": prefix + message_text}]

    response = await ai_service.run_sync(
        config=config,
        provider=provider,
        registry=registry,
        ctx_manager=ctx_manager,
        messages=messages,
        chat_service=chat_service,
        conversation_id=chatty_conv_id,
        integration_tool_defs=integration_tool_defs or None,
        integration_tool_modes=integration_tool_modes,
        source="telegram-group",
    )

    return response or "I had trouble generating a response. Please try again."
