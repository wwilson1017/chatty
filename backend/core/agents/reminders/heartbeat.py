"""Chatty — Reminder heartbeat.

Called periodically by APScheduler to process due reminders.
Self-reminders trigger a background AI turn so the agent can act.
"""

import logging

from . import service
from core.agents.background_runner import run_background_turn

logger = logging.getLogger(__name__)

_MAX_PER_TICK = 3
_MAX_TOOL_ITERATIONS = 5


def process_due_reminders() -> None:
    """Check for and process due reminders. Called by APScheduler every 60s."""
    try:
        due = service.get_due_reminders()
    except Exception as e:
        logger.error("Failed to query due reminders: %s", e)
        return

    if not due:
        return

    processed = 0
    for reminder in due[:_MAX_PER_TICK]:
        try:
            _process_self_reminder(reminder)
            processed += 1
        except Exception as e:
            logger.error("Failed to process reminder %s: %s", reminder["id"], e)
            service.mark_fired(reminder["id"], f"error: {e}")

    if processed:
        logger.info("Processed %d due reminders", processed)


def _process_self_reminder(reminder: dict) -> None:
    """Process a self-reminder by running a background AI turn."""
    agent_name = reminder["agent"]

    # Resolve agent config
    from agents.engine import get_context_manager, DATA_DIR
    from agents import db as agent_db

    # Find agent by slug (reminder stores agent slug)
    agents = agent_db.list_agents()
    agent = None
    for a in agents:
        if a["slug"] == agent_name:
            agent = a
            break

    if not agent:
        service.mark_fired(reminder["id"], f"error: agent '{agent_name}' not found")
        return

    ctx_manager = get_context_manager(agent["slug"])
    context = ctx_manager.load_all_context()
    context_snippet = context[:30000] if context else "(no context files)"

    from agents.tool_loader import format_current_time
    date_str, time_str = format_current_time()

    system_prompt = (
        (
            f"You are {agent['agent_name']}, a helpful AI assistant.\n\n"
            f"# Reminder Triggered\n\n"
            f"A reminder you set has fired. Take appropriate action.\n\n"
            f"- **Message:** {reminder['message']}\n"
            f"- **Context:** {reminder.get('context') or 'None'}\n"
            f"- **Originally set at:** {reminder['created_at']}\n\n"
            f"# Your Knowledge (abbreviated)\n\n{context_snippet}\n\n"
        ),
        (
            f"# Current Date & Time\n\n"
            f"- Date: {date_str}\n"
            f"- Time: {time_str}\n\n"
            f"Take any appropriate action using your tools. Be concise."
        ),
    )

    user_message = f"Your reminder just fired: {reminder['message']}"

    from agents.tool_loader import load_integration_tools, build_agent_handlers, INTEGRATION_MODULES
    from agents.engine import build_agent_config
    from integrations.registry import is_enabled as _is_enabled, get_tool_mode
    from integrations.google.policy import google_capabilities
    from core.agents.tool_registry import ToolRegistry
    from core.agents.tool_definitions import get_tool_definitions
    from core.agents.tools.real_tools import load_all_real_tools
    from pathlib import Path

    config = build_agent_config(agent)
    google_connected = _is_enabled("google")
    integration_tool_defs, integration_executors = load_integration_tools()
    google_caps = google_capabilities()
    reminder_handlers, sa_handlers = build_agent_handlers(agent["slug"])

    real_tools_dir = str(Path(config.context_dir).parent / "real_tools")
    dynamic_real_tools = load_all_real_tools(real_tools_dir)

    tool_defs = get_tool_definitions(
        integration_tools=integration_tool_defs,
        dynamic_real_tools=dynamic_real_tools or None,
        web_enabled=True,
        **google_caps,
    )

    integration_modes = {name: get_tool_mode(name) for name in INTEGRATION_MODULES}
    tool_defs = [
        t for t in tool_defs
        if not (t.get("integration") and t.get("writes")
                and integration_modes.get(t["integration"]) == "read-only")
    ]

    registry = ToolRegistry(
        context_dir=config.context_dir,
        gcs_prefix=config.gcs_prefix,
        google_connected=google_connected,
        integration_executors=integration_executors,
        agent_slug=agent["slug"],
        agent_name=config.agent_name,
        reminder_handlers=reminder_handlers,
        scheduled_action_handlers=sa_handlers,
    )

    try:
        result = run_background_turn(
            system_prompt=system_prompt,
            user_message=user_message,
            tool_defs=tool_defs,
            registry=registry,
            max_iterations=_MAX_TOOL_ITERATIONS,
        )
        service.mark_fired(reminder["id"], f"processed: {result.text[:500]}")
        logger.info("Self-reminder %s processed: %s", reminder["id"], result.text[:200])
    except Exception as e:
        logger.error("Self-reminder %s background turn failed: %s", reminder["id"], e)
        service.mark_fired(reminder["id"], f"error: {e}")
