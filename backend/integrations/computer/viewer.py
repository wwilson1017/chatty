"""
Chatty — the live screen viewer (/api/computer/*, absolute paths; mounted
without a prefix like core/todo/capture.py so GET /computer can serve the SPA
shell ahead of the static mount).

  POST /api/computer/viewer-ticket   {mode, agent, task_id?, reattach?} → opaque single-use ticket
  WS   /api/computer/vnc?ticket=…    relays bytes between the browser (noVNC) and the computer's WS /vnc
  GET  /api/computer/control/status  the control session this relay opened (for "I'm done" / reattach)
  POST /api/computer/control/end     "I'm done" → the computer's /control/end
  GET  /computer                     the SPA shell (the page itself is JWT-protected by the SPA)

A ticket is NOT a JWT — get_current_user would accept a JWT ticket as a login.
Issuing one changes nothing on the computer; for `control` the WebSocket handler
calls /control/start with the ticket's agent and task when the socket connects,
so a link for task A can never take over agent B's screen.
"""

import asyncio
import logging
import secrets
import time
from typing import Literal

import websockets
from fastapi import APIRouter, Depends, HTTPException, WebSocket
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from core.auth import get_current_user
from core.todo.web import _index_html  # the same built index.html the static mount serves

from . import card
from .client import ComputerError, get_client

logger = logging.getLogger(__name__)
router = APIRouter()

TICKET_TTL_S = 60
# Tickets and live relays. Every reader and writer is an `async def` on the one
# event loop, so no lock.
# simplification: single gunicorn worker; upgrade: SQLite table
_tickets: dict[str, dict] = {}
_open: dict[WebSocket, dict] = {}  # live relays → {mode, agent, task_id, control_session_id, stop}


def issue_ticket(mode: str, agent: str, task_id: str | None = None, reattach: str | None = None) -> str:
    now = time.monotonic()
    for tok in [t for t, v in _tickets.items() if v["expires"] <= now]:
        del _tickets[tok]
    tok = secrets.token_urlsafe(32)
    _tickets[tok] = {"mode": mode, "agent": agent, "task_id": task_id, "reattach": reattach,
                     "expires": now + TICKET_TTL_S}
    return tok


def redeem_ticket(tok: str) -> dict | None:
    """The ticket's binding, deleting it; None when unknown or expired."""
    t = _tickets.pop(tok, None) if tok else None
    return t if t and t["expires"] > time.monotonic() else None


def open_count() -> int:
    return len(_open)


def current_control() -> dict | None:
    for v in _open.values():
        if v["mode"] == "control":
            return {k: v[k] for k in ("control_session_id", "agent", "task_id")}
    return None


async def close_all(reason: str) -> None:
    """Disabling the integration: every open relay closes (the computer's own grace/end handles control)."""
    for v in list(_open.values()):
        v["reason"] = reason
        v["stop"].set()


class TicketRequest(BaseModel):
    mode: Literal["view", "control"]
    agent: str = Field(..., pattern=card.SLUG_RE.pattern)
    task_id: str | None = Field(None, max_length=64)
    reattach: str | None = Field(None, max_length=128)


class ControlEndRequest(BaseModel):
    control_session_id: str = Field(..., min_length=1, max_length=128)


@router.post("/api/computer/viewer-ticket")
async def viewer_ticket(body: TicketRequest, user=Depends(get_current_user)):
    err = card.policy_error(body.agent)
    if err:
        raise HTTPException(status_code=409, detail=err)
    return {"ticket": issue_ticket(body.mode, body.agent, body.task_id, body.reattach), "expires_in": TICKET_TTL_S}


@router.get("/api/computer/control/status")
async def control_status(user=Depends(get_current_user)):
    return {"control": current_control()}


@router.post("/api/computer/control/end")
async def control_end(body: ControlEndRequest, user=Depends(get_current_user)):
    client = card._client()
    try:
        await client.control_end(body.control_session_id)
    except ComputerError as e:
        if e.status != 404:  # 404 no_such_session: it already ended (grace or timeout) — nothing left to do
            raise card._http_error(e) from e
    finally:
        await client.aclose()
    return {"ok": True}


async def _safe_close(ws: WebSocket, code: int, reason: str = "") -> None:
    try:
        await ws.close(code=code, reason=reason[:120])
    except Exception:  # already closed by the other side
        pass


async def _relay(ws: WebSocket, up, stop: asyncio.Event) -> str | None:
    """Pump frames both ways until either side ends or `stop` is set.

    Returns the computer's close reason ("" if it sent none) when the computer hung
    up, None when the browser or `stop` ended it — so the page can say why.
    """
    async def to_computer():
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                return
            await up.send(msg["bytes"] if msg.get("bytes") is not None else msg.get("text", ""))

    async def to_browser():
        while True:
            try:
                data = await up.recv()
            except websockets.exceptions.ConnectionClosed as e:
                return e.rcvd.reason if e.rcvd else ""  # control ended, desktop stopped, or the container restarted
            if isinstance(data, bytes):
                await ws.send_bytes(data)
            else:
                await ws.send_text(data)

    to_up, to_down, stopped = (asyncio.create_task(c) for c in (to_computer(), to_browser(), stop.wait()))
    tasks = [to_up, to_down, stopped]
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for t in done:  # a pump that died (peer closed mid-frame) ends the relay; it isn't an error worth raising
            if t.exception():
                logger.debug("computer viewer pump ended: %r", t.exception())
        return to_down.result() if to_down in done and not to_down.exception() else None
    finally:
        for t in tasks:
            t.cancel()


@router.websocket("/api/computer/vnc")
async def vnc(ws: WebSocket, ticket: str = ""):
    t = redeem_ticket(ticket)
    if not t or card.policy_error(t["agent"]):
        await ws.close(code=4401)  # before accept: the handshake itself is refused (HTTP 403)
        return
    try:
        client = get_client()
    except ComputerError as e:
        await ws.close(code=4502, reason=e.detail[:120])
        return
    await ws.accept()
    state = {**t, "control_session_id": t["reattach"], "stop": asyncio.Event(), "reason": ""}
    try:
        if t["mode"] == "control" and not t["reattach"]:
            try:
                state["control_session_id"] = (await client.control_start(t["agent"], t["task_id"]))["control_session_id"]
            except ComputerError as e:
                await _safe_close(ws, 4409 if e.status == 409 else 4502, e.detail)
                return
        url = client.vnc_url(t["mode"], state["control_session_id"] if t["mode"] == "control" else None)
        try:
            async with websockets.connect(url, additional_headers={"Authorization": f"Bearer {client.secret}"},
                                          subprotocols=["binary"], max_size=None, open_timeout=10) as up:
                # Re-checked here, with no await before the registration below: a disable that landed
                # during the handshake above would otherwise miss this relay in close_all().
                if card.policy_error(t["agent"]):
                    await _safe_close(ws, 4000, "The computer was turned off.")
                    return
                _open[ws] = state
                try:
                    hung_up = await _relay(ws, up, state["stop"])
                finally:
                    _open.pop(ws, None)
                if hung_up is not None and not state["reason"]:
                    state["reason"] = "The computer ended the stream" + (
                        f": {hung_up}" if hung_up else " (control ended, or the desktop stopped).")
        except websockets.exceptions.InvalidStatus as e:
            # The computer refuses before the upgrade (HTTP 403): the desktop is asleep (idle), or the
            # control session already ended. A readable reason beats "InvalidStatus" on a phone.
            await _safe_close(ws, 4403, f"The computer refused the stream (HTTP {e.response.status_code}): "
                                        "it may be asleep, or the control session ended.")
            return
        except (OSError, asyncio.TimeoutError, websockets.exceptions.WebSocketException) as e:
            logger.warning("computer viewer stream failed: %s", e)
            await _safe_close(ws, 4502, f"The computer's screen stream failed: {e.__class__.__name__}")
            return
        await _safe_close(ws, 4000 if state["reason"] else 1000, state["reason"])
    finally:
        await client.aclose()


# ── tasks (dashboard) ────────────────────────────────────────────────────────

@router.get("/api/computer/tasks")
def list_tasks(limit: int = 20, agent: str | None = None, user=Depends(get_current_user)):
    from . import db
    limit = max(1, min(limit, 100))
    sql, params = "SELECT * FROM tasks", []
    if agent:
        sql, params = sql + " WHERE agent_slug = ?", [agent]
    rows = db.query(sql + " ORDER BY created_at DESC, rowid DESC LIMIT ?", (*params, limit))
    return {"tasks": [db.task_view(dict(r), result_chars=300) for r in rows]}


@router.get("/api/computer/tasks/{task_id}")
def get_task(task_id: str, user=Depends(get_current_user)):
    from . import db
    task = db.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    out = db.task_view(task, result_chars=20000)
    gate = db.get_gate(task["gate_id"]) if task["gate_id"] else None
    out["gate"] = db.gate_view(gate) if gate else None
    return out


@router.get("/api/computer/tasks/{task_id}/steps")
def get_task_steps(task_id: str, user=Depends(get_current_user)):
    from . import db
    if not db.get_task(task_id):
        raise HTTPException(status_code=404, detail="Task not found")
    return {"steps": db.list_steps(task_id)}


@router.post("/api/computer/tasks/{task_id}/cancel")
def cancel_task(task_id: str, user=Depends(get_current_user)):
    from . import db
    if not db.get_task(task_id):
        raise HTTPException(status_code=404, detail="Task not found")
    cancelled = db.finish_task(task_id, "cancelled", "cancelled by owner", notify=False, cancel_requested=1)
    return {"ok": True, "cancelled": cancelled}


_UNBUILT_HTML = ("<!doctype html><meta charset='utf-8'><title>Computer</title>"
                 "<p style='font-family:system-ui;padding:32px'>Frontend build not found. Run "
                 "<code>python run.py</code> (or <code>npm run build</code> in <code>frontend/</code>) and reload.</p>")


@router.get("/computer", response_class=HTMLResponse)
async def computer_page():
    """The viewer is a client-side route; the static mount has no SPA fallback, so serve the shell here."""
    html = _index_html()
    if not html:
        return HTMLResponse(_UNBUILT_HTML, status_code=503)
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})
