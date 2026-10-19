"""
Chatty — the helper loop: one worker drives the computer for one task at a time.

The pool has one thread (the process-level lock), `start()` takes an exclusive
flock so one Chatty process owns the queue, and the computer's screen lease is
the real lock across overlapping deploys. Two backends: text mode (any provider;
the helper sees aria snapshots and acts through refs) and screenshot mode
(Anthropic's computer_toolset_20260801 through the SDK; the helper sees the screen
and clicks by pixel — _Run.screenshot_loop / batch / pixel). card.mode_for picks.

Every checked action is classified by gates.classify() BEFORE it is sent. A gate
ends the task as `needs_approval` and asks the owner (approvals.py); approving
queues a follow-up whose first step is _Run.consume(): one activation bound to
the stored gate, re-checked by the computer, never re-sent. A gate that can't be
bound becomes a takeover task (_Run.takeover) that opens the page for the owner
and performs nothing itself. A gate a scheduled action pre-approved
(preapprovals.match: host + button text, never a purchase) is recorded already
approved and dispatched at once. Logins never go through the helper either:
`request_takeover` hands the screen to the owner and waits
(tool_request_takeover), the computer refusing every agent call meanwhile.

Caps cover the whole follow-up chain (root_task_id): steps and time are hard;
money is a budget enforced on conservative reservations saved before each
model call (see _reserve). Nothing here makes a task terminal except
db.finish_task().
"""

import asyncio
import base64
import fcntl
import json
import logging
import math
import re
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit

from core.agents.security.delimiters import DELIMITER_SYSTEM_INSTRUCTION, wrap_result
from core.config import settings
from core.providers import get_ai_provider
from core.providers.pricing import get_max_rates, rates_for_prompt

from . import approvals, card, db, gates, preapprovals
from .client import ComputerClient, ComputerError, get_client

logger = logging.getLogger(__name__)

RENEW_EVERY_S = 30
CONTROL_POLL_S = 2
TAKEOVER_WAIT_S = 15 * 60  # how long the screen is held for the owner to take it (request_takeover and takeover tasks)
BUSY_RETRY_S = 5
RECONCILE_WAIT_S = 5       # between the two journal reads after a lost response
MODEL_TIMEOUT_S = 300
SHELL_DEFAULT_S = 120
SHELL_MAX_S = 600
SNAPSHOT_CHARS = 20000
FILE_READ_CHARS = 60000
DEFAULT_MAX_TOKENS = 8192
MIN_OUTPUT_TOKENS = 256
CACHE_WRITE_MARGIN = 1.25  # a cache write bills 1.25× the input rate; the reservation assumes every token is one

# Screenshot mode (Anthropic). The toolset entry takes no name or display size; calls arrive as
# tool_use blocks named by member with toolset_name "computer", and every result echoes it.
TOOLSET = {"type": "computer_toolset_20260801"}
# Old screenshots are cleared by the API (context editing), never pruned here: removing one would
# invalidate every later thinking block. Trigger well under the model's window; keep the last few.
CONTEXT_BETA = "context-management-2025-06-27"
CONTEXT_EDITS = [{"type": "clear_tool_uses_20250919", "trigger": {"type": "input_tokens", "value": 40000},
                  "keep": {"type": "tool_uses", "value": 5}, "clear_at_least": {"type": "input_tokens", "value": 8000}}]
SKIPPED = "skipped: an earlier action needs approval or failed"
CUT_OFF = "the model's reply was cut off at max_tokens"
SHOT_TTL_DAYS = 14  # a task's screenshots (step and gate) are deleted this long after it finished

_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="computer-runner")
_lock_file = None
_started = False
_stopping = False  # stop() asked the worker to end its task at the next step
_idle = threading.Event()  # clear while the worker thread is draining
_idle.set()
_inflight: tuple[asyncio.AbstractEventLoop, asyncio.Task] | None = None  # the running task's loop + task, for stop()
_drain_lock = threading.Lock()
_draining = False
CANCEL_WAIT_S = 10


# ── process lifecycle ────────────────────────────────────────────────────────

def start() -> bool:
    """Web-app lifespan only (never the CLI). Takes the exclusive runner lock and runs the queue;
    False when another process already holds it."""
    global _lock_file, _started, _stopping
    db.DATA_DIR.mkdir(parents=True, exist_ok=True)
    f = open(db.DATA_DIR / "runner.lock", "a+")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.close()
        logger.warning("Computer runner: another process holds %s; this one runs no tasks", db.DATA_DIR / "runner.lock")
        return False
    _lock_file = f
    _started = True
    _stopping = False
    kick()
    return True


def stop(wait_s: float = 0) -> bool:
    """Stop claiming and ask a running task to end at its next step ("interrupted"). If it is
    still inside a model or shell call after `wait_s`, cancel its coroutine: the task writes
    nothing more (its lease is still released; the sweep marks it interrupted later) and the
    worker thread is joined. Then release the lock. Returns whether the worker is idle."""
    global _lock_file, _started, _stopping
    _started = False
    _stopping = True
    idle = _idle.wait(wait_s) if wait_s else _idle.is_set()
    if not idle and wait_s:
        inflight = _inflight
        if inflight:
            loop, task = inflight
            loop.call_soon_threadsafe(task.cancel)
        idle = _idle.wait(CANCEL_WAIT_S)
    if _lock_file:
        fcntl.flock(_lock_file, fcntl.LOCK_UN)
        _lock_file.close()
        _lock_file = None
    return idle


def is_active() -> bool:
    """Whether a runner holds the lock — this process or another (the web app, while the CLI
    harness only initializes the store). A queued task runs only if this is True."""
    if _started:
        return True
    path = db.DATA_DIR / "runner.lock"
    if not path.exists():
        return False
    with open(path, "a+") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return True
        fcntl.flock(f, fcntl.LOCK_UN)
    return False


def kick() -> bool:
    """Drain the queue on the worker thread if this process owns it and isn't already draining."""
    global _draining
    if not _started:
        return False
    with _drain_lock:
        if _draining:
            return True
        _draining = True
    _pool.submit(_drain_safe)
    return True


def _drain_safe() -> None:
    global _draining
    _idle.clear()
    try:
        _drain()
    except Exception:
        logger.exception("Computer runner: drain failed")
    finally:
        with _drain_lock:
            _draining = False
        _idle.set()
    # simplification: a task queued between the last empty claim and the flag reset waits for
    # the 60 s sweep's kick; upgrade: loop until a claim under _drain_lock finds nothing


def _run_cancellable(coro):
    """asyncio.run() with the task recorded so stop() can cancel it from another thread."""
    global _inflight
    loop = asyncio.new_event_loop()
    try:
        task = loop.create_task(coro)
        _inflight = (loop, task)
        return loop.run_until_complete(task)
    finally:
        _inflight = None
        loop.close()


def _drain() -> None:
    wid = db.worker_id()
    while _started:
        task = db.claim_next(wid)
        if not task:
            return
        try:
            outcome = _run_cancellable(run_task(task, wid))
        except asyncio.CancelledError:
            logger.info("Computer task %s cancelled by stop(); the sweep marks it interrupted", task["id"])
            return
        if outcome == "busy":
            time.sleep(BUSY_RETRY_S)  # the task is queued again; another agent holds the screen


# ── the helper's tools ───────────────────────────────────────────────────────

TOOL_DEFS = [
    {
        "name": "browser",
        "description": (
            "Drive the computer's Chromium. `snapshot` returns the page as an accessibility tree with refs "
            "like e12; refs come from the LATEST snapshot only. click/fill/type/press/select/hover/scroll "
            "act on a ref (press/type act on the focused element when ref is omitted). navigate/back/"
            "forward/reload move the tab; tabs lists, opens (url), switches (index) or closes (index) tabs. "
            "Actions that change the page return a fresh snapshot."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["snapshot", "navigate", "click", "fill", "type", "press", "select",
                                                     "hover", "scroll", "back", "forward", "reload", "tabs"]},
                "ref": {"type": "string"},
                "text": {"type": "string", "description": "fill/type: the text"},
                "key": {"type": "string", "description": "press: e.g. Enter, Tab, ArrowDown, Control+a"},
                "value": {"type": "string", "description": "select: the option value"},
                "url": {"type": "string", "description": "navigate / tabs open"},
                "index": {"type": "integer", "description": "tabs switch/close"},
                "tab_action": {"type": "string", "enum": ["list", "open", "switch", "close"]},
                "dy": {"type": "integer", "description": "scroll: pixels (positive = down) when no ref"},
            },
            "required": ["action"],
        },
    },
    {
        "name": "shell",
        "description": (
            "Run a bash command on the computer as the `computer` user (sudo available), cwd "
            "/workspace/<agent>. Output is capped at 64 KB per stream. Never use it to drive the browser."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "timeout": {"type": "integer", "description": f"seconds, default {SHELL_DEFAULT_S}, max {SHELL_MAX_S}"},
                "cwd": {"type": "string"},
            },
            "required": ["command"],
        },
    },
    {
        "name": "files",
        "description": "List, read or write files under /workspace/<agent> (or /workspace/shared). Paths are relative to the agent's folder.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["list", "read", "write"]},
                "path": {"type": "string"},
                "content": {"type": "string", "description": "write: the text to save"},
            },
            "required": ["action", "path"],
        },
    },
    {
        "name": "request_approval",
        "description": (
            "Declare the consequential action you are about to take (buy/pay, send, post, delete, submit a form), "
            "then take it with ONE plain click or key press. Chatty stops that action for the owner's approval and "
            "shows your details next to what it read from the page; a follow-up task performs it once approved. "
            "For a purchase give item, store and total exactly as the page shows them — a total that differs from "
            "the page's total is refused."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": list(gates.KINDS)},
                "reason": {"type": "string", "description": "what you are about to do and why"},
                "item": {"type": "string"},
                "store": {"type": "string"},
                "total": {"type": "string", "description": "e.g. $45.00"},
            },
            "required": ["kind", "reason"],
        },
    },
    {
        "name": "request_takeover",
        "description": (
            "Call this when the page needs the owner in person: a sign-in, a 2FA code, a CAPTCHA. The owner is "
            "told why and gets a link to the screen; the task waits (up to 15 min) while they do it, and you "
            "continue from a fresh snapshot once they press I'm done. Never ask for or type passwords yourself."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "reason": {"type": "string", "description": "what the owner needs to do, e.g. 'sign in to shop.example'"},
            },
            "required": ["reason"],
        },
    },
]

HANDBACK_NOTE = ("The person is done and handed the screen back. The screen may have changed: work from this fresh "
                 "snapshot. Never ask for or type the password yourself.")

_SEEING = {
    "text": "- Work from snapshots. Refs (e12, f1e3) are valid only for the latest snapshot; take a new one when the page changed.\n",
    "screenshot": (
        "- Work from screenshots: the screen is 1280×800 and coordinates are screen pixels. The browser tool is there "
        "too — snapshot for a page's exact text, act on a ref for a reliable click on a named control (refs are valid "
        "only for the latest snapshot). Several actions in one turn run in order and stop at the first that fails or "
        "needs approval.\n"
    ),
}

_RULES = (
    "- Consequential actions — buying or paying, sending, posting, deleting, submitting a form, confirming — need the "
    "owner's approval. Call request_approval(kind, reason, item/store/total) right before such a click, then make the "
    "click (one plain click or Enter, never a double click): Chatty stops it there, asks the owner, and a follow-up "
    "task performs it once approved. Chatty also checks every click itself; a stop at an approval point is expected, "
    "not an error. Do everything up to that point (fill the cart, write the message) and let the task stop there.\n"
    "- Drafts: when asked to write an email, post or message, write it and leave it unsent.\n"
    "- Passwords and keys: never type them, never look for saved ones, never ask the owner for them. If a site "
    "needs a sign-in, a 2FA code or a CAPTCHA, call request_takeover(reason): the owner does it on the screen "
    "and you continue afterwards.\n"
    "- Never drive Chrome from the shell (no xdotool, CDP, 127.0.0.1:9222, playwright). The shell is for files and "
    "command-line work.\n"
    "- Be economical: one snapshot per page state, no busy-waiting loops. The task chain is capped at "
    f"{db.MAX_STEPS} steps, ${db.BUDGET_USD:.0f} and {db.MAX_SECONDS // 3600} h.\n"
    "- Finish with a plain-text report: what you did, what you found, where files are (/workspace/<agent>/…), and "
    "anything left undone. Your final message goes to the agent verbatim.\n"
)


def build_system_prompt(agent_name: str, slug: str, mode: str = "text") -> str:
    return (
        f"You are the computer helper working for {agent_name}, a Chatty agent. You operate a Linux desktop "
        f"(Chromium, bash, files under /workspace/{slug}) to complete ONE task for the agent, then report back.\n\n"
        "# Rules\n" + _SEEING[mode] + _RULES + "\n" + DELIMITER_SYSTEM_INSTRUCTION
    )


def anthropic_client(provider):
    """The SDK client for the helper's Anthropic credentials (count_tokens, and the screenshot backend)."""
    from core.providers.anthropic_provider import _get_client
    return _get_client(provider.api_key, provider.auth_token)


def _countable(messages: list) -> list:
    """Messages with image data swapped for a placeholder worth ~1,500 tokens (a 1280×800 screenshot),
    so the chars ÷ 2 estimate counts a screenshot as a screenshot, not as 200 KB of base64."""
    def fix(x):
        if isinstance(x, dict):
            return {"type": "image", "data": "x" * 3000} if x.get("type") == "image" else {k: fix(v) for k, v in x.items()}
        return [fix(v) for v in x] if isinstance(x, list) else x
    return fix(messages)


def build_user_message(task: dict, parent: dict | None) -> str:
    if not parent:
        return task["task"]
    return (
        f"This is a follow-up of task {parent['id']}.\n\n## Original task\n{parent['task']}\n\n"
        f"## What the previous run reported ({parent['status']}{': ' + parent['finish_reason'] if parent['finish_reason'] else ''})\n"
        f"{(parent['result_text'] or '(no report)')[:6000]}\n\n## Now\n{task['task']}"
    )


def takeover_url(task_id: str, slug: str) -> str:
    return f"{settings.frontend_url.rstrip('/')}/computer?task={task_id}&agent={slug}"


def notify_takeover(task: dict, reason: str) -> None:
    """Tell the owner the helper needs them: the reason, the agent and the viewer link — to the chat the
    task came from (Telegram gets a URL button only when the link is https; Telegram refuses the rest),
    otherwise every notification channel. A Telegram group is never told: the link goes to the owner's
    private chat instead. A failed send is logged, not fatal: the card and the viewer are always there.
    The reason is the helper's words about an untrusted page, so it never renders."""
    from agents.db import get_agent_by_slug
    slug = task["agent_slug"]
    agent = get_agent_by_slug(slug) or {}
    url = takeover_url(task["id"], slug)
    title = f"{agent.get('agent_name') or slug} needs you on the computer"
    text = (f"{reason}\n\nOpen the screen, press Take control, do it there, then press I'm done. "
            f"The helper sees nothing you type.\n{url}")
    route = json.loads(task["route"]) if task["route"] else {}
    try:
        chat = approvals.owner_telegram_chat(task, agent) if route.get("channel") == "telegram" else None
        if chat and agent.get("telegram_bot_token"):
            from integrations.telegram.client import send_message
            markup = {"inline_keyboard": [[{"text": "Open the screen", "url": url}]]} if url.startswith("https://") else None
            send_message(chat, f"{title}\n\n{text}", agent["telegram_bot_token"], reply_markup=markup, plain=True)
        elif route.get("channel") == "whatsapp":
            from integrations.whatsapp.client import send_message
            send_message(route["chat_id"], f"*{title}*\n\n{text}")
        else:
            from core.agents.notifications.delivery import deliver_notification
            deliver_notification(slug, title, text)
    except Exception:
        logger.warning("Computer task %s: takeover notice failed", task["id"], exc_info=True)


class _Stop(Exception):
    """The task is over (finished by us or by someone else): unwind without further calls."""


class _Fenced(_Stop):
    """The lease is gone: send nothing more to the computer."""


class _Paused(Exception):
    """A desktop call was refused because a person had control; control has since ended."""


class _EpochChanged(Exception):
    """A run that never resends (a direct session) was refused `stale_epoch`: the screen changed hands, the
    new epoch is adopted, and the whole operation stops there. Not a ComputerError, so no handler that
    swallows those (pixel_action's preliminary snapshot) carries on under the new epoch."""


EPOCH_CHANGED = {"error": "not performed: the screen changed hands (a person used it, or it was taken over) since "
                          "your last look; take a fresh snapshot before acting again", "code": "stale_epoch"}
MARK_NAME_CHARS = 80  # the computer cuts a mark's name to this many characters
BOX_TOLERANCE_PX = 4  # and checks `expect.box` against the live control within this


def mark_moved(want: dict, element: dict) -> bool:
    """Whether the control under a mark's pixel is no longer the marked one: role, name (a prefix when the
    mark's name was cut) and a screen box within BOX_TOLERANCE_PX. Two identical look-alikes in the same
    place can't be told apart."""
    def norm(s) -> str:
        return " ".join(str(s or "").split()).lower()
    name, have = norm(want.get("name")), norm(element.get("name"))
    if not element.get("found") or element.get("role") != want.get("role") or not (
            have == name or (len(want.get("name") or "") >= MARK_NAME_CHARS and have.startswith(name))):
        return True
    box, live = want.get("box") or {}, element.get("screen_box") or {}
    try:
        return not all(abs(float(box[k]) - float(live[k])) <= BOX_TOLERANCE_PX for k in ("x", "y", "w", "h"))
    except (KeyError, TypeError, ValueError):
        return True


class _Run:
    """State of one task run. Single-threaded (one event loop), so plain attributes."""

    def __init__(self, task: dict, worker_id: str, client: ComputerClient):
        self.task = task
        self.id = task["id"]
        self.slug = task["agent_slug"]
        self.worker_id = worker_id
        self.client = client
        self.lease: str | None = None
        self.epoch: str | None = None
        self.fenced = False
        self.finished = False
        self.phase = ""
        self.pending_action_id: str | None = None
        self.url = ""
        self.snapshot_text = ""
        self.last_text = ""
        self.gate_id: str | None = None      # the gate this run opened or consumed (goes on the report)
        self.declared: dict | None = None    # the helper's request_approval declaration, attached to the next gate
        self.last_result: dict = {}          # execute()'s last raw result (batch() reads error/stopped from it)
        self.shots = 0                       # screenshots saved for the record: shots/<task>/<n>.png
        # Defaults are the helper's; a direct session (direct.py) sets all three False.
        self.notify = True                   # finish() queues the agent's report turn
        self.retry_epoch = True              # computer() resends once after stale_epoch (False: _EpochChanged)
        self.renew_adopts_epoch = True       # renew_loop() overwrites `epoch` (False: it only sets latest_epoch)
        self.latest_epoch: str | None = None  # the newest epoch renew_loop saw, adopted between operations
        self.op_lock = asyncio.Lock()        # one direct operation at a time; renewals never take it
        # The latest observation of each kind ("snapshot", "screen"): (epoch it was sent
        # under, its number). A ref is only good while that epoch is the run's epoch (direct.py checks).
        self.observed: dict[str, tuple[str | None, int]] = {}
        self.observations = 0
        self.marks: tuple[str, list[dict]] | None = None  # the latest marked screenshot: (observation id, its marks)
        # Counted time: wall time minus takeover waits. `segment_start` is None while paused.
        self.counted = float(task["running_seconds"] or 0)
        self.segment_start: float | None = time.monotonic()

    # ── time and caps ────────────────────────────────────────────────────────

    def seconds(self) -> float:
        return self.counted + (time.monotonic() - self.segment_start if self.segment_start is not None else 0)

    def _pause_clock(self) -> None:
        if self.segment_start is not None:
            self.counted += time.monotonic() - self.segment_start
            self.segment_start = None

    def _resume_clock(self) -> None:
        if self.segment_start is None:
            self.segment_start = time.monotonic()

    def chain(self) -> dict:
        """Chain totals with this task's unpersisted seconds folded in."""
        t = db.chain_totals(self.task["root_task_id"])
        row = db.get_task(self.id) or {}
        t["seconds"] += self.seconds() - float(row.get("running_seconds") or 0)
        return t

    def remaining_seconds(self) -> float:
        return db.MAX_SECONDS - self.chain()["seconds"]

    def cap_reason(self) -> str | None:
        t = self.chain()
        if t["steps"] >= db.MAX_STEPS:
            return f"step cap reached ({db.MAX_STEPS} steps over the task chain)"
        if t["seconds"] >= db.MAX_SECONDS:
            return f"time cap reached ({db.MAX_SECONDS // 3600} h over the task chain)"
        if t["cost"] >= db.BUDGET_USD:
            return f"budget reached (${db.BUDGET_USD:.2f} over the task chain)"
        return None

    # ── liveness ─────────────────────────────────────────────────────────────

    def heartbeat(self) -> None:
        if _stopping:  # stop(): the process is restoring a backup or shutting down
            self.finish("failed", "interrupted", error="Chatty stopped the helper (shutdown or backup restore)")
            raise _Stop()
        if not db.heartbeat(self.id, self.worker_id, self.seconds(), self.phase, self.pending_action_id):
            self.finished = True  # cancelled or finished elsewhere; whoever did it queued the report
            raise _Stop()

    def check_alive(self) -> None:
        """Before every step and model call: still ours, not fenced, still allowed, not stopping."""
        if self.fenced:
            raise _Fenced()
        self.heartbeat()
        err = card.policy_error(self.slug)
        if err:
            self.finish("cancelled", "disabled", error=err)
            raise _Stop()

    def finish(self, status: str, reason: str, **fields) -> None:
        if not self.finished:
            self.finished = True
            fields.setdefault("result_text", self.last_text or None)
            fields.setdefault("gate_id", self.gate_id)
            db.finish_task(self.id, status, reason, notify=self.notify, running_seconds=self.seconds(), **fields)

    def cap_report(self, reason: str) -> str:
        """No extra model call at a cap: the helper's last message plus a step-log summary."""
        t = self.chain()
        recent = db.list_steps(self.id)[-5:]
        lines = [f"- {s['tool']} {s['args_excerpt'] or ''}".rstrip()[:160] for s in recent]
        return (f"{self.last_text}\n\n" if self.last_text else "") + (
            f"[Stopped: {reason}. {t['steps']} steps, ${t['cost']:.2f}, {t['seconds'] / 60:.0f} min over the chain."
            + (" Last steps:\n" + "\n".join(lines) if lines else "") + "]"
        )

    # ── the computer ─────────────────────────────────────────────────────────

    def _desktop(self, body: dict | None = None) -> dict:
        return {**(body or {}), "lease": self.lease, "epoch": self.epoch}

    async def computer(self, method: str, path: str, *, body: dict | None = None, retry_epoch: bool | None = None,
                       **kw) -> dict:
        """One desktop call under the lease. human_in_control → wait for control to end, then
        raise _Paused so the tool reports "not performed"; lease_lost → fenced; stale_epoch (refused
        before anything ran) → always adopt the refusal's epoch, then retry once with a fresh action id
        (`retry_epoch`, default self.retry_epoch) or re-raise. A run that never resends raises
        _EpochChanged instead, which ends the whole operation."""
        if self.fenced:
            raise _Fenced()
        try:
            return await self.client.request(method, path, json=self._desktop(body), **kw)
        except ComputerError as e:
            if e.code == "lease_lost":
                self.fenced = True
                raise _Fenced() from e
            if e.code == "human_in_control":
                await self.wait_for_control_end()
                raise _Paused() from e
            if e.code == "stale_epoch":
                self.epoch = e.body.get("epoch") or (await self.client.control_status()).get("epoch") or self.epoch
                self.latest_epoch = None  # whatever renew_loop stored is no newer than this refusal's epoch
                if not self.retry_epoch:
                    raise _EpochChanged() from e
                if retry_epoch is not False:
                    if body and "action_id" in body:
                        body = {**body, "action_id": db.ulid()}  # refused before journaling: a fresh id, nothing ran
                    return await self.computer(method, path, body=body, retry_epoch=False, **kw)
            raise

    async def activate(self) -> str | None:
        """Take the screen. Returns "busy" when another task holds it (caller requeues)."""
        while True:
            try:
                r = await self.client.request("POST", "/desktop/activate", json={"agent": self.slug, "task_id": self.id})
            except ComputerError as e:
                if e.code == "busy":
                    return "busy"
                if e.code == "human_in_control":
                    await self.wait_for_control_end()
                    continue
                raise
            self.lease, self.epoch = r["lease"], r.get("epoch")
            return None

    async def release(self) -> None:
        if self.lease and not self.fenced:
            try:
                await self.client.request("POST", "/desktop/lease/release", json={"lease": self.lease})
            except ComputerError:
                pass

    async def renew_loop(self) -> None:
        """Every 30 s for the whole task: renew the lease (exempt from human_in_control) and mark the
        worker alive. Any failed renewal fences the worker: no further action is ever sent. A newer
        epoch is adopted at once, or (renew_adopts_epoch False) kept for the next operation's start."""
        while True:
            await asyncio.sleep(RENEW_EVERY_S)
            try:
                r = await self.client.request("POST", "/desktop/lease/renew", json={"lease": self.lease})
            except ComputerError:
                self.fenced = True
                return
            if r.get("epoch"):
                if self.renew_adopts_epoch:
                    self.epoch = r["epoch"]
                else:
                    self.latest_epoch = r["epoch"]
            try:
                self.heartbeat()
            except _Stop:
                return

    async def wait_control(self, *, human: bool, timeout: float | None = None) -> dict | None:
        """Poll /control/status every 2 s (the clock stops) until human_in_control == `human`; that
        status, or None once `timeout` passes. Cancels, policy changes and a lost lease still end
        the task (check_alive). The lease keeps renewing meanwhile: renew is exempt from control."""
        self._pause_clock()
        prev, self.phase = self.phase, "wait"
        deadline = time.monotonic() + timeout if timeout is not None else None
        try:
            while deadline is None or time.monotonic() < deadline:
                await asyncio.sleep(CONTROL_POLL_S)
                self.check_alive()
                st = await self.client.control_status()
                if bool(st.get("human_in_control")) == human:
                    return st
            return None
        finally:
            self.phase = prev
            self._resume_clock()

    async def wait_for_control_end(self) -> None:
        """A person has the screen (takeover_state 'active'): wait until the computer reports control
        ended — "I'm done", the 60 s disconnect grace, or the 15 min limit, all on the computer's side —
        then adopt the new epoch. The only "I'm done" path is /api/computer/control/end → /control/end."""
        db.set_takeover(self.id, "active")
        try:
            st = await self.wait_control(human=False)
            if st.get("epoch"):
                self.epoch = st["epoch"]
        finally:
            db.set_takeover(self.id, "")

    # ── model calls and money ────────────────────────────────────────────────

    async def count_input_tokens(self, provider, system: str, messages: list, tools: list,
                                 api_tools: list | None = None) -> int:
        """Exact for Anthropic (count_tokens), otherwise chars ÷ 2 — deliberately high. `api_tools` is
        screenshot mode's wire-format tool list (the toolset entry plus the custom tools), whose
        history carries thinking blocks and screenshots."""
        if getattr(provider, "provider_name", "") == "anthropic":
            try:
                kw = {"tools": api_tools, "thinking": {"type": "adaptive"}} if api_tools is not None \
                    else {"tools": provider._format_tools(tools)}
                r = await anthropic_client(provider).messages.count_tokens(
                    model=provider.model, system=system,
                    messages=[m for m in messages if m.get("role") in ("user", "assistant")], **kw,
                )
                return int(r.input_tokens)
            except Exception as e:  # fall back to the estimate rather than stall the task
                logger.warning("count_tokens failed (%s); estimating", e.__class__.__name__)
        return (len(json.dumps(_countable(messages))) + len(system) + len(json.dumps(tools))) // 2

    async def reserve(self, provider, system: str, messages: list, tools: list,
                      api_tools: list | None = None) -> tuple[float, int, int] | None:
        """Reserve the most this call could cost, in one transaction with the budget check:
        input at the model's highest rate × the cache-write margin, plus max_tokens of output.
        max_tokens is cut to fit; None when even a minimal answer doesn't fit.
        Returns (reserved_usd, max_tokens, counted_input_tokens)."""
        rates = get_max_rates(provider.model)
        if not rates:
            return None
        in_tok = await self.count_input_tokens(provider, system, messages, tools, api_tools)
        in_cost = in_tok * rates[0] * CACHE_WRITE_MARGIN / 1e6
        out_rate = rates[1] / 1e6
        remaining = db.BUDGET_USD - self.chain()["cost"]
        max_tokens = min(DEFAULT_MAX_TOKENS, math.floor((remaining - in_cost) / out_rate)) if remaining > in_cost else 0
        if max_tokens < MIN_OUTPUT_TOKENS:
            return None
        usd = in_cost + max_tokens * out_rate
        if not db.reserve(self.id, self.task["root_task_id"], usd):
            return None
        return usd, max_tokens, in_tok

    @staticmethod
    def estimated_usage(in_tok: int, turn: dict) -> dict:
        """For providers whose stream carries no usage (only Anthropic's does today): the counted
        input plus the streamed output at chars ÷ 2 — high, but far below the max_tokens reservation."""
        out_chars = len(turn["text"]) + sum(len(json.dumps(tc.get("args") or {})) for tc in turn["tool_calls"])
        return {"input_tokens": in_tok, "output_tokens": max(1, out_chars // 2), "estimated": True}

    @staticmethod
    def actual_cost(model: str, usage: dict) -> float:
        in_tok = int(usage.get("input_tokens") or 0)
        cw = int(usage.get("cache_creation_input_tokens") or 0)
        cr = int(usage.get("cache_read_input_tokens") or 0)
        out = int(usage.get("output_tokens") or 0)
        rates = rates_for_prompt(model, in_tok + cw + cr) or (0.0, 0.0)
        return (in_tok * rates[0] + cw * rates[0] * 1.25 + cr * rates[0] * 0.1 + out * rates[1]) / 1e6

    async def model_call(self, provider, messages: list, tools: list, system: str, timeout: float) -> dict:
        async def consume():
            out = {"text": "", "tool_calls": [], "usage": {}, "stop": "stop", "error": None}
            async for ev in provider.stream_turn(messages, tools, system):
                t = ev.get("type")
                if t == "text":
                    out["text"] += ev.get("text", "")
                elif t == "error":
                    out["error"] = ev.get("error") or "provider error"
                elif t == "_turn_complete":
                    out["tool_calls"] = ev.get("tool_calls") or []
                    out["stop"] = ev.get("stop_reason") or "stop"
                    out["usage"] = ev.get("usage") or {}
            return out
        return await asyncio.wait_for(consume(), timeout=timeout)

    # ── tools ────────────────────────────────────────────────────────────────

    async def snapshot(self, max_chars: int = SNAPSHOT_CHARS) -> dict:
        sent = self.epoch
        r = await self.computer("POST", "/browser/snapshot", body={"max_chars": max_chars})
        self.snapshot_text = r.get("snapshot") or ""
        self.url = r.get("url") or self.url
        self.observe("snapshot", sent)
        return {k: r.get(k) for k in ("url", "title", "snapshot", "truncated", "tabs")}

    def observe(self, kind: str, epoch: str | None) -> int:
        """Record an observation (its refs, later its marks) taken under `epoch`; returns its number."""
        self.observations += 1
        self.observed[kind] = (epoch, self.observations)
        return self.observations

    async def act(self, kind: str, params: dict, *, label: str, text: str | None = None, verdict_out: list) -> dict:
        """Classify (when checked, via gate_or_expect), then send the act with an action id and `expect`.
        A gated action — or any checked action the helper declared consequential — opens a gate instead,
        unless a scheduled action pre-approved it."""
        expect = None
        if gates.needs_check(label, text):
            target = {"ref": params["ref"]} if params.get("ref") else {"focused": True}
            element = await self.computer("POST", "/browser/element", body=target)
            done, expect = await self.gate_or_expect(label, element, verdict_out, params=params)
            if done:
                return done
        action_id = db.ulid()
        body = {"action_id": action_id, "kind": kind, **{k: v for k, v in params.items() if v is not None}}
        if expect:
            body["expect"] = expect
        self.phase, self.pending_action_id = "action", action_id
        self.heartbeat()
        try:
            r = await self.computer("POST", "/browser/act", body=body)
        finally:
            self.phase, self.pending_action_id = "", None
        res = r.get("result") or {}
        self.url = res.get("url") or self.url
        return res

    async def tool_browser(self, a: dict, verdicts: list) -> dict:
        action = a.get("action")
        ref, text, key = a.get("ref"), a.get("text"), a.get("key")
        if action == "snapshot":
            return await self.snapshot()
        if action == "tabs" and (a.get("tab_action") or "list") == "list":
            return {"tabs": (await self.snapshot(2000)).get("tabs")}
        kind, params, label, changes_page = action, {}, f"act:{action}", True
        if action == "navigate":
            params = {"url": a.get("url")}
        elif action in ("click", "hover"):
            params, changes_page = {"ref": ref}, action == "click"
        elif action == "fill":
            params, changes_page = {"ref": ref, "text": text or ""}, False
        elif action == "type":
            params, changes_page = {"ref": ref, "text": text or ""}, "\n" in (text or "")
        elif action == "press":
            params, label = {"ref": ref, "key": key or ""}, f"act:press:{key or ''}"
        elif action == "select":
            params = {"ref": ref, "value": a.get("value")}
        elif action == "scroll":
            params, changes_page = ({"ref": ref} if ref else {"dx": 0, "dy": int(a.get("dy") or 600)}), False
        elif action in ("back", "forward", "reload"):
            params = {}
        elif action == "tabs":
            ta = a["tab_action"]
            kind = {"open": "new_tab", "switch": "switch_tab", "close": "close_tab"}[ta]
            params = {"url": a.get("url")} if ta == "open" else {"index": a.get("index")}
        else:
            return {"error": f"unknown browser action {action!r}"}
        res = await self.act(kind, params, label=label, text=text, verdict_out=verdicts)
        if "stopped" in res or not changes_page:
            return res
        try:
            return {**res, **await self.snapshot()}
        except (_Paused, _Fenced, _EpochChanged, ComputerError) as e:  # the action itself was performed: say so
            self.observed.pop("snapshot", None)
            why = e.detail if isinstance(e, ComputerError) else {
                _Paused: "a person took the screen", _Fenced: "lost the screen", _EpochChanged: "the screen changed hands"}[type(e)]
            return {**res, "performed": True, "snapshot_error": why,
                    "hint": "the action was performed; take a fresh snapshot before acting again"}

    async def tool_shell(self, a: dict) -> dict:
        t = max(1, min(int(a.get("timeout") or SHELL_DEFAULT_S), SHELL_MAX_S, int(self.remaining_seconds()) or 1))
        body = {"command": a.get("command") or "", "timeout": t}
        if a.get("cwd"):
            body["cwd"] = a["cwd"]
        self.phase = "action"
        self.heartbeat()
        try:
            return await self.computer("POST", "/shell", body=body, timeout=t + 15)
        finally:
            self.phase = ""

    async def tool_files(self, a: dict) -> dict:
        action, path = a.get("action"), a.get("path") or "."
        if action == "list":
            return await self.client.request("GET", "/files", params={"agent": self.slug, "path": path})
        if action == "read":
            data, name = await self.client.get_file(self.slug, path)
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError:
                return {"path": path, "name": name, "binary": True, "size": len(data),
                        "note": "binary file; the agent can fetch it with computer_file_get"}
            return {"path": path, "name": name, "size": len(data), "content": text[:FILE_READ_CHARS],
                    "truncated": len(text) > FILE_READ_CHARS}
        if action == "write":
            return await self.client.put_file(self.slug, path, (a.get("content") or "").encode("utf-8"))
        return {"error": f"unknown files action {action!r}"}

    def tool_request_approval(self, a: dict) -> dict:
        """The helper's declaration. It doesn't stop the task: the next checked action is gated (whatever
        the classifier says) and carries these details, so the card shows the helper's item, store and
        total next to what the page shows."""
        kind = a.get("kind")
        if kind not in gates.KINDS:
            return {"error": f"kind must be one of {', '.join(gates.KINDS)}"}
        self.declared = {"kind": kind, "reason": (a.get("reason") or "")[:1000], "item": a.get("item"),
                         "store": a.get("store"), "total": a.get("total")}
        return {"noted": f"Declared: {kind}. Now take the action itself with one plain click or key press; Chatty "
                         "stops it for the owner's approval with these details attached."}

    @staticmethod
    def _amount(text) -> float | None:
        m = re.search(r"\d[\d,]*(?:\.\d+)?", str(text or ""))
        return float(m.group(0).replace(",", "")) if m else None

    def declaration_error(self, element: dict) -> str | None:
        """A declared total that isn't the page's total is refused (the declaration is dropped)."""
        d = self.declared or {}
        page_total = element.get("total")
        if d.get("total") and isinstance(page_total, dict):
            mine, theirs = self._amount(d["total"]), self._amount(page_total.get("amount"))
            if mine is None or theirs is None or abs(mine - theirs) > 0.005:
                self.declared = None
                return (f"refused: your declared total {d['total']!r} doesn't match the page's total "
                        f"{page_total.get('text') or page_total.get('amount')!r}; re-check the page and declare again")
        return None

    # ── gates: open, resume, dispatch, take over ─────────────────────────────

    @staticmethod
    def save_png(rel: str, image_b64: str) -> str | None:
        """Write a base64 PNG under data/computer/<rel>; None on failure (a gate or step without its
        screenshot is still a gate or step)."""
        try:
            path = db.DATA_DIR / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(base64.b64decode(image_b64))
            return rel
        except (ValueError, OSError):
            return None

    async def screenshot_to(self, rel: str) -> str | None:
        """Best effort: a PNG of the screen saved under data/computer/<rel>; None on any failure."""
        try:
            r = await self.computer("POST", "/actions", body={"action_id": db.ulid(), "name": "screenshot", "input": {}})
            image = (r.get("result") or {}).get("image")
            return self.save_png(rel, image) if image else None
        except (_Paused, _Fenced, _EpochChanged, ComputerError):
            return None

    async def open_gate(self, kind: str, note: str, rule: str, label: str, element: dict | None, *,
                        reason: str | None = None, item: str | None = None, store: str | None = None,
                        total_text: str | None = None) -> str:
        """Stop before a consequential action: record the gate (Chatty's `note`, the helper's declaration
        if any, and a screenshot), end the task as needs_approval and ask the owner."""
        d, self.declared = self.declared or {}, None
        gate_id = db.insert_gate(self.task, kind=kind, note=note[:1000], reason=reason or d.get("reason"), rule=rule,
                                 action=label, element=element, url=self.url, item=item or d.get("item"),
                                 store=store or d.get("store"), total_text=total_text or d.get("total"))
        shot = await self.screenshot_to(f"shots/{self.id}/{gate_id}.png")
        if shot:
            db.execute("UPDATE gates SET screenshot = ? WHERE id = ?", (shot, gate_id))
        self.gate_id = gate_id
        name = (element or {}).get("name") or label
        self.finish("needs_approval", f"stopped before {kind}: {name[:120]}", gate_id=gate_id)
        await asyncio.to_thread(approvals.request, gate_id)
        return gate_id

    def _page_only(self) -> dict:
        u = urlsplit(self.url or "")
        return {"found": False, "page": {"host": u.hostname or "", "path": u.path or "", "title": ""}}

    async def regate(self, gate: dict, reason: str, element: dict | None) -> None:
        """The approved action can't be sent as approved: spend the old gate (nothing happened) and open
        a new one for the control as it is now — with no readable control it becomes a takeover card."""
        db.execute("UPDATE gates SET status = 'cancelled' WHERE id = ? AND status IN ('approved', 'dispatching')", (gate["id"],))
        await self.open_gate(gate["kind"], f"{reason} (replaces gate {gate['id']})", "rebind", gate["action"] or "",
                             element or self._page_only(), reason=gate["reason"], item=gate["item"], store=gate["store"],
                             total_text=gate["total_text"])

    async def locate(self, bound: gates.ApprovalBinding) -> tuple[str | None, dict | None]:
        """(ref, element) of the control in a fresh snapshot that still matches the binding; (None,
        first look-alike) when none does; (None, None) when nothing of that role and name is there."""
        await self.snapshot()
        fresh = None
        for ref in gates.locate(self.snapshot_text, bound.role, bound.name):
            el = await self.computer("POST", "/browser/element", body={"ref": ref})
            if not el.get("found"):
                continue
            fresh = fresh or el
            if not bound.mismatches(gates.ApprovalBinding.from_element(bound.action, el)):
                return ref, el
        return None, fresh

    async def consume(self, gate: dict) -> str | None:
        """The approved gate a follow-up starts with. A FRESH snapshot (old refs are stale) is used only
        to locate candidates; the binding — built from the stored gate — picks the one that is still
        the approved control, and dispatch() sends exactly one activation with that binding as
        `expect`. Returns the note the helper continues from, or None when the task is over (a new gate
        opened, or the outcome is unknown)."""
        self.gate_id = gate["id"]
        bound = gates.ApprovalBinding.from_gate(gate)
        for attempt in (1, 2):
            try:
                chosen, fresh = await self.locate(bound)
                break
            except _Paused:  # nothing sent yet: a person had the screen, look again once they hand it back
                if attempt == 2:
                    await self.regate(gate, "a person kept control of the screen", None)
                    return None
        if not chosen:
            await self.regate(gate, gates.change_reason(bound, gates.ApprovalBinding.from_element(bound.action, fresh) if fresh else None), fresh)
            return None
        if not await self.dispatch(gate, {"ref": chosen}, fresh):
            return None
        try:
            page = await self.snapshot()
        except (_Paused, ComputerError):
            page = {"hint": "take a new snapshot"}
        kind, _ = gates.dispatch_for(bound.action)
        return (f"## Approved action performed\nThe owner approved this {gate['kind']} — {bound.role} \"{bound.name}\" on "
                f"{bound.host}{bound.path} — and Chatty has just performed it ONCE (one {kind}). Do not repeat it. Continue "
                f"from the page as it is now: confirm the outcome and report.\n\n" + wrap_result("browser", json.dumps(page)))

    async def dispatch(self, gate: dict, params: dict, element: dict) -> bool:
        """Send the ONE activation an approved gate allows — a browser act on the located ref, or for a
        pixel gate one left_click at the located control's centre through /actions — with `expect`
        built from the stored gate so the computer refuses anything that differs (409 element_changed
        → a new gate). The gate is marked `dispatching` with its action id BEFORE the send; a lost
        response goes to reconcile(). A consequential action is never re-sent: the only retry is after
        `stale_epoch`, which the computer refuses before journaling anything. True when performed."""
        bound = gates.ApprovalBinding.from_gate(gate)
        kind, extra = gates.dispatch_for(bound.action) or (None, None)
        if kind is None:
            self.finish("failed", "approval can't be dispatched", error=f"{bound.action} isn't a single activation")
            return False
        coord = None
        if kind in gates.PIXEL_KINDS:
            box = (element or {}).get("screen_box")
            if not box:
                await self.regate(gate, "the control's position on the screen couldn't be read", element)
                return False
            coord = [int(box["x"] + box["w"] / 2), int(box["y"] + box["h"] / 2)]
        if self.fenced:
            raise _Fenced()
        self.phase, self.pending_action_id = "action", db.ulid()
        self.heartbeat()  # still ours — checked before the gate is marked, so a dead task never marks one
        if db.execute("UPDATE gates SET status = 'dispatching', action_id = ? WHERE id = ? AND status = 'approved'",
                      (self.pending_action_id, gate["id"])) != 1:
            self.phase, self.pending_action_id = "", None
            self.finish("failed", "approval no longer valid", error=f"gate {gate['id']} is {(db.get_gate(gate['id']) or {}).get('status')}")
            return False
        try:
            for attempt in (1, 2):
                if coord:
                    path = "/actions"
                    body = {"action_id": self.pending_action_id, "name": kind, "input": {"coordinate": coord, **extra},
                            "expect": bound.expect()}
                else:
                    path = "/browser/act"
                    body = {"action_id": self.pending_action_id, "kind": kind, **params, **extra, "expect": bound.expect()}
                try:
                    await self.computer("POST", path, body=body, retry_epoch=False)
                except ComputerError as e:
                    if e.code == "stale_epoch" and attempt == 1:  # refused before journaling: fresh id, nothing ran
                        self.epoch = e.body.get("epoch") or self.epoch
                        self.pending_action_id = db.ulid()
                        db.execute("UPDATE gates SET action_id = ? WHERE id = ? AND status = 'dispatching'",
                                   (self.pending_action_id, gate["id"]))
                        continue
                    if e.code == "element_changed":  # journaled as failed; nothing was clicked
                        # The facts we located are the ones the computer just rejected: describe the control
                        # again for the replacement gate (unreadable → a takeover card, never stale facts).
                        try:  # by ref when one was located; a pre-approved pixel click by its pixel, a pre-approved key by focus
                            fresh = await self.computer("POST", "/browser/element",
                                                        body=params or ({"x": coord[0], "y": coord[1]} if coord else {"focused": True}))
                        except (_Paused, _EpochChanged, ComputerError):
                            fresh = None
                        await self.regate(gate, "changed under the click: " + ", ".join(e.body.get("mismatches") or ["page"]),
                                          fresh if fresh and fresh.get("found") else None)
                        return False
                    return await self.reconcile(gate, element) == "done"
                except _Paused:  # refused before journaling, but a person had the screen: the page may differ now
                    await self.regate(gate, "a person took control of the screen before the action was sent", element)
                    return False
                except _Fenced:
                    await self.reconcile(gate, element)  # the lease is gone but the action may have run
                    raise
                except (_Stop, _EpochChanged):  # the task ended (cancel, policy) while we waited for a person to hand the
                    # screen back, or a direct session's screen changed hands: refused before journaling, nothing was sent
                    db.execute("UPDATE gates SET status = 'cancelled' WHERE id = ? AND status = 'dispatching'", (gate["id"],))
                    raise
                db.execute("UPDATE gates SET status = 'done' WHERE id = ? AND status = 'dispatching'", (gate["id"],))
                db.add_step(self.id, "approved_action", {"gate": gate["id"], "kind": kind, **params, **({"coordinate": coord} if coord else {})},
                            '{"performed": true}', url=self.url, action_id=self.pending_action_id,
                            verdict=f"{'pre' if gate.get('decision') == 'preapproved' else ''}approved:{gate['kind']}")
                return True
            return False  # unreachable: the loop returns or raises
        finally:
            self.phase, self.pending_action_id = "", None

    async def reconcile(self, gate: dict, element: dict) -> str:
        """After a lost response, ask the journal. `done` → the gate is done; `failed` (the computer
        refused it, nothing was performed) → a new gate for the page as it is; anything else →
        outcome_unknown: the gate and task end there, the report carries a screenshot, and nothing is
        ever re-sent."""
        status = None
        for _ in range(2):
            try:
                status = (await self.client.request("GET", f"/actions/{self.pending_action_id}")).get("status")
            except ComputerError:
                status = None
            if status not in ("reserved", "executing"):
                break
            await asyncio.sleep(RECONCILE_WAIT_S)
        if status == "done":
            db.execute("UPDATE gates SET status = 'done' WHERE id = ? AND status = 'dispatching'", (gate["id"],))
            return "done"
        if status == "failed":
            await self.regate(gate, "the computer refused the action; nothing was performed", element)
            return "failed"
        db.execute("UPDATE gates SET status = 'outcome_unknown' WHERE id = ? AND status = 'dispatching'", (gate["id"],))
        shot = await self.screenshot_to(f"shots/{self.id}/{gate['id']}-unknown.png")
        if shot:
            db.execute("UPDATE gates SET screenshot = ? WHERE id = ?", (shot, gate["id"]))
        self.finish("outcome_unknown", f"sent {gate['kind']}: {gate['name'] or gate['action']} and couldn't confirm the outcome",
                    gate_id=gate["id"],
                    error="the computer's response to the approved action was lost and its journal couldn't confirm it; "
                          "check the site before anything is repeated — nothing is retried automatically")
        return "unknown"

    async def takeover(self, gate: dict) -> None:
        """An unbindable gate the owner approved: open the gate's page on this agent's screen, send
        the viewer link, wait (≤ 15 min) for a person to take control and then hand it back, and
        finish WITHOUT acting. The owner does the pressing; the report says what they left on screen."""
        self.gate_id = gate["id"]
        b = gates.ApprovalBinding.from_gate(gate)
        what = f"{gate['kind']} ({b.role or 'control'} \"{b.name}\") on {b.host or gate['url'] or 'the page'}"
        try:
            if gate["url"] and (await self.snapshot()).get("url") != gate["url"]:
                await self.act("navigate", {"url": gate["url"]}, label="act:navigate", verdict_out=[])
        except (_Paused, ComputerError):  # best effort: the owner can navigate themselves
            pass
        reason = f"you approved doing the {what} yourself; the page is open and held for {TAKEOVER_WAIT_S // 60:.0f} minutes"
        db.set_takeover(self.id, "waiting", reason)
        try:
            await asyncio.to_thread(notify_takeover, self.task, reason)
            if await self.wait_control(human=True, timeout=TAKEOVER_WAIT_S) is None:
                self.finish("failed", f"nobody took over within {TAKEOVER_WAIT_S // 60:.0f} min",
                            result_text=f"The page for the {what} was opened and the owner was sent the screen link, "
                                        "but nobody took control. Nothing was done.")
                return
            await self.wait_for_control_end()
        finally:
            db.set_takeover(self.id, "")
        try:
            page = await self.snapshot()
        except (_Paused, ComputerError):
            page = {}
        self.finish("done", "handed back after takeover",
                    result_text=f"The owner took over the screen for the {what}; Chatty performed nothing itself. "
                                f"The screen now shows {page.get('title') or ''} ({page.get('url') or self.url}).\n\n"
                                + (page.get("snapshot") or "")[:3000])

    async def tool_request_takeover(self, a: dict) -> dict:
        """Ask the owner to take the screen, hold it until they do (≤ 15 min, the clock stopped), wait
        for the handback, then continue from a fresh snapshot. Nobody coming ends the task "sign-in
        needed" with a plain result; a cancel or lost lease during either wait ends it as usual."""
        reason = (a.get("reason") or "").strip()[:300] or "the page needs you in person"
        db.set_takeover(self.id, "waiting", reason)
        db.add_step(self.id, "request_takeover", a, f"waiting for the owner: {reason}", url=self.url)
        try:
            await asyncio.to_thread(notify_takeover, self.task, reason)
            if await self.wait_control(human=True, timeout=TAKEOVER_WAIT_S) is None:
                self.finish("failed", "sign-in needed", result_text=self.cap_report(
                    f"sign-in needed — {reason}; nobody took the screen within {TAKEOVER_WAIT_S // 60} min"))
                return {"stopped": f"nobody took over within {TAKEOVER_WAIT_S // 60} minutes; the task ends as 'sign-in needed'"}
            await self.wait_for_control_end()
        finally:
            db.set_takeover(self.id, "")
        return {"handback": HANDBACK_NOTE, **await self.snapshot()}

    async def execute(self, tc: dict) -> str:
        """One tool call → its result string (wrapped as untrusted where it carries page/command output)."""
        name, args = tc.get("name", ""), tc.get("args") or {}
        verdicts: list = []
        try:
            if name == "browser":
                result = await self.tool_browser(args, verdicts)
            elif name == "shell":
                result = await self.tool_shell(args)
            elif name == "files":
                result = await self.tool_files(args)
            elif name == "request_approval":
                result = self.tool_request_approval(args)
            elif name == "request_takeover":
                result = await self.tool_request_takeover(args)
            else:
                result = {"error": f"unknown tool {name!r}"}
        except _Stop:
            raise
        except _Paused:
            result = {"error": "not performed: a person took control of the screen and has handed it back; "
                               "the page may have changed"}
            try:
                result.update(await self.snapshot())
            except (_Paused, _EpochChanged, ComputerError):
                result["hint"] = "take a new snapshot"
        except _EpochChanged:
            result = dict(EPOCH_CHANGED)
        except ComputerError as e:
            result = {"error": e.detail, "code": e.code}
            if e.code == "element_changed":
                result["hint"] = "the page changed under the action; take a new snapshot"
        except Exception as e:  # bad arguments and the like: the helper's mistake, not the task's end
            result = {"error": f"{e.__class__.__name__}: {e}"[:300]}
        verdict = verdicts[0] if verdicts else None
        s = json.dumps(result)
        db.add_step(self.id, name, args, s, url=self.url, verdict=self._verdict_tag(verdict))
        self.last_result = result
        if "stopped" in result or name == "request_approval":
            return s
        # Our own words stay outside the untrusted wrapper (last_result keeps them: a direct call returns it whole)
        for tool, ours in (("request_takeover", "handback"), ("browser", "preapproved")):
            if name == tool and ours in result:
                rest = {k: v for k, v in result.items() if k != ours}
                return result[ours] + "\n" + wrap_result("browser", json.dumps(rest))
        return wrap_result(name, s)

    @staticmethod
    def _verdict_tag(verdict: gates.Verdict | None) -> str | None:
        if not verdict:
            return None
        if not verdict.gated:
            return f"free:{verdict.rule}"
        return f"{'preapproved' if verdict.rule == 'preapproved' else 'gated'}:{verdict.kind}"

    # ── screenshot mode: pixel actions, checked at press time ────────────────

    async def gate_or_expect(self, label: str, element: dict, verdict_out: list, *, repeat: int = 1,
                             params: dict | None = None) -> tuple[dict | None, dict | None]:
        """Classify a checked action — a browser act or a pixel action — from the element the computer
        described. (result, None) when it is not sent as asked: refused (a multi-activation, a bad
        declaration), gated (recorded, task ended as needs_approval), or already performed ONCE as a
        scheduled action's pre-approval; (None, expect) when it may go, with the `expect` the computer
        re-checks. `params` is the browser act's ref, which dispatch() re-reads a pre-approved control by."""
        verdict = gates.classify(label, element, page_text=self.snapshot_text, repeat=repeat)
        if not verdict.gated and self.declared:  # the helper said so; the classifier missing it changes nothing
            verdict = gates.Verdict(True, self.declared["kind"], "declared", f"{self.declared['kind']}: declared by the helper")
        verdict_out.append(verdict)
        if not verdict.gated:
            return None, gates.expect_for(label, element)
        name = element.get("name") or label
        if verdict.multi:
            return {"error": f"refused: {label} on {name!r} would activate it more than once; a consequential control "
                             "gets exactly one plain click or key press, after the owner's approval"}, None
        err = self.declaration_error(element)
        if err:
            return {"error": err}, None
        # ── pre-approved (scheduled actions): a named host + button crosses without asking ──
        kind = "buy" if (self.declared or {}).get("kind") == "buy" else verdict.kind  # a declared purchase is one
        pre = preapprovals.match(self.task.get("action_id"), kind, label, element)
        if pre:
            verdict_out[-1] = gates.Verdict(True, verdict.kind, "preapproved", f"{verdict.kind}: {name!r} pre-approved ({verdict.rule})")
            d, self.declared = self.declared or {}, None
            self.gate_id = db.insert_gate(
                self.task, kind=verdict.kind, rule=verdict.rule, action=label, element=element, url=self.url,
                note=f"pre-approved for scheduled action {self.task['action_id']}: {pre['host']} / {pre['button_text']!r} ({verdict.rule})",
                reason=d.get("reason"), decision="preapproved", decided_by=f"scheduled_action:{self.task['action_id']}")
            if not await self.dispatch(db.get_gate(self.gate_id), {"ref": params["ref"]} if (params or {}).get("ref") else {}, element):
                return {"stopped": f"pre-approved {verdict.kind} on {name!r} was not performed as approved"}, None
            return {"performed": True, "url": self.url,
                    "preapproved": f"Chatty performed this {verdict.kind} ({name!r} on {pre['host']}) ONCE: it is allowed "
                                   "without asking for this scheduled action. Do not repeat it; continue from the page as it is."}, None
        # ── end pre-approved ──
        await self.open_gate(verdict.kind, verdict.reason, verdict.rule, label, element)
        return {"stopped": f"needs approval ({verdict.kind}): {name}"}, None

    async def pixel_action(self, member: str, inp: dict, label: str, verdicts: list, want: dict | None = None) -> dict:
        """One toolset member. Checked members — every click, mouse-down and drag start, Enter/Space/
        Ctrl+Enter/Ctrl+S keys, typed newlines — are classified first from the element under the pixel
        (the focused element for keys), with a fresh snapshot for the page-level facts; a target the
        page can't identify is a gate (fail closed), so a click on a desktop app ends up as a takeover
        card. Allowed actions go through /actions with an action id and `expect`. `want` is a direct
        session's mark ({role, name, box}): the element under the pixel must still be that control
        before it is classified, and `expect` carries its box so the computer re-checks the position too."""
        expect = None
        if gates.needs_check(label, inp.get("text") if member == "type" else None):
            if member in gates.CLICK_MEMBERS:
                coord = inp.get("start_coordinate") if member == "left_click_drag" else inp.get("coordinate")
                if not coord:  # a click where the cursor is
                    pos = (await self.computer("POST", "/actions", body={"action_id": db.ulid(), "name": "cursor_position",
                                                                         "input": {}})).get("result") or {}
                    coord = [pos.get("x"), pos.get("y")]
                target = {"x": int(coord[0]), "y": int(coord[1])}
            else:
                target = {"focused": True}
            try:
                await self.snapshot()
            except ComputerError:  # no browser attached: the classifier works from the element alone
                self.snapshot_text = ""
            element = await self.computer("POST", "/browser/element", body=target)
            if want and mark_moved(want, element):
                return {"error": "not performed: the screen changed under that mark; take a new screenshot",
                        "code": "mark_changed"}
            refusal, expect = await self.gate_or_expect(label, element, verdicts, repeat=int(inp.get("repeat") or 1))
            if refusal:
                return refusal
            if want and expect:
                expect["box"] = want["box"]
        action_id = db.ulid()
        body = {"action_id": action_id, "name": member, "input": inp}
        if expect:
            body["expect"] = expect
        self.phase, self.pending_action_id = "action", action_id
        self.heartbeat()
        try:
            r = await self.computer("POST", "/actions", body=body)
        finally:
            self.phase, self.pending_action_id = "", None
        return dict(r.get("result") or {})

    async def recorded(self, member: str, inp: dict, act, verdicts: list) -> tuple[dict, str | None]:
        """One screen call `act()` logged as a step: errors become results, and an image is saved under
        shots/<task>/<n>.png for the record (result["screenshot"]). (result, the image's base64)."""
        try:
            result = await act()
            if member in ("screenshot", "zoom") and not result.get("image"):
                result = {"error": "the computer returned no image"}
        except _Stop:
            raise
        except _Paused:
            result = {"error": "not performed: a person took control of the screen and has handed it back; "
                               "the screen may have changed — take a screenshot"}
        except _EpochChanged:
            result = dict(EPOCH_CHANGED)
        except ComputerError as e:
            result = {"error": e.detail, "code": e.code}
            if e.code == "element_changed":
                result["hint"] = "the page changed under the action; take a screenshot"
        except Exception as e:  # bad arguments and the like: the caller's mistake, not the task's end
            result = {"error": f"{e.__class__.__name__}: {e}"[:300]}
        image, shot = result.pop("image", None), None
        if image:
            self.shots += 1
            shot = self.save_png(f"shots/{self.id}/{self.shots}.png", image)
            result["screenshot"] = shot
        db.add_step(self.id, member, inp, json.dumps(result), url=self.url, screenshot=shot,
                    verdict=self._verdict_tag(verdicts[0] if verdicts else None))
        self.last_result = result
        return result, image

    async def pixel(self, member: str, inp: dict, *, want: dict | None = None) -> dict:
        """A toolset call → the fields of its tool_result (`content`, `is_error`), logged as a step.
        screenshot/zoom images are saved under shots/<task>/<n>.png for the record and returned as an
        image block; everything else answers "OK" (cursor_position its coordinates). `want`: see pixel_action."""
        label = f"{member}:{inp.get('text') or ''}" if member in ("key", "hold_key") else member
        verdicts: list = []
        result, image = await self.recorded(member, inp, lambda: self.pixel_action(member, inp, label, verdicts, want),
                                            verdicts)
        if "error" in result:
            return {"content": " — ".join(filter(None, (result["error"], result.get("hint")))), "is_error": True}
        if "stopped" in result:
            return {"content": result["stopped"], "is_error": False}
        if "preapproved" in result:  # Chatty's own note about a pre-approved action; no wrapper needed
            return {"content": result["preapproved"], "is_error": False}
        if image:
            return {"content": [{"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": image}}],
                    "is_error": False}
        if member == "cursor_position":
            return {"content": f"({result.get('x')}, {result.get('y')})", "is_error": False}
        return {"content": "OK", "is_error": False}

    async def marked_screenshot(self) -> tuple[dict, str | None]:
        """A screenshot with the browser's visible controls numbered (POST /screen/marked), recorded like
        pixel(). Its marks become the latest "screen" observation, under the epoch the request was sent
        with (direct.py presses a mark only while that is still the run's epoch). (result, image)."""
        async def take() -> dict:
            sent = self.epoch
            r = await self.computer("POST", "/screen/marked")
            if r.get("image"):
                self.observe("screen", sent)
                self.marks = (r.get("observation_id"), r.get("marks") or [])
            return {"image": r.get("image"), "observation": r.get("observation_id"), "marks": r.get("marks") or []}
        return await self.recorded("screenshot", {"marked": True}, take, [])

    async def batch(self, calls: list[dict]) -> list[dict]:
        """A response's tool_use blocks, run ONE AT A TIME in order and dispatched by (toolset_name,
        name). The batch stops at the first gated or failed call; every later call gets an is_error
        result that still echoes toolset_name, so the conversation stays valid and nothing runs past
        an approval point. Returns the tool_result blocks for the next user message."""
        results, halted = [], False
        for c in calls:
            res = {"type": "tool_result", "tool_use_id": c["id"]}
            if c.get("toolset_name"):
                res["toolset_name"] = c["toolset_name"]
            if not halted:
                self.check_alive()
                reason = self.cap_reason()
                if reason:
                    self.finish("failed", reason, result_text=self.cap_report(reason))
                    halted = True
            if halted:
                results.append({**res, "is_error": True, "content": SKIPPED})
                continue
            args = c.get("input") or {}
            if c.get("toolset_name") == "computer":
                res.update(await self.pixel(c["name"], args))
            else:
                res["content"] = await self.execute({"id": c["id"], "name": c["name"], "args": args})
                res["is_error"] = "error" in self.last_result
            halted = self.finished or res["is_error"]
            results.append(res)
        return results

    async def screenshot_loop(self, provider, system: str, opening: str) -> None:
        """Screenshot-and-click: the SDK called directly with the computer toolset plus the custom
        tools, adaptive thinking, and server-side context editing. History is append-only — each
        response's blocks go back verbatim (to_dict(), thinking blocks included) and screenshots are
        never pruned here."""
        import anthropic
        client = anthropic_client(provider)
        api_tools = [TOOLSET, *provider._format_tools(TOOL_DEFS)]
        messages: list[dict] = [{"role": "user", "content": opening}]
        while True:
            prepared = await self.prepare_call(provider, system, messages, TOOL_DEFS, api_tools)
            if prepared is None:
                return
            reserved, max_tokens, _in_tok, remaining = prepared
            self.phase = "model"
            self.heartbeat()
            try:
                response = await asyncio.wait_for(client.beta.messages.create(
                    model=provider.model, max_tokens=max_tokens,
                    system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                    messages=messages, tools=api_tools, thinking={"type": "adaptive"},
                    betas=[CONTEXT_BETA], context_management={"edits": CONTEXT_EDITS},
                ), timeout=min(MODEL_TIMEOUT_S, remaining))
            except asyncio.TimeoutError:
                self.finish("failed", "model call timed out")  # usage unknown: the reservation stays charged
                return
            except anthropic.APIError as e:
                self.finish("failed", f"model error: {e}"[:200])
                return
            finally:
                self.phase = ""
            usage = response.usage.to_dict()
            db.settle(self.id, reserved, self.actual_cost(provider.model, usage),
                      int(usage.get("input_tokens") or 0), int(usage.get("output_tokens") or 0))
            blocks = [b.to_dict() for b in response.content]
            messages.append({"role": "assistant", "content": blocks})
            text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text").strip()
            if text:
                self.last_text = text
            if response.stop_reason == "refusal":
                self.finish("failed", "model refused the task")
                return
            calls = [b for b in blocks if b.get("type") == "tool_use"]
            if response.stop_reason == "max_tokens" and not calls:  # cut off mid-thought (a budget-trimmed max_tokens): not finished
                self.finish("failed", CUT_OFF, result_text=self.cap_report(CUT_OFF))
                return
            if not calls:
                self.finish("done", "finished", result_text=self.last_text or "(no report)")
                return
            messages.append({"role": "user", "content": await self.batch(calls)})
            if self.finished:
                return

    # ── the loop ─────────────────────────────────────────────────────────────

    async def prepare_call(self, provider, system: str, messages: list, tools: list, api_tools: list | None = None):
        """Before every model call: alive, under the caps, a reservation that fits, time left.
        (reserved_usd, max_tokens, counted_input_tokens, remaining_seconds), or None when the task was
        finished here."""
        self.check_alive()
        reason = self.cap_reason()
        if reason:
            self.finish("failed", reason, result_text=self.cap_report(reason))
            return None
        reservation = await self.reserve(provider, system, messages, tools, api_tools)
        if reservation is None:
            reason = f"budget reached (${db.BUDGET_USD:.2f} over the task chain)"
            self.finish("failed", reason, result_text=self.cap_report(reason))
            return None
        reserved, max_tokens, in_tok = reservation
        remaining = self.remaining_seconds()  # counting tokens took time too
        if remaining < 1:
            db.settle(self.id, reserved, 0, 0, 0)  # nothing was called; give the reservation back
            reason = f"time cap reached ({db.MAX_SECONDS // 3600} h over the task chain)"
            self.finish("failed", reason, result_text=self.cap_report(reason))
            return None
        return reserved, max_tokens, in_tok, remaining

    async def loop(self, preamble: str | None = None) -> None:
        """The helper loop. `preamble` (an approved action just performed) is appended to the opening message."""
        provider = get_ai_provider(agent_provider=self.task["helper_provider"], agent_model=self.task["helper_model"])
        if not provider:
            self.finish("failed", f"no {self.task['helper_provider']} credentials for the helper model")
            return
        from agents.db import get_agent_by_slug
        agent = get_agent_by_slug(self.slug) or {}
        mode = self.task.get("mode") or "text"
        system = build_system_prompt(agent.get("agent_name") or self.slug, self.slug, mode)
        parent = db.get_task(self.task["parent_task_id"]) if self.task.get("parent_task_id") else None
        opening = build_user_message(self.task, parent) + (f"\n\n{preamble}" if preamble else "")
        if mode == "screenshot":
            return await self.screenshot_loop(provider, system, opening)
        messages = [{"role": "user", "content": opening}]
        tools = TOOL_DEFS

        while True:
            prepared = await self.prepare_call(provider, system, messages, tools)
            if prepared is None:
                return
            reserved, max_tokens, in_tok, remaining = prepared
            provider.max_tokens = max_tokens
            self.phase = "model"
            self.heartbeat()
            try:
                turn = await self.model_call(provider, messages, tools, system, min(MODEL_TIMEOUT_S, remaining))
            except asyncio.TimeoutError:
                self.finish("failed", "model call timed out")  # usage unknown: the reservation stays charged
                return
            finally:
                self.phase = ""
            # A completed turn replaces its reservation with what it cost; a provider that reports
            # no usage is estimated. An errored turn's usage is unknown, so its reservation stands.
            usage = turn["usage"] or (self.estimated_usage(in_tok, turn) if turn["stop"] != "error" and not turn["error"] else None)
            if usage:
                db.settle(self.id, reserved, self.actual_cost(provider.model, usage),
                          int(usage.get("input_tokens") or 0), int(usage.get("output_tokens") or 0))
            if turn["text"].strip():
                self.last_text = turn["text"].strip()
            if turn["stop"] == "error" or turn["error"]:
                self.finish("failed", f"model error: {turn['error'] or 'provider error'}"[:200])
                return
            if turn["stop"] == "max_tokens" and not turn["tool_calls"]:  # cut off mid-thought: not finished
                self.finish("failed", CUT_OFF, result_text=self.cap_report(CUT_OFF))
                return
            if turn["stop"] != "tool_use" or not turn["tool_calls"]:
                self.finish("done", "finished", result_text=self.last_text or "(no report)")
                return

            results = []
            for tc in turn["tool_calls"]:
                self.check_alive()
                reason = self.cap_reason()
                if reason:
                    self.finish("failed", reason, result_text=self.cap_report(reason))
                    return
                results.append({"tool_use_id": tc.get("id", ""), "tool_name": tc.get("name", ""),
                                "content": await self.execute(tc)})
                if self.finished:
                    return
            messages = provider.add_tool_results(messages, turn["tool_calls"], results)


async def run_task(task: dict, worker_id: str, client: ComputerClient | None = None) -> str:
    """Run one claimed task to a terminal state. Returns "busy" when the screen belonged to someone
    else (the task is queued again), "done" otherwise."""
    run = _Run(task, worker_id, client or get_client())
    renew = None
    # A direct session's approval follow-up: no helper model and no helper caps — it makes the approved
    # click, and the agent carries on itself in the completion turn.
    agent_driven = task.get("driver") == "agent"
    try:
        err = card.policy_error(run.slug)
        if err:
            run.finish("cancelled", "disabled", error=err)
            return "done"
        err = None if agent_driven else card.helper_model_error(task["helper_model"])
        if err:
            run.finish("failed", "helper model refused", error=err)
            return "done"
        reason = None if agent_driven else run.cap_reason()
        if reason:
            run.finish("failed", reason, result_text=run.cap_report(reason))
            return "done"
        gate = db.get_gate(task["approved_gate_id"]) if task.get("approved_gate_id") else None
        if gate and gate["status"] != "approved":
            run.finish("failed", "approval no longer valid", error=f"gate {gate['id']} is {gate['status']}")
            return "done"
        if await run.activate() == "busy":
            db.requeue(run.id, worker_id)
            return "busy"
        renew = asyncio.create_task(run.renew_loop())
        if gate and gates.unbindable_reason(gate):
            await run.takeover(gate)
        else:
            note = await run.consume(gate) if gate else None  # None: consume() already ended the task
            if not run.finished:
                if agent_driven:
                    run.finish("done", "approved action performed", result_text=note)
                else:
                    await run.loop(note)
    except _Fenced:
        run.finish("failed", "lost the screen", error="the computer's screen lease was lost; nothing was retried")
    except _Stop:
        pass
    except Exception as e:
        logger.exception("Computer task %s crashed", run.id)
        run.finish("failed", f"error: {e.__class__.__name__}", error=str(e)[:500])
    finally:
        if renew:
            renew.cancel()
        try:
            await run.release()
        finally:
            if client is None:
                await run.client.aclose()
    if not run.finished:  # a _Stop raised by heartbeat() means someone else finished it
        logger.info("Computer task %s ended elsewhere (%s)", run.id, (db.get_task(run.id) or {}).get("status"))
    return "done"


def prune_shots() -> int:
    """Sweep: delete a task's screenshot folder (step shots and gate shots alike) SHOT_TTL_DAYS after
    the task finished, or when its task row is gone. Returns how many folders went."""
    root = db.DATA_DIR / "shots"
    if not root.is_dir():
        return 0
    n = 0
    for folder in root.iterdir():
        keep = db.query("SELECT 1 FROM tasks WHERE id = ? AND (finished_at IS NULL OR finished_at > datetime('now', ?))",
                        (folder.name, f"-{SHOT_TTL_DAYS} days"))
        if not keep:
            shutil.rmtree(folder, ignore_errors=True)
            n += 1
    return n


_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def safe_filename(name: str) -> str:
    return _SAFE_NAME.sub("_", name or "file").strip("._") or "file"
