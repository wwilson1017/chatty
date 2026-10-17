"""Chatty — the computer's agent tools.

computer_task / computer_task_get / computer_task_list / computer_task_cancel /
computer_file_get / computer_info. All `writes: False`: the tools gate themselves
(policy, priced helper model, chain caps, own-task ownership) and every
consequential action on the computer stops for the owner's approval anyway —
with writes: True they would vanish from Telegram and route through the
browser-held web confirmation.

Every executor takes the server-built `_ctx` ToolRegistry injects for
`context_aware` tools: {agent_slug, agent_name, conversation_id, origin, route,
action_id, cache_dir}. Nothing in it comes from the model.
"""

import logging
import mimetypes

from core.agents.tools.file_cache import cache_file, load_cached_file

from . import card, db, runner
from .client import ComputerError, get_client

logger = logging.getLogger(__name__)

TASK_MAX_CHARS = 8000
MAX_FILE_REFS = 10


def _own_task(task_id: str, agent_slug: str) -> dict | None:
    task = db.get_task(task_id)
    return task if task and task["agent_slug"] == agent_slug else None


def _chain_cap_error(root_task_id: str) -> str | None:
    t = db.chain_totals(root_task_id)
    if t["steps"] >= db.MAX_STEPS or t["seconds"] >= db.MAX_SECONDS or t["cost"] >= db.BUDGET_USD:
        return (f"That task chain has used its allowance ({t['steps']} steps, ${t['cost']:.2f}, "
                f"{t['seconds'] / 60:.0f} min). Start a new task instead of a follow-up.")
    return None


async def computer_task(task: str, follow_up_of: str | None = None, file_refs: list[str] | None = None,
                        *, _ctx: dict) -> dict:
    slug, origin = _ctx["agent_slug"], _ctx["origin"]
    task = (task or "").strip()
    if not task:
        return {"error": "task is required"}
    if len(task) > TASK_MAX_CHARS:
        return {"error": f"task is too long ({len(task)} chars, max {TASK_MAX_CHARS})"}
    err = card.policy_error(slug)
    if err:
        return {"error": err}
    model = card.helper_model()
    err = card.helper_model_error(model)
    if err:
        return {"error": err}
    if not runner.is_active():
        return {"error": "The computer helper isn't running: tasks run inside Chatty's web server, not the CLI "
                         "harness. Start the server (python run.py) and try again."}
    parent = None
    if follow_up_of:
        parent = _own_task(follow_up_of, slug)
        if not parent:
            return {"error": f"No task {follow_up_of} for this agent."}
        if parent["status"] not in db.TERMINAL_STATUSES:
            return {"error": f"Task {follow_up_of} hasn't finished yet — wait for it, or cancel it first."}
        err = _chain_cap_error(parent["root_task_id"])
        if err:
            return {"error": err}

    inbox: list[str] = []
    if file_refs:
        if len(file_refs) > MAX_FILE_REFS:
            return {"error": f"at most {MAX_FILE_REFS} file_refs per task"}
        client = get_client()
        try:
            for ref in file_refs:
                f = load_cached_file(_ctx.get("cache_dir") or "", str(ref))
                if not f:
                    return {"error": f"file_ref {ref!r} is unknown or expired"}
                path = f"inbox/{runner.safe_filename(f['filename'])}"
                await client.put_file(slug, path, f["raw"])
                inbox.append(f"/workspace/{slug}/{path}")
        except ComputerError as e:
            return {"error": f"Couldn't copy files to the computer: {e.detail}"}
        finally:
            await client.aclose()
    if inbox:
        task += "\n\nFiles for this task are in: " + ", ".join(inbox)

    task_id = db.insert_task(
        agent_slug=slug, origin=origin, task=task, helper_provider=card.provider_for_model(model), helper_model=model,
        conversation_id=_ctx.get("conversation_id"), route=_ctx.get("route"), action_id=_ctx.get("action_id"),
        parent=parent,
    )
    runner.kick()
    return {
        "task_id": task_id,
        "status": "queued",
        "helper_model": model,
        "inbox_files": inbox,
        "note": ("Queued; the helper runs tasks one at a time and you'll get a follow-up turn with the result — "
                 "don't poll. Anything that buys, sends, posts, deletes or submits stops for the owner's approval."),
    }


def computer_task_get(task_id: str, *, _ctx: dict) -> dict:
    task = _own_task(task_id, _ctx["agent_slug"])
    if not task:
        return {"error": f"No task {task_id} for this agent."}
    out = db.task_view(task, result_chars=20000)
    if task["gate_id"]:
        gate = db.get_gate(task["gate_id"])
        out["gate"] = db.gate_view(gate) if gate else None
    return out


def computer_task_list(status: str | None = None, limit: int = 10, *, _ctx: dict) -> dict:
    limit = max(1, min(int(limit or 10), 50))
    sql = "SELECT * FROM tasks WHERE agent_slug = ?"
    params: list = [_ctx["agent_slug"]]
    if status:
        sql += " AND status = ?"
        params.append(status)
    rows = db.query(sql + " ORDER BY created_at DESC, rowid DESC LIMIT ?", (*params, limit))
    return {"tasks": [db.task_view(dict(r), result_chars=300) for r in rows]}


def computer_task_cancel(task_id: str, *, _ctx: dict) -> dict:
    task = _own_task(task_id, _ctx["agent_slug"])
    if not task:
        return {"error": f"No task {task_id} for this agent."}
    if not db.finish_task(task_id, "cancelled", "cancelled by agent", notify=False, cancel_requested=1):
        return {"error": f"Task {task_id} already finished ({task['status']})."}
    return {"ok": True, "task_id": task_id, "status": "cancelled"}


async def computer_file_get(path: str, *, _ctx: dict) -> dict:
    """Fetch a file the helper left under /workspace/<agent> into the chat file cache and return a
    file_ref, so Drive/Gmail tools can send it on."""
    slug = _ctx["agent_slug"]
    err = card.policy_error(slug)
    if err:
        return {"error": err}
    path = (path or "").strip()
    if not path:
        return {"error": "path is required"}
    client = get_client()
    try:
        raw, name = await client.get_file(slug, path)
    except ComputerError as e:
        return {"error": e.detail}
    finally:
        await client.aclose()
    mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
    ref = cache_file(_ctx["cache_dir"], raw, name, mime)
    return {"file_ref": ref, "filename": name, "mime_type": mime, "size_bytes": len(raw)}


def computer_info(*, _ctx: dict) -> dict:
    c = card.creds()
    counts = {r["status"]: r["n"] for r in db.query("SELECT status, COUNT(*) AS n FROM tasks WHERE status IN ('queued','running') GROUP BY status")}
    return {
        "configured": bool(c) and card.policy_error(_ctx["agent_slug"]) != "The computer is not set up or is turned off.",
        "enabled_for_this_agent": card.policy_error(_ctx["agent_slug"]) is None,
        "runner_active": runner.is_active(),
        "helper_model": card.helper_model(),
        "queued": counts.get("queued", 0),
        "running": counts.get("running", 0),
        "caps_per_task_chain": {"steps": db.MAX_STEPS, "seconds": db.MAX_SECONDS, "budget_usd": db.BUDGET_USD},
        "workspace": f"/workspace/{_ctx['agent_slug']}",
    }


_TASK_ID = {"type": "string", "description": "Task id returned by computer_task"}

COMPUTER_TOOL_DEFS = [
    {
        "name": "computer_task",
        "description": (
            "Hand a task to the helper that operates the owner's virtual computer (Chromium, a shell, files). "
            "Use it for anything that needs a real browser or desktop: looking something up on a site, filling a "
            "cart, downloading a report, running a program. Brief it like a capable colleague with none of your "
            "context: the goal, the facts it needs, what done looks like. It runs asynchronously — you'll get a "
            "follow-up turn with the result; don't poll. The helper never buys, sends, posts, deletes or submits "
            "without the owner's approval: it stops at that point and reports. To continue a finished task, pass "
            "follow_up_of=<task_id>. Chat attachments go along as file_refs (copied to /workspace/<agent>/inbox)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "task": {"type": "string", "description": f"Full brief (max {TASK_MAX_CHARS} chars)"},
                "follow_up_of": {"type": "string", "description": "Task id to continue"},
                "file_refs": {"type": "array", "items": {"type": "string"},
                              "description": "file_refs from chat attachments or other tools"},
            },
            "required": ["task"],
        },
        "kind": "integration",
        "writes": False,
        "context_aware": True,
    },
    {
        "name": "computer_task_get",
        "description": "Get a computer task's status, result and (if it stopped for approval) what it was about to do.",
        "input_schema": {"type": "object", "properties": {"task_id": _TASK_ID}, "required": ["task_id"]},
        "kind": "integration",
        "writes": False,
        "context_aware": True,
    },
    {
        "name": "computer_task_list",
        "description": "List your recent computer tasks, newest first.",
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": list(db.ACTIVE_STATUSES + db.TERMINAL_STATUSES)},
                "limit": {"type": "integer", "description": "Max tasks (default 10, max 50)"},
            },
            "required": [],
        },
        "kind": "integration",
        "writes": False,
        "context_aware": True,
    },
    {
        "name": "computer_task_cancel",
        "description": "Cancel one of your queued or running computer tasks.",
        "input_schema": {"type": "object", "properties": {"task_id": _TASK_ID}, "required": ["task_id"]},
        "kind": "integration",
        "writes": False,
        "context_aware": True,
    },
    {
        "name": "computer_file_get",
        "description": (
            "Fetch a file from your folder on the computer (/workspace/<agent>/…, e.g. downloads/report.pdf) into "
            "the chat file cache. Returns a file_ref you can pass to Drive, Gmail or other file-aware tools."
        ),
        "input_schema": {"type": "object", "properties": {"path": {"type": "string", "description": "Relative to your workspace folder"}},
                         "required": ["path"]},
        "kind": "integration",
        "writes": False,
        "context_aware": True,
    },
    {
        "name": "computer_info",
        "description": "Whether the computer is available to you, which helper model drives it, the queue, and the task caps.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
        "kind": "integration",
        "writes": False,
        "context_aware": True,
    },
]

TOOL_EXECUTORS = {
    "computer_task": computer_task,
    "computer_task_get": computer_task_get,
    "computer_task_list": computer_task_list,
    "computer_task_cancel": computer_task_cancel,
    "computer_file_get": computer_file_get,
    "computer_info": computer_info,
}
