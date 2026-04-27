"""Chatty — WhatsApp message processing service.

Routes inbound WhatsApp messages to the appropriate Chatty agent,
runs the agent synchronously via background_runner, and returns
the response text. The router handles sending the response back
via the WhatsApp client.

Ported from CAKE OS messaging/service.py.
Adapted: uses Chatty's background_runner + agent engine instead of
CAKE OS's run_sync + load_agent_components.
"""

import importlib
import logging
import threading
import uuid

from agents.db import get_agent_by_slug
from agents.engine import build_agent_config, get_context_manager, get_chat_service
from core.agents.background_runner import run_background_turn
from core.agents.tool_registry import ToolRegistry
from core.agents.tool_definitions import get_tool_definitions
from core.agents.tools.real_tools import load_all_real_tools
from core.providers.credentials import CredentialStore
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

from . import state

logger = logging.getLogger(__name__)

# Maximum recent messages to include for context
MAX_CONTEXT_MESSAGES = 20

# Per-agent lock to prevent concurrent AI turns from corrupting context files
_agent_locks: dict[str, threading.Lock] = {}
_agent_locks_guard = threading.Lock()


def _get_agent_lock(agent_slug: str) -> threading.Lock:
    """Get or create a lock for a specific agent."""
    with _agent_locks_guard:
        if agent_slug not in _agent_locks:
            _agent_locks[agent_slug] = threading.Lock()
        return _agent_locks[agent_slug]

# Integration module registry (same as agents/router.py)
_INTEGRATION_MODULES = {
    "crm_lite": ("integrations.crm_lite.tools", "CRM_LITE_TOOL_DEFS"),
    "odoo": ("integrations.odoo.tools", "ODOO_TOOL_DEFS"),
    "bamboohr": ("integrations.bamboohr.tools", "BAMBOOHR_TOOL_DEFS"),
    "quickbooks": ("integrations.quickbooks.tools", "QB_TOOL_DEFS"),
    "shopify": ("integrations.shopify.tools", "SHOPIFY_TOOL_DEFS"),
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


def process_message(
    agent_slug: str,
    phone: str,
    sender_name: str,
    message_text: str,
) -> str:
    """Route an inbound WhatsApp message to the agent and return the response.

    Uses a per-agent lock to prevent concurrent AI turns from corrupting
    context files when multiple messages arrive simultaneously.

    Args:
        agent_slug: The agent's slug identifier
        phone: Sender's phone number
        sender_name: Display name from WhatsApp
        message_text: The message content

    Returns:
        The agent's response text.
    """
    lock = _get_agent_lock(agent_slug)
    with lock:
        return _process_message_locked(agent_slug, phone, sender_name, message_text)


def _process_message_locked(
    agent_slug: str,
    phone: str,
    sender_name: str,
    message_text: str,
) -> str:
    """Internal: process message with agent lock held."""
    # 1. Load agent
    agent = get_agent_by_slug(agent_slug)
    if not agent:
        return "I had trouble starting up. Please try again."

    # 2. Build agent components
    config = build_agent_config(agent)
    ctx_manager = get_context_manager(agent_slug)
    chat_service = get_chat_service(agent_slug)

    # 3. Get/create conversation for multi-turn context
    conv = state.get_or_create_conversation(phone, agent_slug, "whatsapp")

    # 4. Resolve or create Chatty chat history conversation
    chatty_conv_id = conv.get("chatty_conversation_id")
    if not chatty_conv_id and chat_service:
        try:
            new_conv = chat_service.create_conversation(source="whatsapp")
            chatty_conv_id = new_conv["id"]
            state.set_chatty_conversation_id(conv["id"], chatty_conv_id)
        except Exception as e:
            logger.warning("Failed to create chat history conversation: %s", e)

    # 5. Save the user message to chat history
    if chat_service and chatty_conv_id:
        try:
            chat_service.save_message(
                conversation_id=chatty_conv_id,
                msg_id=str(uuid.uuid4()),
                role="user",
                content=message_text,
            )
        except Exception as e:
            logger.warning("Failed to save user message to chat history: %s", e)

    # 6. Build system prompt
    system_prompt = _build_system_prompt(config, ctx_manager)

    # 7. Load recent messages for context
    messages_for_context = _load_recent_messages(chat_service, chatty_conv_id)
    # If no history, just use the current message
    user_message = f"[via WhatsApp from {sender_name}] {message_text}"
    if messages_for_context:
        # background_runner takes a single user_message, not a full messages array.
        # We'll include recent context in the system prompt instead.
        context_lines = []
        for msg in messages_for_context[:-1]:  # exclude the most recent (current) message
            role = msg["role"]
            content = msg["content"][:500]
            context_lines.append(f"[{role}]: {content}")
        if context_lines:
            system_prompt += "\n\n# Recent Conversation Context\n\n" + "\n".join(context_lines)

    # 8. Build tool registry
    store = CredentialStore()
    from integrations.registry import is_enabled as _is_enabled
    google_connected = _is_enabled("google")

    integration_tool_defs, integration_executors = _load_integration_tools()

    from integrations.registry import get_tool_mode
    integration_tool_modes = {name: get_tool_mode(name) for name in _INTEGRATION_MODULES}

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

    registry = ToolRegistry(
        context_dir=config.context_dir,
        google_connected=google_connected,
        integration_executors=integration_executors,
        agent_slug=agent_slug,
        reminder_handlers=reminder_handlers,
        scheduled_action_handlers=sa_handlers,
    )

    # 9. Build tool definitions
    dynamic_real_tools = load_all_real_tools(agent_slug)
    from integrations.google.policy import google_capabilities
    google_caps = google_capabilities()
    tool_defs = get_tool_definitions(
        integration_tools=integration_tool_defs or None,
        dynamic_real_tools=dynamic_real_tools or None,
        **google_caps,
    )

    # Apply integration permission ceilings — messaging channels have no approval UI,
    # so both "read-only" and "normal" ceilings must strip write tools here.
    if integration_tool_modes:
        tool_defs = [
            t for t in tool_defs
            if not t.get("writes", False)
            or t.get("context_memory", False)
            or integration_tool_modes.get(t.get("integration", ""), "power") == "power"
        ]

    # 10. Run the agent
    result = run_background_turn(
        system_prompt=system_prompt,
        user_message=user_message,
        tool_defs=tool_defs,
        registry=registry,
        max_iterations=5,
        model_override=config.model_override or None,
    )

    response_text = result.text

    # 11. Save assistant response to chat history
    if chat_service and chatty_conv_id and response_text:
        try:
            chat_service.save_message(
                conversation_id=chatty_conv_id,
                msg_id=str(uuid.uuid4()),
                role="assistant",
                content=response_text,
            )
        except Exception as e:
            logger.warning("Failed to save assistant message to chat history: %s", e)

    return response_text or "I had trouble generating a response. Please try again."


def _build_system_prompt(config, ctx_manager) -> str:
    """Build a system prompt for WhatsApp message processing.

    Mirrors ai_service._build_system_prompt but without training mode.
    """
    from datetime import datetime
    from zoneinfo import ZoneInfo

    ct_tz = ZoneInfo("America/Chicago")
    now_ct = datetime.now(ct_tz)
    date_str = now_ct.strftime("%A, %B %d, %Y")
    time_str = now_ct.strftime("%I:%M %p CT")

    context = ctx_manager.load_all_context()

    personality = config.personality or (
        f"You are {config.agent_name}, a helpful personal AI assistant."
    )

    parts = [
        personality,
        "",
        "# Your Knowledge (Long-Term Memory)",
        "",
        "These are your persistent memory files. They carry forward across all conversations. "
        "Read them carefully — this is what you know. Update them actively when you learn new things.",
        "",
        context if context else "(No knowledge files yet. Create them using write_context_file.)",
        "",
        "# Current Session",
        "",
        f"- Date: {date_str}",
        f"- Time: {time_str}",
        f"- Channel: WhatsApp (messages are from a phone, keep responses concise)",
        "",
        "# Instructions",
        "",
        f"- You are {config.agent_name}. Be helpful, concise, and proactive.",
        "- Use your knowledge files to personalize every response.",
        "- When you learn something new, save it immediately.",
        "- Keep responses brief and mobile-friendly — this is a WhatsApp conversation.",
        "",
    ]

    return "\n".join(parts)


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
