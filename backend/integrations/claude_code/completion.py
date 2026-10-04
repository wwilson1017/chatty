"""Chatty — Claude Code job completion: the requesting agent's report-back turn.

The durable queue is the job row's completion_status (none → pending → running
→ done), set to 'pending' by finish_job(notify=True) in the same UPDATE that
makes the job terminal.

Guarantee: the agent turn runs AT MOST ONCE (it may call tools or delegate
again, so it is never re-run); delivery is best-effort. finalize() is the one
idempotent tail shared by the normal path and every recovery path: it upserts
the cc-<job_id> conversation message, delivers, and marks the completion done.
"""

import json
import logging
from concurrent.futures import ThreadPoolExecutor

from core.agents.security.delimiters import wrap_result

from . import db

logger = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="cc-completion")

MAX_PRE_TURN_ATTEMPTS = 3
STALE_COMPLETION_MINUTES = 15  # background turns time out at 5 min
STALE_JOB_MINUTES = 10

_INSTRUCTIONS = {
    "user": (
        "A Claude Code job you started at the user's request has finished. Report the outcome "
        "to the user now: what was done, the key results, and anything they need to do. Be "
        "concise. Mention the job id so they can ask for a follow-up. Always report — never "
        "answer [SILENT]."
    ),
    "background": (
        "A Claude Code job you started on your own (from a scheduled or background task) has "
        "finished. Report it to the user only if the result is worth surfacing; otherwise "
        "respond with exactly [SILENT]."
    ),
}


def _fixed_line(job: dict) -> str:
    return f"Claude Code job {job['id']} finished ({job['status']}) — ask me for the result"


def submit(job_id: str) -> None:
    _executor.submit(_safe_complete, job_id)


def _safe_complete(job_id: str) -> None:
    try:
        complete_job(job_id)
    except Exception:
        logger.exception("Claude Code completion %s failed", job_id)


def _claim(job_id: str) -> bool:
    conn = db.get_db()
    with db.write_lock():
        n = conn.execute(
            "UPDATE jobs SET completion_status = 'running', completion_claimed_at = datetime('now'), "
            "completion_attempts = completion_attempts + 1 "
            "WHERE id = ? AND completion_status = 'pending'",
            (job_id,),
        ).rowcount
        conn.commit()
    return n == 1


def complete_job(job_id: str) -> None:
    if not _claim(job_id):
        return
    job = db.get_job(job_id)

    # Pre-turn: failures here are safe to retry (no tools have run).
    from core.agents.scheduled_actions.processor import _resolve_agent
    agent = _resolve_agent(job["agent_slug"])
    if not agent:
        if job["completion_attempts"] >= MAX_PRE_TURN_ATTEMPTS:
            finalize(job_id)
        else:
            conn = db.get_db()
            with db.write_lock():
                conn.execute("UPDATE jobs SET completion_status = 'pending' WHERE id = ?", (job_id,))
                conn.commit()
        return

    # The turn: invoked at most once. Any exception from here on → finalize, never retry.
    # simplification: "pre-turn" ends where run_agent_background_turn is called, so a
    # context-load failure inside it is not retried; split the helper if that matters.
    tool_log: list = []
    try:
        from core.agents.scheduled_actions.processor import (
            _AGENT_TURN_ERRORS,
            run_agent_background_turn,
        )
        payload = json.dumps({
            "task": job["task"],
            "result_text": (job["result_text"] or "")[:20000],
            "error": job["error"],
        })
        user_message = (
            f"Claude Code job {job['id']} ({job['runner']}, {job['mode']}) finished with status "
            f"'{job['status']}'"
            + (f" ({job['finish_reason']})" if job["finish_reason"] else "")
            + f". Created {job['created_at']} UTC, finished {job['finished_at']} UTC."
            + (f" Session can be continued with follow_up_of='{job['id']}'." if job["session_id"] else "")
            + "\n\n" + wrap_result("job", payload)
        )
        result, _registry = run_agent_background_turn(
            agent, "Claude Code job finished", _INSTRUCTIONS.get(job["origin"], _INSTRUCTIONS["background"]),
            user_message, source="claude_code",
            conversation_id=job["conversation_id"],
            route=json.loads(job["route"]) if job["route"] else None,
        )
        tool_log = result.tool_log
        text = (result.text or "").strip()
        if text and not result.error and text not in _AGENT_TURN_ERRORS:
            conn = db.get_db()
            with db.write_lock():
                conn.execute("UPDATE jobs SET summary_text = ? WHERE id = ?", (text, job_id))
                conn.commit()
    except Exception:
        logger.exception("Claude Code completion turn for %s raised — delivering without re-running", job_id)
    finalize(job_id, tool_log=tool_log)


def finalize(job_id: str, *, tool_log: list | tuple = ()) -> None:
    """Idempotent tail: save the cc-<id> message, deliver to the job's route, mark done."""
    from core.agents.scheduled_actions.processor import (
        SILENT_MARKER,
        deliver_background_result,
    )

    job = db.get_job(job_id)
    text = job["summary_text"] or _fixed_line(job)
    if text.strip().upper() != SILENT_MARKER:
        if job["conversation_id"] and job["agent_slug"]:
            try:
                from agents.engine import get_chat_service
                get_chat_service(job["agent_slug"]).save_message(
                    job["conversation_id"], msg_id=f"cc-{job_id}", role="assistant",
                    content=f"[Claude Code job {job_id}] {text}",
                )
            except Exception:
                logger.warning("Claude Code job %s: saving to conversation failed", job_id, exc_info=True)
        deliver_background_result(
            job["agent_slug"], "Claude Code job finished", text, tool_log=tool_log,
            route=json.loads(job["route"]) if job["route"] else None,
        )
    conn = db.get_db()
    with db.write_lock():
        conn.execute("UPDATE jobs SET completion_status = 'done' WHERE id = ?", (job_id,))
        conn.commit()


def sweep() -> None:
    """Scheduler job: expired approvals, stale running jobs, lost completions, abandoned completions."""
    conn = db.get_db()
    from .approvals import expire_stale
    expire_stale()
    if not db.is_online():
        stale = db.query(
            "SELECT id FROM jobs WHERE status = 'running' AND "
            "COALESCE(last_reported_at, claimed_at) < datetime('now', ?)",
            (f"-{STALE_JOB_MINUTES} minutes",),
        )
        for r in stale:
            db.finish_job(r["id"], "failed", "connector stopped reporting", notify=True)

    for r in db.query("SELECT id FROM jobs WHERE completion_status = 'pending'"):
        submit(r["id"])

    for r in db.query(
        "SELECT id FROM jobs WHERE completion_status = 'running' AND completion_claimed_at < datetime('now', ?)",
        (f"-{STALE_COMPLETION_MINUTES} minutes",),
    ):
        # Re-claim so two overlapping sweeps can't both finalize; the turn is never re-run.
        with db.write_lock():
            n = conn.execute(
                "UPDATE jobs SET completion_claimed_at = datetime('now') WHERE id = ? "
                "AND completion_status = 'running' AND completion_claimed_at < datetime('now', ?)",
                (r["id"], f"-{STALE_COMPLETION_MINUTES} minutes"),
            ).rowcount
            conn.commit()
        if n:
            try:
                finalize(r["id"])
            except Exception:
                logger.exception("Claude Code completion recovery %s failed", r["id"])
