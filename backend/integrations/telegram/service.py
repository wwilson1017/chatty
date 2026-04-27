"""Telegram integration — Message processing service.

Routes inbound Telegram messages to the appropriate Chatty agent,
runs the agent (non-streaming), and returns the response text.
The router handles sending the response back via the Telegram client.
"""

import importlib
import logging
import uuid

from agents import db as agent_db
from agents.engine import (
    build_agent_config,
    get_context_manager,
    get_chat_service,
)
from core.providers import get_ai_provider
from core.providers.credentials import CredentialStore
from core.agents.tool_registry import ToolRegistry
from core.agents.reminders.tools import (
    create_reminder_handler,
    list_reminders_handler,
    cancel_reminder_handler,
)
from core.agents.scheduled_actions.tools import (
    create_scheduled_action_handler,
    list_scheduled_actions_handler,
    update_scheduled_action_handler,
    delete_scheduled_action_handler,
)
from core.agents import ai_service

from . import state
from .group import build_group_prefix

logger = logging.getLogger(__name__)

# Maximum recent messages to include for context
MAX_CONTEXT_MESSAGES = 20


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

# Integration module registry (same as agents/router.py)
_INTEGRATION_MODULES = {
    "crm_lite": ("integrations.crm_lite.tools", "CRM_LITE_TOOL_DEFS"),
    "odoo": ("integrations.odoo.tools", "ODOO_TOOL_DEFS"),
    "bamboohr": ("integrations.bamboohr.tools", "BAMBOOHR_TOOL_DEFS"),
    "quickbooks": ("integrations.quickbooks.tools", "QB_TOOL_DEFS"),
    "qb_csv": ("integrations.qb_csv.tools", "QB_CSV_TOOL_DEFS"),
    "paperclip": ("integrations.paperclip.tools", "PAPERCLIP_TOOL_DEFS"),
    "todoist": ("integrations.todoist.tools", "TODOIST_TOOL_DEFS"),
}


def _load_integration_tools() -> tuple[list[dict], dict]:
    """Load tool definitions and executors from all enabled integrations."""
    from integrations.registry import is_enabled

    tool_defs: list[dict] = []
    executors: dict = {}

    for name, (module_path, defs_attr) in _INTEGRATION_MODULES.items():
        if not is_enabled(name):
            continue
        try:
            if name == "crm_lite":
                from integrations.crm_lite.db import init_db, _connection
                if _connection is None:
                    init_db()

            mod = importlib.import_module(module_path)
            defs = getattr(mod, defs_attr, [])
            execs = getattr(mod, "TOOL_EXECUTORS", {})
            tool_defs.extend({**d, "integration": name} for d in defs)
            executors.update(execs)
        except Exception as e:
            logger.warning("Failed to load integration %s: %s", name, e)

    return tool_defs, executors


def _build_agent_handlers(agent_slug: str) -> tuple[dict, dict]:
    """Build reminder and scheduled action handler dicts for an agent."""
    reminder_handlers = {
        "create_reminder": lambda **kw: create_reminder_handler(agent_slug, **kw),
        "list_reminders": lambda **kw: list_reminders_handler(agent_slug, **kw),
        "cancel_reminder": lambda **kw: cancel_reminder_handler(agent_slug, **kw),
    }
    sa_handlers = {
        "create_scheduled_action": lambda **kw: create_scheduled_action_handler(agent_slug, **kw),
        "list_scheduled_actions": lambda **kw: list_scheduled_actions_handler(agent_slug, **kw),
        "update_scheduled_action": lambda **kw: update_scheduled_action_handler(agent_slug, **kw),
        "delete_scheduled_action": lambda **kw: delete_scheduled_action_handler(agent_slug, **kw),
    }
    return reminder_handlers, sa_handlers


async def process_message(
    sender_id: str,
    sender_name: str,
    message_text: str,
) -> str:
    """Route an inbound Telegram message to the appropriate agent and return the response.

    Args:
        sender_id: Telegram user ID (string)
        sender_name: Display name from Telegram
        message_text: The message content

    Returns:
        The agent's response text.
    """
    # 1. Look up sender → agent_id
    mapping = state.get_mapping_by_sender("telegram", sender_id)
    if not mapping:
        return (
            "I don't recognize your account yet. "
            "Please ask the admin to reset the registration window."
        )

    agent_id = mapping["agent_id"]

    # 2. Load agent
    agent = agent_db.get_agent(agent_id)
    if not agent:
        return "This agent is no longer available."

    # 3. Check Telegram is enabled
    if not agent.get("telegram_enabled"):
        return "Telegram messaging is currently disabled for this agent."

    slug = agent["slug"]

    # 4. Build the agent pipeline (mirrors agents/router.py::_stream_chat)
    config = build_agent_config(agent)
    ctx_manager = get_context_manager(slug)
    chat_service = get_chat_service(slug)

    store = CredentialStore()
    provider = get_ai_provider(
        agent_provider=config.provider_override or None,
        agent_model=config.model_override or None,
    )
    if not provider:
        return "No AI provider is configured. Please set up an AI provider in Settings."

    from integrations.registry import is_enabled as _is_enabled
    google_connected = _is_enabled("google")

    integration_tool_defs, integration_executors = _load_integration_tools()

    from integrations.registry import get_tool_mode
    integration_tool_modes = {name: get_tool_mode(name) for name in _INTEGRATION_MODULES}

    reminder_handlers, sa_handlers = _build_agent_handlers(slug)
    registry = ToolRegistry(
        context_dir=config.context_dir,
        google_connected=google_connected,
        integration_executors=integration_executors,
        agent_slug=slug,
        reminder_handlers=reminder_handlers,
        scheduled_action_handlers=sa_handlers,
    )

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

    # 7. Load recent messages for context
    messages = _load_recent_messages(chat_service, chatty_conv_id)
    platform_prefix = f"[via Telegram from {sender_name}] "
    if not messages:
        messages = [{"role": "user", "content": platform_prefix + message_text}]
    else:
        messages.append({"role": "user", "content": platform_prefix + message_text})

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
    )

    return response or "I had trouble generating a response. Please try again."


async def process_group_message(
    chat_id: int,
    agent_id: str,
    sender_name: str,
    sender_is_bot: bool,
    group_name: str,
    message_text: str,
) -> str:
    """Process a group chat message for a specific agent."""

    agent = agent_db.get_agent(agent_id)
    if not agent:
        return "This agent is no longer available."
    if not agent.get("telegram_enabled"):
        return "Telegram messaging is currently disabled for this agent."

    slug = agent["slug"]

    config = build_agent_config(agent)
    ctx_manager = get_context_manager(slug)
    chat_service = get_chat_service(slug)

    store = CredentialStore()
    provider = get_ai_provider(
        agent_provider=config.provider_override or None,
        agent_model=config.model_override or None,
    )
    if not provider:
        return "No AI provider is configured. Please set up an AI provider in Settings."

    from integrations.registry import is_enabled as _is_enabled
    google_connected = _is_enabled("google")

    integration_tool_defs, integration_executors = _load_integration_tools()

    from integrations.registry import get_tool_mode
    integration_tool_modes = {name: get_tool_mode(name) for name in _INTEGRATION_MODULES}

    reminder_handlers, sa_handlers = _build_agent_handlers(slug)
    registry = ToolRegistry(
        context_dir=config.context_dir,
        google_connected=google_connected,
        integration_executors=integration_executors,
        agent_slug=slug,
        reminder_handlers=reminder_handlers,
        scheduled_action_handlers=sa_handlers,
    )

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

    messages = _load_recent_messages(chat_service, chatty_conv_id)
    prefix = build_group_prefix(group_name, sender_name, sender_is_bot)
    if not messages:
        messages = [{"role": "user", "content": prefix + message_text}]
    else:
        messages.append({"role": "user", "content": prefix + message_text})

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
    )

    return response or "I had trouble generating a response. Please try again."


def _load_recent_messages(chat_service, conversation_id: str | None) -> list[dict]:
    """Load recent messages from chat history for conversation context."""
    if not chat_service or not conversation_id:
        return []

    try:
        conv = chat_service.get_conversation(conversation_id)
        if not conv or "messages" not in conv:
            return []

        messages = []
        for msg in conv["messages"][-MAX_CONTEXT_MESSAGES:]:
            role = msg.get("role")
            content = msg.get("content", "")
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": content})
        return messages
    except Exception as e:
        logger.warning("Failed to load chat history messages: %s", e)
        return []
