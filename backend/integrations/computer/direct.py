"""
Chatty — the agent drives its computer itself, in its own turn.

computer_browser / computer_shell / computer_files run the helper's own tools
(runner._Run.execute → tool_browser / tool_shell / tool_files: gates, the action
journal, the step log) from the agent's turn, with no helper model and no helper
caps. A turn's first call opens a *direct session*: a task row with
driver='agent', inserted running for worker direct:<pid>:<turn_id> (the runner
never claims it), and a _Run that takes the screen lease, renews it, and never
resends (notify, retry_epoch and renew_adopts_epoch all False). So the card shows
each session and its steps, a gate opens the usual approval card (the session
ends needs_approval; approving queues a follow-up that makes that one click and
gives the agent a turn), and the sweep cleans up after a crash.

What the helper loop does around its tools, this module does itself: policy and
liveness before every call; once a gate opens, every computer call for the rest
of the turn is refused (computer_task included); at most MAX_ACTIONS calls per
turn; and a ref is used only while the latest snapshot belongs to this session
and its current epoch. The epoch is pinned per operation (run.op_lock): adopted
at an operation's start, or from a stale_epoch refusal that ends the operation.

A session ends at the turn's end (ToolRegistry.aclose → close_turn), when the
agent hands work to the helper (computer_task → hand_off), after IDLE_S without a
call, or when the lease is lost (the next call opens a new one).
"""

import asyncio
import logging
import os
import time

from core.agents.tool_registry import TURN_END_HOOKS

from . import card, db, runner
from .client import ComputerError, get_client

logger = logging.getLogger(__name__)

BUSY_WAIT_S = 30    # how long a first call waits for another task to free the screen
BUSY_POLL_S = 3
IDLE_S = 90         # a session idle this long closes itself, in case the turn-end hook never runs
MAX_ACTIONS = 100   # direct computer calls per turn

STALE_REF = ("That ref isn't from your latest snapshot in this session, or the screen changed hands since. "
             "Take a fresh snapshot and use its refs.")


class _Session:
    """One open direct session: the _Run, its renew and idle tasks, and whether a call is in flight."""

    def __init__(self, run: runner._Run):
        self.run = run
        self.renew: asyncio.Task | None = None
        self.idle: asyncio.Task | None = None
        self.inflight = False
        self.last_end = time.monotonic()
        self.closed = False


class _Turn:
    """Turn-scoped state, kept apart from the session so closing or replacing one can't reset it."""

    def __init__(self):
        self.lock = asyncio.Lock()  # one session opening at a time
        self.session: _Session | None = None
        self.actions = 0
        self.blocked: str | None = None  # set once a gate opened (or the session was ended): refuse everything


_turns: dict[str, _Turn] = {}


def refusal(ctx: dict, *, policy: bool = True) -> str | None:
    """Why this turn may not use the computer, or None: a group member who isn't the owner, a gate (or an
    ended session) earlier in this turn, or (`policy`) the card's policy. Every computer tool checks it."""
    if ctx.get("origin") == "group" and not ctx.get("group_owner"):
        return "Only the owner can use the computer from a group."
    turn = _turns.get(ctx.get("turn_id") or "")
    if turn and turn.blocked:
        return turn.blocked
    return card.policy_error(ctx["agent_slug"]) if policy else None


async def _open(ctx: dict) -> tuple[_Session | None, str | None]:
    """The session row and its lease, or (None, why not). A row whose screen never came — busy past
    BUSY_WAIT_S, an error, the turn cancelled — is finished here, never left running."""
    client = get_client()
    wid = f"{db.DIRECT_WORKER_PREFIX}{os.getpid()}:{ctx['turn_id']}"
    task_id = db.insert_task(
        agent_slug=ctx["agent_slug"], origin="user" if ctx["origin"] == "user" else "background",
        task="direct session", helper_provider="", helper_model="", conversation_id=ctx.get("conversation_id"),
        route=ctx.get("route"), action_id=ctx.get("action_id"), driver="agent", worker_id=wid,
    )
    run = runner._Run(db.get_task(task_id), wid, client)
    run.notify = run.retry_epoch = run.renew_adopts_epoch = False
    acquired = False
    try:
        deadline = time.monotonic() + BUSY_WAIT_S
        while await run.activate() == "busy":
            if time.monotonic() >= deadline:
                run.finish("failed", "screen busy", error=f"another task held the screen for {BUSY_WAIT_S} s")
                return None, ("The screen is in use by another task right now. Hand this to computer_task "
                              "instead: it queues and runs as soon as the screen is free.")
            await asyncio.sleep(BUSY_POLL_S)
        acquired = True
    except (ComputerError, runner._Stop) as e:
        run.finish("failed", "couldn't take the screen", error=str(e)[:500])
        return None, f"Couldn't take the screen: {e}"[:300]
    finally:
        if not acquired:
            run.finish("cancelled", "the turn ended before the screen was free")  # no-op once finished above
            await client.aclose()
    s = _Session(run)
    s.renew = asyncio.create_task(run.renew_loop())
    return s, None


async def _close(turn: _Turn, s: _Session, status: str = "done", reason: str = "direct session ended", **fields) -> None:
    """Idempotent. Stop renewing; release the screen unless fenced or a call is still in flight; finish
    the row only if it is still running (first write wins, so needs_approval or failed stands)."""
    if turn.session is s:
        turn.session = None
    if s.closed:
        return
    s.closed = True
    tasks = [t for t in (s.renew, s.idle) if t and t is not asyncio.current_task()]
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    if not s.inflight:
        await s.run.release()
    s.run.finish(status, reason, **fields)
    if not s.inflight:
        await s.run.client.aclose()


async def _idle_close(turn: _Turn, s: _Session) -> None:
    """Close the session after IDLE_S without a call. The clock runs from the end of the last call and
    stops while one is in flight, so a long shell command never counts as idle."""
    while True:
        left = IDLE_S - (time.monotonic() - s.last_end)
        if not s.inflight and left <= 0:
            await _close(turn, s, reason=f"idle for {IDLE_S} s")
            return
        await asyncio.sleep(IDLE_S if s.inflight else left)


async def close_turn(turn_id: str) -> None:
    """TURN_END_HOOKS: the turn is over; its session (if any) finishes `done` and frees the screen."""
    turn = _turns.pop(turn_id, None)
    if turn and turn.session:
        await _close(turn, turn.session)


async def hand_off(turn_id: str | None) -> None:
    """computer_task: free the screen so the helper can take it (the agent's browser profile stays as it is)."""
    turn = _turns.get(turn_id or "")
    if turn and turn.session:
        await _close(turn, turn.session, reason="handed to the helper")


async def _call(tool: str, args: dict, ctx: dict) -> dict:
    """One direct call: refusals, the turn's session (opened on first use), then the helper's `tool`
    through _Run.execute under the session's op_lock. The policy is checked before a session opens, and
    for an open one by check_alive(), which also ends it (cancelled: disabled)."""
    err = refusal(ctx, policy=False)
    if err:
        return {"error": err}
    turn = _turns.setdefault(ctx["turn_id"], _Turn())
    if turn.actions >= MAX_ACTIONS:
        return {"error": f"This turn has used {MAX_ACTIONS} computer actions; hand the rest to computer_task."}
    turn.actions += 1
    async with turn.lock:
        s = turn.session
        if s is None:
            err = card.policy_error(ctx["agent_slug"])
            if err:
                return {"error": err}
            s, err = await _open(ctx)
            if err:
                return {"error": err}
            turn.session = s
            s.idle = asyncio.create_task(_idle_close(turn, s))
    run, ended = s.run, None
    async with run.op_lock:
        s.inflight = True
        try:
            run.check_alive()
            if run.latest_epoch and run.latest_epoch != run.epoch:  # the screen changed hands between calls
                run.epoch, run.latest_epoch = run.latest_epoch, None
                run.observed.clear()
            seen = run.observed.get("snapshot")
            if args.get("ref") and (not seen or seen[0] != run.epoch):
                return {"error": STALE_REF, "code": "stale_ref"}
            await run.execute({"name": tool, "args": args})
            result = run.last_result
        except runner._Fenced:
            ended = "fenced"
        except runner._Stop:
            ended = "stopped"
        finally:
            s.inflight = False
            s.last_end = time.monotonic()
    if ended == "fenced":
        await _close(turn, s, "failed", "lost the screen", error="the screen lease was lost; nothing was retried")
        return {"error": "Lost the screen (its lease ended); nothing was retried. Your next computer call starts a "
                         "new session: take a fresh snapshot first."}
    if ended or run.finished:  # cancelled or turned off, or a gate (or a failed pre-approved click) ended the session
        await _close(turn, s)
        row = db.get_task(run.id) or {}
        if row.get("status") == "needs_approval" and run.gate_id:
            gate = db.get_gate(run.gate_id) or {}
            turn.blocked = (f"Waiting for the owner's approval of gate {run.gate_id}; no more computer calls "
                            "this turn.")
            return {
                "stopped": (f"Needs your approval ({gate.get('kind')}: {gate.get('name') or gate.get('action')}). "
                            "I've sent the card. When it's approved, the click is made and you'll get the outcome "
                            "as a new message."),
                "gate_id": run.gate_id,
                "note": ("Nothing was clicked. Tell the user it's waiting for their approval (Telegram or the "
                         "Computer card) and don't try it another way. The computer is off for the rest of this turn."),
            }
        turn.blocked = (f"The computer session ended ({row.get('status')}: {row.get('finish_reason')}); "
                        "no more computer calls this turn.")
        return {"error": turn.blocked}
    return result


# ── tool definitions ─────────────────────────────────────────────────────────

_SCHEMAS = {d["name"]: d["input_schema"] for d in runner.TOOL_DEFS}
_HAND_OFF = (f" A turn can make up to {MAX_ACTIONS} computer calls. Use these tools for quick or interactive work; "
             "hand chores of more than about 20 steps, or anything that needn't finish in this conversation, to "
             "computer_task ({helper_model} does it in the background, in the same browser, with its own caps).")


def _tool(name: str, helper_tool: str, description: str) -> dict:
    return {"name": name, "description": description + _HAND_OFF, "input_schema": _SCHEMAS[helper_tool],
            "kind": "integration", "writes": False, "context_aware": True, "extends_turn": True, "always_loaded": True}


TOOL_DEFS = [
    _tool("computer_browser", "browser", (
        "Drive your computer's Chromium yourself, right now (your own browser profile, so your logins). `snapshot` "
        "returns the page as an accessibility tree with refs like e12; a ref is good only for your latest snapshot. "
        "click/fill/type/press/select/hover/scroll act on a ref (press/type act on the focused element without one); "
        "navigate/back/forward/reload move the tab; tabs lists, opens (url), switches or closes (index) tabs. Actions "
        "that change the page return a fresh snapshot. Anything that buys, pays, sends, posts, deletes or submits "
        "stops for the owner's approval: nothing is clicked, they get a card, and once they approve the click is made "
        "and you get the outcome as a new message. Never type passwords or look for saved ones; the owner signs in on "
        "the screen themselves."
    )),
    _tool("computer_shell", "shell", (
        "Run a bash command on your computer as the `computer` user (sudo available), in /workspace/<your slug>. "
        "Output is capped at 64 KB per stream. Never use it to drive the browser (no xdotool, CDP or playwright)."
    )),
    _tool("computer_files", "files", (
        "List, read or write files in your folder on the computer, /workspace/<your slug> (or /workspace/shared); "
        "paths are relative to your folder. To send a file on with Drive or Gmail, use computer_file_get."
    )),
]


def _executor(helper_tool: str):
    async def run(*, _ctx: dict, **args) -> dict:
        return await _call(helper_tool, args, _ctx)
    return run


TOOL_EXECUTORS = {"computer_browser": _executor("browser"), "computer_shell": _executor("shell"),
                  "computer_files": _executor("files")}

TURN_END_HOOKS.append(close_turn)
