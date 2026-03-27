"""Chatty — Scheduled actions processor.

Called periodically by APScheduler to process due scheduled actions.
Uses the provider-agnostic background_runner for AI execution.
"""

import logging
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from . import service
from core.agents.background_runner import run_background_turn
from core.agents.tool_registry import ToolRegistry
from core.agents.tool_definitions import get_tool_definitions

logger = logging.getLogger(__name__)

_MAX_PER_TICK = 5


def _in_active_hours(action: dict) -> bool:
    """Check if the current time is within the action's active hours window."""
    tz_name = action.get("active_hours_tz", "America/Chicago")
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("America/Chicago")

    now = datetime.now(tz)
    start_str = action.get("active_hours_start", "06:00")
    end_str = action.get("active_hours_end", "20:00")

    try:
        start_h, start_m = map(int, str(start_str).split(":"))
        end_h, end_m = map(int, str(end_str).split(":"))
    except (ValueError, TypeError):
        start_h, start_m = 6, 0
        end_h, end_m = 20, 0

    current_minutes = now.hour * 60 + now.minute
    start_minutes = start_h * 60 + start_m
    end_minutes = end_h * 60 + end_m

    # Handle overnight windows (e.g., 22:00 - 06:00)
    if start_minutes <= end_minutes:
        return start_minutes <= current_minutes < end_minutes
    else:
        return current_minutes >= start_minutes or current_minutes < end_minutes


def process_due_actions() -> None:
    """Process due scheduled actions. Called by APScheduler every 60s."""
    try:
        due = service.get_due_actions()
    except Exception as e:
        logger.error("Failed to query due actions: %s", e)
        return

    if not due:
        return

    processed = 0
    for action in due[:_MAX_PER_TICK]:
        if not _in_active_hours(action):
            # Reschedule without running
            service.mark_executed(
                action["id"], "skipped", "Outside active hours",
            )
            continue

        try:
            _process_action(action)
            processed += 1
        except Exception as e:
            logger.error("Failed to process action %s: %s", action["id"], e)
            service.mark_executed(
                action["id"], "error", f"error: {e}",
            )

    if processed:
        logger.info("Processed %d due scheduled actions", processed)


def _process_action(action: dict) -> None:
    """Process a single scheduled action by running a background AI turn."""
    agent_slug = action["agent"]
    t_start = time.time()

    # Resolve agent
    from agents.engine import get_context_manager, DATA_DIR
    from agents import db as agent_db

    agents = agent_db.list_agents()
    agent = None
    for a in agents:
        if a["slug"] == agent_slug:
            agent = a
            break

    if not agent:
        service.mark_executed(
            action["id"], "error", f"Agent '{agent_slug}' not found",
        )
        return

    ctx_manager = get_context_manager(agent["slug"])
    context = ctx_manager.load_all_context()
    context_snippet = context[:30000] if context else "(no context files)"

    system_prompt = (
        f"You are {agent['agent_name']}, a helpful AI assistant.\n\n"
        f"# Scheduled Action: {action['name']}\n\n"
        f"{action.get('description', '')}\n\n"
        f"# Your Knowledge (abbreviated)\n\n{context_snippet}\n\n"
        f"Execute the requested action using your tools. Be thorough but concise."
    )

    user_message = action.get("prompt", "Run your scheduled task.")

    tool_defs = get_tool_definitions(web_enabled=True)
    registry = ToolRegistry(
        context_dir=str(DATA_DIR / agent["slug"] / "context"),
        agent_slug=agent["slug"],
    )

    max_iters = action.get("max_tool_iterations", 5)
    model = action.get("model_override")

    try:
        result = run_background_turn(
            system_prompt=system_prompt,
            user_message=user_message,
            tool_defs=tool_defs,
            registry=registry,
            max_iterations=max_iters,
            model_override=model,
        )
        duration_ms = int((time.time() - t_start) * 1000)
        service.mark_executed(
            action["id"], "ok", result.text[:2000],
            duration_ms=duration_ms,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
        )
        logger.info("Action %s (%s) completed in %dms", action["id"], action["name"], duration_ms)
    except Exception as e:
        duration_ms = int((time.time() - t_start) * 1000)
        logger.error("Action %s failed: %s", action["id"], e)
        service.mark_executed(
            action["id"], "error", f"error: {e}",
            duration_ms=duration_ms,
        )
