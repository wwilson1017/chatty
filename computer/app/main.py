"""Control API for the Chatty virtual computer. See computer/README.md for the contract."""
import asyncio
import base64
import hmac
import json
import logging
import os
import re
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import uvicorn
from fastapi import APIRouter, Depends, FastAPI, Request, Response, WebSocket
from fastapi.responses import JSONResponse, StreamingResponse
from playwright.async_api import Error as PlaywrightError
from pydantic import BaseModel, Field

from .browser import SNAPSHOT_MAX_CHARS, BrowserError, BrowserSession
from .desktop import CONTROL_PORT, VIEW_PORT, ActionError, Desktop
from .journal import Journal, payload_hash

API_VERSION = "1.0"
DATA_DIR = Path("/data")
WORKSPACE = DATA_DIR / "workspace"
SETTINGS_FILE = DATA_DIR / "settings.json"
LEASE_SECONDS = 120
CONTROL_GRACE_SECONDS = 60
CONTROL_MAX_SECONDS = 15 * 60
IDLE_CHECK_SECONDS = 60
DEFAULT_IDLE_MINUTES = 30
SHELL_OUTPUT_CAP = 64 * 1024
SHELL_DEFAULT_TIMEOUT = 120
SHELL_MAX_TIMEOUT = 600
FILE_CAP = 25 * 1024 * 1024
REPLAY_WAIT_SECONDS = 60
MARKS_TIMEOUT_SECONDS = 15
AGENT_RE = re.compile(r"^[a-z0-9-]{1,64}$")
MCP_NAME_RE = re.compile(r"^[a-z0-9_-]{1,64}$")
# Children (Chromium, shells, mcp-proxy) inherit the environment; the secret stays in this process.
SECRET = os.environ.pop("COMPUTER_SECRET", "")

log = logging.getLogger("computer")


class ApiError(Exception):
    def __init__(self, status: int, code: str, detail: str, **extra):
        super().__init__(detail)
        self.status, self.code, self.detail, self.extra = status, code, detail, extra


def check_agent(agent: str) -> str:
    if not AGENT_RE.match(agent or ""):
        raise ApiError(400, "bad_agent", "agent slug must match ^[a-z0-9-]{1,64}$")
    return agent


class State:
    def __init__(self):
        self.boot_id = secrets.token_hex(4)
        self.epoch_n = 0
        self.desktop = Desktop()
        self.browser = BrowserSession(self.desktop)
        self.journal = Journal(str(DATA_DIR / "actions.db"))
        self.lease: dict | None = None
        self.control: dict | None = None
        self.control_ended: dict | None = None
        self.inflight = 0
        self.op_lock = asyncio.Lock()
        self.shells: dict[int, dict] = {}  # pgid -> {"killed": bool}
        self.mcp: dict[str, dict] = {}
        self.vnc_connections = 0  # open /vnc relays (view or control); an open viewer counts as activity
        self.last_activity = time.time()
        try:
            self.idle_minutes = int(json.loads(SETTINGS_FILE.read_text())["idle_minutes"])
        except (OSError, ValueError, KeyError):
            self.idle_minutes = DEFAULT_IDLE_MINUTES

    @property
    def epoch(self) -> str:
        return f"{self.boot_id}:{self.epoch_n}"

    def lease_live(self) -> bool:
        return self.lease is not None and self.lease["expires_at"] > time.time()

    def lease_public(self):
        if self.lease is None:
            return None
        return {"agent": self.lease["agent"], "task_id": self.lease["task_id"],
                "expires_in": max(0, round(self.lease["expires_at"] - time.time()))}

    def control_public(self):
        c = self.control
        if c is None:
            return None
        return {"agent": c["agent"], "task_id": c["task_id"], "connected": c["ws"] is not None,
                "started_at": c["started_at"],
                "expires_in": max(0, round(c["started_at"] + CONTROL_MAX_SECONDS - time.time()))}


state: State = None  # set in lifespan


@asynccontextmanager
async def operation(screen: bool = True):
    """Counts an in-flight lease-bound operation; screen operations also serialise on the desktop."""
    state.inflight += 1
    state.last_activity = time.time()
    try:
        if screen:
            async with state.op_lock:
                yield
        else:
            yield
    finally:
        state.inflight -= 1


def check_lease(lease: str, epoch: str, *, exempt_control: bool = False):
    if not state.lease_live() or not hmac.compare_digest(lease or "", state.lease["token"]):
        raise ApiError(409, "lease_lost", "this lease is not the live one; stop sending actions")
    if epoch != state.epoch:
        raise ApiError(409, "stale_epoch", "the screen changed hands; read the new epoch", epoch=state.epoch)
    if not exempt_control and state.control is not None:
        raise ApiError(409, "human_in_control", "a person has the screen; wait for control to end")


def kill_shells():
    for pgid, info in state.shells.items():
        info["killed"] = True
        try:
            os.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:
            pass


async def bring_up(agent: str):
    d = state.desktop
    await d.ensure_display()
    await d.start_chromium(agent)
    if not state.browser.connected or state.browser.agent != agent:
        await state.browser.connect(agent, str(WORKSPACE / agent / "downloads"))


async def end_control(reason: str):
    """Under the desktop lock (any running action finishes first), flip the state in one step — no
    agent call can pass the human_in_control check with the old epoch — then tear the stream down."""
    async with state.op_lock:
        c = state.control
        if c is None:
            return
        state.control = None
        state.epoch_n += 1
        state.control_ended = {"at": time.time(), "reason": reason, "agent": c["agent"], "task_id": c["task_id"],
                               "epoch": state.epoch}
        for t in (c["grace_task"], c["timeout_task"]):
            if t is not None and t is not asyncio.current_task():
                t.cancel()
        if c["ws"] is not None:
            try:
                await c["ws"].close(code=1000)
            except Exception:  # noqa: BLE001 - the socket may already be gone
                pass
        await state.desktop.stop_control_vnc()
    log.info("control ended (%s) for %s; epoch now %s", reason, c["agent"], state.epoch)


async def control_grace(c: dict):
    await asyncio.sleep(CONTROL_GRACE_SECONDS)
    if state.control is c and c["ws"] is None:
        await end_control("disconnected")


async def control_timeout(c: dict):
    await asyncio.sleep(CONTROL_MAX_SECONDS)
    if state.control is c:
        await end_control("timeout")


async def idle_loop():
    while True:
        await asyncio.sleep(IDLE_CHECK_SECONDS)
        try:
            idle_for = time.time() - state.last_activity
            if (state.idle_minutes and state.desktop.running and not state.lease_live()
                    and state.control is None and state.inflight == 0 and state.vnc_connections == 0
                    and idle_for > state.idle_minutes * 60):
                log.info("idle for %d s; stopping the desktop", idle_for)
                async with state.op_lock:
                    await state.browser.close()
                    await state.desktop.stop_all()
        except Exception:  # noqa: BLE001
            log.exception("idle loop")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global state
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    (WORKSPACE / "shared").mkdir(parents=True, exist_ok=True)
    state = State()
    idle = asyncio.create_task(idle_loop())
    log.info("computer up: boot_id=%s api_version=%s", state.boot_id, API_VERSION)
    try:
        yield
    finally:
        idle.cancel()
        for s in list(state.mcp.values()):
            stop_proc(s["proc"])
        await end_control("shutdown")
        await state.browser.close()
        await state.desktop.stop_all()


app = FastAPI(title="chatty-computer", version=API_VERSION, lifespan=lifespan, docs_url=None, redoc_url=None,
              openapi_url=None)


@app.exception_handler(ApiError)
async def api_error_handler(_request, exc: ApiError):
    return JSONResponse({"error": exc.code, "detail": exc.detail, **exc.extra}, status_code=exc.status)


@app.exception_handler(Exception)
async def unexpected_error_handler(_request, exc: Exception):
    """Keep the {error, detail} shape for anything that slipped past the routes (still logged by Starlette)."""
    return JSONResponse({"error": "internal", "detail": str(exc).splitlines()[0][:300] if str(exc) else type(exc).__name__},
                        status_code=500)


def authorized(header: str) -> bool:
    return header.startswith("Bearer ") and hmac.compare_digest(header[7:].encode(), SECRET.encode())


def require_auth(request: Request):
    if not authorized(request.headers.get("authorization", "")):
        raise ApiError(401, "unauthorized", "missing or wrong bearer token")
    state.last_activity = time.time()


router = APIRouter(dependencies=[Depends(require_auth)])


# ----- models ----------------------------------------------------------------------------------

class ActivateBody(BaseModel):
    agent: str
    task_id: str | None = None


class LeaseBody(BaseModel):
    lease: str


class Screened(BaseModel):
    lease: str
    epoch: str


class ActionBody(Screened):
    action_id: str
    name: str
    input: dict = Field(default_factory=dict)
    expect: dict | None = None


class ActBody(Screened):
    action_id: str
    kind: str
    ref: str | None = None
    text: str | None = None
    key: str | None = None
    value: str | list[str] | None = None
    url: str | None = None
    index: int | None = None
    dx: int | None = None
    dy: int | None = None
    expect: dict | None = None


class SnapshotBody(Screened):
    max_chars: int = Field(default=SNAPSHOT_MAX_CHARS, ge=1000, le=400000)


class ElementBody(Screened):
    ref: str | None = None
    x: int | None = None
    y: int | None = None
    focused: bool = False


class ShellBody(Screened):
    command: str
    timeout: float = Field(default=SHELL_DEFAULT_TIMEOUT, gt=0, le=SHELL_MAX_TIMEOUT)
    cwd: str | None = None


class SettingsBody(BaseModel):
    idle_minutes: int = Field(ge=0, le=24 * 60)


class ControlStartBody(BaseModel):
    agent: str
    task_id: str | None = None


class ControlEndBody(BaseModel):
    control_session_id: str


class McpBody(BaseModel):
    command: str
    env: dict[str, str] = Field(default_factory=dict)


# ----- health & settings ------------------------------------------------------------------------

@app.get("/health")
async def health():
    du = shutil.disk_usage(DATA_DIR)
    return {
        "api_version": API_VERSION, "boot_id": state.boot_id, "epoch": state.epoch,
        "chromium_version": state.desktop.chromium_version,
        "desktop_running": state.desktop.running, "active_agent": state.desktop.active_agent,
        "lease": state.lease_public(), "human_in_control": state.control is not None,
        "control": state.control_public(), "control_ended": state.control_ended,
        "idle_minutes": state.idle_minutes,
        "disk": {"total": du.total, "used": du.used, "free": du.free},
        "mcp_servers": sorted(state.mcp),
    }


@router.put("/settings")
async def put_settings(body: SettingsBody):
    state.idle_minutes = body.idle_minutes
    SETTINGS_FILE.write_text(json.dumps({"idle_minutes": body.idle_minutes}))
    return {"idle_minutes": body.idle_minutes}


# ----- screen lease -------------------------------------------------------------------------------

@router.post("/desktop/activate")
async def activate(body: ActivateBody):
    check_agent(body.agent)
    if state.control is not None:
        raise ApiError(409, "human_in_control", "a person has the screen")
    if state.lease_live():
        raise ApiError(409, "busy", "another task holds the screen",
                       holder={"agent": state.lease["agent"], "task_id": state.lease["task_id"]})
    if state.inflight > 0:
        kill_shells()
        raise ApiError(409, "busy", "an operation under the previous lease is still finishing",
                       reason="operation_running")
    state.epoch_n += 1
    state.lease = {"agent": body.agent, "task_id": body.task_id, "token": secrets.token_urlsafe(32),
                   "expires_at": time.time() + LEASE_SECONDS}
    async with operation():
        try:
            await bring_up(body.agent)
        except Exception as e:  # noqa: BLE001
            log.exception("activate failed")
            state.lease = None
            raise ApiError(500, "desktop_failed", str(e)[:300]) from e
    log.info("screen -> %s (task %s) epoch %s", body.agent, body.task_id, state.epoch)
    return {"lease": state.lease["token"], "epoch": state.epoch, "expires_in": LEASE_SECONDS}


@router.post("/desktop/lease/renew")
async def renew(body: LeaseBody):
    if not state.lease_live() or not hmac.compare_digest(body.lease, state.lease["token"]):
        raise ApiError(409, "lease_lost", "this lease is not the live one; stop sending actions")
    state.lease["expires_at"] = time.time() + LEASE_SECONDS
    return {"epoch": state.epoch, "expires_in": LEASE_SECONDS, "human_in_control": state.control is not None,
            "control_ended": state.control_ended}


@router.post("/desktop/lease/release")
async def release(body: LeaseBody):
    if state.lease is not None and hmac.compare_digest(body.lease, state.lease["token"]):
        state.lease = None
        return {"released": True}
    return {"released": False}


# ----- journaled actions --------------------------------------------------------------------------

def stored_copy(resp: dict) -> dict:
    """What the journal keeps: everything but image bytes."""
    result = resp.get("result")
    if isinstance(result, dict) and "image" in result:
        return {**resp, "result": {**result, "image": None, "image_omitted": True}}
    return resp


async def replay(action_id: str, row: dict) -> JSONResponse:
    deadline = time.monotonic() + REPLAY_WAIT_SECONDS
    while row["status"] in ("reserved", "executing") and time.monotonic() < deadline:
        await asyncio.sleep(0.05)
        row = state.journal.get(action_id)
    if row["status"] in ("unknown", "reserved", "executing"):
        return JSONResponse({"error": "outcome_unknown", "action_id": action_id, "status": row["status"],
                             "detail": "this action's outcome is not known; it will not be re-run"}, status_code=409)
    return JSONResponse(row["response"], status_code=row["http_status"])


async def run_journaled(action_id: str, payload: dict, lease: str, epoch: str, execute) -> JSONResponse:
    """The at-most-once wrapper shared by /actions and /browser/act."""
    if (err := state.journal.validate_id(action_id)) is not None:
        raise ApiError(400, err, "action_id must be a ULID created within the last 24 hours")
    sha = payload_hash(payload)
    row = state.journal.get(action_id)
    if row is not None and row["payload_sha256"] == sha:
        return await replay(action_id, row)
    check_lease(lease, epoch)
    status, row = state.journal.reserve(action_id, sha)
    if status == "conflict":
        raise ApiError(409, "action_conflict", "this action_id was already used with a different payload")
    if status == "replay":
        return await replay(action_id, row)
    async with operation():
        state.journal.set_status(action_id, "executing")
        try:
            http_status, resp = await execute()
        except ActionError as e:
            http_status, resp = 400, {"error": "bad_input", "action_id": action_id, "status": "failed", "detail": str(e)}
        except BrowserError as e:
            http_status, resp = 500, {"error": "action_failed", "action_id": action_id, "status": "failed", "detail": str(e)}
        except Exception as e:  # noqa: BLE001
            log.exception("action %s failed", action_id)
            http_status, resp = 500, {"error": "action_failed", "action_id": action_id, "status": "failed",
                                      "detail": str(e)[:300]}
        state.journal.set_status(action_id, resp["status"], http_status, stored_copy(resp))
    return JSONResponse(resp, status_code=http_status)


async def precheck(action: str, expect: dict, **target) -> dict | None:
    """Re-read the target right before acting. Returns an `element_changed` body or None."""
    if not state.browser.connected:
        actual = {"found": False}
    else:
        page = await state.browser.current_page()
        actual = await state.browser.describe(page, **target)
    mismatches = state.browser.expect_mismatches(expect, actual, action)
    if not mismatches:
        return None
    actual.pop("box", None)
    actual.pop("screen_box", None)
    return {"error": "element_changed", "status": "failed", "detail": "the page no longer matches `expect`",
            "mismatches": mismatches, "expected": expect, "actual": actual}


def action_label(name: str, inp: dict) -> str:
    return f"{name}:{inp.get('text')}" if name in ("key", "hold_key") else name


@router.post("/actions")
async def post_action(body: ActionBody):
    payload = {"name": body.name, "input": body.input, "expect": body.expect}

    async def execute():
        if body.expect is not None:
            where = state.desktop.action_target(body.name, body.input)
            if where is not None:
                if where == "point":
                    coord = body.input.get("start_coordinate" if body.name == "left_click_drag" else "coordinate")
                    target = {"point": tuple(coord)}
                elif where == "cursor":
                    target = {"point": await state.desktop.cursor_position()}
                else:
                    target = {"focused": True}
                if (bad := await precheck(action_label(body.name, body.input), body.expect, **target)) is not None:
                    return 409, {**bad, "action_id": body.action_id}
        result = await state.desktop.run_action(body.name, body.input)
        if isinstance(result.get("image"), bytes):
            result["image"] = base64.b64encode(result["image"]).decode()
        return 200, {"action_id": body.action_id, "status": "done", "result": result}

    return await run_journaled(body.action_id, payload, body.lease, body.epoch, execute)


@router.get("/actions/{action_id}")
async def get_action(action_id: str):
    row = state.journal.get(action_id)
    if row is None:
        raise ApiError(404, "unknown_action", "no action with that id")
    return {"action_id": action_id, "status": row["status"], "http_status": row["http_status"],
            "response": row["response"]}


@router.post("/screen/marked")
async def screen_marked(body: Screened):
    """A screenshot with the browser's visible interactive elements numbered; a plain one (no
    marks) when no browser is attached, another window is in front, or the page can't be read."""
    check_lease(body.lease, body.epoch)
    async with operation():
        shot = await state.desktop.grab()
        marks = []
        if state.browser.connected:
            try:
                page = await state.browser.current_page()
                marks = await asyncio.wait_for(state.browser.marks(page), MARKS_TIMEOUT_SECONDS)
            except (BrowserError, PlaywrightError, asyncio.TimeoutError) as e:
                log.warning("marks skipped: %r", e)
        png = state.desktop.draw_marks(shot, marks)
    return {"observation_id": "o" + secrets.token_hex(4), "epoch": body.epoch,
            "image": base64.b64encode(png).decode(), "marks": marks}


# ----- browser ---------------------------------------------------------------------------------

def need_browser():
    if not state.browser.connected:
        raise ApiError(409, "no_browser", "no browser is attached; activate the screen first")


@router.post("/browser/snapshot")
async def browser_snapshot(body: SnapshotBody):
    check_lease(body.lease, body.epoch)
    need_browser()
    async with operation():
        try:
            return await state.browser.snapshot(body.max_chars)
        except BrowserError as e:
            raise ApiError(500, "browser_failed", str(e)) from e


@router.post("/browser/element")
async def browser_element(body: ElementBody):
    check_lease(body.lease, body.epoch)
    need_browser()
    if body.ref:
        target = {"ref": body.ref}
    elif body.x is not None and body.y is not None:
        target = {"point": (body.x, body.y)}
    elif body.focused:
        target = {"focused": True}
    else:
        raise ApiError(400, "bad_input", "give ref, x and y, or focused=true")
    async with operation():
        try:
            page = await state.browser.current_page()
            return await state.browser.describe(page, **target)
        except BrowserError as e:
            raise ApiError(500, "browser_failed", str(e)) from e


@router.post("/browser/act")
async def browser_act(body: ActBody):
    params = {k: v for k, v in body.model_dump(exclude={"lease", "epoch", "action_id", "expect", "kind"}).items()
              if v is not None}
    payload = {"kind": body.kind, **params, "expect": body.expect}
    label = f"act:{body.kind}:{body.key}" if body.kind == "press" else f"act:{body.kind}"
    need_browser()  # before the journal: a missing browser is a 409, not a failed action

    async def execute():
        if body.expect is not None and body.kind in ("click", "fill", "type", "press", "select", "hover"):
            target = {"ref": body.ref} if body.ref else {"focused": True}
            if (bad := await precheck(label, body.expect, **target)) is not None:
                return 409, {**bad, "action_id": body.action_id}
        result = await state.browser.act(body.kind, params)
        return 200, {"action_id": body.action_id, "status": "done", "result": result}

    return await run_journaled(body.action_id, payload, body.lease, body.epoch, execute)


# ----- shell -------------------------------------------------------------------------------------

async def read_capped(stream, buf: bytearray, cap: int) -> bool:
    """Drain `stream` into `buf` (so partial output survives a cancel); True if output was cut."""
    truncated = False
    while chunk := await stream.read(65536):
        if len(buf) < cap:
            buf += chunk[: cap - len(buf)]
        else:
            truncated = True
    return truncated


@router.post("/shell")
async def shell(body: ShellBody):
    check_lease(body.lease, body.epoch)
    agent = state.lease["agent"]
    cwd = body.cwd or str(WORKSPACE / agent)
    os.makedirs(cwd, exist_ok=True)
    async with operation(screen=False):
        proc = await asyncio.create_subprocess_exec(
            "bash", "-lc", body.command, cwd=cwd, start_new_session=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env={**os.environ, "DISPLAY": ":1", "CHATTY_AGENT": agent},
        )
        info = state.shells[proc.pid] = {"killed": False}
        out, err = bytearray(), bytearray()
        readers = [asyncio.ensure_future(read_capped(proc.stdout, out, SHELL_OUTPUT_CAP)),
                   asyncio.ensure_future(read_capped(proc.stderr, err, SHELL_OUTPUT_CAP))]
        timed_out = False
        try:
            await asyncio.wait_for(proc.wait(), timeout=body.timeout)
        except asyncio.TimeoutError:
            timed_out = True
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            await proc.wait()
        finally:
            state.shells.pop(proc.pid, None)
        # a server the command left running in the background may still hold the pipes: give the
        # readers a moment to reach EOF, then let go with what they have
        done, pending = await asyncio.wait(readers, timeout=1.0)
        for t in pending:
            t.cancel()
        truncated = any(t.result() for t in done if t.exception() is None)
    return {"exit_code": proc.returncode, "stdout": out.decode(errors="replace"), "stderr": err.decode(errors="replace"),
            "truncated": truncated, "timed_out": timed_out, "killed": info["killed"]}


# ----- files -------------------------------------------------------------------------------------

def resolve_path(agent: str, path: str) -> Path:
    check_agent(agent)
    p = Path(path or ".")
    if p.is_absolute():
        if p.parts[:2] != ("/", "workspace"):
            raise ApiError(403, "path_forbidden", "paths must stay under /workspace/<agent> or /workspace/shared")
        p = WORKSPACE.joinpath(*p.parts[2:])
    else:
        p = WORKSPACE / agent / p
    real = p.resolve()
    roots = [(WORKSPACE / agent).resolve(), (WORKSPACE / "shared").resolve()]
    if not any(real == r or r in real.parents for r in roots):
        raise ApiError(403, "path_forbidden", "paths must stay under /workspace/<agent> or /workspace/shared")
    return real


def public_path(real: Path) -> str:
    return "/workspace/" + str(real.relative_to(WORKSPACE.resolve()))


@router.get("/files")
async def list_files(agent: str, path: str = "."):
    real = resolve_path(agent, path)
    if not real.is_dir():
        raise ApiError(404, "not_a_directory", "no such directory")
    entries = []
    for child in sorted(real.iterdir(), key=lambda c: c.name):
        st = child.lstat()
        entries.append({"name": child.name, "type": "dir" if child.is_dir() else "file", "size": st.st_size,
                        "mtime": st.st_mtime})
    return {"path": public_path(real), "entries": entries}


@router.get("/files/content")
async def get_file(agent: str, path: str):
    real = resolve_path(agent, path)
    if not real.is_file():
        raise ApiError(404, "not_found", "no such file")
    if real.stat().st_size > FILE_CAP:
        raise ApiError(413, "too_large", f"files over {FILE_CAP} bytes can't be transferred")
    return Response(real.read_bytes(), media_type="application/octet-stream",
                    headers={"X-File-Name": real.name, "X-File-Path": public_path(real)})


@router.put("/files/content")
async def put_file(request: Request, agent: str, path: str):
    real = resolve_path(agent, path)
    if int(request.headers.get("content-length") or 0) > FILE_CAP:
        raise ApiError(413, "too_large", f"uploads over {FILE_CAP} bytes are refused")
    real.parent.mkdir(parents=True, exist_ok=True)
    size = 0
    fd, part = tempfile.mkstemp(dir=real.parent, prefix=f".{real.name}.", suffix=".part")
    try:
        with os.fdopen(fd, "wb") as f:
            async for chunk in request.stream():
                size += len(chunk)
                if size > FILE_CAP:
                    raise ApiError(413, "too_large", f"uploads over {FILE_CAP} bytes are refused")
                f.write(chunk)
        os.replace(part, real)
    except BaseException:
        Path(part).unlink(missing_ok=True)
        raise
    return {"path": public_path(real), "size": size}


# ----- browser profiles ---------------------------------------------------------------------------

@router.get("/profiles/{agent}/sites")
async def list_sites(agent: str):
    check_agent(agent)
    if state.desktop.active_agent == agent and state.browser.connected:
        try:
            return {"agent": agent, "sites": await state.browser.list_sites_live(), "live": True}
        except (BrowserError, PlaywrightError):
            pass  # fall back to the database
    return {"agent": agent, "sites": await asyncio.to_thread(BrowserSession.list_sites, agent), "live": False}


@router.delete("/profiles/{agent}/sites/{domain}")
async def clear_site(agent: str, domain: str):
    check_agent(agent)
    if not re.match(r"^\.?[a-z0-9.-]{1,253}$", domain, re.I):
        raise ApiError(400, "bad_domain", "not a domain")
    async with operation():  # under the desktop lock so an activation can't open the same profile meanwhile
        if state.desktop.active_agent == agent and state.browser.connected:
            await state.browser.clear_site_live(domain)
            return {"cleared": True, "live": True}
        try:
            await BrowserSession.clear_site_offline(agent, domain)
        except BrowserError as e:
            raise ApiError(500, "browser_failed", str(e)) from e
    return {"cleared": True, "live": False}


@router.delete("/profiles/{agent}")
async def reset_profile(agent: str):
    check_agent(agent)
    if state.lease_live() and state.lease["agent"] == agent:
        raise ApiError(409, "busy", "this agent is using the browser right now")
    if state.control is not None and state.control["agent"] == agent:
        raise ApiError(409, "human_in_control", "a person has this agent's screen")
    async with operation():
        if state.desktop.active_agent == agent:
            await state.browser.close()
            await state.desktop.stop_chromium()
        await asyncio.to_thread(BrowserSession.delete_profile, agent)
    return {"reset": True}


# ----- takeover ------------------------------------------------------------------------------------

@router.post("/control/start")
async def control_start(body: ControlStartBody):
    check_agent(body.agent)
    if state.control is not None:
        raise ApiError(409, "control_active", "someone already has control")
    if state.lease_live() and (state.lease["agent"] != body.agent
                               or (body.task_id is not None and state.lease["task_id"] != body.task_id)):
        raise ApiError(409, "lease_mismatch", "the screen belongs to a different agent or task",
                       holder={"agent": state.lease["agent"], "task_id": state.lease["task_id"]})
    c = state.control = {"id": secrets.token_urlsafe(24), "agent": body.agent, "task_id": body.task_id,
                         "started_at": time.time(), "ws": None, "grace_task": None, "timeout_task": None}
    # anything already running finishes first; new agent calls now get human_in_control
    deadline = time.monotonic() + 30
    while state.inflight > 0 and state.control is c and time.monotonic() < deadline:
        await asyncio.sleep(0.1)
    if state.control is not c:  # ended through /control/end while we waited
        raise ApiError(409, "control_ended", "this control session was ended before it started")
    if state.inflight > 0:
        state.control = None
        raise ApiError(409, "busy", "an action is still running; try again")
    try:
        async with state.op_lock:
            if state.control is not c:
                raise ApiError(409, "control_ended", "this control session was ended before it started")
            if not (state.lease_live() and state.desktop.active_agent == body.agent):
                await bring_up(body.agent)
            await state.desktop.start_control_vnc()
    except ApiError:
        raise
    except Exception as e:  # noqa: BLE001
        log.exception("control start failed")
        if state.control is c:
            state.control = None
        raise ApiError(500, "desktop_failed", str(e)[:300]) from e
    c["grace_task"] = asyncio.create_task(control_grace(c))
    c["timeout_task"] = asyncio.create_task(control_timeout(c))
    log.info("control started for %s (task %s)", body.agent, body.task_id)
    return {"control_session_id": c["id"], "expires_in": CONTROL_MAX_SECONDS, "epoch": state.epoch}


@router.post("/control/end")
async def control_end(body: ControlEndBody):
    c = state.control
    if c is None or not hmac.compare_digest(body.control_session_id, c["id"]):
        raise ApiError(404, "no_such_session", "no control session with that id")
    await end_control("done")
    return {"ended": True, "epoch": state.epoch}


@router.get("/control/status")
async def control_status():
    control = state.control_public()
    if control is not None:  # authed route only; /health never carries the id
        control["control_session_id"] = state.control["id"]
    return {"human_in_control": state.control is not None, "control": control,
            "control_ended": state.control_ended, "epoch": state.epoch, "lease": state.lease_public()}


@app.websocket("/vnc")
async def vnc(ws: WebSocket, mode: str = "view", control_session_id: str | None = None):
    if not authorized(ws.headers.get("authorization", "")):
        await ws.close(code=4401)
        return
    state.last_activity = time.time()
    c = state.control
    if mode == "control":
        if c is None or not hmac.compare_digest(control_session_id or "", c["id"]):
            await ws.close(code=4403)
            return
        port = CONTROL_PORT
    elif mode == "view":
        if not state.desktop.running:
            await ws.close(code=4404)
            return
        port = VIEW_PORT
    else:
        await ws.close(code=4400)
        return
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
    except OSError:
        await ws.close(code=4502)
        return
    offered = ws.headers.get("sec-websocket-protocol", "")
    await ws.accept(subprotocol="binary" if "binary" in offered else None)
    if mode == "control":
        if c["grace_task"] is not None:
            c["grace_task"].cancel()
            c["grace_task"] = None
        old, c["ws"] = c["ws"], ws
        if old is not None:
            try:
                await old.close(code=4409)
            except Exception:  # noqa: BLE001
                pass

    async def ws_to_tcp():
        while True:
            writer.write(await ws.receive_bytes())
            await writer.drain()

    async def tcp_to_ws():
        while data := await reader.read(65536):
            await ws.send_bytes(data)

    tasks = [asyncio.create_task(ws_to_tcp()), asyncio.create_task(tcp_to_ws())]
    state.vnc_connections += 1
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        state.vnc_connections -= 1
        state.last_activity = time.time()  # the idle clock starts when the viewer leaves
        for t in tasks:
            t.cancel()
        writer.close()
        try:
            await ws.close()
        except Exception:  # noqa: BLE001 - already closed
            pass
        if mode == "control" and state.control is c and c["ws"] is ws:
            c["ws"] = None
            c["grace_task"] = asyncio.create_task(control_grace(c))


# ----- command MCP servers ----------------------------------------------------------------------

def stop_proc(proc: subprocess.Popen):
    if proc.poll() is None:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
            proc.wait(timeout=5)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def mcp_public(name: str, s: dict) -> dict:
    return {"name": name, "command": s["command"], "running": s["proc"].poll() is None, "started_at": s["started_at"],
            "url": f"/mcp/{name}/mcp"}


@router.put("/mcp/servers/{name}")
async def mcp_put(name: str, body: McpBody):
    if not MCP_NAME_RE.match(name):
        raise ApiError(400, "bad_name", "server name must match ^[a-z0-9_-]{1,64}$")
    if (old := state.mcp.pop(name, None)) is not None:
        stop_proc(old["proc"])
    port = free_port()
    env = {"PATH": os.environ["PATH"], "HOME": os.environ.get("HOME", "/data/home"), "LANG": "C.UTF-8", **body.env}
    logfile = open(f"/tmp/mcp-{name}.log", "wb")  # noqa: SIM115 - handed to the child
    proc = subprocess.Popen(
        ["mcp-proxy", "--named-server", name, body.command, "--port", str(port), "--host", "127.0.0.1",
         "--pass-environment"],
        env=env, cwd=str(WORKSPACE / "shared"), stdout=logfile, stderr=subprocess.STDOUT, start_new_session=True,
    )
    logfile.close()
    async with httpx.AsyncClient(timeout=1.0) as client:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline and proc.poll() is None:
            try:
                if (await client.get(f"http://127.0.0.1:{port}/status")).status_code == 200:
                    break
            except httpx.HTTPError:
                await asyncio.sleep(0.2)
        else:
            stop_proc(proc)
            tail = Path(f"/tmp/mcp-{name}.log").read_text(errors="replace")[-2000:]
            raise ApiError(502, "mcp_start_failed", "mcp-proxy did not come up", log=tail)
    state.mcp[name] = {"command": body.command, "port": port, "proc": proc, "started_at": time.time()}
    return mcp_public(name, state.mcp[name])


@router.get("/mcp/servers")
async def mcp_list():
    return {"servers": [mcp_public(n, s) for n, s in sorted(state.mcp.items())]}


@router.get("/mcp/servers/{name}")
async def mcp_get(name: str):
    if name not in state.mcp:
        raise ApiError(404, "mcp_server_not_running", "no such server on this computer")
    return mcp_public(name, state.mcp[name])


@router.delete("/mcp/servers/{name}")
async def mcp_delete(name: str):
    s = state.mcp.pop(name, None)
    if s is not None:
        stop_proc(s["proc"])
    return {"stopped": s is not None}


HOP_HEADERS = {"host", "authorization", "content-length", "connection", "transfer-encoding", "date", "server"}


@router.api_route("/mcp/{name}/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
async def mcp_proxy(name: str, path: str, request: Request):
    s = state.mcp.get(name)
    if s is None or s["proc"].poll() is not None:
        raise ApiError(404, "mcp_server_not_running", "no such server on this computer; start it again")
    url = f"http://127.0.0.1:{s['port']}/servers/{name}/{path}"
    if request.url.query:
        url += "?" + request.url.query
    headers = {k: v for k, v in request.headers.items() if k.lower() not in HOP_HEADERS}
    client = httpx.AsyncClient(timeout=httpx.Timeout(None, connect=5))
    try:
        upstream = await client.send(client.build_request(request.method, url, headers=headers, content=request.stream()),
                                     stream=True)
    except httpx.HTTPError as e:
        await client.aclose()
        raise ApiError(502, "mcp_unreachable", str(e)[:200]) from e

    async def body():
        try:
            async for chunk in upstream.aiter_raw():
                yield chunk
        finally:
            await upstream.aclose()
            await client.aclose()

    resp_headers = {k: v for k, v in upstream.headers.items() if k.lower() not in HOP_HEADERS}
    return StreamingResponse(body(), status_code=upstream.status_code, headers=resp_headers)


app.include_router(router)


if __name__ == "__main__":
    if len(SECRET) < 32:
        print("COMPUTER_SECRET must be at least 32 characters; refusing to start", file=sys.stderr)
        sys.exit(1)
    # plain asyncio, not uvloop: uvloop leaks the subprocess pipe fds into grandchildren, so a server
    # a shell command left running in the background would keep /shell waiting until its timeout
    uvicorn.run(app, host=os.environ.get("HOST", "::"), port=int(os.environ.get("PORT", "8080")),
                log_level="info", loop="asyncio", ws_max_size=16 * 1024 * 1024)
