"""Chatty — Scheduled actions parallel processor.

Called periodically by APScheduler to execute due heartbeats and cron jobs.
Uses a ThreadPoolExecutor for parallel execution with atomic claim/lease
to prevent duplicate work across overlapping ticks.
"""

import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from zoneinfo import ZoneInfo

from core.agents.background_runner import run_background_turn
from core.agents.tool_registry import ToolRegistry
from core.agents.tool_definitions import get_tool_definitions

from . import history, notifications, service

logger = logging.getLogger(__name__)

_MAX_WORKERS = int(os.environ.get("SCHEDULED_ACTION_WORKERS", "4"))
_executor = ThreadPoolExecutor(max_workers=_MAX_WORKERS, thread_name_prefix="heartbeat")

# -- In-flight tracking --------------------------------------------------
_in_flight_count = 0
_in_flight_agents: set[str] = set()
_in_flight_lock = threading.Lock()


def _get_available_capacity() -> int:
    with _in_flight_lock:
        return max(_MAX_WORKERS - _in_flight_count, 0)


def _get_in_flight_agents() -> set[str]:
    with _in_flight_lock:
        return _in_flight_agents.copy()


def _worker_started(agent: str) -> None:
    global _in_flight_count
    with _in_flight_lock:
        _in_flight_count += 1
        _in_flight_agents.add(agent)


def _worker_finished(agent: str) -> None:
    global _in_flight_count
    with _in_flight_lock:
        _in_flight_count = max(_in_flight_count - 1, 0)
        _in_flight_agents.discard(agent)


# -- Tick-gap monitoring --------------------------------------------------
_last_tick_time: float | None = None


def process_due_actions() -> None:
    """Claim due actions, submit to thread pool, return immediately."""
    global _last_tick_time
    tick_start = time.monotonic()

    if _last_tick_time is not None:
        gap = tick_start - _last_tick_time
        if gap > 90:
            logger.warning("TICK GAP: %.1fs since last tick (expected ~60s)", gap)
    _last_tick_time = tick_start

    available = _get_available_capacity()
    if available == 0:
        logger.debug("Tick: pool full (%d workers) — skipping claim", _MAX_WORKERS)
        return

    try:
        claimed = service.claim_due_actions(
            available_capacity=available,
            exclude_agents=_get_in_flight_agents(),
        )
    except Exception as e:
        logger.error("Failed to claim due actions: %s", e)
        return

    if not claimed:
        return

    submitted = 0
    for action in claimed:
        lease_id = action.get("lease_id")

        if action.get("consecutive_errors", 0) >= 5:
            service.mark_executed(action["id"], "error", "auto-disabled: consecutive_errors >= 5", 0, lease_id=lease_id)
            continue

        if not action.get("always_on") and not _in_active_hours(action):
            service.release_lease(action["id"], lease_id, advance_next_run=True)
            continue

        _worker_started(action["agent"])
        try:
            _executor.submit(_process_action_safe, action)
            submitted += 1
        except Exception as e:
            logger.error("Failed to submit action %s: %s", action["id"][:8], e)
            _worker_finished(action["agent"])
            service.release_lease(action["id"], lease_id)

    if submitted:
        logger.info(
            "Tick: claimed %d, submitted %d (in-flight: %d/%d)",
            len(claimed), submitted, _MAX_WORKERS - _get_available_capacity(), _MAX_WORKERS,
        )


def _in_active_hours(action: dict) -> bool:
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

    if start_minutes <= end_minutes:
        return start_minutes <= current_minutes < end_minutes
    else:
        return current_minutes >= start_minutes or current_minutes < end_minutes


def _process_action_safe(action: dict) -> None:
    """Worker entry point: renew lease, run action, track in-flight state."""
    agent_name = action["agent"]
    lease_id = action.get("lease_id")

    if lease_id:
        if not service.renew_lease(action["id"], lease_id):
            logger.warning("Lease lost before worker started for %s/%s", agent_name, action["id"][:8])
            _worker_finished(agent_name)
            return

    try:
        _process_action(action)
    except Exception as e:
        logger.error("Action %s/%s failed: %s", agent_name, action["id"][:8], e)
        completed = service.mark_executed(action["id"], "error", f"unhandled: {e}", 0, lease_id=lease_id)
        if not completed:
            logger.warning("Lease expired for %s/%s — error result discarded", agent_name, action["id"][:8])
    finally:
        _worker_finished(agent_name)


def _process_action(action: dict) -> None:
    """Dispatch to type-specific handler."""
    action_type = action["action_type"]
    if action_type == "heartbeat":
        _process_heartbeat(action)
    elif action_type == "cron":
        _process_cron(action)
    else:
        service.mark_executed(action["id"], "skipped", f"unknown action_type: {action_type}", 0, lease_id=action.get("lease_id"))


def _resolve_agent(agent_slug: str) -> dict | None:
    """Resolve agent row from DB."""
    from agents import db as agent_db
    agents = agent_db.list_agents()
    for a in agents:
        if a["slug"] == agent_slug:
            return a
    return None


def _process_heartbeat(action: dict) -> None:
    """Process heartbeat: read HEARTBEAT.md, optional triage, full execution."""
    agent_slug = action["agent"]
    lease_id = action.get("lease_id")

    agent = _resolve_agent(agent_slug)
    if not agent:
        service.mark_executed(action["id"], "error", f"Agent '{agent_slug}' not found", 0, lease_id=lease_id)
        return

    from agents.engine import get_context_manager, DATA_DIR
    ctx_manager = get_context_manager(agent["slug"])

    # Read HEARTBEAT.md
    heartbeat_path = ctx_manager.data_dir / "HEARTBEAT.md"
    checklist = ""
    if heartbeat_path.exists():
        try:
            checklist = heartbeat_path.read_text(encoding="utf-8").strip()
        except Exception as e:
            logger.warning("Failed to read HEARTBEAT.md for %s: %s", agent_slug, e)

    if not checklist or _is_effectively_empty(checklist):
        service.mark_executed(action["id"], "skipped", "no checklist content", 0, lease_id=lease_id)
        return

    execution_id = history.record_start(action["id"], agent_slug, "heartbeat")
    provider_override = agent.get("provider_override") or None
    model_override = action.get("model_override") or agent.get("model_override") or None

    tz_name = action.get("active_hours_tz") or "America/Chicago"
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("America/Chicago")
    now_local = datetime.now(tz)
    now_str = now_local.strftime(f"%Y-%m-%d %I:%M %p {now_local.strftime('%Z')}")

    context = ctx_manager.load_all_context()
    context_snippet = context[:30000] if context else "(no context files)"

    tool_defs = get_tool_definitions(web_enabled=True)
    registry = ToolRegistry(
        context_dir=str(DATA_DIR / agent["slug"] / "context"),
        agent_slug=agent["slug"],
    )

    start_time = time.monotonic()
    try:
        # Optional triage pass
        triage_data = None
        if action.get("triage_enabled", 1):
            triage_result = run_background_turn(
                system_prompt=(
                    f"You are {agent['agent_name']}.\n\n"
                    f"# Quick Heartbeat Triage\n\n"
                    f"Quickly check the following items using your tools. "
                    f"Respond with ONLY one of:\n"
                    f"- NEEDS_ACTION: <brief reason>\n"
                    f"- ALL_CLEAR\n\n"
                    f"## Checklist\n\n{checklist}\n"
                ),
                user_message="Quick triage check — anything need attention?",
                tool_defs=tool_defs,
                registry=registry,
                max_iterations=2,
                provider_override=provider_override,
                model_override=model_override,
            )
            triage_data = {
                "result": "NEEDS_ACTION" if "NEEDS_ACTION" in triage_result.text.upper() else "ALL_CLEAR",
                "model": triage_result.model_used,
                "input_tokens": triage_result.input_tokens,
                "output_tokens": triage_result.output_tokens,
            }
            if "NEEDS_ACTION" not in triage_result.text.upper():
                duration_ms = int((time.monotonic() - start_time) * 1000)
                service.mark_executed(
                    action["id"], "ok", "Triage: all clear", duration_ms,
                    triage_result.input_tokens, triage_result.output_tokens, lease_id=lease_id,
                )
                history.record_complete(
                    execution_id, status="ok",
                    result_summary="Triage: all clear",
                    result_full="Triage returned ALL_CLEAR — skipping full check.",
                    tool_calls=[{"triage": triage_data}],
                    model_used=triage_result.model_used,
                    input_tokens=triage_result.input_tokens,
                    output_tokens=triage_result.output_tokens,
                    duration_ms=duration_ms,
                )
                logger.info("Heartbeat %s: triage ALL_CLEAR (%dms)", agent_slug, duration_ms)
                return

        # Full execution
        system_prompt = (
            f"You are {agent['agent_name']}.\n\n"
            f"# Heartbeat Check — {now_str}\n\n"
            f"You are performing a periodic heartbeat check. Review your checklist "
            f"and check each item against current data using your tools.\n\n"
            f"## Your Checklist\n\n{checklist}\n\n"
            f"## Your Knowledge (abbreviated)\n\n{context_snippet}\n\n"
            f"## Rules\n\n"
            f"- If everything is normal and no action is needed, respond with exactly: HEARTBEAT_OK\n"
            f"- If something needs attention, take action and respond with: ACTION_TAKEN: <brief description>\n"
            f"- Be concise. This is an automated check, not a conversation.\n"
        )

        result = run_background_turn(
            system_prompt=system_prompt,
            user_message="Perform your heartbeat check now.",
            tool_defs=tool_defs,
            registry=registry,
            max_iterations=action.get("max_tool_iterations", 5),
            provider_override=provider_override,
            model_override=model_override,
        )
        duration_ms = int((time.monotonic() - start_time) * 1000)

        # Classification
        if result.error:
            status = "error"
        elif "HEARTBEAT_OK" in result.text.upper():
            status = "ok"
        elif "ACTION_TAKEN:" in result.text.upper():
            status = "action_taken"
        else:
            status = "ok"

        total_inp = result.input_tokens + (triage_data["input_tokens"] if triage_data else 0)
        total_out = result.output_tokens + (triage_data["output_tokens"] if triage_data else 0)
        full_tool_log = ([{"triage": triage_data}] if triage_data else []) + result.tool_log

        service.mark_executed(
            action["id"], status, result.text[:2000], duration_ms, total_inp, total_out, lease_id=lease_id,
        )

        notified = notifications.evaluate_and_notify(action, status, result.text[:300], agent_slug)

        history.record_complete(
            execution_id, status=status,
            result_summary=result.text[:500],
            result_full=result.text,
            tool_calls=full_tool_log,
            model_used=result.model_used,
            input_tokens=total_inp,
            output_tokens=total_out,
            duration_ms=duration_ms,
            notification_sent=notified,
        )
        logger.info("Heartbeat %s: %s (%dms, tools: %d)", agent_slug, status, duration_ms, len(result.tool_log))

    except Exception as e:
        duration_ms = int((time.monotonic() - start_time) * 1000)
        logger.error("Heartbeat %s failed: %s", agent_slug, e)
        service.mark_executed(action["id"], "error", str(e)[:2000], duration_ms, lease_id=lease_id)
        history.record_complete(execution_id, status="error", result_summary=str(e)[:500], result_full=str(e), duration_ms=duration_ms)


def _process_cron(action: dict) -> None:
    """Process a cron scheduled action."""
    agent_slug = action["agent"]
    lease_id = action.get("lease_id")
    prompt = action.get("prompt", "")
    if not prompt:
        service.mark_executed(action["id"], "skipped", "no prompt configured", 0, lease_id=lease_id)
        return

    agent = _resolve_agent(agent_slug)
    if not agent:
        service.mark_executed(action["id"], "error", f"Agent '{agent_slug}' not found", 0, lease_id=lease_id)
        return

    execution_id = history.record_start(action["id"], agent_slug, "cron")

    from agents.engine import get_context_manager, DATA_DIR
    ctx_manager = get_context_manager(agent["slug"])
    context = ctx_manager.load_all_context()
    context_snippet = context[:30000] if context else "(no context files)"

    provider_override = agent.get("provider_override") or None
    model_override = action.get("model_override") or agent.get("model_override") or None

    system_prompt = (
        f"You are {agent['agent_name']}.\n\n"
        f"# Scheduled Action: {action.get('name', 'Unnamed')}\n\n"
        f"{prompt}\n\n"
        f"# Your Knowledge (abbreviated)\n\n{context_snippet}\n\n"
        f"Take appropriate action using your tools. Be concise."
    )

    tool_defs = get_tool_definitions(web_enabled=True)
    registry = ToolRegistry(
        context_dir=str(DATA_DIR / agent["slug"] / "context"),
        agent_slug=agent["slug"],
    )

    start_time = time.monotonic()
    try:
        result = run_background_turn(
            system_prompt=system_prompt,
            user_message=f"Execute scheduled action: {action.get('name', prompt[:100])}",
            tool_defs=tool_defs,
            registry=registry,
            max_iterations=action.get("max_tool_iterations", 5),
            provider_override=provider_override,
            model_override=model_override,
        )
        duration_ms = int((time.monotonic() - start_time) * 1000)

        status = "error" if result.error else "ok"
        service.mark_executed(
            action["id"], status, result.text[:2000], duration_ms,
            result.input_tokens, result.output_tokens, lease_id=lease_id,
        )
        history.record_complete(
            execution_id, status=status,
            result_summary=result.text[:500],
            result_full=result.text,
            tool_calls=result.tool_log,
            model_used=result.model_used,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            duration_ms=duration_ms,
        )
        logger.info("Cron %s/%s: %s (%dms)", agent_slug, action["id"][:8], status, duration_ms)
    except Exception as e:
        duration_ms = int((time.monotonic() - start_time) * 1000)
        logger.error("Cron %s failed: %s", agent_slug, e)
        service.mark_executed(action["id"], "error", str(e)[:2000], duration_ms, lease_id=lease_id)
        history.record_complete(execution_id, status="error", result_summary=str(e)[:500], result_full=str(e), duration_ms=duration_ms)


def _is_effectively_empty(content: str) -> bool:
    for line in content.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            continue
        if stripped.startswith("<!--") and stripped.endswith("-->"):
            continue
        return False
    return True


def get_executor_stats() -> dict:
    with _in_flight_lock:
        return {
            "max_workers": _MAX_WORKERS,
            "in_flight": _in_flight_count,
            "in_flight_agents": sorted(_in_flight_agents),
            "available": max(_MAX_WORKERS - _in_flight_count, 0),
            "last_tick_gap_s": round(time.monotonic() - _last_tick_time, 1) if _last_tick_time else None,
        }


def run_action_now_with_tracking(action_id: str) -> dict | None:
    """Manual trigger with lease tracking. Returns updated action or None."""
    global _in_flight_count

    action_row = service.get_action(action_id)
    if not action_row:
        return None

    agent_name = action_row["agent"]

    with _in_flight_lock:
        if agent_name in _in_flight_agents:
            raise RuntimeError(f"Agent '{agent_name}' already has a worker in flight")
        _in_flight_count += 1
        _in_flight_agents.add(agent_name)

    action = None
    try:
        action = service.claim_single_action(action_id)
        if not action:
            raise RuntimeError("Action is currently being processed")
        _process_action(action)
    except Exception:
        if action:
            lease_id = action.get("lease_id")
            completed = service.mark_executed(action["id"], "error", "manual run failed", 0, lease_id=lease_id)
            if not completed and lease_id:
                service.release_lease(action["id"], lease_id)
        raise
    finally:
        _worker_finished(agent_name)

    return service.get_action(action_id)


def shutdown_executor() -> None:
    _executor.shutdown(wait=False, cancel_futures=True)
