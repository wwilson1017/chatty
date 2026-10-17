"""
Chatty — the helper loop: one worker drives the computer for one task at a time.

The pool has one thread (the process-level lock), `start()` takes an exclusive
flock so one Chatty process owns the queue, and the computer's screen lease is
the real lock across overlapping deploys. The loop is text mode: the helper
model sees aria snapshots and acts through refs; PR 5 adds screenshot-and-click.

Every checked action is classified by gates.classify() BEFORE it is sent. In
this PR a gate ends the task as `needs_approval`; PR 4 adds approval + resume.

Caps cover the whole follow-up chain (root_task_id): steps and time are hard;
money is a budget enforced on conservative reservations saved before each
model call (see _reserve). Nothing here makes a task terminal except
db.finish_task().
"""

import asyncio
import fcntl
import json
import logging
import math
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from core.agents.security.delimiters import DELIMITER_SYSTEM_INSTRUCTION, wrap_result
from core.providers import get_ai_provider
from core.providers.pricing import get_max_rates, rates_for_prompt

from . import card, db, gates
from .client import ComputerClient, ComputerError, get_client

logger = logging.getLogger(__name__)

RENEW_EVERY_S = 30
CONTROL_POLL_S = 2
BUSY_RETRY_S = 5
MODEL_TIMEOUT_S = 300
SHELL_DEFAULT_S = 120
SHELL_MAX_S = 600
SNAPSHOT_CHARS = 20000
FILE_READ_CHARS = 60000
DEFAULT_MAX_TOKENS = 8192
MIN_OUTPUT_TOKENS = 256
CACHE_WRITE_MARGIN = 1.25  # a cache write bills 1.25× the input rate; the reservation assumes every token is one

_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="computer-runner")
_lock_file = None
_started = False
_drain_lock = threading.Lock()
_draining = False


# ── process lifecycle ────────────────────────────────────────────────────────

def start() -> bool:
    """Web-app lifespan only (never the CLI). Takes the exclusive runner lock and runs the queue;
    False when another process already holds it."""
    global _lock_file, _started
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
    kick()
    return True


def stop() -> None:
    global _lock_file, _started
    _started = False
    if _lock_file:
        fcntl.flock(_lock_file, fcntl.LOCK_UN)
        _lock_file.close()
        _lock_file = None


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
    try:
        _drain()
    except Exception:
        logger.exception("Computer runner: drain failed")
    finally:
        with _drain_lock:
            _draining = False
    # simplification: a task queued between the last empty claim and the flag reset waits for
    # the 60 s sweep's kick; upgrade: loop until a claim under _drain_lock finds nothing


def _drain() -> None:
    wid = db.worker_id()
    while _started:
        task = db.claim_next(wid)
        if not task:
            return
        if asyncio.run(run_task(task, wid)) == "busy":
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
            "Call this BEFORE any action that leaves the computer and can't be undone: buy/pay, send, post, "
            "delete, or submit a form. The task stops here and the owner is asked; a follow-up task "
            "continues after approval. For a purchase give item, store and total exactly as the page shows them."
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
]

_RULES = (
    "# Rules\n"
    "- Work from snapshots. Refs (e12, f1e3) are valid only for the latest snapshot; take a new one when the page changed.\n"
    "- Consequential actions — buying or paying, sending, posting, deleting, submitting a form, confirming — need the "
    "owner's approval. Call request_approval(kind, reason, item/store/total) right before such a click. Chatty also "
    "checks every click itself and stops the task at an approval point; that is expected, not an error. Do everything "
    "up to that point (fill the cart, write the message) and let the task stop there.\n"
    "- Drafts: when asked to write an email, post or message, write it and leave it unsent.\n"
    "- Passwords and keys: never type them, never look for saved ones. If a site needs a sign-in, stop and report "
    "\"sign-in needed on <site>\"; the owner signs in by taking over the screen.\n"
    "- Never drive Chrome from the shell (no xdotool, CDP, 127.0.0.1:9222, playwright). The shell is for files and "
    "command-line work.\n"
    "- Be economical: one snapshot per page state, no busy-waiting loops. The task chain is capped at "
    f"{db.MAX_STEPS} steps, ${db.BUDGET_USD:.0f} and {db.MAX_SECONDS // 3600} h.\n"
    "- Finish with a plain-text report: what you did, what you found, where files are (/workspace/<agent>/…), and "
    "anything left undone. Your final message goes to the agent verbatim.\n"
)


def build_system_prompt(agent_name: str, slug: str) -> str:
    return (
        f"You are the computer helper working for {agent_name}, a Chatty agent. You operate a Linux desktop "
        f"(Chromium, bash, files under /workspace/{slug}) to complete ONE task for the agent, then report back.\n\n"
        + _RULES + "\n" + DELIMITER_SYSTEM_INSTRUCTION
    )


def build_user_message(task: dict, parent: dict | None) -> str:
    if not parent:
        return task["task"]
    return (
        f"This is a follow-up of task {parent['id']}.\n\n## Original task\n{parent['task']}\n\n"
        f"## What the previous run reported ({parent['status']}{': ' + parent['finish_reason'] if parent['finish_reason'] else ''})\n"
        f"{(parent['result_text'] or '(no report)')[:6000]}\n\n## Now\n{task['task']}"
    )


class _Stop(Exception):
    """The task is over (finished by us or by someone else): unwind without further calls."""


class _Fenced(_Stop):
    """The lease is gone: send nothing more to the computer."""


class _Paused(Exception):
    """A desktop call was refused because a person had control; control has since ended."""


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
        if not db.heartbeat(self.id, self.worker_id, self.seconds(), self.phase, self.pending_action_id):
            self.finished = True  # cancelled or finished elsewhere; whoever did it queued the report
            raise _Stop()

    def check_alive(self) -> None:
        """Before every step and model call: still ours, not fenced, still allowed."""
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
            db.finish_task(self.id, status, reason, notify=True, **fields)

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

    async def computer(self, method: str, path: str, *, body: dict | None = None, retry_epoch: bool = True, **kw) -> dict:
        """One desktop call under the lease. human_in_control → wait for control to end, then
        raise _Paused so the tool reports "not performed"; lease_lost → fenced; stale_epoch →
        refresh the epoch and retry once with a fresh action id."""
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
            if e.code == "stale_epoch" and retry_epoch:
                self.epoch = e.body.get("epoch") or (await self.client.request("GET", "/control/status")).get("epoch") or self.epoch
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
        worker alive. Any failed renewal fences the worker: no further action is ever sent."""
        while True:
            await asyncio.sleep(RENEW_EVERY_S)
            try:
                r = await self.client.request("POST", "/desktop/lease/renew", json={"lease": self.lease})
            except ComputerError:
                self.fenced = True
                return
            if r.get("epoch"):
                self.epoch = r["epoch"]
            try:
                self.heartbeat()
            except _Stop:
                return

    async def wait_for_control_end(self) -> None:
        """A person has the screen: poll /control/status every 2 s (the clock stops) until it ends,
        then adopt the new epoch. Cancels and policy changes still end the task."""
        self._pause_clock()
        prev, self.phase = self.phase, "wait"
        try:
            while True:
                await asyncio.sleep(CONTROL_POLL_S)
                self.check_alive()
                st = await self.client.request("GET", "/control/status")
                if not st.get("human_in_control"):
                    if st.get("epoch"):
                        self.epoch = st["epoch"]
                    return
        finally:
            self.phase = prev
            self._resume_clock()

    # ── model calls and money ────────────────────────────────────────────────

    async def count_input_tokens(self, provider, system: str, messages: list, tools: list) -> int:
        """Exact for Anthropic (count_tokens), otherwise chars ÷ 2 — deliberately high."""
        if getattr(provider, "provider_name", "") == "anthropic":
            try:
                from core.providers.anthropic_provider import _get_client
                client = _get_client(provider.api_key, provider.auth_token)
                r = await client.messages.count_tokens(
                    model=provider.model, system=system, tools=provider._format_tools(tools),
                    messages=[m for m in messages if m.get("role") in ("user", "assistant")],
                )
                return int(r.input_tokens)
            except Exception as e:  # fall back to the estimate rather than stall the task
                logger.warning("count_tokens failed (%s); estimating", e.__class__.__name__)
        return (len(json.dumps(messages)) + len(system) + len(json.dumps(tools))) // 2

    async def reserve(self, provider, system: str, messages: list, tools: list) -> tuple[float, int] | None:
        """Reserve the most this call could cost, in one transaction with the budget check:
        input at the model's highest rate × the cache-write margin, plus max_tokens of output.
        max_tokens is cut to fit; None when even a minimal answer doesn't fit."""
        rates = get_max_rates(provider.model)
        if not rates:
            return None
        in_tok = await self.count_input_tokens(provider, system, messages, tools)
        in_cost = in_tok * rates[0] * CACHE_WRITE_MARGIN / 1e6
        out_rate = rates[1] / 1e6
        remaining = db.BUDGET_USD - self.chain()["cost"]
        max_tokens = min(DEFAULT_MAX_TOKENS, math.floor((remaining - in_cost) / out_rate)) if remaining > in_cost else 0
        if max_tokens < MIN_OUTPUT_TOKENS:
            return None
        usd = in_cost + max_tokens * out_rate
        if not db.reserve(self.id, self.task["root_task_id"], usd):
            return None
        return usd, max_tokens

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
        r = await self.computer("POST", "/browser/snapshot", body={"max_chars": max_chars})
        self.snapshot_text = r.get("snapshot") or ""
        self.url = r.get("url") or self.url
        return {k: r.get(k) for k in ("url", "title", "snapshot", "truncated", "tabs")}

    async def act(self, kind: str, params: dict, *, label: str, text: str | None = None, verdict_out: list) -> dict:
        """Classify (when checked), then send the act with an action id and `expect`."""
        expect = None
        if gates.needs_check(label, text):
            target = {"ref": params["ref"]} if params.get("ref") else {"focused": True}
            element = await self.computer("POST", "/browser/element", body=target)
            verdict = gates.classify(label, element, page_text=self.snapshot_text)
            verdict_out.append(verdict)
            if verdict.gated:
                gate_id = db.insert_gate(self.task, kind=verdict.kind, reason=verdict.reason, rule=verdict.rule,
                                         action=label, element=element, url=self.url)
                self.finish("needs_approval", f"stopped before {verdict.kind}: {element.get('name') or label}",
                            gate_id=gate_id)
                return {"stopped": f"needs approval ({verdict.kind}): {element.get('name') or label}"}
            expect = gates.expect_for(label, element)
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
        return {**res, **await self.snapshot()}

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
        kind = a.get("kind")
        if kind not in gates.KINDS:
            return {"error": f"kind must be one of {', '.join(gates.KINDS)}"}
        gate_id = db.insert_gate(self.task, kind=kind, reason=(a.get("reason") or "")[:1000], rule="helper",
                                 url=self.url, item=a.get("item"), store=a.get("store"), total_text=a.get("total"))
        self.finish("needs_approval", f"stopped before {kind}: {(a.get('item') or a.get('reason') or '')[:120]}",
                    gate_id=gate_id)
        return {"stopped": f"needs approval ({kind})"}

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
            else:
                result = {"error": f"unknown tool {name!r}"}
        except _Stop:
            raise
        except _Paused:
            result = {"error": "not performed: a person took control of the screen and has handed it back; "
                               "the page may have changed"}
            try:
                result.update(await self.snapshot())
            except (_Paused, ComputerError):
                result["hint"] = "take a new snapshot"
        except ComputerError as e:
            result = {"error": e.detail, "code": e.code}
            if e.code == "element_changed":
                result["hint"] = "the page changed under the action; take a new snapshot"
        except Exception as e:  # bad arguments and the like: the helper's mistake, not the task's end
            result = {"error": f"{e.__class__.__name__}: {e}"[:300]}
        verdict = verdicts[0] if verdicts else None
        s = json.dumps(result)
        db.add_step(self.id, name, args, s, url=self.url,
                    verdict=(f"gated:{verdict.kind}" if verdict.gated else f"free:{verdict.rule}") if verdict else None)
        if "stopped" in result:
            return s
        return wrap_result(name, s) if name != "request_approval" else s

    # ── the loop ─────────────────────────────────────────────────────────────

    async def loop(self) -> None:
        provider = get_ai_provider(agent_provider=self.task["helper_provider"], agent_model=self.task["helper_model"])
        if not provider:
            self.finish("failed", f"no {self.task['helper_provider']} credentials for the helper model")
            return
        from agents.db import get_agent_by_slug
        agent = get_agent_by_slug(self.slug) or {}
        system = build_system_prompt(agent.get("agent_name") or self.slug, self.slug)
        parent = db.get_task(self.task["parent_task_id"]) if self.task.get("parent_task_id") else None
        messages = [{"role": "user", "content": build_user_message(self.task, parent)}]
        tools = TOOL_DEFS

        while True:
            self.check_alive()
            reason = self.cap_reason()
            if reason:
                self.finish("failed", reason, result_text=self.cap_report(reason))
                return
            reservation = await self.reserve(provider, system, messages, tools)
            if reservation is None:
                reason = f"budget reached (${db.BUDGET_USD:.2f} over the task chain)"
                self.finish("failed", reason, result_text=self.cap_report(reason))
                return
            reserved, max_tokens = reservation
            provider.max_tokens = max_tokens
            self.phase = "model"
            self.heartbeat()
            try:
                turn = await self.model_call(provider, messages, tools, system, min(MODEL_TIMEOUT_S, max(5.0, self.remaining_seconds())))
            except asyncio.TimeoutError:
                self.finish("failed", "model call timed out")  # usage unknown: the reservation stays charged
                return
            finally:
                self.phase = ""
            usage = turn["usage"]
            if usage:
                db.settle(self.id, reserved, self.actual_cost(provider.model, usage),
                          int(usage.get("input_tokens") or 0), int(usage.get("output_tokens") or 0))
            if turn["text"].strip():
                self.last_text = turn["text"].strip()
            if turn["stop"] == "error" or turn["error"]:
                self.finish("failed", f"model error: {turn['error'] or 'provider error'}"[:200])
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
    try:
        err = card.policy_error(run.slug)
        if err:
            run.finish("cancelled", "disabled", error=err)
            return "done"
        err = card.helper_model_error(task["helper_model"])
        if err:
            run.finish("failed", "helper model refused", error=err)
            return "done"
        reason = run.cap_reason()
        if reason:
            run.finish("failed", reason, result_text=run.cap_report(reason))
            return "done"
        if await run.activate() == "busy":
            db.requeue(run.id, worker_id)
            return "busy"
        renew = asyncio.create_task(run.renew_loop())
        await run.loop()
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


_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def safe_filename(name: str) -> str:
    return _SAFE_NAME.sub("_", name or "file").strip("._") or "file"
