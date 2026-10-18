"""Chatty — owner approval of a computer gate: the Telegram card (screenshot, then
checked facts with buttons), the dashboard card's decide path, the single-use
decision that queues the follow-up, and expiry.

A gate is where the helper was stopped before a consequential action. The
approval is bound to the page facts stored on the gate at that moment
(gates.ApprovalBinding); the follow-up task (runner._Run.consume) re-sends
exactly that, once, and the computer re-checks every field inside the request.
When those facts couldn't be read (no form or composer, no single total) the
card offers "take over to do this yourself" and approving queues a takeover
task that opens the page and hands the screen to the owner. We never pretend an
approval is bound to details we couldn't read.

decide() is the one path from `pending`: one conditional UPDATE and the
follow-up INSERT in the same commit, so an approval is single-use however many
buttons are pressed at once.
# simplification: copied from claude_code/approvals.py; extract when a third
# integration needs owner approvals
"""

import json
import logging
from pathlib import Path

from . import card, db, gates

logger = logging.getLogger(__name__)

CARD = "the Computer card in Chatty's integrations"
_OUTCOME = {
    "approve": "approved — Chatty performs it once after re-checking the page",
    "takeover": "approved — the screen opens for you to do it yourself",
    "deny": "denied; nothing was done",
    "expired": f"expired without a decision after {db.GATE_TTL_HOURS} h; nothing was done",
}


def _agent(slug: str) -> dict | None:
    from agents.db import get_agent_by_slug
    return get_agent_by_slug(slug)


def _bot_token(agent: dict | None) -> str | None:
    return agent["telegram_bot_token"] if agent and agent.get("telegram_enabled") and agent.get("telegram_bot_token") else None


def _route(task: dict | None) -> dict | None:
    return json.loads(task["route"]) if task and task.get("route") else None


def _approval_chat(task: dict | None, agent: dict) -> str | None:
    """The Telegram chat to ask in: the request's own chat, else the agent's first Telegram
    user. A WhatsApp chat id is never used as a Telegram destination."""
    route = _route(task) or {}
    if route.get("channel") == "telegram" and route.get("chat_id"):
        return str(route["chat_id"])
    from integrations.telegram.state import first_telegram_user
    user = first_telegram_user(agent["id"])
    return str(user) if user else None


def screenshot_path(gate: dict) -> Path | None:
    """The gate's screenshot file (under data/computer), or None."""
    if not gate.get("screenshot"):
        return None
    p = (db.DATA_DIR / gate["screenshot"]).resolve()
    return p if p.is_file() and p.is_relative_to(db.DATA_DIR.resolve()) else None


def _control(b: gates.ApprovalBinding) -> str:
    return f'{b.role or "element"} "{b.name}"'


def _message(gate: dict, agent: dict) -> str:
    """Checked facts (what Chatty read and will re-check) apart from the helper's own words.
    Sent plain: names, reasons and item text come from the page and the helper."""
    b = gates.ApprovalBinding.from_gate(gate)
    who = agent.get("agent_name") or gate["agent_slug"]
    where = b.host or gate.get("url") or "the page"
    lines = [f"{who}'s computer helper stopped before a {gate['kind']} on {where}.",
             f"Why Chatty stopped it: {gate['note']}" if gate.get("note") else "", ""]
    takeover = gates.unbindable_reason(gate)
    if takeover:
        lines += [f"Chatty couldn't bind an approval to page facts ({takeover}), so it won't press this for you.",
                  "Approving opens the screen for you to do it yourself: you get a link when the page is ready, "
                  "and the screen is held for 15 minutes."]
    else:
        element = json.loads(gate["element_json"]) if gate.get("element_json") else {}
        lines += ["Checked on the page (re-checked again right before the click):",
                  f"• site: {b.host}{b.path}", f"• control: {_control(b)}"]
        if gate["kind"] == "buy" and b.total:
            total = json.loads(gate["total_json"])
            shown = total.get("text") or f"{b.total['amount']} {b.total['currency']}"
            lines.append(f"• total on the page: {shown}")
        if b.context_fp:
            what = "the form's fields" if element.get("context_kind") == "form" else "the message's recipients and text"
            lines.append(f"• {what} must be exactly as they are now")
    helper = [f"reason: {gate['reason']}"] if gate.get("reason") else []
    helper += [f"{k}: {gate[k]}" for k in ("item", "store", "total_text") if gate.get(k)]
    if helper:
        lines += ["", "Helper's own account (not verified): " + " · ".join(helper).replace("total_text", "total")]
    lines += ["", f"Gate {gate['id']} · task {gate['task_id']} · expires in {db.GATE_TTL_HOURS} h"]
    return "\n".join(lines)


def request(gate_id: str) -> str:
    """Ask the owner on Telegram: the screenshot (when one exists), then the facts with buttons.
    Returns where the approval is waiting. A send failure leaves the gate pending — the card is
    always an approval surface."""
    gate = db.get_gate(gate_id)
    if not gate:
        return CARD
    try:
        agent = _agent(gate["agent_slug"])
        token = _bot_token(agent)
        chat_id = _approval_chat(db.get_task(gate["task_id"]), agent) if token else None
        if not chat_id:
            return CARD
        from integrations.telegram import client as tg
        shot = screenshot_path(gate)
        if shot:
            tg.send_photo(chat_id, shot.read_bytes(), token,
                          caption=f"{agent.get('agent_name') or gate['agent_slug']}: the screen before the "
                                  f"{gate['kind']} on {gate['host'] or 'the page'} (gate {gate_id})")
        yes = "Take over to do this yourself" if gates.unbindable_reason(gate) else "Approve"
        buttons = {"inline_keyboard": [[
            {"text": yes, "callback_data": f"vc:{gate_id}:approve"},
            {"text": "Deny", "callback_data": f"vc:{gate_id}:deny"},
        ]]}
        sent = tg.send_message(chat_id, _message(gate, agent), token, reply_markup=buttons, plain=True)
        last = sent[-1]
        last = last.get("result", last)  # tolerate the raw API envelope
        db.execute("UPDATE gates SET approval_ref = ? WHERE id = ?",
                   (json.dumps({"chat_id": chat_id, "message_id": last["message_id"]}), gate_id))
        return f"Telegram, or {CARD}"
    except Exception:
        logger.warning("Computer gate %s: approval request on Telegram failed", gate_id, exc_info=True)
        return CARD


def _edit_message(gate: dict, outcome: str) -> None:
    if not gate.get("approval_ref"):
        return
    try:
        ref = json.loads(gate["approval_ref"])
        token = _bot_token(_agent(gate["agent_slug"]))
        if token:
            from integrations.telegram import client as tg
            b = gates.ApprovalBinding.from_gate(gate)
            tg.edit_message_text(ref["chat_id"], ref["message_id"],
                                 f"Computer approval {gate['id']}: {_OUTCOME[outcome]}.\n\n"
                                 f"{gate['kind']}: {_control(b)} on {b.host or gate.get('url') or 'the page'}", token)
    except Exception:
        logger.warning("Computer gate %s: editing the approval message failed", gate["id"], exc_info=True)


def _tell_route(gate: dict, text: str) -> None:
    """One fixed line to the chat the task came from (no agent turn)."""
    from core.agents.scheduled_actions.processor import deliver_background_result
    deliver_background_result(gate["agent_slug"], "Computer approval", text, route=_route(db.get_task(gate["task_id"])))


def _follow_up_text(gate: dict, takeover: str | None) -> str:
    b = gates.ApprovalBinding.from_gate(gate)
    where = f"{b.host}{b.path}" if b.host else (gate.get("url") or "the page")
    if takeover:
        return (f"Owner takeover for the {gate['kind']} on {where}: open the page, hand the screen to the owner "
                f"and report what they left on screen. Chatty performs nothing itself.")
    return (f"Approved by the owner: {gate['kind']} — {_control(b)} on {where}. Perform it once (the page facts are "
            f"re-checked first), then continue the original task from there: confirm the outcome and report.")


def decide(gate_id: str, decision: str, via: str, decided_by: str, *,
           agent_slug: str | None = None, approval_ref: dict | None = None) -> dict:
    """Apply the owner's decision once. agent_slug / approval_ref (the Telegram path) must match
    the gate. Policy is re-checked (integration enabled, agent not excluded) and an approval
    inserts the follow-up task in the same commit. Returns {ok, gate_id, decision, task_id,
    takeover} or {error}."""
    if decision not in ("approve", "deny"):
        return {"error": "decision must be approve or deny"}
    gate = db.get_gate(gate_id)
    if not gate or (agent_slug is not None and gate["agent_slug"] != agent_slug):
        return {"error": "No such approval", "not_found": True}
    if approval_ref is not None:
        stored = json.loads(gate["approval_ref"]) if gate["approval_ref"] else None
        if not stored or (str(stored["chat_id"]), stored["message_id"]) != (
                str(approval_ref.get("chat_id")), approval_ref.get("message_id")):
            return {"error": "This approval message doesn't match the gate"}
    if gate["status"] != "pending":
        return {"error": f"Gate {gate_id} is no longer waiting for a decision ({gate['status']})"}
    err = card.policy_error(gate["agent_slug"]) if decision == "approve" else None  # a deny is always safe
    if err:  # disabled or excluded since the request
        return {"error": err}
    parent = db.get_task(gate["task_id"])
    if not parent:
        return {"error": "The task this approval belongs to no longer exists"}
    takeover = gates.unbindable_reason(gate)

    conn = db.get_db()
    task_id = None
    with db.write_lock():
        n = conn.execute(
            "UPDATE gates SET status = ?, decision = ?, decided_by = ?, decided_via = ?, decided_at = datetime('now') "
            "WHERE id = ? AND status = 'pending' AND decision IS NULL AND expires_at > datetime('now')",
            ("approved" if decision == "approve" else "denied", decision, decided_by[:200], via, gate_id),
        ).rowcount
        if n and decision == "approve":
            task_id = db.insert_task(
                agent_slug=gate["agent_slug"], origin="user", task=_follow_up_text(gate, takeover),
                helper_provider=parent["helper_provider"], helper_model=parent["helper_model"],
                conversation_id=parent["conversation_id"], route=_route(parent), action_id=parent["action_id"],
                parent=parent, approved_gate_id=gate_id, mode=parent["mode"], commit=False,
            )
        conn.commit()
    if not n:
        return {"error": f"Gate {gate_id} was already decided or has expired"}
    outcome = "deny" if decision == "deny" else ("takeover" if takeover else "approve")
    _edit_message(gate, outcome)
    logger.info("Computer gate %s: %s via %s by %s → task %s", gate_id, decision, via, decided_by, task_id)
    if decision == "deny":
        b = gates.ApprovalBinding.from_gate(gate)
        _tell_route(gate, f"Computer task {gate['task_id']}: the {gate['kind']} ({_control(b)} on "
                          f"{b.host or 'the page'}) was denied; nothing was done.")
    else:
        from . import runner
        runner.kick()
    return {"ok": True, "gate_id": gate_id, "decision": decision, "task_id": task_id,
            "takeover": bool(takeover) if decision == "approve" else False}


def handle_telegram_callback(agent_slug: str, callback_query: dict, bot_token: str) -> None:
    """A `vc:<gate_id>:<decision>` button press on this agent's bot. A press by a Telegram user
    not linked to the agent changes nothing."""
    from integrations.telegram import client as tg
    from integrations.telegram.state import get_mapping_by_sender

    _, gate_id, decision = (callback_query.get("data", "").split(":") + ["", "", ""])[:3]
    sender = str((callback_query.get("from") or {}).get("id", ""))
    agent = _agent(agent_slug)
    # simplification: a user mapped to the agent's bot is the owner — single-user app
    if not agent or not sender or not get_mapping_by_sender("telegram", sender, agent["id"]):
        result = {"error": "You can't decide computer approvals for this assistant."}
    else:
        msg = callback_query.get("message") or {}
        result = decide(gate_id, decision, "telegram", f"telegram:{sender}", agent_slug=agent_slug,
                        approval_ref={"chat_id": (msg.get("chat") or {}).get("id"),
                                      "message_id": msg.get("message_id")})
    try:
        outcome = "takeover" if result.get("takeover") else decision
        tg.answer_callback_query(callback_query.get("id", ""),
                                 result.get("error") or f"Gate {gate_id}: {_OUTCOME.get(outcome, decision)}", bot_token)
    except Exception:
        logger.warning("Computer approvals: answering Telegram callback failed", exc_info=True)


def expire_stale() -> None:
    """Sweep: pending gates past their deadline become `expired` (no agent turn); the Telegram
    message is edited and one fixed line goes to the request's route."""
    for r in db.query("SELECT * FROM gates WHERE status = 'pending' AND expires_at <= datetime('now')"):
        gate = dict(r)
        try:
            if db.execute("UPDATE gates SET status = 'expired' WHERE id = ? AND status = 'pending'", (gate["id"],)) != 1:
                continue
            _edit_message(gate, "expired")
            b = gates.ApprovalBinding.from_gate(gate)
            _tell_route(gate, f"Computer task {gate['task_id']}: the approval for the {gate['kind']} ({_control(b)} on "
                              f"{b.host or 'the page'}) expired after {db.GATE_TTL_HOURS} h; nothing was done.")
        except Exception:
            logger.warning("Computer gate %s: expiring the approval failed", gate["id"], exc_info=True)
