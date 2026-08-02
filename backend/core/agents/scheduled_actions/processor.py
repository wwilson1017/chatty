"""Chatty — Scheduled actions parallel processor.

Called periodically by APScheduler to execute due heartbeats and cron jobs.
Uses a ThreadPoolExecutor for parallel execution with atomic claim/lease
to prevent duplicate work across overlapping ticks.
"""

import json
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from core.agents.background_runner import run_background_turn
from core.agents.tool_registry import ToolRegistry
from core.agents.tool_definitions import get_tool_definitions
from core.agents.security.delimiters import DELIMITER_SYSTEM_INSTRUCTION
from core.todo.coaching import gtd_coaching_block

from . import history, notifications, service

logger = logging.getLogger(__name__)

_MAX_WORKERS = int(os.environ.get("SCHEDULED_ACTION_WORKERS", "4"))
_executor = ThreadPoolExecutor(max_workers=_MAX_WORKERS, thread_name_prefix="heartbeat")

_AGENT_TURN_ERRORS = frozenset({
    "(lease lost -- aborted)",
    "(no response)",
    "(max iterations reached)",
})

# Marker the model emits to suppress auto-delivery of a cron run's output
# (Hermes-style). When a cron's final response is exactly this, nothing is sent.
SILENT_MARKER = "[SILENT]"


def _delivered_via_tool(tool_log: list) -> bool:
    """True only if a notify_user/post_message call actually SUCCEEDED this run.

    Checks the tool RESULT, not just the tool name: a notify_user entry can be a
    failure — rejected by the write budget / hourly rate limit (background_runner)
    or an arg/error return (tool_registry). Conservative on unparseable results:
    treat as NOT delivered so the auto-fallback fires (a possible duplicate beats
    a silent miss). Both notify_user and post_message return {"ok": True, ...} on
    success and {"error": ...} on failure.
    """
    for tc in tool_log:
        if tc.get("tool") not in ("notify_user", "post_message"):
            continue
        try:
            res = json.loads(tc.get("result") or "")
        except (ValueError, TypeError):
            continue
        if isinstance(res, dict) and res.get("ok") is True:
            return True
    return False


# Status marker a heartbeat emits when it has something to report. HEARTBEAT_OK is
# its silent marker (OpenClaw uses the same token). Delivery is guaranteed unless
# the run went silent — see scheduled-action-guaranteed-delivery solution doc.
_ACTION_MARKER = "ACTION_TAKEN:"


def _strip_action_marker(text: str) -> str:
    """Return the heartbeat report body with the ACTION_TAKEN: marker removed, so
    the delivered notification reads cleanly (mirrors OpenClaw's stripHeartbeatToken).
    Falls back to the full text if nothing follows the marker."""
    s = text.strip()
    idx = s.upper().find(_ACTION_MARKER)
    if idx == -1:
        return s
    return s[idx + len(_ACTION_MARKER):].strip() or s

# Triage classifier model is resolved via tiers.get_triage_classifier()
# (override -> inferred -> hardcoded), unifying what used to be a separate,
# drift-prone _TRIAGE_MODELS map here.

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

        if action.get("consecutive_errors", 0) >= service.AUTO_DISABLE_THRESHOLD:
            _mark_and_alert(action, "error", f"auto-disabled: consecutive_errors >= {service.AUTO_DISABLE_THRESHOLD}", 0, lease_id=lease_id, agent_slug=action["agent"])
            continue

        if not _within_active_hours(action):
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


# -- Helpers ---------------------------------------------------------------

def _within_active_hours(action: dict) -> bool:
    if action.get("always_on"):
        return True

    start_str = action.get("active_hours_start")
    end_str = action.get("active_hours_end")
    if not start_str or not end_str:
        return True
    if start_str == "00:00" and end_str == "23:59":
        return True

    tz_name = action.get("active_hours_tz") or "America/Chicago"
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        return True

    now = datetime.now(tz)
    try:
        start_h, start_m = map(int, str(start_str).split(":"))
        end_h, end_m = map(int, str(end_str).split(":"))
    except (ValueError, TypeError):
        return True

    current_minutes = now.hour * 60 + now.minute
    start_minutes = start_h * 60 + start_m
    end_minutes = end_h * 60 + end_m

    if start_minutes <= end_minutes:
        return start_minutes <= current_minutes < end_minutes
    else:
        return current_minutes >= start_minutes or current_minutes < end_minutes


def _build_tools(agent_slug: str, agent: dict, *, background_mode: bool = False) -> tuple[list[dict], ToolRegistry, dict]:
    """Build full tool definitions and registry with integration parity.

    Returns (tool_defs, registry, account_info_map).
    """
    from agents.tool_loader import load_integration_tools, build_agent_handlers, INTEGRATION_MODULES
    from agents.engine import build_agent_config
    from integrations.registry import get_tool_mode, list_google_accounts as _list_ga
    from integrations.google.policy import google_capabilities_union
    from core.agents.tools.real_tools import load_all_real_tools

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
    reminder_handlers, sa_handlers = build_agent_handlers(agent_slug)

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
        background_mode=background_mode,
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
        agent_slug=agent_slug,
        agent_name=config.agent_name,
        reminder_handlers=reminder_handlers,
        scheduled_action_handlers=sa_handlers,
        gmail_account_ids=gmail_ids,
        calendar_account_ids=calendar_ids,
        drive_account_ids=drive_ids,
        account_info_map=account_info_map,
    )

    return tool_defs, registry, account_info_map


def _make_lease_renewer(action_id: str, lease_id: str | None):
    if not lease_id:
        return None
    def _renew(_iteration: int) -> bool:
        return service.renew_lease(action_id, lease_id)
    return _renew


def _mark_and_alert(action, status, result, duration_ms, input_tokens=0, output_tokens=0, lease_id=None, agent_slug=""):
    """Wrapper: mark_executed + failure alert evaluation (lock-safe)."""
    completed = service.mark_executed(
        action["id"], status, result, duration_ms, input_tokens, output_tokens, lease_id=lease_id,
    )
    if completed and status == "error":
        old_errors = action.get("consecutive_errors", 0)
        new_errors = old_errors + 1
        if new_errors >= notifications.FAILURE_ALERT_THRESHOLD:
            try:
                notifications.evaluate_failure_alert(action, new_errors, result, agent_slug)
            except Exception as e:
                logger.debug("Failure alert check failed: %s", e)
    return completed


def _build_error_context(action: dict, agent_slug: str) -> str:
    """Build error context for heartbeat system prompt based on consecutive errors."""
    consecutive_errors = action.get("consecutive_errors", 0)
    if consecutive_errors == 0:
        return ""

    last_result = action.get("last_result", "")
    if consecutive_errors >= 3:
        recent_errors = history.get_recent_errors(agent_slug, action_id=action["id"], limit=3)
        error_lines = []
        for err in recent_errors:
            error_lines.append(f"  - [{err['started_at']}] {err.get('result_summary', '')[:200]}")
        return (
            f"\n\n## Recent Failures\n\n"
            f"This check has failed {consecutive_errors} times consecutively. "
            f"Diagnose the root cause rather than retrying the same approach.\n\n"
            f"Recent errors:\n" + "\n".join(error_lines) + "\n"
        )
    else:
        return (
            f"\n\n## Note\n\n"
            f"This check failed {consecutive_errors} time(s) recently. "
            f"Last error: {last_result[:200]}\n"
        )


# -- Action processors -----------------------------------------------------

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
        completed = _mark_and_alert(action, "error", f"unhandled: {e}", 0, lease_id=lease_id, agent_slug=agent_name)
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
        _mark_and_alert(action, "skipped", f"unknown action_type: {action_type}", 0, lease_id=action.get("lease_id"), agent_slug=action["agent"])


def _resolve_triage_provider(agent: dict) -> str:
    """Return provider type for triage model lookup, or '' if cheap triage is not applicable."""
    from core.providers.credentials import CredentialStore
    store = CredentialStore()
    profile_name, profile = store.get_active_profile(
        provider_override=agent.get("provider_override") or None
    )
    if not profile:
        return ""
    if profile.get("type") == "chatgpt_oauth":
        return ""
    return profile_name.split(":", 1)[0]


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
        _mark_and_alert(action, "error", f"Agent '{agent_slug}' not found", 0, lease_id=lease_id, agent_slug=agent_slug)
        return

    from agents.engine import get_context_manager
    ctx_manager = get_context_manager(agent["slug"])

    heartbeat_path = ctx_manager.data_dir / "HEARTBEAT.md"
    checklist = ""
    if heartbeat_path.exists():
        try:
            checklist = heartbeat_path.read_text(encoding="utf-8").strip()
        except Exception as e:
            logger.warning("Failed to read HEARTBEAT.md for %s: %s", agent_slug, e)

    # Inferred follow-ups due for a check-in ride this heartbeat. Peeked (not
    # marked) here: an empty checklist normally skips the heartbeat, but due
    # follow-ups are work of their own and force a full run even with no
    # checklist. The surfacing budget is only consumed right before the full
    # run is committed to execute (after triage and the lease re-check).
    followups = []
    try:
        from core.agents.memory.commitments import (
            claim_followups_for_surfacing, format_followups_block, peek_due_followups,
        )
        followups = peek_due_followups(agent_slug)
    except Exception as e:
        logger.warning("Heartbeat %s: commitment follow-ups skipped: %s", agent_slug, e)

    followups_only_run = False
    if not checklist or _is_effectively_empty(checklist):
        if not followups:
            _mark_and_alert(action, "skipped", "no checklist content", 0, lease_id=lease_id, agent_slug=agent_slug)
            return
        followups_only_run = True
        checklist = "(no checklist items — this run is for the inferred follow-ups below)"

    execution_id = None
    try:
        execution_id = history.record_start(action["id"], agent_slug, "heartbeat")
    except Exception as e:
        logger.error("Failed to record heartbeat start for %s: %s", agent_slug, e)
    provider_override = agent.get("provider_override") or None
    model_override = action.get("model_override") or agent.get("model_override") or None

    tz_name = action.get("active_hours_tz") or "America/Chicago"
    from agents.tool_loader import format_current_time
    date_str, time_str = format_current_time(tz_name)

    context = ctx_manager.load_all_context()
    context_snippet = context[:30000] if context else "(no context files)"

    tool_defs, registry, account_info_map = _build_tools(agent_slug, agent, background_mode=True)
    on_iteration = _make_lease_renewer(action["id"], lease_id)

    from core.agents.ai_service import _google_accounts_context
    from agents.engine import build_agent_config as _bac
    _cfg = _bac(agent)
    ga_ctx = _google_accounts_context(account_info_map, _cfg.google_accounts)

    start_time = time.monotonic()
    try:
        triage_data = None

        from core.admin_settings import load_admin_settings
        admin = load_admin_settings()
        triage_mode = admin["triage_mode"]

        triage_model_override = model_override
        cheap_model = None
        if triage_mode in ("cheap", "always_cheap"):
            from core.providers.tiers import get_triage_classifier
            cheap_model = get_triage_classifier(_resolve_triage_provider(agent))
            if cheap_model:
                triage_model_override = cheap_model

        if triage_mode == "always_cheap" and cheap_model:
            do_triage = True
        else:
            do_triage = bool(action.get("triage_enabled", 1))

        if followups:
            # Due follow-ups always warrant a full run; triage can't see them.
            do_triage = False

        if do_triage:
            triage_result = run_background_turn(
                system_prompt=(
                    f"You are {agent['agent_name']}.\n\n"
                    + (f"{ga_ctx}\n\n" if ga_ctx else "")
                    + f"# Heartbeat Triage — {date_str}, {time_str}\n\n"
                    f"Look at the checklist items below and their time conditions. "
                    f"Based on the current date and time ({date_str}, {time_str}), "
                    f"determine if any items are due now.\n\n"
                    f"If an item has no explicit time condition, assume it NEEDS_ACTION.\n\n"
                    f"Do NOT use tools — just assess the time conditions.\n\n"
                    f"Respond with ONLY one of:\n"
                    f"- NEEDS_ACTION: <brief reason>\n"
                    f"- ALL_CLEAR\n\n"
                    f"## Checklist\n\n{checklist}\n"
                    + "\n\n" + DELIMITER_SYSTEM_INSTRUCTION
                ),
                user_message="Quick triage check — anything need attention?",
                tool_defs=[],
                registry=registry,
                max_iterations=2,
                provider_override=provider_override,
                model_override=triage_model_override,
                on_iteration=on_iteration,
            )

            if triage_result.error or triage_result.text in _AGENT_TURN_ERRORS:
                duration_ms = int((time.monotonic() - start_time) * 1000)
                completed = _mark_and_alert(
                    action, "error", f"triage failed: {triage_result.text[:200]}", duration_ms,
                    input_tokens=triage_result.input_tokens, output_tokens=triage_result.output_tokens,
                    lease_id=lease_id, agent_slug=agent_slug,
                )
                if execution_id:
                    history.record_complete(
                        execution_id, status="error" if completed else "lease_lost",
                        result_summary=f"triage failed: {triage_result.text[:200]}",
                        result_full=triage_result.text,
                        model_used=triage_result.model_used, provider=triage_result.provider,
                        input_tokens=triage_result.input_tokens,
                        output_tokens=triage_result.output_tokens,
                        duration_ms=duration_ms,
                    )
                logger.warning("Heartbeat %s: triage error — aborting (%dms)", agent_slug, duration_ms)
                return
            else:
                triage_data = {
                    "result": "NEEDS_ACTION" if "NEEDS_ACTION" in triage_result.text.upper() else "ALL_CLEAR",
                    "model": triage_result.model_used,
                    "input_tokens": triage_result.input_tokens,
                    "output_tokens": triage_result.output_tokens,
                }
                if "NEEDS_ACTION" not in triage_result.text.upper():
                    duration_ms = int((time.monotonic() - start_time) * 1000)
                    completed = _mark_and_alert(
                        action, "ok", "Triage: all clear", duration_ms,
                        triage_result.input_tokens, triage_result.output_tokens,
                        lease_id=lease_id, agent_slug=agent_slug,
                    )
                    if completed and execution_id:
                        history.record_complete(
                            execution_id, status="ok",
                            result_summary="Triage: all clear",
                            result_full="Triage returned ALL_CLEAR — skipping full check.",
                            tool_calls=[{"triage": triage_data}],
                            model_used=triage_result.model_used, provider=triage_result.provider,
                            input_tokens=triage_result.input_tokens,
                            output_tokens=triage_result.output_tokens,
                            duration_ms=duration_ms,
                        )
                    logger.info("Heartbeat %s: triage ALL_CLEAR (%dms)", agent_slug, duration_ms)
                    return

        if lease_id and not service.renew_lease(action["id"], lease_id):
            logger.warning("Heartbeat %s: lease lost before full execution", agent_slug)
            if execution_id:
                history.record_complete(
                    execution_id, status="lease_lost",
                    result_summary="Lease lost between triage and full execution",
                    duration_ms=int((time.monotonic() - start_time) * 1000),
                )
            return

        followups_block = ""
        if followups:
            # The full run is committed — atomically claim the budget now.
            # The claim re-validates against concurrent surfacing/resolution,
            # so only still-eligible items reach the prompt.
            try:
                claimed = claim_followups_for_surfacing(agent_slug, followups)
                followups_block = format_followups_block(claimed) if claimed else ""
            except Exception as e:
                logger.warning("Heartbeat %s: commitment follow-ups skipped: %s", agent_slug, e)

        if followups_only_run and not followups_block:
            # The follow-ups that justified this run were claimed by another
            # path (or resolved) between peek and claim — with a placeholder
            # checklist there is nothing left to do; don't spend a model turn.
            duration_ms = int((time.monotonic() - start_time) * 1000)
            completed = _mark_and_alert(
                action, "ok", "Follow-ups already surfaced elsewhere", duration_ms,
                lease_id=lease_id, agent_slug=agent_slug,
            )
            if completed and execution_id:
                history.record_complete(
                    execution_id, status="ok",
                    result_summary="Follow-ups already surfaced elsewhere — skipping full run.",
                    duration_ms=duration_ms,
                )
            logger.info("Heartbeat %s: follow-ups claimed elsewhere, skipping (%dms)", agent_slug, duration_ms)
            return

        error_context = _build_error_context(action, agent_slug)

        system_prompt = (
            (
                f"You are {agent['agent_name']}.\n\n"
                + (f"{ga_ctx}\n\n" if ga_ctx else "")
                + f"# Heartbeat Check\n\n"
                f"You are performing a periodic heartbeat check. Review your checklist "
                f"and check each item against current data using your tools.\n\n"
                f"## Your Checklist\n\n{checklist}\n\n"
                f"## Your Knowledge (abbreviated)\n\n{context_snippet}\n\n"
                + DELIMITER_SYSTEM_INSTRUCTION + "\n\n"
                + gtd_coaching_block(tool_defs)
            ),
            (
                f"# Current Date & Time\n\n"
                f"- Date: {date_str}\n"
                f"- Time: {time_str}\n\n"
                + (f"{followups_block}\n\n" if followups_block else "")
                + "## Rules\n\n"
                "- If nothing NEW needs attention since your last check, respond with exactly: HEARTBEAT_OK (this suppresses any notification).\n"
                "- If something needs attention, take action using your tools, then respond with: ACTION_TAKEN: <concise summary of what you found/did>.\n"
                "- That ACTION_TAKEN summary is delivered to the user automatically (push, Telegram, WhatsApp, in-app log) — you do NOT need to call `notify_user`.\n"
                "- Only report what is NEW since your last check — do not re-report standing conditions you already reported, or you will spam the user.\n"
                "- Be concise. This is an automated check, not a conversation.\n"
                f"{error_context}"
            ),
        )

        result = run_background_turn(
            system_prompt=system_prompt,
            user_message="Perform your heartbeat check now.",
            tool_defs=tool_defs,
            registry=registry,
            max_iterations=action.get("max_tool_iterations", 10),
            provider_override=provider_override,
            model_override=model_override,
            on_iteration=on_iteration,
            model_tier=_cfg.model_tier,
        )
        duration_ms = int((time.monotonic() - start_time) * 1000)

        if result.error or result.text in _AGENT_TURN_ERRORS:
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

        completed = _mark_and_alert(
            action, status, result.text[:2000], duration_ms, total_inp, total_out,
            lease_id=lease_id, agent_slug=agent_slug,
        )

        if not completed:
            logger.warning("Heartbeat %s: lease lost — discarding result", agent_slug)
            if execution_id:
                history.record_complete(
                    execution_id, status="lease_lost",
                    result_summary="Lease lost before result could be recorded",
                    duration_ms=duration_ms,
                )
            return

        model_notified = _delivered_via_tool(result.tool_log)

        # Guaranteed delivery, same model as cron and OpenClaw's heartbeat: the
        # run's report is delivered unless the model went silent with HEARTBEAT_OK
        # (status "ok"). status == "action_taken" means a real report → deliver it,
        # unless the model already delivered (avoids a double-send). Triage and the
        # empty-checklist early-returns above keep most ticks from ever getting
        # here, and the prompt tells the model to report only what is NEW.
        auto_delivered = False
        delivery_marker = None
        if status == "action_taken" and not model_notified:
            body = _strip_action_marker(result.text)
            if body:
                try:
                    from core.agents.notifications.delivery import deliver_notification
                    title = action.get("name") or "Heartbeat update"
                    report = deliver_notification(agent_slug, title, body[:4000])
                    auto_delivered = bool(report.get("ok"))
                    channels = report.get("channels_sent", [])
                    delivery_marker = {"tool": "auto_deliver", "ok": auto_delivered, "channels": channels}
                    if auto_delivered:
                        logger.info("Heartbeat %s: auto-delivered action report (channels=%s)", agent_slug, channels or ["in-app log"])
                    else:
                        logger.warning("Heartbeat %s: auto-delivery returned not-ok: %s", agent_slug, report)
                except Exception as e:
                    delivery_marker = {"tool": "auto_deliver", "ok": False, "error": str(e)[:200]}
                    logger.warning("Heartbeat %s: auto-delivery failed: %s", agent_slug, e)

        notification_sent = model_notified or auto_delivered
        # Prepend the marker so it survives history's 10 KB tool_calls truncation.
        if delivery_marker:
            full_tool_log = [delivery_marker] + full_tool_log

        if execution_id:
            history.record_complete(
                execution_id, status=status,
                result_summary=result.text[:500],
                result_full=result.text,
                tool_calls=full_tool_log,
                model_used=result.model_used, provider=result.provider,
                input_tokens=total_inp,
                output_tokens=total_out,
                duration_ms=duration_ms,
                notification_sent=notification_sent,
            )
        logger.info(
            "Heartbeat %s: %s (%dms, tools: %d, notified=%s, auto=%s)",
            agent_slug, status, duration_ms, len(result.tool_log), model_notified, auto_delivered,
        )

    except Exception as e:
        duration_ms = int((time.monotonic() - start_time) * 1000)
        logger.error("Heartbeat %s failed: %s", agent_slug, e)
        _mark_and_alert(action, "error", str(e)[:2000], duration_ms, lease_id=lease_id, agent_slug=agent_slug)
        if execution_id:
            history.record_complete(execution_id, status="error", result_summary=str(e)[:500], result_full=str(e), duration_ms=duration_ms)


def _process_cron(action: dict) -> None:
    """Process a cron scheduled action."""
    agent_slug = action["agent"]
    lease_id = action.get("lease_id")
    prompt = action.get("prompt", "")
    if not prompt:
        _mark_and_alert(action, "skipped", "no prompt configured", 0, lease_id=lease_id, agent_slug=agent_slug)
        return

    agent = _resolve_agent(agent_slug)
    if not agent:
        _mark_and_alert(action, "error", f"Agent '{agent_slug}' not found", 0, lease_id=lease_id, agent_slug=agent_slug)
        return

    execution_id = None
    try:
        execution_id = history.record_start(action["id"], agent_slug, "cron")
    except Exception as e:
        logger.error("Failed to record cron start for %s: %s", agent_slug, e)

    from agents.engine import get_context_manager
    ctx_manager = get_context_manager(agent["slug"])
    context = ctx_manager.load_all_context()
    context_snippet = context[:30000] if context else "(no context files)"

    provider_override = agent.get("provider_override") or None
    model_override = action.get("model_override") or agent.get("model_override") or None

    tz_name = action.get("active_hours_tz") or "America/Chicago"
    from agents.tool_loader import format_current_time
    date_str, time_str = format_current_time(tz_name)

    tool_defs, registry, _aim = _build_tools(agent_slug, agent, background_mode=True)
    on_iteration = _make_lease_renewer(action["id"], lease_id)

    from core.agents.ai_service import _google_accounts_context
    from agents.engine import build_agent_config as _bac2
    _cfg2 = _bac2(agent)
    ga_ctx2 = _google_accounts_context(_aim, _cfg2.google_accounts)
    system_prompt = (
        (
            f"You are {agent['agent_name']}.\n\n"
            + (f"{ga_ctx2}\n\n" if ga_ctx2 else "")
            + f"# Scheduled Action: {action.get('name', 'Unnamed')}\n\n"
            f"{prompt}\n\n"
            f"# Your Knowledge (abbreviated)\n\n{context_snippet}\n\n"
            + DELIMITER_SYSTEM_INSTRUCTION + "\n\n"
            + gtd_coaching_block(tool_defs)
        ),
        (
            f"# Current Date & Time\n\n"
            f"- Date: {date_str}\n"
            f"- Time: {time_str}\n\n"
            f"Take appropriate action using your tools. Be concise.\n"
            f"Your final response will be delivered to the user automatically — just "
            f"produce your report as your final response. You do not need to call "
            f"`notify_user`. If there is genuinely nothing to report, respond with "
            f"exactly [SILENT] and nothing else."
        ),
    )

    start_time = time.monotonic()
    try:
        result = run_background_turn(
            system_prompt=system_prompt,
            user_message=f"Execute scheduled action: {action.get('name', prompt[:100])}",
            tool_defs=tool_defs,
            registry=registry,
            max_iterations=action.get("max_tool_iterations", 10),
            provider_override=provider_override,
            model_override=model_override,
            on_iteration=on_iteration,
            model_tier=_cfg2.model_tier,
        )
        duration_ms = int((time.monotonic() - start_time) * 1000)

        if result.error or result.text in _AGENT_TURN_ERRORS:
            status = "error"
        else:
            status = "ok"

        completed = _mark_and_alert(
            action, status, result.text[:2000], duration_ms,
            result.input_tokens, result.output_tokens,
            lease_id=lease_id, agent_slug=agent_slug,
        )

        if not completed:
            logger.warning("Cron %s: lease lost — discarding result", agent_slug)
            if execution_id:
                history.record_complete(
                    execution_id, status="lease_lost",
                    result_summary="Lease lost before result could be recorded",
                    duration_ms=duration_ms,
                )
            return

        model_notified = _delivered_via_tool(result.tool_log)

        # Model-independent delivery guarantee: a cron action's whole purpose is
        # to report back, so if the run produced output but the model didn't
        # deliver it (and didn't explicitly go silent), the system delivers it
        # via the same path notify_user uses. Best-effort against MODEL behavior
        # (a model swap / a skipped tool call) — not crash-proof; see the
        # scheduled-action-guaranteed-delivery solution doc.
        text = result.text.strip()
        is_silent = text.upper() == SILENT_MARKER
        auto_delivered = False
        delivery_marker = None
        if status == "ok" and text and not is_silent and not model_notified:
            try:
                from core.agents.notifications.delivery import deliver_notification
                title = action.get("name") or "Scheduled update"
                report = deliver_notification(agent_slug, title, result.text[:4000])
                auto_delivered = bool(report.get("ok"))
                channels = report.get("channels_sent", [])
                delivery_marker = {"tool": "auto_deliver", "ok": auto_delivered, "channels": channels}
                if auto_delivered:
                    # Empty channels just means "in-app log only" (no push sub /
                    # external channels off) — a valid state, not an error.
                    logger.info("Cron %s: auto-delivered result (channels=%s)", agent_slug, channels or ["in-app log"])
                else:
                    logger.warning("Cron %s: auto-delivery returned not-ok: %s", agent_slug, report)
            except Exception as e:
                delivery_marker = {"tool": "auto_deliver", "ok": False, "error": str(e)[:200]}
                logger.warning("Cron %s: auto-delivery failed: %s", agent_slug, e)
        elif is_silent:
            logger.info("Cron %s: model returned [SILENT] — skipping delivery", agent_slug)

        notification_sent = model_notified or auto_delivered
        # Prepend the marker so it survives history.record_complete's 10 KB
        # tool_calls truncation. The durable signal is the notification_sent
        # column; status=ok + notification_sent=False flags "ran but not notified".
        tool_calls = ([delivery_marker] + result.tool_log) if delivery_marker else result.tool_log

        if completed and execution_id:
            history.record_complete(
                execution_id, status=status,
                result_summary=result.text[:500],
                result_full=result.text,
                tool_calls=tool_calls,
                model_used=result.model_used, provider=result.provider,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                duration_ms=duration_ms,
                notification_sent=notification_sent,
            )
        logger.info(
            "Cron %s/%s: %s (%dms, notified=%s, auto=%s)",
            agent_slug, action["id"][:8], status, duration_ms, model_notified, auto_delivered,
        )
    except Exception as e:
        duration_ms = int((time.monotonic() - start_time) * 1000)
        logger.error("Cron %s failed: %s", agent_slug, e)
        _mark_and_alert(action, "error", str(e)[:2000], duration_ms, lease_id=lease_id, agent_slug=agent_slug)
        if execution_id:
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
            completed = _mark_and_alert(action, "error", "manual run failed", 0, lease_id=lease_id, agent_slug=agent_name)
            if not completed and lease_id:
                service.release_lease(action["id"], lease_id)
        raise
    finally:
        _worker_finished(agent_name)

    return service.get_action(action_id)


def shutdown_executor() -> None:
    _executor.shutdown(wait=False, cancel_futures=True)
