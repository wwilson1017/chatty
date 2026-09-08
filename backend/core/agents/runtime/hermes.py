"""
Chatty — Hermes runtime.

One Chatty conversation ↔ one Hermes session. Every turn:

  prepare   → reject Chatty-only modes, take the conversation mutex, reconcile
              any unresolved journal row (crash recovery), all before streaming
  stream    → journal `submitting` → POST /v1/runs → journal `submitted` →
              mirror the user row → translate the run's SSE events into Chatty
              events → persist exactly the streamed text → journal `done`
  drop      → the Hermes event stream cannot be resumed; poll GET /v1/runs/{id}
              and finish from its `output` (emitted as `text_replace`)
  disconnect→ a background task asks Hermes to stop and keeps the journal
              `stopping` until Hermes reports a terminal state

Approvals: Hermes emits `approval.request {request_id, ...}`. When the
connection advertises `approval_request_id` (an upstream Hermes fix), the card
is actionable and the answer is bound to that id. Otherwise the card is shown
for information and denied immediately — on a FIFO approval endpoint that is
the only fail-safe answer.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from typing import AsyncGenerator

from fastapi import HTTPException

from core.providers.base import _sse
from integrations.hermes import onboarding as hermes_conn
from integrations.hermes.client import (
    HermesClient,
    HermesConnectionError,
    HermesRequestError,
)

from . import admission
from . import registry as run_registry
from .base import AgentRuntime, RequestCtx, TurnPlan
from .history import build_conversation_history, build_snapshot

logger = logging.getLogger(__name__)

STREAM_SILENCE_S = float(os.environ.get("HERMES_STREAM_SILENCE_S", "120"))
POLL_INTERVAL_S = 2.0
POLL_MAX_S = 600.0
STOP_SETTLE_S = 60.0
# Total wall-clock budget for reconciliation inside a request (prepare/Resolve);
# whatever is still unresolved after this is left for the next Resolve.
RECONCILE_BUDGET_S = float(os.environ.get("HERMES_RECONCILE_BUDGET_S", "60"))
TERMINAL_STATUSES = {"completed", "failed", "cancelled"}
_APPROVAL_PASSTHROUGH = ("event", "choices", "run_id", "timestamp", "request_id")

# Strong refs to detached cleanup tasks (a GC'd task would be cancelled).
_background: set[asyncio.Task] = set()


def _spawn(coro) -> asyncio.Task:
    task = asyncio.get_running_loop().create_task(coro)
    _background.add(task)
    task.add_done_callback(_background.discard)
    return task


def _user_text(messages: list[dict]) -> str:
    last = next((m for m in reversed(messages) if m.get("role") == "user"), None)
    if not last:
        return ""
    content = last.get("content", "")
    if isinstance(content, str):
        return content
    return " ".join(p.get("text", "") for p in content
                    if isinstance(p, dict) and p.get("type") == "text")


def turn_public(row: dict | None) -> dict | None:
    """Journal row as the UI sees it (no run ids)."""
    if not row:
        return None
    return {"turn_id": row["turn_id"], "state": row["state"],
            "input": (row.get("input") or "")[:500], "created_at": row.get("created_at")}


class HermesRuntime(AgentRuntime):
    name = "hermes"

    # ── preflight ─────────────────────────────────────────────────────────

    async def prepare(self, *, agent, config, conversation_id, request_ctx: RequestCtx,
                      chat_service, **kw) -> TurnPlan:
        mode = request_ctx.chatty_only_mode
        if mode:
            raise HTTPException(
                status_code=400,
                detail=f"{mode} is not available while this agent runs on Hermes")
        if not hermes_conn.connection_enabled():
            raise HTTPException(status_code=400, detail="Hermes is not connected")
        creds = hermes_conn.get_connection()
        plan = TurnPlan(runtime=self.name, context_dir=config.context_dir,
                        gcs_prefix=config.gcs_prefix,
                        data={"creds": creds, "lock": None, "conversation_id": conversation_id})
        if conversation_id:
            lock = await admission.try_lock_conversation(conversation_id)
            plan.data["lock"] = lock
            try:
                still = await self._reconcile_locked(agent, conversation_id, chat_service, creds)
                if still:
                    raise HTTPException(status_code=409, detail={
                        "message": "A previous Hermes turn is unresolved; resolve it first",
                        "turn": turn_public(still)})
            except BaseException:
                lock.release()
                plan.data["lock"] = None
                raise
        return plan

    async def release(self, plan: TurnPlan) -> None:
        if plan.data.get("transferred"):
            return
        lock = plan.data.pop("lock", None)
        if lock is not None and lock.locked():
            lock.release()
        client = plan.data.pop("client", None)
        if client is not None:
            await client.aclose()

    # ── the turn ──────────────────────────────────────────────────────────

    async def stream_turn(self, plan: TurnPlan, *, agent, config, chat_service, ctx_manager,
                          messages, conversation_id=None, **kw) -> AsyncGenerator[str, None]:
        creds = plan.data["creds"]
        client = hermes_conn.make_client(creds)
        plan.data["client"] = client
        lock = plan.data.get("lock")
        user_text = _user_text(messages)
        turn_id: str | None = None
        run_id: str | None = None
        entry: run_registry.RunEntry | None = None
        terminal_reached = False

        try:
            # 1. Conversation (+ mutex once its id exists)
            if not conversation_id:
                conv = chat_service.create_conversation()
                conversation_id = conv["id"]
                chat_service.auto_title(conversation_id, user_text)
                lock = await admission.try_lock_conversation(conversation_id)
                plan.data["lock"] = lock
            plan.data["conversation_id"] = conversation_id
            yield _sse({"type": "conversation_id", "id": conversation_id})

            # 2. Hermes session bound to this connection
            state = chat_service.get_external_state(conversation_id) or {}
            session_id = None
            snapshot = None
            if (state.get("external_runtime") == self.name
                    and state.get("external_connection_id") == creds.get("connection_id")
                    and state.get("external_session_id")):
                session_id = state["external_session_id"]
                snapshot = state.get("context_snapshot") or ""
            if not session_id:
                snapshot = build_snapshot(
                    config.personality, ctx_manager.load_all_context(config.agent_name),
                    config.agent_name)
                title = (chat_service.get_conversation(conversation_id) or {}).get("title")
                try:
                    session = await client.create_session(title=title)
                except HermesConnectionError as e:
                    yield _sse({"type": "error", "error": f"Could not reach Hermes: {e}"})
                    return
                except HermesRequestError as e:
                    yield _sse({"type": "error", "error": f"Hermes rejected the session: {e}"})
                    return
                session_id = session.get("id")
                if not session_id:
                    yield _sse({"type": "error", "error": "Hermes returned no session id"})
                    return
                chat_service.set_external_session(conversation_id, session_id, self.name,
                                                  creds.get("connection_id") or "", snapshot)

            # 3. Compaction (an Anthropic-backed AI job; skipped without it)
            self._maybe_compact(chat_service, conversation_id)

            # 4. History from the mirror (the new user turn is not saved yet)
            ext = chat_service.get_external_state(conversation_id) or {}
            history = build_conversation_history(
                chat_service.get_history_rows(conversation_id),
                ext.get("compaction_summary"), ext.get("compaction_first_kept_seq"))

            # 5. Journal + submit
            turn_id = uuid.uuid4().hex
            chat_service.open_turn(turn_id, conversation_id, user_text)
            try:
                run_id = await client.create_run(
                    input=user_text, session_id=session_id, instructions=snapshot,
                    conversation_history=history, session_key=config.slug)
            except HermesConnectionError as e:
                chat_service.delete_turn(turn_id)  # nothing reached Hermes
                turn_id = None
                yield _sse({"type": "error", "error": f"Could not reach Hermes: {e}"})
                return
            except HermesRequestError as e:
                # The request may have been accepted (Hermes starts the run in a
                # background task); leave the journal ambiguous for Resolve.
                chat_service.mark_turn(turn_id, "ambiguous")
                yield _sse({"type": "error",
                            "error": f"Hermes did not confirm the turn ({e}); "
                                     "it is recorded as unresolved"})
                return
            chat_service.mark_turn(turn_id, "submitted", run_id)
            entry = run_registry.register(run_id, agent["id"], conversation_id, turn_id)
            try:
                chat_service.save_message(
                    conversation_id=conversation_id, msg_id=f"{turn_id}:user", role="user",
                    content=user_text, runtime=self.name, turn_id=turn_id)
            except Exception as e:
                logger.warning("Hermes user-row save failed, stopping run %s: %s", run_id, e)
                chat_service.mark_turn(turn_id, "stopping")
                self._transfer_cleanup(plan, client, run_id, turn_id, chat_service, lock)
                yield _sse({"type": "error", "error": "Could not record the message; the run was stopped"})
                return

            # 6. Stream + translate
            text_parts: list[str] = []
            cards: list[dict] = []
            supports_ids = bool(hermes_conn.supports("approval_request_id", creds))
            terminal: dict | None = None
            dropped = False
            recovered = False
            n_tools = 0

            try:
                async for ev in self._events_with_watchdog(client, run_id):
                    if ev is None:
                        yield ": keepalive\n\n"
                        continue
                    name = ev.get("event")
                    if name == "message.delta":
                        delta = ev.get("delta") or ""
                        if delta:
                            text_parts.append(delta)
                            yield _sse({"type": "text", "text": delta})
                    elif name == "tool.started":
                        n_tools += 1
                        tool = ev.get("tool") or "tool"
                        tuid = f"hermes:{run_id}:{n_tools}"
                        card = {"tool": tool, "tool_use_id": tuid, "preview": ev.get("preview"),
                                "status": "running", "started_at": time.time()}
                        cards.append(card)
                        yield _sse({"type": "tool_start", "tool": tool, "tool_use_id": tuid})
                        yield _sse({"type": "tool_args", "tool": tool, "tool_use_id": tuid,
                                    "args": {"preview": ev.get("preview")} if ev.get("preview") else {},
                                    "description": ""})
                    elif name == "tool.completed":
                        tool = ev.get("tool") or "tool"
                        # Best-effort pairing: Hermes gives no call id and may
                        # finish same-named concurrent calls out of order.
                        card = next((c for c in cards if c["tool"] == tool
                                     and c["status"] == "running"), None)
                        if card is None:
                            continue
                        card["status"] = "error" if ev.get("error") else "done"
                        duration = ev.get("duration") or 0
                        card["elapsed_ms"] = int(float(duration) * 1000)
                        yield _sse({"type": "tool_end", "tool": tool,
                                    "tool_use_id": card["tool_use_id"],
                                    "result": {"ok": not ev.get("error")},
                                    "elapsed_ms": card["elapsed_ms"]})
                    elif name == "approval.request":
                        async for frame in self._approval_request(client, entry, ev, supports_ids, run_id):
                            yield frame
                    elif name == "approval.responded":
                        for frame in self._approval_resolved(entry, ev.get("request_id")):
                            yield frame
                    elif name in ("run.completed", "run.failed", "run.cancelled", "error"):
                        terminal = ev
                        break
                    # reasoning.available, run.started, run.steered, subagent.*: ignored
            except (HermesConnectionError, HermesRequestError, asyncio.TimeoutError) as e:
                logger.info("Hermes event stream dropped for run %s: %s", run_id, e)
                dropped = True
            if terminal is None and not dropped:
                # The stream ended cleanly without a terminal event (proxy
                # closed it, Hermes restarted): the run may still be executing.
                logger.info("Hermes event stream for run %s ended without a terminal event", run_id)
                dropped = True

            # 7. Dropped stream → poll status (the stream cannot be resumed)
            if terminal is None and dropped:
                status = None
                started = time.time()
                while time.time() - started < POLL_MAX_S:
                    try:
                        status = await client.get_run(run_id)
                    except (HermesConnectionError, HermesRequestError):
                        status = {"status": "polling-error"}
                    if status is None or status.get("status") in TERMINAL_STATUSES:
                        break
                    if status.get("status") == "waiting_for_approval":
                        break
                    await asyncio.sleep(POLL_INTERVAL_S)
                    yield ": keepalive\n\n"
                if status is None:
                    chat_service.mark_turn(turn_id, "unknown")
                    for frame in self._approval_resolved(entry, None):
                        yield frame
                    yield _sse({"type": "error",
                                "error": "Hermes no longer reports this run; it is recorded as unresolved"})
                    terminal_reached = True
                    return
                st = status.get("status")
                if st == "completed":
                    output = status.get("output") or ""
                    if output:
                        text_parts = [output]
                        recovered = True
                        yield _sse({"type": "text_replace", "text": output})
                    terminal = {"event": "run.completed", "output": output,
                                "usage": status.get("usage")}
                elif st in ("failed", "cancelled"):
                    terminal = {"event": f"run.{st}", "error": status.get("error")}
                elif st == "waiting_for_approval":
                    chat_service.mark_turn(turn_id, "stopping")
                    self._transfer_cleanup(plan, client, run_id, turn_id, chat_service, lock)
                    for frame in self._approval_resolved(entry, None):
                        yield frame
                    yield _sse({"type": "error",
                                "error": "Hermes was waiting for an approval that was lost with the "
                                         "connection; the run was stopped safely"})
                    return
                else:
                    chat_service.mark_turn(turn_id, "stopping")
                    self._transfer_cleanup(plan, client, run_id, turn_id, chat_service, lock)
                    yield _sse({"type": "error",
                                "error": "Hermes did not finish the run in time; it was stopped"})
                    return

            # 8. Terminal handling
            terminal_reached = True
            for frame in self._approval_resolved(entry, None):
                yield frame
            name = (terminal or {}).get("event")
            text = "".join(text_parts)
            if name == "run.completed":
                if not text and terminal.get("output"):
                    text = terminal["output"]  # no deltas arrived at all
                    yield _sse({"type": "text", "text": text})
                model = await self._model_label(client, run_id, creds)
                meta = {"hermes_tools": cards, "recovered": recovered}
                usage = terminal.get("usage") or {}
                if usage:
                    meta["usage"] = usage
                chat_service.save_message(
                    conversation_id=conversation_id, msg_id=f"{turn_id}:assistant",
                    role="assistant", content=text, model=model or "", runtime=self.name,
                    turn_id=turn_id, display_meta=json.dumps(meta))
                chat_service.mark_turn(turn_id, "done")
                chat_service.set_external_synced_seq(conversation_id, chat_service.last_seq(conversation_id))
                yield _sse({"type": "done", "model": model or "", "runtime": self.name})
            else:
                err = (terminal or {}).get("error") or (terminal or {}).get("message") or name or "run failed"
                if isinstance(err, dict):
                    err = err.get("message") or json.dumps(err)
                if text:
                    chat_service.save_message(
                        conversation_id=conversation_id, msg_id=f"{turn_id}:assistant",
                        role="assistant", content=text, runtime=self.name, turn_id=turn_id,
                        display_meta=json.dumps({"hermes_tools": cards, "partial": True}))
                chat_service.mark_turn(turn_id, "failed")
                yield _sse({"type": "error", "error": str(err)})
        finally:
            if entry is not None:
                run_registry.finish(run_id)
            if run_id and turn_id and not terminal_reached and not plan.data.get("transferred"):
                # Client went away (or an unexpected exception) with the run
                # still live: stop it and settle the journal off-request.
                chat_service.mark_turn(turn_id, "stopping")
                self._transfer_cleanup(plan, client, run_id, turn_id, chat_service, lock)

    # ── helpers ───────────────────────────────────────────────────────────

    @staticmethod
    def _maybe_compact(chat_service, conversation_id: str) -> None:
        try:
            from core.providers import get_ai_provider
            from core.providers.credentials import CredentialStore
            from core.agents.compaction.service import maybe_compact
            provider = get_ai_provider()
            _, anthropic_profile = CredentialStore().get_active_profile(provider_override="anthropic")
            key = (anthropic_profile or {}).get("key", "") or (anthropic_profile or {}).get("api_key", "")
            if provider and key:
                maybe_compact(chat_service, provider, conversation_id, key)
        except Exception as e:  # never break a turn on compaction
            logger.debug("compaction skipped: %s", e)

    async def _events_with_watchdog(self, client: HermesClient, run_id: str):
        gen = client.iter_run_events(run_id)
        try:
            while True:
                try:
                    item = await asyncio.wait_for(gen.__anext__(), timeout=STREAM_SILENCE_S)
                except StopAsyncIteration:
                    return
                yield item
        finally:
            await gen.aclose()

    async def _approval_request(self, client, entry, ev, supports_ids, run_id):
        request_id = ev.get("request_id")
        n = len(entry.approval_meta) + 1
        tool_use_id = request_id or f"hermes:{run_id}:approval:{n}"
        tool = ev.get("tool") or ev.get("command") or "approval"
        args = {k: v for k, v in ev.items() if k not in _APPROVAL_PASSTHROUGH}
        actionable = bool(supports_ids and request_id)
        card = {
            "type": "confirm", "tool": tool, "args": args, "tool_use_id": tool_use_id,
            "msg_id": None, "description": ev.get("description") or "",
            "approval": {"choices": ev.get("choices") or [], "actionable": actionable,
                         "runtime": "hermes"},
        }
        entry.approval_meta[tool_use_id] = card
        if actionable:
            entry.pending_approvals[tool_use_id] = "pending"
            yield _sse(card)
            return
        card["approval"]["note"] = ("Your Hermes does not support request-bound approvals yet, "
                                    "so this request was denied automatically")
        yield _sse(card)
        try:
            await client.respond_approval(run_id, "deny")
        except (HermesConnectionError, HermesRequestError) as e:
            logger.info("auto-deny failed for run %s: %s", run_id, e)
        yield _sse({"type": "confirm_resolved", "tool_use_id": tool_use_id, "outcome": "denied"})

    @staticmethod
    def _approval_resolved(entry, request_id):
        if entry is None:
            return []
        frames = []
        ids = [request_id] if request_id else list(entry.pending_approvals.keys())
        for rid in ids:
            if rid in entry.pending_approvals:
                state = entry.pending_approvals.pop(rid)
                frames.append(_sse({"type": "confirm_resolved", "tool_use_id": rid,
                                    "outcome": "responded" if state == "responded" else "resolved"}))
        return frames

    @staticmethod
    async def _model_label(client, run_id, creds) -> str | None:
        try:
            st = await client.get_run(run_id)
            if st and st.get("model"):
                return str(st["model"])
        except (HermesConnectionError, HermesRequestError):
            pass
        return (creds.get("capabilities") or {}).get("model")

    @staticmethod
    async def _stop_quietly(client, run_id):
        try:
            await client.stop_run(run_id)
        except (HermesConnectionError, HermesRequestError) as e:
            logger.info("stop_run(%s) failed: %s", run_id, e)

    def _transfer_cleanup(self, plan, client, run_id, turn_id, chat_service, lock):
        """Hand the run to a detached task that stops it and settles the journal."""
        plan.data["transferred"] = True
        _spawn(self._settle(client, run_id, turn_id, chat_service, lock))

    async def _settle(self, client, run_id, turn_id, chat_service, lock):
        try:
            await self._stop_quietly(client, run_id)
            started = time.time()
            status = None
            while time.time() - started < STOP_SETTLE_S:
                try:
                    status = await client.get_run(run_id)
                except (HermesConnectionError, HermesRequestError):
                    status = {"status": "polling-error"}
                if status is None or status.get("status") in TERMINAL_STATUSES:
                    break
                await asyncio.sleep(POLL_INTERVAL_S)
            row = chat_service.get_turn(turn_id) or {}
            conversation_id = row.get("conversation_id")
            if conversation_id and status is not None and status.get("status") in TERMINAL_STATUSES:
                # The turn may have been handed here before its user row was
                # saved (e.g. that save failed); the transcript must not end up
                # with a reply and no question.
                chat_service.ensure_message(conversation_id, f"{turn_id}:user", "user",
                                            row.get("input") or "", runtime=self.name,
                                            turn_id=turn_id)
            if status is None:
                chat_service.mark_turn(turn_id, "unknown")
            elif status.get("status") == "completed":
                if conversation_id and status.get("output"):
                    chat_service.ensure_message(
                        conversation_id, f"{turn_id}:assistant", "assistant", status["output"],
                        runtime=self.name, turn_id=turn_id,
                        display_meta=json.dumps({"hermes_tools": [], "recovered": True}))
                chat_service.mark_turn(turn_id, "done")
            elif status.get("status") in ("failed", "cancelled"):
                chat_service.mark_turn(turn_id, "failed")
            # otherwise the journal stays 'stopping'; Resolve reconciles later
        except Exception as e:  # pragma: no cover — cleanup must never raise
            logger.warning("Hermes settle task failed for run %s: %s", run_id, e)
        finally:
            if lock is not None and lock.locked():
                lock.release()
            await client.aclose()

    # ── reconciliation (crash recovery) ───────────────────────────────────

    async def reconcile(self, *, agent, conversation_id, chat_service) -> dict | None:
        row = chat_service.unresolved_turn(conversation_id)
        if not row:
            return None
        lock = await admission.try_lock_conversation(conversation_id)
        try:
            return await self._reconcile_locked(agent, conversation_id, chat_service,
                                                hermes_conn.get_connection())
        finally:
            lock.release()

    async def _reconcile_locked(self, agent, conversation_id, chat_service, creds) -> dict | None:
        """Settle unresolved journal rows. Caller holds the conversation mutex."""
        client = None
        deadline = time.time() + RECONCILE_BUDGET_S
        try:
            for _ in range(20):
                row = chat_service.unresolved_turn(conversation_id)
                if not row:
                    return None
                if time.time() >= deadline:
                    return row  # out of budget; Resolve can continue later
                state, turn_id, run_id = row["state"], row["turn_id"], row.get("run_id")
                if state == "submitting":
                    # Only a dead process leaves this behind (a live turn holds
                    # the mutex we hold now) → the user must decide.
                    chat_service.mark_turn(turn_id, "ambiguous")
                    return chat_service.get_turn(turn_id)
                if state in ("ambiguous", "unknown"):
                    return row
                if state in ("submitted", "stopping") and run_id:
                    if client is None:
                        try:
                            client = hermes_conn.make_client(creds)
                        except (ValueError, HermesConnectionError):
                            return row
                    settled = await self._settle_from_status(
                        client, chat_service, row, deadline=deadline)
                    if not settled:
                        return chat_service.get_turn(turn_id)
                    continue
                # submitted/stopping without a run id cannot happen; fail closed
                chat_service.mark_turn(turn_id, "ambiguous")
                return chat_service.get_turn(turn_id)
            return chat_service.unresolved_turn(conversation_id)
        finally:
            if client is not None:
                await client.aclose()

    async def _settle_from_status(self, client, chat_service, row,
                                  deadline: float | None = None) -> bool:
        """Returns True when the row reached done/failed. `deadline` bounds the
        stop-and-wait poll so a request-scoped reconciliation cannot outlive
        the HTTP client."""
        turn_id, run_id, conversation_id = row["turn_id"], row["run_id"], row["conversation_id"]
        try:
            status = await client.get_run(run_id)
        except (HermesConnectionError, HermesRequestError):
            return False
        if status is None:
            chat_service.mark_turn(turn_id, "unknown")
            return False
        st = status.get("status")
        if st not in TERMINAL_STATUSES:
            await self._stop_quietly(client, run_id)
            chat_service.mark_turn(turn_id, "stopping")
            started = time.time()
            settle_until = started + STOP_SETTLE_S
            if deadline is not None:
                settle_until = min(settle_until, deadline)
            while time.time() < settle_until:
                await asyncio.sleep(POLL_INTERVAL_S)
                try:
                    status = await client.get_run(run_id)
                except (HermesConnectionError, HermesRequestError):
                    return False
                if status is None:
                    chat_service.mark_turn(turn_id, "unknown")
                    return False
                st = status.get("status")
                if st in TERMINAL_STATUSES:
                    break
            if st not in TERMINAL_STATUSES:
                return False
        chat_service.ensure_message(conversation_id, f"{turn_id}:user", "user",
                                    row.get("input") or "", runtime=self.name, turn_id=turn_id)
        if st == "completed":
            output = status.get("output") or ""
            chat_service.ensure_message(
                conversation_id, f"{turn_id}:assistant", "assistant", output,
                runtime=self.name, turn_id=turn_id,
                display_meta=json.dumps({"hermes_tools": [], "recovered": True}))
            chat_service.mark_turn(turn_id, "done")
        else:
            chat_service.mark_turn(turn_id, "failed")
        return True

    async def resolve(self, *, agent, conversation_id, chat_service, action: str) -> dict:
        """Explicit Resolve endpoint: retry reconciliation or mark failed."""
        lock = await admission.try_lock_conversation(conversation_id)
        try:
            if action == "mark_failed":
                row = chat_service.unresolved_turn(conversation_id)
                if row:
                    chat_service.ensure_message(
                        conversation_id, f"{row['turn_id']}:user", "user",
                        row.get("input") or "", runtime=self.name, turn_id=row["turn_id"])
                    chat_service.mark_turn(row["turn_id"], "failed")
                still = chat_service.unresolved_turn(conversation_id)
            else:
                still = await self._reconcile_locked(agent, conversation_id, chat_service,
                                                     hermes_conn.get_connection())
            return {"resolved": still is None, "turn": turn_public(still)}
        finally:
            lock.release()

    # ── approvals ─────────────────────────────────────────────────────────

    async def handle_approval(self, *, agent, conversation_id, tool_use_id, choice) -> dict:
        creds = hermes_conn.get_connection()
        if not hermes_conn.supports("approval_request_id", creds):
            raise HTTPException(status_code=409,
                                detail="Approvals are not actionable on this Hermes version")
        entry = run_registry.get_by_conversation(agent["id"], conversation_id)
        if entry is None or tool_use_id not in entry.approval_meta:
            raise HTTPException(status_code=404, detail="No such pending approval")
        state = entry.pending_approvals.get(tool_use_id)
        if state != "pending":
            raise HTTPException(status_code=409, detail=f"Approval is {state or 'already resolved'}")
        entry.pending_approvals[tool_use_id] = "submitting"
        client = hermes_conn.make_client(creds)
        try:
            await client.respond_approval(entry.run_id, "once" if choice == "once" else "deny",
                                          request_id=tool_use_id)
        except HermesRequestError as e:
            if e.status and 400 <= e.status < 500:
                entry.pending_approvals[tool_use_id] = "expired"
                return {"ok": False, "outcome": "expired", "detail": str(e)}
            entry.pending_approvals[tool_use_id] = "uncertain"
            return {"ok": False, "outcome": "uncertain", "detail": str(e)}
        except HermesConnectionError as e:
            entry.pending_approvals[tool_use_id] = "uncertain"
            return {"ok": False, "outcome": "uncertain", "detail": str(e)}
        finally:
            await client.aclose()
        entry.pending_approvals[tool_use_id] = "responded"
        return {"ok": True, "outcome": "responded", "choice": choice}
