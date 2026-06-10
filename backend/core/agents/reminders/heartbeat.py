"""Chatty — Reminder heartbeat.

Called periodically by APScheduler to process due reminders.
Self-reminders trigger a background AI turn so the agent can act.
"""

import logging

from . import service
from .notifications import notify_reminder_fired
from core.agents.background_runner import run_background_turn
from core.agents.security.delimiters import DELIMITER_SYSTEM_INSTRUCTION

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
    agent_slug = reminder["agent"]

    # Resolve agent config
    from agents.engine import get_context_manager
    from agents import db as agent_db

    # Find agent by slug (reminder stores agent slug)
    agents = agent_db.list_agents()
    agent = None
    for a in agents:
        if a["slug"] == agent_slug:
            agent = a
            break

    if not agent:
        service.mark_fired(reminder["id"], f"error: agent '{agent_slug}' not found")
        return

    ctx_manager = get_context_manager(agent["slug"])
    context = ctx_manager.load_all_context()
    context_snippet = context[:30000] if context else "(no context files)"

    from agents.tool_loader import format_current_time
    date_str, time_str = format_current_time()

    recurrence_line = ""
    if reminder.get("recurrence_rule"):
        recurrence_line = "- **Recurrence:** This is a recurring reminder.\n"

    user_message = f"Your reminder just fired: {reminder['message']}"

    from agents.tool_loader import load_integration_tools, build_agent_handlers, INTEGRATION_MODULES
    from agents.engine import build_agent_config
    from integrations.registry import get_tool_mode, list_google_accounts as _list_ga
    from integrations.google.policy import google_capabilities_union
    from core.agents.tool_registry import ToolRegistry
    from core.agents.tool_definitions import get_tool_definitions
    from core.agents.tools.real_tools import load_all_real_tools
    from pathlib import Path

    config = build_agent_config(agent)
    ga = config.google_accounts
    gmail_ids = ga.get("gmail", [])
    calendar_ids = ga.get("calendar", [])
    drive_ids = ga.get("drive", [])
    google_connected = bool(gmail_ids or calendar_ids or drive_ids)

    all_ga = _list_ga()
    account_info_map = {
        aid: {"email": a.get("email", ""), "scope_grants": a.get("scope_grants", {}), "connection_status": a.get("connection_status", "ok")}
        for aid, a in all_ga.items()
    }

    integration_tool_defs, integration_executors = load_integration_tools()
    gmail_caps = google_capabilities_union(gmail_ids)
    cal_caps = google_capabilities_union(calendar_ids)
    drive_caps = google_capabilities_union(drive_ids)
    reminder_handlers, sa_handlers = build_agent_handlers(agent["slug"])

    real_tools_dir = str(Path(config.context_dir).parent / "real_tools")
    dynamic_real_tools = load_all_real_tools(real_tools_dir)

    tool_defs = get_tool_definitions(
        integration_tools=integration_tool_defs,
        dynamic_real_tools=dynamic_real_tools or None,
        web_enabled=True,
        gmail_read_enabled=gmail_caps["gmail_read_enabled"],
        gmail_send_enabled=gmail_caps["gmail_send_enabled"],
        calendar_read_enabled=cal_caps["calendar_read_enabled"],
        calendar_write_enabled=cal_caps["calendar_write_enabled"],
        drive_read_enabled=drive_caps["drive_read_enabled"],
        drive_write_enabled=drive_caps["drive_write_enabled"],
        multi_gmail=len(gmail_ids) > 1,
        multi_calendar=len(calendar_ids) > 1,
        multi_drive=len(drive_ids) > 1,
        background_mode=True,
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
        gmail_account_ids=gmail_ids,
        calendar_account_ids=calendar_ids,
        drive_account_ids=drive_ids,
        account_info_map=account_info_map,
    )

    from core.agents.ai_service import _google_accounts_context
    ga_ctx = _google_accounts_context(account_info_map, ga)
    system_prompt = (
        (
            f"You are {agent['agent_name']}, a helpful AI assistant.\n\n"
            + (f"{ga_ctx}\n\n" if ga_ctx else "")
            + f"# Reminder Triggered\n\n"
            f"A reminder you set has fired. Take appropriate action.\n\n"
            f"- **Message:** {reminder['message']}\n"
            f"- **Context:** {reminder.get('context') or 'None'}\n"
            f"- **Originally set at:** {reminder['created_at']}\n"
            f"{recurrence_line}\n"
            f"# Your Knowledge (abbreviated)\n\n{context_snippet}\n\n"
            + DELIMITER_SYSTEM_INSTRUCTION + "\n\n"
        ),
        (
            f"# Current Date & Time\n\n"
            f"- Date: {date_str}\n"
            f"- Time: {time_str}\n\n"
            f"Take any appropriate action using your tools. Be concise.\n"
            f"Use `notify_user` to alert the user about important findings or actions taken."
        ),
    )

    try:
        result = run_background_turn(
            system_prompt=system_prompt,
            user_message=user_message,
            tool_defs=tool_defs,
            registry=registry,
            max_iterations=_MAX_TOOL_ITERATIONS,
            model_tier=config.model_tier,
        )
        service.mark_fired(reminder["id"], f"processed: {result.text[:500]}")
        _schedule_next_if_recurring(reminder)
        try:
            notify_reminder_fired(reminder, result.text[:300], agent_slug, error=result.error)
        except Exception as ne:
            logger.warning("Notification failed for reminder %s: %s", reminder["id"], ne)
        logger.info("Self-reminder %s processed: %s", reminder["id"], result.text[:200])
    except Exception as e:
        logger.error("Self-reminder %s background turn failed: %s", reminder["id"], e)
        service.mark_fired(reminder["id"], f"error: {e}")
        _schedule_next_if_recurring(reminder)
        try:
            notify_reminder_fired(reminder, str(e)[:300], agent_slug, error=True)
        except Exception as ne:
            logger.warning("Error notification failed for reminder %s: %s", reminder["id"], ne)


def _schedule_next_if_recurring(reminder: dict) -> None:
    """If this is a recurring reminder, create the next pending occurrence."""
    if not reminder.get("recurrence_rule"):
        return
    try:
        next_rem = service.create_next_occurrence(reminder)
        if next_rem and next_rem.get("ok"):
            logger.info(
                "Recurring reminder %s: next occurrence %s at %s",
                reminder["id"], next_rem["id"], next_rem["due_at"],
            )
        elif next_rem:
            logger.warning("Failed to create next occurrence for %s: %s", reminder["id"], next_rem)
    except Exception as e:
        logger.error("Error scheduling next occurrence for %s: %s", reminder["id"], e)
