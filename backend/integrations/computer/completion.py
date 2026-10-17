"""Chatty — computer task completion: the requesting agent's report-back turn,
the usage row, and the sweep (orphans, policy, lost completions).

The durable queue is the task row's completion_status (none → pending → running
→ done), set to 'pending' by finish_task(notify=True) in the same UPDATE that
makes the task terminal.

Guarantee: the agent turn runs AT MOST ONCE (it may call tools or queue another
task, so it is never re-run); delivery is best-effort. finalize() is the one
idempotent tail shared by the normal path and every recovery path: it upserts
the vc-<task_id> conversation message, delivers, and marks the completion done.
"""

import json
import logging
from concurrent.futures import ThreadPoolExecutor

from core.agents.security.delimiters import wrap_result

from . import card, db

logger = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="vc-completion")

MAX_PRE_TURN_ATTEMPTS = 3
STALE_COMPLETION_MINUTES = 15  # background turns time out at 5 min
ORPHAN_MINUTES = 3  # a running task's heartbeat is written every 30 s

_INSTRUCTIONS = {
    "user": (
        "A computer task you started at the user's request has finished. Report the outcome to the user "
        "now: what the helper did, what it found, where any files are, and anything they need to do. Be "
        "concise. Mention the task id so they can ask for a follow-up. Always report — never answer [SILENT]."
    ),
    "background": (
        "A computer task you started on your own (from a scheduled or background task) has finished. "
        "Report it to the user only if the result is worth surfacing; otherwise respond with exactly [SILENT]."
    ),
}

_STATUS_NOTES = {
    "needs_approval": (
        "The helper stopped BEFORE a consequential action ({what}) because it needs the owner's approval. "
        "Approvals from chat aren't available yet: tell the user exactly what was about to happen and that they "
        "can finish it themselves on the computer's screen (/computer), or ask you to try a different approach."
    ),
    "outcome_unknown": (
        "The helper performed an action ({what}) and could NOT confirm what happened. Tell the user to check the "
        "site before anything is repeated; nothing will be retried automatically."
    ),
}


def _fixed_line(task: dict) -> str:
    return f"Computer task {task['id']} finished ({task['status']}) — ask me for the result"


def submit(task_id: str) -> None:
    _executor.submit(_safe_complete, task_id)


def _safe_complete(task_id: str) -> None:
    try:
        complete_task(task_id)
    except Exception:
        logger.exception("Computer completion %s failed", task_id)


def _claim(task_id: str) -> bool:
    conn = db.get_db()
    with db.write_lock():
        n = conn.execute(
            "UPDATE tasks SET completion_status = 'running', completion_claimed_at = datetime('now'), "
            "completion_attempts = completion_attempts + 1 WHERE id = ? AND completion_status = 'pending'",
            (task_id,),
        ).rowcount
        conn.commit()
    return n == 1


def record_usage(task_id: str) -> None:
    """One activity row per task (event_type 'computer'), keyed by the task id so re-running is a no-op;
    then clear accounting_pending. Called by finish_task and re-tried by the sweep."""
    task = db.get_task(task_id)
    if not task or task["status"] not in db.TERMINAL_STATUSES:
        return
    try:
        from core.agents.activity_log import log_chat_event
        log_chat_event(
            task["agent_slug"], event_id=f"vc-{task_id}", event_type="computer", source="computer",
            conversation_id=task["conversation_id"] or "", status="ok" if task["status"] == "done" else "error",
            result_summary=f"[{task['status']}] {task['finish_reason'] or ''}: {task['task']}"[:500],
            model_used=task["helper_model"], provider=task["helper_provider"],
            input_tokens=task["input_tokens"], output_tokens=task["output_tokens"],
            duration_ms=int((task["running_seconds"] or 0) * 1000),
        )
        db.execute("UPDATE tasks SET accounting_pending = 0 WHERE id = ?", (task_id,))
    except Exception:
        logger.warning("Computer task %s: usage row failed (the sweep retries)", task_id, exc_info=True)


def complete_task(task_id: str) -> None:
    if not _claim(task_id):
        return
    task = db.get_task(task_id)

    # Pre-turn: failures here are safe to retry (no tools have run).
    from core.agents.scheduled_actions.processor import _resolve_agent
    agent = _resolve_agent(task["agent_slug"])
    if not agent:
        if task["completion_attempts"] >= MAX_PRE_TURN_ATTEMPTS:
            finalize(task_id)
        else:
            db.execute("UPDATE tasks SET completion_status = 'pending' WHERE id = ?", (task_id,))
        return

    # The turn: invoked at most once. Any exception from here on → finalize, never retry.
    tool_log: list = []
    try:
        from core.agents.scheduled_actions.processor import _AGENT_TURN_ERRORS, run_agent_background_turn
        gate = db.get_gate(task["gate_id"]) if task["gate_id"] else None
        what = (f"{gate['kind']}: {gate['name'] or gate['reason'] or ''} on {gate['host'] or gate['url'] or 'the page'}"
                if gate else task["finish_reason"] or "")
        payload = json.dumps({
            "task": task["task"],
            "result_text": (task["result_text"] or "")[:20000],
            "error": task["error"],
            "gate": db.gate_view(gate) if gate else None,
        })
        user_message = (
            f"Computer task {task['id']} finished with status '{task['status']}'"
            + (f" ({task['finish_reason']})" if task["finish_reason"] else "")
            + f". {task['steps']} steps, ${task['cost_reserved_usd'] + task['cost_actual_usd']:.2f}, "
              f"{(task['running_seconds'] or 0) / 60:.0f} min. Created {task['created_at']} UTC, finished {task['finished_at']} UTC."
            + (" " + _STATUS_NOTES[task["status"]].format(what=what) if task["status"] in _STATUS_NOTES else "")
            + " A follow-up is a new task: computer_task(task=..., follow_up_of='" + task["id"] + "')."
            + "\n\n" + wrap_result("computer_task", payload)
        )
        result, _registry = run_agent_background_turn(
            agent, "Computer task finished", _INSTRUCTIONS.get(task["origin"], _INSTRUCTIONS["background"]),
            user_message, source="computer",
            conversation_id=task["conversation_id"],
            route=json.loads(task["route"]) if task["route"] else None,
        )
        tool_log = result.tool_log
        text = (result.text or "").strip()
        if text and not result.error and text not in _AGENT_TURN_ERRORS:
            db.execute("UPDATE tasks SET summary_text = ? WHERE id = ?", (text, task_id))
    except Exception:
        logger.exception("Computer completion turn for %s raised — delivering without re-running", task_id)
    finalize(task_id, tool_log=tool_log)


def finalize(task_id: str, *, tool_log: list | tuple = ()) -> None:
    """Idempotent tail: save the vc-<id> message, deliver to the task's route, mark done."""
    from core.agents.scheduled_actions.processor import SILENT_MARKER, deliver_background_result

    task = db.get_task(task_id)
    text = task["summary_text"] or _fixed_line(task)
    if text.strip().upper() != SILENT_MARKER:
        if task["conversation_id"] and task["agent_slug"]:
            try:
                from agents.engine import get_chat_service
                get_chat_service(task["agent_slug"]).save_message(
                    task["conversation_id"], msg_id=f"vc-{task_id}", role="assistant",
                    content=f"[Computer task {task_id}] {text}",
                )
            except Exception:
                logger.warning("Computer task %s: saving to conversation failed", task_id, exc_info=True)
        deliver_background_result(
            task["agent_slug"], "Computer task finished", text, tool_log=tool_log,
            route=json.loads(task["route"]) if task["route"] else None,
        )
    db.execute("UPDATE tasks SET completion_status = 'done' WHERE id = ?", (task_id,))


def orphan_outcome(task: dict) -> tuple[str, str]:
    """Where a dead worker's task ends up. A consequential action whose response never came back is
    `outcome_unknown` (PR 4 marks the gate `dispatching` with the action id before sending it);
    everything else — a model call or the gap between steps — is `failed` "interrupted", and a
    reservation made for an unfinished model call stays charged."""
    if task["phase"] == "action" and task["pending_action_id"] and db.query(
            "SELECT 1 FROM gates WHERE task_id = ? AND status = 'dispatching' AND action_id = ?",
            (task["id"], task["pending_action_id"])):
        return "outcome_unknown", "the worker died during a consequential action; check the site"
    return "failed", "interrupted"


def sweep() -> None:
    """Scheduler job (60 s): policy cancels, orphans, usage rows, completion recovery, then kick the runner."""
    from . import runner
    conn = db.get_db()

    for r in db.query("SELECT id, agent_slug FROM tasks WHERE status = 'queued'"):
        err = card.policy_error(r["agent_slug"])
        if err:
            db.finish_task(r["id"], "cancelled", "disabled", notify=True, error=err)

    for r in db.query("SELECT * FROM tasks WHERE status = 'running' AND heartbeat_at < datetime('now', ?)",
                      (f"-{ORPHAN_MINUTES} minutes",)):
        status, reason = orphan_outcome(dict(r))
        db.finish_task(r["id"], status, reason, notify=True)

    for r in db.query("SELECT id FROM tasks WHERE accounting_pending = 1 AND status IN "
                      f"({','.join('?' * len(db.TERMINAL_STATUSES))})", db.TERMINAL_STATUSES):
        record_usage(r["id"])

    for r in db.query("SELECT id FROM tasks WHERE completion_status = 'pending'"):
        submit(r["id"])

    for r in db.query(
        "SELECT id FROM tasks WHERE completion_status = 'running' AND completion_claimed_at < datetime('now', ?)",
        (f"-{STALE_COMPLETION_MINUTES} minutes",),
    ):
        # Re-claim so two overlapping sweeps can't both finalize; the turn is never re-run.
        with db.write_lock():
            n = conn.execute(
                "UPDATE tasks SET completion_claimed_at = datetime('now') WHERE id = ? "
                "AND completion_status = 'running' AND completion_claimed_at < datetime('now', ?)",
                (r["id"], f"-{STALE_COMPLETION_MINUTES} minutes"),
            ).rowcount
            conn.commit()
        if n:
            try:
                finalize(r["id"])
            except Exception:
                logger.exception("Computer completion recovery %s failed", r["id"])

    runner.kick()
