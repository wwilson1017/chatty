"""Live-meeting coach: gated background turns over the rolling transcript.

Each turn ends with a VERDICT line — PASS (say nothing), NUDGE (post the text
above the verdict into the conversation), or ESCALATE (re-run once on the top
tier for deeper reasoning). Nudges are ordinary assistant rows saved via
ChatHistoryService, so the chat UI needs no special rendering and the coach's
own prior nudges ride back in as conversation history.
"""

import asyncio
import logging
import re
import time
import uuid
from datetime import datetime, timezone

from core.agents.live import session as live
from core.agents.live.session import (
    COACH_MIN_GAP_S,
    COACH_MIN_NEW_CHARS,
    COACH_TRANSCRIPT_TAIL,
    ESCALATE_MIN_GAP_S,
    TURN_TIMEOUT_LONG_S,
    TURN_TIMEOUT_S,
    LiveSession,
)

logger = logging.getLogger(__name__)

# Outbound-communication tools the coach must never hold (enforced, not
# prompt-only): a mis-transcription must not be able to email or message
# anyone. notify_user stays — it is the sanctioned nudge channel.
_COACH_EXCLUDED_TOOLS = {
    "send_email",
    "reply_to_email",
    "send_email_with_attachment",
    "post_message",
}

_VERDICT_RE = re.compile(
    r"^\s*\**\s*VERDICT\s*[:—\-]?\s*(PASS|NUDGE|ESCALATE)\b\**\s*(.*)$",
    re.IGNORECASE,
)

_COACH_CONTRACT = (
    "# Output Contract\n\n"
    "End your final response with exactly one line:\n"
    "VERDICT: PASS — nothing useful to add right now.\n"
    "VERDICT: NUDGE — the text ABOVE the verdict line is your nudge.\n"
    "VERDICT: ESCALATE — <one-line reason> — this moment deserves deeper "
    "reasoning than you can give it.\n\n"
    "Jump in whenever something is happening you can add value to: a decision "
    "forming, a number or date mentioned, a commitment made, an objection "
    "raised, a question you can strengthen, a fact from your knowledge or "
    "memory that helps, an action item worth capturing, or something the user "
    "seems to be missing. Early in the meeting, if the type of meeting or who "
    "is present is unclear and knowing would help you coach, it's fine to ask "
    "once — and equally fine to get no answer; keep listening either way. "
    "Stay quiet through smalltalk, logistics, and anything you'd only be "
    "repeating. Nudges are at most 3 sentences — short and frequent beats "
    "long and rare. Do not summarize the meeting as it goes, do not narrate "
    "your tool use, and do not repeat earlier nudges."
)


def parse_verdict(text: str) -> tuple[str, str, str]:
    """Return (verdict, body, reason). Body is the text above the verdict
    line (the nudge); reason is the verdict line's trailing text (ESCALATE's
    one-line justification). Missing/unparseable verdict → PASS (for a gated
    coach, spam is the worse failure). Last matching line wins because the
    turn text concatenates across tool iterations."""
    if not text:
        return ("PASS", "", "")
    lines = text.splitlines()
    for i in range(len(lines) - 1, -1, -1):
        m = _VERDICT_RE.match(lines[i])
        if m:
            verdict = m.group(1).upper()
            body = "\n".join(lines[:i]).strip()[:2000]
            reason = (m.group(2) or "").strip().strip("—-–: *").strip()[:300]
            return (verdict, body, reason)
    logger.warning("Coach turn had no VERDICT line; treating as PASS")
    return ("PASS", "", "")


def _coach_model_plan(config) -> dict:
    """Resolve which model/tier each coach turn runs on, honoring the admin
    default_model_tier lock and per-agent pins (already folded into config by
    build_agent_config — never forward config.model_tier implicitly)."""
    if config.model_override:
        base = {"model_override": config.model_override,
                "provider_override": config.provider_override or None}
        return {"base": base, "escalate": None, "label": "pinned"}
    if config.model_tier != "auto":
        base = {"model_tier": config.model_tier,
                "provider_override": config.provider_override or None}
        return {"base": base, "escalate": None, "label": config.model_tier}
    return {
        "base": {"model_tier": "mid", "provider_override": config.provider_override or None},
        "escalate": {"model_tier": "top", "provider_override": config.provider_override or None},
        "label": "mid",
    }


def build_coach_context(agent: dict) -> dict:
    """Assemble config, tool defs, and registry for coach turns.

    Mirrors reminders/heartbeat.py _process_self_reminder (copy #3 of this
    assembly — extract a shared helper if a fourth appears).
    """
    from pathlib import Path

    from agents.engine import build_agent_config, get_context_manager
    from agents.tool_loader import (
        INTEGRATION_MODULES,
        build_agent_handlers,
        load_integration_tools,
    )
    from core.agents.tool_definitions import get_tool_definitions
    from core.agents.tool_registry import ToolRegistry
    from core.agents.tools.real_tools import load_all_real_tools
    from integrations.google.policy import google_capabilities_union
    from integrations.registry import get_tool_mode, list_google_accounts

    config = build_agent_config(agent)
    ctx_manager = get_context_manager(agent["slug"])
    context = ctx_manager.load_all_context()
    context_snippet = context[:30000] if context else "(no context files)"

    ga = config.google_accounts
    gmail_ids = ga.get("gmail", [])
    calendar_ids = ga.get("calendar", [])
    drive_ids = ga.get("drive", [])

    all_ga = list_google_accounts()
    account_info_map = {
        aid: {"email": a.get("email", ""), "scope_grants": a.get("scope_grants", {}),
              "connection_status": a.get("connection_status", "ok")}
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
    tool_defs = [t for t in tool_defs if t.get("name") not in _COACH_EXCLUDED_TOOLS]

    registry = ToolRegistry(
        context_dir=config.context_dir,
        gcs_prefix=config.gcs_prefix,
        google_connected=bool(gmail_ids or calendar_ids or drive_ids),
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

    return {
        "config": config,
        "tool_defs": tool_defs,
        "registry": registry,
        "context_snippet": context_snippet,
        "model_plan": _coach_model_plan(config),
    }


def _static_prompt(session: LiveSession, ctx: dict) -> str:
    from core.agents.security.delimiters import DELIMITER_SYSTEM_INSTRUCTION

    config = ctx["config"]
    personality = f"\n\n# Your Personality\n\n{config.personality}" if getattr(config, "personality", "") else ""
    prep = f"\n- Meeting context from the user: {session.prep_note}" if session.prep_note else ""
    return (
        f"You are {config.agent_name}, acting as a silent meeting coach for "
        f"your user during a live meeting.{personality}\n\n"
        f"# Live Meeting Coaching\n\n"
        f"A meeting is being recorded; you receive the rolling machine "
        f"transcript (imperfect, unlabeled speakers) in batches. Your job: "
        f"be an engaged coach in the user's corner — talking points they are "
        f"missing, questions they should ask, facts from your knowledge and "
        f"memory that strengthen their position, commitments and action items "
        f"worth capturing (use your reminder/memory tools directly). You have "
        f"standing permission to speak up when something is happening; the "
        f"user wants to hear from you, not wonder if you're there.\n"
        f"- Recording started: {session.started_at}{prep}\n"
        f"- Do NOT narrate tool use. Do NOT initiate outbound communication "
        f"(no emails or messages) based on overheard audio.\n"
        f"- `notify_user` is available for urgent nudges (the user's screen "
        f"may be dimmed).\n\n"
        f"# Your Knowledge (abbreviated)\n\n{ctx['context_snippet']}\n\n"
        f"{DELIMITER_SYSTEM_INSTRUCTION}\n\n"
        f"{_COACH_CONTRACT}"
    )


def _volatile_prompt(session: LiveSession) -> str:
    from agents.engine import get_chat_service

    now = datetime.now(timezone.utc).astimezone()
    recent = ""
    try:
        history = get_chat_service(session.agent_slug).get_clean_history(
            session.conversation_id, limit=6
        )
        lines = [
            f"[{m.get('role', '?')}] {(m.get('content') or '')[:300]}"
            for m in history if m.get("content")
        ]
        if lines:
            recent = "# Recent Conversation (includes your prior nudges)\n\n" + "\n".join(lines) + "\n\n"
    except Exception:
        logger.debug("Coach history fetch failed", exc_info=True)
    return (
        f"# Current Date & Time\n\n{now.strftime('%A, %B %d, %Y at %H:%M %Z')}\n\n"
        f"{recent}"
    )


def _turn_user_message(session: LiveSession, delta_text: str, *, wrapup: bool,
                       reason: str = "") -> str:
    from core.agents.security.delimiters import wrap_result

    if wrapup:
        full = live.transcript_text(session, tail_chars=60_000)
        return (
            f"The meeting has ended ({reason or 'stopped'}). Full transcript:\n\n"
            + wrap_result("live_meeting_transcript", full or "(no transcript captured)")
            + "\n\nPost a wrap-up for the user: outcomes, decisions, and action "
            "items (create reminders / save memory only where clearly "
            "warranted). This wrap-up IS delivered — end with VERDICT: NUDGE."
        )
    tail = live.transcript_text(session, tail_chars=COACH_TRANSCRIPT_TAIL)
    marked = tail
    if delta_text and delta_text in tail:
        marked = tail.replace(delta_text, "=== NEW SINCE YOUR LAST REVIEW ===\n" + delta_text, 1)
    prefix = ""
    if reason:
        prefix = f"A fast review flagged this moment: {reason}. Reason deeply and decide.\n\n"
    return prefix + wrap_result("live_meeting_transcript", marked or "(nothing yet)")


async def run_coach_turn(session: LiveSession, ctx: dict, delta_text: str, *,
                         escalate_reason: str = "", wrapup: bool = False,
                         finalize_reason: str = "") -> None:
    """Run one gated coach turn; persist and emit the nudge if any."""
    from core.agents.background_runner import run_background_turn_async

    plan = ctx["model_plan"]
    escalated = bool(escalate_reason)
    if escalated and plan["escalate"]:
        model_args = plan["escalate"]
    elif wrapup and plan["escalate"]:
        model_args = plan["escalate"]  # wrap-up deserves the top tier when unpinned
    else:
        model_args = plan["base"]

    registry = ctx["registry"]
    registry._current_conversation_id = session.conversation_id

    timeout = TURN_TIMEOUT_LONG_S if (escalated or wrapup) else TURN_TIMEOUT_S
    live.mark_conversation_busy(session.conversation_id)  # advisory lease
    try:
        result = await asyncio.wait_for(
            run_background_turn_async(
                system_prompt=(_static_prompt(session, ctx), _volatile_prompt(session)),
                user_message=_turn_user_message(
                    session, delta_text, wrapup=wrapup,
                    reason=escalate_reason or finalize_reason,
                ),
                tool_defs=ctx["tool_defs"],
                registry=registry,
                max_iterations=5,
                source="live_coach",
                agent_slug=session.agent_slug,
                **model_args,
            ),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        logger.warning("Coach turn timed out (%ss) for session %s", timeout, session.session_id)
        return
    finally:
        live.clear_conversation_busy(session.conversation_id)

    if result.error:
        logger.warning("Coach turn errored: %s", result.text[:200])
        return

    verdict, body, reason = parse_verdict(result.text)

    if verdict == "ESCALATE" and not wrapup and not escalated:
        if plan["escalate"] is None:
            verdict, body = ("NUDGE", body) if body else ("PASS", "")
        elif time.time() - session.coach_last_escalate_at < ESCALATE_MIN_GAP_S:
            logger.info("Escalation rate-limited; dropping")
            return
        else:
            session.coach_last_escalate_at = time.time()
            session.escalations += 1
            await run_coach_turn(session, ctx, delta_text,
                                 escalate_reason=reason or body or "flagged moment")
            return
    elif verdict == "ESCALATE":
        # Escalated/wrap-up turn asking to escalate again: no recursion.
        verdict, body = ("NUDGE", body) if body else ("PASS", "")

    if verdict != "NUDGE" or not body:
        return

    # Defer the save while a user turn is streaming in this conversation —
    # cosmetic adjacency is legal (_coalesce_consecutive) but avoid it.
    waited = 0.0
    while live.is_conversation_busy(session.conversation_id) and waited < 120:
        await asyncio.sleep(1)
        waited += 1

    from agents.engine import get_chat_service

    msg_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).isoformat()
    try:
        get_chat_service(session.agent_slug).save_message(
            session.conversation_id, msg_id, "assistant", body,
            model=result.model_used,
        )
    except Exception:
        logger.exception("Failed to save coach nudge")
        return

    live.emit(session, {
        "type": "coach",
        "message": {
            "id": msg_id, "role": "assistant", "content": body,
            "model": result.model_used, "created_at": created_at,
        },
        "tier": plan["label"] if not (escalated or wrapup) else ("top" if plan["escalate"] else plan["label"]),
        "escalated": escalated,
        "wrapup": wrapup,
    })


async def coach_loop(session: LiveSession, ctx: dict) -> None:
    """Watch the transcript; run a gated turn when enough new content lands."""
    try:
        while session.status == "recording":
            try:
                await asyncio.wait_for(session.wake.wait(), timeout=30)
            except asyncio.TimeoutError:
                continue
            session.wake.clear()

            delta_segs = [
                s for s in sorted(session.segments.values(), key=lambda s: s.index)
                if s.status == "done" and s.text and s.index not in session.reviewed_indexes
            ]
            delta_text = "\n".join(s.text for s in delta_segs)
            if len(delta_text) < COACH_MIN_NEW_CHARS:
                continue
            since_last = time.time() - session.coach_last_run_at
            if since_last < COACH_MIN_GAP_S:
                await asyncio.sleep(COACH_MIN_GAP_S - since_last)
                session.wake.set()  # re-collect (more may have arrived)
                continue
            # Defer while a user chat turn is streaming (user priority).
            while live.is_conversation_busy(session.conversation_id):
                await asyncio.sleep(1)
                if session.status != "recording":
                    return

            session.reviewed_indexes.update(s.index for s in delta_segs)
            session.coach_last_run_at = time.time()
            try:
                await run_coach_turn(session, ctx, delta_text)
            except Exception:
                logger.exception("Coach turn crashed; loop continues")
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("Coach loop died for session %s", session.session_id)
