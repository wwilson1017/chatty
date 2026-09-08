"""Hermes runtime: client parsing, the turn lifecycle, approvals, recovery."""

import json

import httpx
import pytest

from core.agents.runtime import admission, registry as run_registry
from core.agents.runtime.history import build_conversation_history
from integrations.hermes import client as hermes_client
from integrations.hermes.client import (
    HermesClient, _STREAM_TIMEOUT, _DEFAULT_TIMEOUT, validate_base_url,
)
from tests.conftest import parse_sse
from tests.test_http_agents import make_agent


# ── Fake Hermes ───────────────────────────────────────────────────────────────

def _frames(events):
    """Serialize a list of event dicts (None = keepalive) as SSE bytes."""
    out = b""
    for ev in events:
        if ev is None:
            out += b": keepalive\n\n"
        else:
            out += b"data: " + json.dumps(ev).encode() + b"\n\n"
    return out


class FakeHermes:
    def __init__(self):
        self.features = {f: True for f in hermes_client.REQUIRED_FEATURES}
        self.runs = []            # bodies of POST /v1/runs
        self.approvals = []       # bodies of POST /v1/runs/{id}/approval
        self.stops = []
        self.scripts = []         # per-run list of events (consumed in order)
        self.statuses = {}        # run_id -> status dict for GET /v1/runs/{id}
        self.approval_status = 200
        self.run_submit_error = None   # exception to raise on POST /v1/runs
        self.run_submit_status = 202
        self.drop_after = None    # frames to send before raising ReadError
        self._n = 0

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        m = request.method
        if path == "/v1/capabilities":
            return httpx.Response(200, json={"features": self.features, "model": "fake-model"})
        if path == "/health":
            return httpx.Response(200, json={"ok": True})
        if path == "/api/model/options":
            return httpx.Response(200, json={"current": "fake-model"})
        if path == "/v1/skills":
            return httpx.Response(200, json={"data": [{"name": "s1"}]})
        if path == "/v1/toolsets":
            return httpx.Response(200, json={"data": [{"name": "memory", "enabled": True}]})
        if path == "/api/sessions" and m == "POST":
            return httpx.Response(201, json={"session": {"id": "sess-1"}})
        if path == "/v1/runs" and m == "POST":
            if self.run_submit_error:
                raise self.run_submit_error
            body = json.loads(request.content)
            self.runs.append(body)
            if self.run_submit_status != 202:
                return httpx.Response(self.run_submit_status, json={"error": {"message": "boom"}})
            self._n += 1
            run_id = f"run-{self._n}"
            self.statuses.setdefault(run_id, {"status": "completed", "output": "", "model": "fake-model"})
            return httpx.Response(202, json={"run_id": run_id, "status": "queued"})
        if path.startswith("/v1/runs/") and path.endswith("/events"):
            events = self.scripts.pop(0) if self.scripts else [{"event": "run.completed", "output": ""}]
            if self.drop_after is not None:
                head, self.drop_after = events[:self.drop_after], None

                async def agen():
                    yield _frames(head)
                    raise httpx.ReadError("dropped")
                return httpx.Response(200, content=agen())
            return httpx.Response(200, content=_frames(events))
        if path.startswith("/v1/runs/") and path.endswith("/approval"):
            self.approvals.append(json.loads(request.content))
            if self.approval_status >= 400:
                return httpx.Response(self.approval_status, json={"error": {"message": "no"}})
            return httpx.Response(200, json={"ok": True})
        if path.startswith("/v1/runs/") and path.endswith("/stop"):
            self.stops.append(path.split("/")[3])
            return httpx.Response(200, json={"status": "stopping"})
        if path.startswith("/v1/runs/"):
            run_id = path.split("/")[3]
            st = self.statuses.get(run_id)
            if st is None:
                return httpx.Response(404, json={"error": {"message": "nf", "code": "run_not_found"}})
            return httpx.Response(200, json={"run_id": run_id, **st})
        return httpx.Response(404, json={"error": {"message": f"unhandled {m} {path}"}})


@pytest.fixture
def hermes(monkeypatch):
    fake = FakeHermes()
    creds = {"base_url": "http://localhost:8642", "api_key": "k", "enabled": True,
             "connection_id": "conn-1",
             "capabilities": {"features": dict(fake.features), "model": "fake-model"}}
    fake.creds = creds
    from integrations.hermes import onboarding as conn

    monkeypatch.setattr(conn, "get_connection", lambda: creds)
    monkeypatch.setattr(conn, "connection_enabled", lambda: True)
    monkeypatch.setattr(
        conn, "make_client",
        lambda c=None: HermesClient("http://localhost:8642", "k",
                                    transport=httpx.MockTransport(fake.handle)))
    admission._reset_for_tests()
    run_registry._reset_for_tests()
    return fake


@pytest.fixture
def hermes_agent(client, hermes):
    from agents import db as agent_db
    agent = make_agent(client, name="Tom")
    agent_db.set_runtime(agent["id"], "hermes")
    return client.get(f"/api/agents/{agent['id']}").json()


def chat(client, agent, text="hello", **extra):
    payload = {"messages": [{"role": "user", "content": text}], **extra}
    return client.post(f"/api/agents/{agent['id']}/chat", json=payload)


def chat_service_for(agent):
    from agents.engine import get_chat_service
    return get_chat_service(agent["slug"])


# ── Client ────────────────────────────────────────────────────────────────────

def test_timeouts_finite_except_stream():
    assert _DEFAULT_TIMEOUT.read == 30.0
    assert _STREAM_TIMEOUT.read is None


def test_validate_base_url():
    assert validate_base_url("http://localhost:8642/") == "http://localhost:8642"
    assert validate_base_url("https://hermes.example.com") == "https://hermes.example.com"
    assert validate_base_url("http://10.0.0.5:8642") == "http://10.0.0.5:8642"
    with pytest.raises(ValueError):
        validate_base_url("http://hermes.example.com")  # public http
    assert validate_base_url("http://hermes.example.com", allow_insecure=True)
    for bad in ("ftp://x", "https://user:pw@h", "https://h/?x=1", "https://h/a/../b", ""):
        with pytest.raises(ValueError):
            validate_base_url(bad)


@pytest.mark.asyncio
async def test_sse_parser_keepalives_and_events(hermes):
    hermes.scripts.append([None, {"event": "message.delta", "delta": "hi"},
                           {"event": "run.completed", "output": "hi"}])
    c = HermesClient("http://localhost:8642", "k", transport=httpx.MockTransport(hermes.handle))
    got = [ev async for ev in c.iter_run_events("run-x")]
    await c.aclose()
    assert got[0] is None
    assert got[1] == {"event": "message.delta", "delta": "hi"}
    assert got[2]["event"] == "run.completed"


# ── Turn lifecycle over HTTP ──────────────────────────────────────────────────

def test_hermes_turn_streams_and_mirrors(client, hermes, hermes_agent):
    hermes.scripts.append([{"event": "run.started"}, {"event": "message.delta", "delta": "Hel"},
                           None, {"event": "message.delta", "delta": "lo"},
                           {"event": "run.completed", "output": "Hello",
                            "usage": {"input_tokens": 3, "output_tokens": 2}}])
    resp = chat(client, hermes_agent, "hi there")
    assert resp.status_code == 200
    events = parse_sse(resp)
    assert events[0]["type"] == "conversation_id"
    assert "".join(e["text"] for e in events if e["type"] == "text") == "Hello"
    assert events[-1] == {"type": "done", "model": "fake-model", "runtime": "hermes"}

    body = hermes.runs[0]
    assert body["input"] == "hi there"
    assert body["session_id"] == "sess-1"
    assert body["conversation_history"] == []
    assert "Tom" in body["instructions"]

    svc = chat_service_for(hermes_agent)
    conv_id = events[0]["id"]
    rows = svc.get_history_rows(conv_id)
    assert [(r["role"], r["runtime"]) for r in rows] == [("user", "hermes"), ("assistant", "hermes")]
    assert rows[1]["content"] == "Hello"
    assert rows[1]["tool_calls"] is None
    state = svc.get_external_state(conv_id)
    assert state["external_session_id"] == "sess-1"
    assert state["external_connection_id"] == "conn-1"
    assert "Tom" in state["context_snapshot"]
    assert svc.unresolved_turn(conv_id) is None
    assert svc.get_turn(rows[0]["turn_id"])["state"] == "done"

    # public payload never leaks internals, and carries the effective runtime
    conv = client.get(f"/api/agents/{hermes_agent['id']}/conversations/{conv_id}").json()
    assert "context_snapshot" not in conv and "external_session_id" not in conv
    assert conv["effective_runtime"] == "hermes"
    assert conv["messages"][1]["runtime"] == "hermes"
    listed = client.get(f"/api/agents/{hermes_agent['id']}/conversations").json()["conversations"]
    assert "context_snapshot" not in listed[0]


def test_two_turn_continuity_sends_mirror_and_same_snapshot(client, hermes, hermes_agent):
    hermes.scripts.append([{"event": "message.delta", "delta": "A1"}, {"event": "run.completed", "output": "A1"}])
    events = parse_sse(chat(client, hermes_agent, "Q1"))
    conv_id = events[0]["id"]
    hermes.scripts.append([{"event": "message.delta", "delta": "A2"}, {"event": "run.completed", "output": "A2"}])
    events2 = parse_sse(chat(client, hermes_agent, "Q2", conversation_id=conv_id))
    assert events2[-1]["type"] == "done"
    b1, b2 = hermes.runs
    assert b2["conversation_history"] == [{"role": "user", "content": "Q1"},
                                          {"role": "assistant", "content": "A1"}]
    assert b2["instructions"] == b1["instructions"]
    assert b2["session_id"] == "sess-1"
    assert len(hermes.runs) == 2


def test_tool_events_become_cards_not_tool_calls(client, hermes, hermes_agent):
    hermes.scripts.append([
        {"event": "tool.started", "tool": "terminal", "preview": "ls"},
        {"event": "tool.started", "tool": "terminal", "preview": "pwd"},
        {"event": "tool.completed", "tool": "terminal", "duration": 0.5, "error": False},
        {"event": "message.delta", "delta": "done"},
        {"event": "run.completed", "output": "done"},
    ])
    events = parse_sse(chat(client, hermes_agent))
    starts = [e for e in events if e["type"] == "tool_start"]
    ends = [e for e in events if e["type"] == "tool_end"]
    assert len(starts) == 2 and len(ends) == 1
    assert ends[0]["tool_use_id"] == starts[0]["tool_use_id"]  # FIFO pairing
    assert ends[0]["elapsed_ms"] == 500
    svc = chat_service_for(hermes_agent)
    rows = svc.get_history_rows(events[0]["id"])
    assert rows[1]["tool_calls"] is None
    meta = json.loads(svc.get_conversation(events[0]["id"])["messages"][1]["display_meta"])
    assert [c["tool"] for c in meta["hermes_tools"]] == ["terminal", "terminal"]


def test_output_used_when_no_deltas(client, hermes, hermes_agent):
    hermes.scripts.append([{"event": "run.completed", "output": "Only output"}])
    events = parse_sse(chat(client, hermes_agent))
    svc = chat_service_for(hermes_agent)
    assert svc.get_history_rows(events[0]["id"])[1]["content"] == "Only output"
    # the browser must see it too, not only the DB
    assert "".join(e["text"] for e in events if e["type"] == "text") == "Only output"


def test_stream_ending_without_terminal_event_enters_recovery(client, hermes, hermes_agent):
    hermes.scripts.append([{"event": "message.delta", "delta": "half"}])  # no run.* event
    hermes.statuses["run-1"] = {"status": "completed", "output": "whole answer"}
    events = parse_sse(chat(client, hermes_agent))
    assert any(e["type"] == "text_replace" and e["text"] == "whole answer" for e in events)
    assert events[-1]["type"] == "done"
    svc = chat_service_for(hermes_agent)
    conv_id = events[0]["id"]
    assert svc.unresolved_turn(conv_id) is None
    assert svc.get_history_rows(conv_id)[1]["content"] == "whole answer"


def test_streamed_text_wins_over_output(client, hermes, hermes_agent):
    hermes.scripts.append([{"event": "message.delta", "delta": "interim "},
                           {"event": "message.delta", "delta": "final"},
                           {"event": "run.completed", "output": "final"}])
    events = parse_sse(chat(client, hermes_agent))
    svc = chat_service_for(hermes_agent)
    assert svc.get_history_rows(events[0]["id"])[1]["content"] == "interim final"


def test_chatty_only_modes_rejected(client, hermes, hermes_agent):
    resp = chat(client, hermes_agent, training_mode=True)
    assert resp.status_code == 400
    assert "training" in resp.json()["detail"]
    resp = chat(client, hermes_agent, plan_mode=True)
    assert resp.status_code == 400
    resp = chat(client, hermes_agent, playbook_slug="daily-review")
    assert resp.status_code == 400 and "playbook" in resp.json()["detail"]
    assert hermes.runs == []
    assert not admission.active_leases(hermes_agent["id"])


def test_native_done_carries_runtime(client, monkeypatch):
    from tests.test_http_chat import MockAIProvider
    monkeypatch.setattr("agents.router.get_ai_provider", lambda **kw: MockAIProvider())
    agent = make_agent(client)
    events = parse_sse(chat(client, agent))
    assert events[-1]["runtime"] == "chatty"


# ── Failure classification ────────────────────────────────────────────────────

def test_connect_error_leaves_nothing_behind(client, hermes, hermes_agent):
    # Session is created first; make the RUN submission fail at connect level.
    hermes.run_submit_error = httpx.ConnectError("refused")
    events = parse_sse(chat(client, hermes_agent))
    assert events[-1]["type"] == "error" and "reach" in events[-1]["error"].lower()
    svc = chat_service_for(hermes_agent)
    conv_id = events[0]["id"]
    assert svc.get_history_rows(conv_id) == []
    assert svc.unresolved_turn(conv_id) is None
    # the conversation is usable again immediately
    hermes.run_submit_error = None
    hermes.scripts.append([{"event": "run.completed", "output": "ok"}])
    assert parse_sse(chat(client, hermes_agent, conversation_id=conv_id))[-1]["type"] == "done"


def test_server_error_on_submit_is_ambiguous_until_resolved(client, hermes, hermes_agent):
    hermes.run_submit_status = 500
    events = parse_sse(chat(client, hermes_agent))
    assert events[-1]["type"] == "error"
    conv_id = events[0]["id"]
    svc = chat_service_for(hermes_agent)
    row = svc.unresolved_turn(conv_id)
    assert row["state"] == "ambiguous"
    # blocked, whatever the runtime
    hermes.run_submit_status = 202
    resp = chat(client, hermes_agent, conversation_id=conv_id)
    assert resp.status_code == 409
    assert resp.json()["detail"]["turn"]["state"] == "ambiguous"
    conv = client.get(f"/api/agents/{hermes_agent['id']}/conversations/{conv_id}").json()
    assert conv["unresolved_turn"]["state"] == "ambiguous"
    # the user decides
    r = client.post(f"/api/agents/{hermes_agent['id']}/conversations/{conv_id}/resolve",
                    json={"action": "mark_failed"})
    assert r.json()["resolved"] is True
    rows = svc.get_history_rows(conv_id)
    assert [r["role"] for r in rows] == ["user"]  # transcript stays complete
    hermes.scripts.append([{"event": "run.completed", "output": "ok"}])
    assert parse_sse(chat(client, hermes_agent, conversation_id=conv_id))[-1]["type"] == "done"


def test_concurrent_turn_on_same_conversation_409(client, hermes, hermes_agent):
    hermes.scripts.append([{"event": "run.completed", "output": "ok"}])
    conv_id = parse_sse(chat(client, hermes_agent))[0]["id"]

    class HeldLock:  # stands in for a turn holding the conversation mutex
        def locked(self):
            return True

    admission._conversation_locks[conv_id] = HeldLock()
    try:
        resp = chat(client, hermes_agent, conversation_id=conv_id)
        assert resp.status_code == 409
        assert len(hermes.runs) == 1
        assert not admission.active_leases(hermes_agent["id"])
    finally:
        admission._conversation_locks.pop(conv_id, None)


def test_dropped_stream_recovers_from_status(client, hermes, hermes_agent):
    hermes.scripts.append([{"event": "message.delta", "delta": "partial "},
                           {"event": "message.delta", "delta": "never sent"}])
    hermes.drop_after = 1
    hermes.statuses["run-1"] = {"status": "completed", "output": "the real answer", "model": "m"}
    events = parse_sse(chat(client, hermes_agent))
    replace = [e for e in events if e["type"] == "text_replace"]
    assert replace and replace[0]["text"] == "the real answer"
    assert events[-1]["type"] == "done"
    svc = chat_service_for(hermes_agent)
    conv = svc.get_conversation(events[0]["id"])
    assert conv["messages"][1]["content"] == "the real answer"
    assert json.loads(conv["messages"][1]["display_meta"])["recovered"] is True


def test_dropped_stream_run_failed(client, hermes, hermes_agent):
    hermes.scripts.append([{"event": "message.delta", "delta": "x"}])
    hermes.drop_after = 1
    hermes.statuses["run-1"] = {"status": "failed", "error": "kaboom"}
    events = parse_sse(chat(client, hermes_agent))
    assert events[-1]["type"] == "error"
    svc = chat_service_for(hermes_agent)
    assert svc.unresolved_turn(events[0]["id"]) is None


def test_dropped_stream_waiting_for_approval_stops(client, hermes, hermes_agent):
    hermes.scripts.append([{"event": "message.delta", "delta": "x"}])
    hermes.drop_after = 1
    hermes.statuses["run-1"] = {"status": "waiting_for_approval"}
    events = parse_sse(chat(client, hermes_agent))
    assert events[-1]["type"] == "error" and "stopped" in events[-1]["error"]
    assert hermes.stops == ["run-1"]


# ── Recovery after a crash (journal reconciliation) ───────────────────────────

def test_reconcile_submitted_row_after_restart(client, hermes, hermes_agent):
    hermes.scripts.append([{"event": "run.completed", "output": "ok"}])
    conv_id = parse_sse(chat(client, hermes_agent))[0]["id"]
    svc = chat_service_for(hermes_agent)
    # Simulate a crash after 202 + journal write, before the user row was saved.
    svc.open_turn("t-crash", conv_id, "lost question")
    svc.mark_turn("t-crash", "submitted", "run-9")
    hermes.statuses["run-9"] = {"status": "completed", "output": "late answer"}
    hermes.scripts.append([{"event": "run.completed", "output": "next"}])
    events = parse_sse(chat(client, hermes_agent, "next q", conversation_id=conv_id))
    assert events[-1]["type"] == "done"
    rows = svc.get_history_rows(conv_id)
    contents = [r["content"] for r in rows]
    assert "lost question" in contents and "late answer" in contents
    assert svc.get_turn("t-crash")["state"] == "done"
    # and the recovered exchange was sent as history
    assert {"role": "user", "content": "lost question"} in hermes.runs[-1]["conversation_history"]


def test_reconcile_404_is_unknown_not_failed(client, hermes, hermes_agent):
    hermes.scripts.append([{"event": "run.completed", "output": "ok"}])
    conv_id = parse_sse(chat(client, hermes_agent))[0]["id"]
    svc = chat_service_for(hermes_agent)
    svc.open_turn("t-gone", conv_id, "q")
    svc.mark_turn("t-gone", "submitted", "run-gone")
    resp = chat(client, hermes_agent, conversation_id=conv_id)
    assert resp.status_code == 409
    assert svc.get_turn("t-gone")["state"] == "unknown"


def test_orphaned_submitting_becomes_ambiguous(client, hermes, hermes_agent):
    hermes.scripts.append([{"event": "run.completed", "output": "ok"}])
    conv_id = parse_sse(chat(client, hermes_agent))[0]["id"]
    svc = chat_service_for(hermes_agent)
    svc.open_turn("t-orphan", conv_id, "q")
    resp = chat(client, hermes_agent, conversation_id=conv_id)
    assert resp.status_code == 409
    assert svc.get_turn("t-orphan")["state"] == "ambiguous"


# ── Approvals ─────────────────────────────────────────────────────────────────

def test_approval_without_capability_is_auto_denied(client, hermes, hermes_agent):
    hermes.scripts.append([
        {"event": "approval.request", "request_id": "r1", "command": "rm -rf /tmp/x",
         "choices": ["once", "deny"]},
        {"event": "message.delta", "delta": "ok"},
        {"event": "run.completed", "output": "ok"},
    ])
    events = parse_sse(chat(client, hermes_agent))
    confirm = next(e for e in events if e["type"] == "confirm")
    assert confirm["approval"]["actionable"] is False
    assert confirm["tool"] == "rm -rf /tmp/x"
    assert hermes.approvals == [{"choice": "deny"}]
    assert any(e["type"] == "confirm_resolved" and e["tool_use_id"] == "r1" for e in events)


def test_approval_with_capability_is_actionable_and_bound(client, hermes, hermes_agent):
    hermes.creds["capabilities"]["features"]["approval_request_id"] = True
    hermes.scripts.append([
        {"event": "approval.request", "request_id": "r1", "tool": "terminal", "choices": ["once", "deny"]},
        {"event": "approval.request", "request_id": "r2", "tool": "terminal", "choices": ["once", "deny"]},
        {"event": "approval.responded", "request_id": "r1"},
        {"event": "run.completed", "output": "ok"},
    ])
    events = parse_sse(chat(client, hermes_agent))
    confirms = [e for e in events if e["type"] == "confirm"]
    assert [c["tool_use_id"] for c in confirms] == ["r1", "r2"]
    assert all(c["approval"]["actionable"] for c in confirms)
    assert hermes.approvals == []  # nothing auto-answered
    resolved = [e["tool_use_id"] for e in events if e["type"] == "confirm_resolved"]
    assert resolved == ["r1", "r2"]  # r1 by the responded event, r2 at terminal


@pytest.mark.asyncio
async def test_handle_approval_posts_request_id(client, hermes, hermes_agent):
    hermes.creds["capabilities"]["features"]["approval_request_id"] = True
    from core.agents.runtime.hermes import HermesRuntime
    entry = run_registry.register("run-7", hermes_agent["id"], "conv-7", "t7")
    entry.approval_meta["r7"] = {}
    entry.pending_approvals["r7"] = "pending"
    rt = HermesRuntime()
    out = await rt.handle_approval(agent=hermes_agent, conversation_id="conv-7",
                                   tool_use_id="r7", choice="once")
    assert out["outcome"] == "responded"
    assert hermes.approvals == [{"choice": "once", "request_id": "r7"}]
    assert entry.pending_approvals["r7"] == "responded"
    # second click → 409, unknown id → 404
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as ei:
        await rt.handle_approval(agent=hermes_agent, conversation_id="conv-7",
                                 tool_use_id="r7", choice="once")
    assert ei.value.status_code == 409
    with pytest.raises(HTTPException) as ei:
        await rt.handle_approval(agent=hermes_agent, conversation_id="conv-7",
                                 tool_use_id="nope", choice="once")
    assert ei.value.status_code == 404


@pytest.mark.asyncio
async def test_handle_approval_classifies_hermes_errors(client, hermes, hermes_agent):
    hermes.creds["capabilities"]["features"]["approval_request_id"] = True
    from core.agents.runtime.hermes import HermesRuntime
    rt = HermesRuntime()
    entry = run_registry.register("run-8", hermes_agent["id"], "conv-8", "t8")
    for rid, status, expected in (("a", 409, "expired"), ("b", 500, "uncertain")):
        entry.approval_meta[rid] = {}
        entry.pending_approvals[rid] = "pending"
        hermes.approval_status = status
        out = await rt.handle_approval(agent=hermes_agent, conversation_id="conv-8",
                                       tool_use_id=rid, choice="deny")
        assert out["outcome"] == expected


def test_tool_execute_hermes_branch_requires_fields(client, hermes, hermes_agent):
    r = client.post(f"/api/agents/{hermes_agent['id']}/tool/execute", json={"kind": "hermes"})
    assert r.status_code == 400
    r = client.post(f"/api/agents/{hermes_agent['id']}/tool/execute",
                    json={"kind": "hermes", "conversation_id": "c", "tool_use_id": "x", "choice": "once"})
    assert r.status_code == 409  # no capability on this fake


# ── History builder ───────────────────────────────────────────────────────────

def _rows(pairs):
    out = []
    for i, (role, content) in enumerate(pairs):
        out.append({"role": role, "content": content, "seq": i, "runtime": "hermes",
                    "tool_calls": None, "tool_results": None})
    return out


def test_history_coalesces_and_trims_whole_exchanges():
    pairs = [("user", "u0"), ("assistant", "a0")]
    for i in range(1, 30):
        pairs += [("user", "u%d" % i * 200), ("assistant", "a%d" % i * 200)]
    pairs += [("assistant", "tail")]  # consecutive assistant rows get merged
    hist = build_conversation_history(_rows(pairs), None, None, budget=3000)
    assert sum(len(m["content"]) for m in hist) <= 3000
    assert hist[0] == {"role": "user", "content": "u0"}
    assert hist[1] == {"role": "assistant", "content": "a0"}
    roles = [m["role"] for m in hist]
    assert all(roles[i] != roles[i + 1] for i in range(len(roles) - 1))
    assert hist[-1]["content"].endswith("tail")


def test_history_compaction_keeps_head_and_gist():
    pairs = [("user", "u0"), ("assistant", "a0"), ("user", "old1"), ("assistant", "old2"),
             ("user", "kept-user"), ("assistant", "kept-a")]
    hist = build_conversation_history(_rows(pairs), "GIST", 4)
    assert hist[0]["content"] == "u0" and hist[1]["content"] == "a0"
    assert "GIST" in hist[2]["content"] and "kept-user" in hist[2]["content"]
    assert not any("old1" in m["content"] for m in hist)


def test_history_protected_prefix_is_bounded():
    pairs = [("user", "x" * 50_000), ("assistant", "y" * 50_000), ("user", "q"), ("assistant", "a")]
    hist = build_conversation_history(_rows(pairs), None, None, budget=10_000)
    assert sum(len(m["content"]) for m in hist) <= 10_000 + 200


# ── Runtime endpoints ─────────────────────────────────────────────────────────

def test_dev_switch_gated_by_env(client, hermes, monkeypatch):
    monkeypatch.delenv("HERMES_DEV_SWITCH", raising=False)
    agent = make_agent(client, name="A")
    r = client.post(f"/api/agents/{agent['id']}/runtime/dev-switch", json={"runtime": "hermes"})
    assert r.status_code == 404
    st = client.get(f"/api/agents/{agent['id']}/runtime/status").json()
    assert st["runtime"] == "chatty" and st["dev_switch"] is False and st["hermes"]["connected"] is True


def test_dev_switch_claims_hermes_once_and_marks_onboarded(client, hermes, monkeypatch):
    monkeypatch.setenv("HERMES_DEV_SWITCH", "1")
    a = make_agent(client, name="A")
    b = make_agent(client, name="B")
    assert not a["onboarding_complete"]
    r = client.post(f"/api/agents/{a['id']}/runtime/dev-switch", json={"runtime": "hermes"})
    assert r.status_code == 200 and r.json()["runtime"] == "hermes"
    a2 = client.get(f"/api/agents/{a['id']}").json()
    assert a2["runtime"] == "hermes" and a2["onboarding_complete"]
    # one Hermes agent per connection
    r = client.post(f"/api/agents/{b['id']}/runtime/dev-switch", json={"runtime": "hermes"})
    assert r.status_code == 409
    # idempotent for the holder, and switching back frees it
    assert client.post(f"/api/agents/{a['id']}/runtime/dev-switch", json={"runtime": "hermes"}).status_code == 200
    assert client.post(f"/api/agents/{a['id']}/runtime/dev-switch", json={"runtime": "chatty"}).json()["runtime"] == "chatty"
    assert client.post(f"/api/agents/{b['id']}/runtime/dev-switch", json={"runtime": "hermes"}).status_code == 200
    assert client.post(f"/api/agents/{a['id']}/runtime/dev-switch", json={"runtime": "nope"}).status_code == 400
    # runtime is never accepted through the generic update
    client.put(f"/api/agents/{a['id']}", json={"runtime": "hermes"})
    assert client.get(f"/api/agents/{a['id']}").json()["runtime"] == "chatty"


def test_settle_after_failed_user_save_keeps_transcript_complete(client, hermes, hermes_agent, monkeypatch):
    """Client-side failure after Hermes accepted the run: the detached settle
    task must still leave BOTH rows and a terminal journal state."""
    import time as _t
    from core.agents.chat_history.service import ChatHistoryService
    real_save = ChatHistoryService.save_message
    calls = {"n": 0}

    def flaky_save(self, *a, **k):
        if k.get("role") == "user" and k.get("runtime") == "hermes":
            calls["n"] += 1
            raise RuntimeError("disk full")
        return real_save(self, *a, **k)

    monkeypatch.setattr(ChatHistoryService, "save_message", flaky_save)
    hermes.scripts.append([{"event": "run.completed", "output": "late"}])
    hermes.statuses["run-1"] = {"status": "completed", "output": "late"}
    events = parse_sse(chat(client, hermes_agent, "q1"))
    assert events[-1]["type"] == "error"
    assert hermes.stops == ["run-1"]
    svc = chat_service_for(hermes_agent)
    conv_id = events[0]["id"]
    for _ in range(50):  # the settle task runs on the app loop
        turn = svc.unresolved_turn(conv_id)
        if turn is None:
            break
        _t.sleep(0.1)
    assert svc.unresolved_turn(conv_id) is None
    rows = svc.get_history_rows(conv_id)
    assert [(r["role"], r["content"]) for r in rows] == [("user", "q1"), ("assistant", "late")]


def test_mark_failed_refuses_to_clear_a_live_run(client, hermes, hermes_agent):
    hermes.scripts.append([{"event": "run.completed", "output": "ok"}])
    conv_id = parse_sse(chat(client, hermes_agent))[0]["id"]
    svc = chat_service_for(hermes_agent)
    svc.open_turn("t-live", conv_id, "still running")
    svc.mark_turn("t-live", "submitted", "run-live")
    hermes.statuses["run-live"] = {"status": "running"}
    # Hermes keeps reporting "running" even after stop: the guard must hold.
    import core.agents.runtime.hermes as hmod
    hmod_settle = hmod.STOP_SETTLE_S
    hmod.STOP_SETTLE_S = 0.1
    try:
        r = client.post(f"/api/agents/{hermes_agent['id']}/conversations/{conv_id}/resolve",
                        json={"action": "mark_failed"})
    finally:
        hmod.STOP_SETTLE_S = hmod_settle
    assert r.status_code == 409
    assert hermes.stops[-1] == "run-live"
    assert svc.get_turn("t-live")["state"] == "stopping"
    # once Hermes reports terminal, the same action settles it
    hermes.statuses["run-live"] = {"status": "cancelled"}
    r = client.post(f"/api/agents/{hermes_agent['id']}/conversations/{conv_id}/resolve",
                    json={"action": "mark_failed"})
    assert r.json()["resolved"] is True
    assert svc.get_turn("t-live")["state"] == "failed"
