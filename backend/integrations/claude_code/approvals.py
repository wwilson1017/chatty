"""Chatty — owner approval for full-access Claude Code jobs.

A full job is inserted as `pending_approval` (24 h expiry) and the owner sees
the verbatim task on Telegram (inline buttons) and on the integration card.
decide() is the one path from pending_approval: a single conditional UPDATE, so
an approval is single-use however many buttons are pressed at once. The claim
in connector_api still re-checks the approved prompt's hash, the ceiling and
the access level before anything runs.
"""

import hashlib
import json
import logging

from . import db
from .tools import build_prompt

logger = logging.getLogger(__name__)

EXCERPT_CHARS = 200
_OUTCOME = {
    "full": "approved — running with full access",
    "sandbox": "running in the sandbox instead",
    "cancel": "cancelled",
    "expired": "expired without a decision",
}


def parent_excerpt(job: dict) -> str | None:
    """One line of the parent job's task, for promotions (sandbox job → full follow-up)."""
    parent = db.get_job(job["parent_job_id"]) if job.get("parent_job_id") else None
    return " ".join(parent["task"].split())[:EXCERPT_CHARS] if parent else None


def _bot_token(agent: dict | None) -> str | None:
    return agent["telegram_bot_token"] if agent and agent.get("telegram_enabled") and agent.get("telegram_bot_token") else None


def _agent(slug: str) -> dict | None:
    from agents.db import get_agent_by_slug
    return get_agent_by_slug(slug)


def _approval_chat(job: dict, agent: dict) -> str | None:
    """The Telegram chat to ask in: the request's own chat, else the agent's first
    Telegram user. A WhatsApp chat id is never used as a Telegram destination."""
    route = json.loads(job["route"]) if job["route"] else {}
    if route.get("channel") == "telegram" and route.get("chat_id"):
        return str(route["chat_id"])
    from integrations.telegram.state import first_telegram_user
    user = first_telegram_user(agent["id"])
    return str(user) if user else None


def _message(job: dict, agent: dict) -> str:
    host = db.creds().get("host") or "your computer"
    lines = [f"{agent.get('agent_name') or job['agent_slug']} wants to run a Claude Code job "
             f"({job['runner']}) with FULL access on {host}. It may push branches and open issues or PRs.",
             f"Job {job['id']} · expires in {db.APPROVAL_TTL_HOURS} h"]
    excerpt = parent_excerpt(job)
    if excerpt:
        lines.append(f"Continues job {job['parent_job_id']}: {excerpt}")
    # Sent with plain=True: the task is untrusted, so nothing in it may render.
    return "\n".join(lines) + f"\n\nThe exact task:\n{job['task']}"


def request_approval(job: dict) -> str:
    """Ask the owner on Telegram. Returns where the approval is waiting. A send
    failure leaves the job pending — the card is always an approval surface."""
    card = "the Claude Code card in Chatty's integrations"
    try:
        agent = _agent(job["agent_slug"])
        token = _bot_token(agent)
        chat_id = _approval_chat(job, agent) if token else None
        if not chat_id:
            return card
        from integrations.telegram import client as tg
        buttons = {"inline_keyboard": [[
            {"text": "Run full", "callback_data": f"cc:{job['id']}:full"},
            {"text": "Run sandbox", "callback_data": f"cc:{job['id']}:sandbox"},
            {"text": "Cancel", "callback_data": f"cc:{job['id']}:cancel"},
        ]]}
        sent = tg.send_message(chat_id, _message(job, agent), token, reply_markup=buttons, plain=True)
        last = sent[-1]
        last = last.get("result", last)  # tolerate the raw API envelope
        ref = {"chat_id": chat_id, "message_id": last["message_id"]}
        conn = db.get_db()
        with db.write_lock():
            conn.execute("UPDATE jobs SET approval_ref = ? WHERE id = ?", (json.dumps(ref), job["id"]))
            conn.commit()
        return f"Telegram, or {card}"
    except Exception:
        logger.warning("Claude Code job %s: approval request on Telegram failed", job["id"], exc_info=True)
        return card


def _edit_message(job: dict, outcome: str) -> None:
    if not job.get("approval_ref"):
        return
    try:
        ref = json.loads(job["approval_ref"])
        token = _bot_token(_agent(job["agent_slug"]))
        if token:
            from integrations.telegram import client as tg
            tg.edit_message_text(ref["chat_id"], ref["message_id"],
                                 f"Claude Code job {job['id']}: {_OUTCOME[outcome]}.\n\n{job['task'][:3000]}", token)
    except Exception:
        logger.warning("Claude Code job %s: editing the approval message failed", job["id"], exc_info=True)


def decide(job_id: str, decision: str, via: str, decided_by: str, *,
           agent_slug: str | None = None, approval_ref: dict | None = None) -> dict:
    """Apply the owner's decision once. agent_slug / approval_ref (the Telegram
    path) must match the job. Returns {ok, job_id, status} or {error}."""
    if decision not in ("full", "sandbox", "cancel"):
        return {"error": "decision must be full, sandbox or cancel"}
    job = db.get_job(job_id)
    if not job or (agent_slug is not None and job["agent_slug"] != agent_slug):
        return {"error": "No such job", "not_found": True}
    if approval_ref is not None:
        stored = json.loads(job["approval_ref"]) if job["approval_ref"] else None
        if not stored or (str(stored["chat_id"]), stored["message_id"]) != (
                str(approval_ref.get("chat_id")), approval_ref.get("message_id")):
            return {"error": "This approval message doesn't match the job"}
    if job["status"] != "pending_approval":
        return {"error": f"Job {job_id} is no longer waiting for approval ({job['status']})"}
    if decision != "cancel":
        err = db.level_error(decision, job["origin"])  # ceiling or access may have dropped since the request
        if err:
            return {"error": err}

    level = job["mode"] if decision == "cancel" else decision
    prompt = build_prompt("sandbox", job["task"]) if decision == "sandbox" else job["prompt"]
    conn = db.get_db()
    with db.write_lock():
        n = conn.execute(
            "UPDATE jobs SET decision = ?, decided_by = ?, decided_via = ?, decided_at = datetime('now'), "
            "approved_prompt_sha256 = ?, mode = ?, prompt = ?, "
            "status = CASE WHEN ? = 'cancel' THEN status ELSE 'queued' END "
            "WHERE id = ? AND status = 'pending_approval' AND decision IS NULL "
            "AND approval_expires_at > datetime('now')",
            (decision, decided_by[:200], via,
             None if decision == "cancel" else hashlib.sha256(prompt.encode()).hexdigest(),
             level, prompt, decision, job_id),
        ).rowcount
        if n and decision == "cancel":
            db.finish_job(job_id, "cancelled", f"cancelled by owner ({via})", notify=False, commit=False)
        conn.commit()
    if not n:
        return {"error": f"Job {job_id} was already decided or has expired"}
    _edit_message(job, decision)
    logger.info("Claude Code job %s: %s via %s by %s", job_id, decision, via, decided_by)
    return {"ok": True, "job_id": job_id, "decision": decision,
            "status": "cancelled" if decision == "cancel" else "queued"}


def handle_telegram_callback(agent_slug: str, callback_query: dict, bot_token: str) -> None:
    """A `cc:<job_id>:<decision>` button press on this agent's bot."""
    from integrations.telegram import client as tg
    from integrations.telegram.state import get_mapping_by_sender

    _, job_id, decision = (callback_query.get("data", "").split(":") + ["", "", ""])[:3]
    sender = str((callback_query.get("from") or {}).get("id", ""))
    agent = _agent(agent_slug)
    # simplification: a user mapped to the agent's bot is the owner — single-user app
    if not agent or not sender or not get_mapping_by_sender("telegram", sender, agent["id"]):
        result = {"error": "You can't approve Claude Code jobs for this assistant."}
    else:
        msg = callback_query.get("message") or {}
        result = decide(job_id, decision, "telegram", f"telegram:{sender}", agent_slug=agent_slug,
                        approval_ref={"chat_id": (msg.get("chat") or {}).get("id"),
                                      "message_id": msg.get("message_id")})
    try:
        tg.answer_callback_query(callback_query.get("id", ""),
                                 result.get("error") or f"Job {job_id}: {_OUTCOME[decision]}", bot_token)
    except Exception:
        logger.warning("Claude Code: answering Telegram callback failed", exc_info=True)


def expire_stale() -> None:
    """Sweep: approvals past their deadline become `expired` (no completion turn);
    the Telegram message is edited and one fixed line goes to the request's route."""
    from core.agents.scheduled_actions.processor import deliver_background_result

    for r in db.query("SELECT * FROM jobs WHERE status = 'pending_approval' "
                      "AND approval_expires_at <= datetime('now')"):
        job = dict(r)
        try:
            if not db.finish_job(job["id"], "expired", "approval expired", notify=False):
                continue
            _edit_message(job, "expired")
            deliver_background_result(
                job["agent_slug"], "Claude Code job expired",
                f"Claude Code job {job['id']} expired — full access wasn't approved within {db.APPROVAL_TTL_HOURS} h.",
                route=json.loads(job["route"]) if job["route"] else None,
            )
        except Exception:
            logger.warning("Claude Code job %s: expiring the approval failed", job["id"], exc_info=True)
