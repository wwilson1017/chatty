"""Computer tasks (PR 3): the agent tools, the helper loop against a fake computer (httpx
MockTransport) and a scripted provider, gates ending a task, the budget, policy at every
boundary, the lease and runner lock, orphan sweep outcomes, completion at most once, and the
idempotent usage row. No network, no real model."""

import asyncio
import fcntl
import json
import threading
import time

import httpx
import pytest

from core.agents.scheduled_actions import processor
from integrations.computer import card, completion, db, runner, tools
from integrations.computer import client as client_mod
from integrations.registry import save_credentials

SECRET = "s3cret-s3cret-s3cret-s3cret-s3cret"
MODEL = "claude-sonnet-4-6"  # exactly priced ($3 / $15)


# ── fakes ────────────────────────────────────────────────────────────────────

class FakeComputer:
    """The control API the runner talks to: lease, snapshots, element descriptions, acts, shell, files."""

    def __init__(self):
        self.calls: list[tuple[str, str, dict | None]] = []
        self.lease = None          # (token, agent, task_id)
        self.epoch_n = 1
        self.human = False         # a person has control
        self.lose_lease = False    # the next renew answers lease_lost
        self.element_changed = False
        self.overlaps = 0          # activations while another lease was live (must stay 0)
        self.elements: dict[str, dict] = {}
        self.focused: dict | None = None
        self.snapshot = '- heading "Shop" [level=1]\n- button "Add to cart" [ref=e5]\n- button "Place order" [ref=e10]'
        self.url = "https://shop.example/checkout"
        self.files: dict[str, bytes] = {}
        self.lock = threading.Lock()

    @property
    def epoch(self):
        return f"boot:{self.epoch_n}"

    def handle(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content and request.headers.get("content-type", "").startswith("application/json") else None
        path = request.url.path
        with self.lock:
            self.calls.append((request.method, path, body))
            assert request.headers["Authorization"] == f"Bearer {SECRET}"
            return self._route(request, path, body)

    def _err(self, status, code, **extra):
        return httpx.Response(status, json={"error": code, "detail": code.replace("_", " "), **extra})

    def _check_lease(self, body):
        if not self.lease or body.get("lease") != self.lease[0]:
            return self._err(409, "lease_lost")
        if body.get("epoch") != self.epoch:
            return self._err(409, "stale_epoch", epoch=self.epoch)
        if self.human:
            return self._err(409, "human_in_control")
        return None

    def _route(self, request, path, body):
        if path == "/health":
            return httpx.Response(200, json={"api_version": "1.0"})
        if path == "/desktop/activate":
            if self.human:
                return self._err(409, "human_in_control")
            if self.lease:
                self.overlaps += 0 if self.lease[2] != body["task_id"] else 0
                return self._err(409, "busy", holder={"agent": self.lease[1], "task_id": self.lease[2]})
            self.epoch_n += 1
            self.lease = (f"lease-{self.epoch_n}", body["agent"], body.get("task_id"))
            return httpx.Response(200, json={"lease": self.lease[0], "epoch": self.epoch, "expires_in": 120})
        if path == "/desktop/lease/renew":
            if self.lose_lease or not self.lease or body["lease"] != self.lease[0]:
                self.lease = None
                return self._err(409, "lease_lost")
            return httpx.Response(200, json={"epoch": self.epoch, "expires_in": 120, "human_in_control": self.human,
                                             "control_ended": None})
        if path == "/desktop/lease/release":
            released = bool(self.lease and body["lease"] == self.lease[0])
            if released:
                self.lease = None
            return httpx.Response(200, json={"released": released})
        if path == "/control/status":
            return httpx.Response(200, json={"human_in_control": self.human, "epoch": self.epoch, "control": None})
        if path.startswith("/files"):
            agent, p = request.url.params["agent"], request.url.params["path"]
            if path == "/files":
                return httpx.Response(200, json={"path": p, "entries": [{"name": n.rsplit("/", 1)[-1], "type": "file", "size": len(d), "mtime": 0}
                                                                         for n, d in self.files.items() if n.startswith(agent)]})
            key = f"{agent}/{p}"
            if request.method == "PUT":
                self.files[key] = request.content
                return httpx.Response(200, json={"path": p, "size": len(request.content)})
            if key not in self.files:
                return self._err(404, "not_found")
            return httpx.Response(200, content=self.files[key], headers={"X-File-Name": p.rsplit("/", 1)[-1],
                                                                          "Content-Type": "application/octet-stream"})
        # everything below needs the lease
        refused = self._check_lease(body or {})
        if refused:
            return refused
        if path == "/browser/snapshot":
            return httpx.Response(200, json={"url": self.url, "title": "Checkout", "snapshot": self.snapshot, "truncated": False,
                                             "total": None, "tabs": [{"index": 0, "url": self.url, "title": "Checkout", "active": True}]})
        if path == "/browser/element":
            el = self.elements.get(body.get("ref")) if body.get("ref") else self.focused
            return httpx.Response(200, json=el or {"found": False, "page": {"host": "shop.example", "path": "/checkout", "title": "Checkout"}})
        if path == "/browser/act":
            if self.element_changed:
                return self._err(409, "element_changed", mismatches=["name"])
            return httpx.Response(200, json={"action_id": body["action_id"], "status": "done", "result": {"url": self.url, "title": "Checkout"}})
        if path == "/shell":
            return httpx.Response(200, json={"exit_code": 0, "stdout": f"ran: {body['command']}", "stderr": "", "truncated": False,
                                             "timed_out": False, "killed": False})
        return httpx.Response(404, json={"error": "not_found", "detail": path})

    def acts(self):
        return [b for m, p, b in self.calls if p == "/browser/act"]


def element(name, ref="e10", *, is_submit=True, path="/checkout", role="button", form_action="https://shop.example/order"):
    return {"found": True, "ref": ref, "tag": "button", "role": role, "name": name, "type": "submit", "href": None,
            "is_submit": is_submit, "form": {"action": form_action, "method": "post"} if is_submit else None,
            "frame_url": f"https://shop.example{path}", "page": {"host": "shop.example", "path": path, "title": "Checkout"},
            "context_kind": "form" if is_submit else None, "context_fp": "abc" if is_submit else None,
            "total": {"amount": "45.00", "currency": "USD", "text": "Total $45.00"}}


class FakeProvider:
    """Scripted turns: each entry is {"text", "tool_calls", "usage"}; the last one repeats."""

    provider_name = "fake"

    def __init__(self, turns, *, usage=None, delay=0.0, on_call=None):
        self.model = MODEL
        self.max_tokens = 16384
        self.turns = turns
        self.usage = usage or {"input_tokens": 1000, "output_tokens": 50}
        self.delay = delay
        self.on_call = on_call
        self.calls = 0
        self.seen: list[list] = []

    async def stream_turn(self, messages, tools, system_prompt):
        self.calls += 1
        self.seen.append(messages)
        if self.on_call:
            self.on_call(self.calls)
        if self.delay:
            await asyncio.sleep(self.delay)
        t = self.turns[min(self.calls - 1, len(self.turns) - 1)]
        if t.get("text"):
            yield {"type": "text", "text": t["text"]}
        calls = [{"id": f"tu{self.calls}-{i}", "name": c[0], "args": c[1]} for i, c in enumerate(t.get("tool_calls", []))]
        usage = dict(self.usage) if callable(getattr(self.usage, "get", None)) else self.usage(self)
        yield {"type": "_turn_complete", "tool_calls": calls, "stop_reason": "tool_use" if calls else "end_turn", "usage": usage}

    def add_tool_results(self, messages, tool_calls, results):
        return messages + [{"role": "assistant", "content": [{"type": "tool_use", "id": tc["id"], "name": tc["name"], "input": tc["args"]} for tc in tool_calls]},
                           {"role": "user", "content": [{"type": "tool_result", "tool_use_id": r["tool_use_id"], "content": r["content"]} for r in results]}]


# ── fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def fake(client, monkeypatch):
    fc = FakeComputer()
    monkeypatch.setenv("COMPUTER_URL", "http://computer.internal:8080")
    monkeypatch.setenv("COMPUTER_SECRET", SECRET)
    def make():
        return client_mod.ComputerClient("http://computer.internal:8080", SECRET, transport=httpx.MockTransport(fc.handle))
    monkeypatch.setattr(client_mod, "get_client", make)
    monkeypatch.setattr(tools, "get_client", make)
    monkeypatch.setattr(runner, "get_client", make)
    monkeypatch.setattr(runner, "CONTROL_POLL_S", 0.01)
    monkeypatch.setattr(runner, "BUSY_RETRY_S", 0.01)
    submitted: list[str] = []
    monkeypatch.setattr(completion, "submit", submitted.append)
    fc.submitted = submitted
    fc.client = client
    save_credentials("computer", {"enabled": True, "helper_model": MODEL})
    yield fc


def _ctx(slug="tom", origin="user", **kw):
    return {"agent_slug": slug, "agent_name": slug.title(), "conversation_id": kw.get("conversation_id", "conv-1"),
            "origin": origin, "route": kw.get("route", {"channel": "web"}), "action_id": kw.get("action_id"),
            "cache_dir": kw.get("cache_dir", "")}


def _queue(task="buy the blue mug", slug="tom", **kw):
    out = asyncio.run(tools.computer_task(task, _ctx=_ctx(slug, **kw), follow_up_of=kw.get("follow_up_of")))
    assert "task_id" in out, out
    return out["task_id"]


def _run(fake, provider, monkeypatch, task_id=None):
    """Claim and run the next task with `provider` as the helper model."""
    monkeypatch.setattr(runner, "get_ai_provider", lambda **kw: provider)
    task = db.claim_next("w1") if task_id is None else db.claim_next("w1")
    assert task and (task_id is None or task["id"] == task_id)
    outcome = asyncio.run(runner.run_task(task, "w1"))
    return outcome, db.get_task(task["id"])


SNAP = ("browser", {"action": "snapshot"})
CLICK_ORDER = ("browser", {"action": "click", "ref": "e10"})
CLICK_CART = ("browser", {"action": "click", "ref": "e5"})
FINAL = {"text": "Done: the mug is in the cart."}


# ── tools ────────────────────────────────────────────────────────────────────

class TestTools:
    def test_queue_and_views(self, fake):
        tid = _queue(action_id="sa-9", origin="background")
        t = db.get_task(tid)
        assert t["status"] == "queued" and t["origin"] == "background" and t["action_id"] == "sa-9"
        assert t["root_task_id"] == tid and t["helper_model"] == MODEL and t["helper_provider"] == "anthropic"
        assert tools.computer_task_get(tid, _ctx=_ctx())["status"] == "queued"
        assert tools.computer_task_get(tid, _ctx=_ctx("dana"))["error"].startswith("No task")
        assert [x["id"] for x in tools.computer_task_list(_ctx=_ctx())["tasks"]] == [tid]
        assert tools.computer_task_list(_ctx=_ctx("dana"))["tasks"] == []
        info = tools.computer_info(_ctx=_ctx())
        assert info["enabled_for_this_agent"] and info["queued"] == 1 and info["helper_model"] == MODEL

    def test_cancel_own_task_only(self, fake):
        tid = _queue()
        assert "error" in tools.computer_task_cancel(tid, _ctx=_ctx("dana"))
        assert tools.computer_task_cancel(tid, _ctx=_ctx())["status"] == "cancelled"
        assert db.get_task(tid)["status"] == "cancelled" and db.get_task(tid)["cancel_requested"] == 1
        assert "already finished" in tools.computer_task_cancel(tid, _ctx=_ctx())["error"]
        assert fake.submitted == []  # the agent cancelled it: no report turn

    def test_refusals_at_queue_time(self, fake):
        assert tools.computer_task_get("nope", _ctx=_ctx())["error"]
        assert "required" in asyncio.run(tools.computer_task("  ", _ctx=_ctx()))["error"]
        save_credentials("computer", {"enabled": True, "helper_model": MODEL, "disabled_agents": ["tom"]})
        assert "turned off for this agent" in asyncio.run(tools.computer_task("x", _ctx=_ctx()))["error"]
        save_credentials("computer", {"enabled": False, "helper_model": MODEL})
        assert "not set up" in asyncio.run(tools.computer_task("x", _ctx=_ctx()))["error"]
        save_credentials("computer", {"enabled": True, "helper_model": "claude-sonnet-5-5-turbo"})
        assert "no exact price" in asyncio.run(tools.computer_task("x", _ctx=_ctx()))["error"]

    def test_follow_up_must_be_own_finished_task(self, fake):
        tid = _queue()
        r = asyncio.run(tools.computer_task("more", follow_up_of=tid, _ctx=_ctx("dana")))
        assert r["error"].startswith("No task")
        r = asyncio.run(tools.computer_task("more", follow_up_of=tid, _ctx=_ctx()))
        assert "hasn't finished" in r["error"]
        db.finish_task(tid, "done", "finished", notify=False, result_text="ok")
        fid = _queue("more", follow_up_of=tid)
        f = db.get_task(fid)
        assert f["parent_task_id"] == tid and f["root_task_id"] == tid

    def test_file_refs_land_in_the_inbox_and_file_get_returns_a_ref(self, fake, tmp_path):
        from core.agents.tools.file_cache import cache_file, load_cached_file
        cache = str(tmp_path / "cache")
        ref = cache_file(cache, b"PDF-bytes", "Q3 report.pdf", "application/pdf")
        out = asyncio.run(tools.computer_task("read it", file_refs=[ref], _ctx=_ctx(cache_dir=cache)))
        assert out["inbox_files"] == ["/workspace/tom/inbox/Q3_report.pdf"]
        assert fake.files["tom/inbox/Q3_report.pdf"] == b"PDF-bytes"
        assert "inbox/Q3_report.pdf" in db.get_task(out["task_id"])["task"]
        assert "unknown or expired" in asyncio.run(tools.computer_task("x", file_refs=["000000000000"], _ctx=_ctx(cache_dir=cache)))["error"]

        fake.files["tom/downloads/out.csv"] = b"a,b\n1,2\n"
        got = asyncio.run(tools.computer_file_get("downloads/out.csv", _ctx=_ctx(cache_dir=cache)))
        assert got["filename"] == "out.csv" and got["mime_type"] == "text/csv" and got["size_bytes"] == 8
        assert load_cached_file(cache, got["file_ref"])["raw"] == b"a,b\n1,2\n"
        assert "not found" in asyncio.run(tools.computer_file_get("nope.txt", _ctx=_ctx(cache_dir=cache)))["error"]

    def test_definitions_are_context_aware_and_registered(self):
        from agents.tool_loader import INTEGRATION_MODULES, tool_flags
        assert INTEGRATION_MODULES["computer"] == ("integrations.computer.tools", "COMPUTER_TOOL_DEFS")
        flags = tool_flags(tools.COMPUTER_TOOL_DEFS)
        assert all(flags[d["name"]] == {"context_aware": True} for d in tools.COMPUTER_TOOL_DEFS)
        assert all(d["writes"] is False and d["kind"] == "integration" for d in tools.COMPUTER_TOOL_DEFS)
        assert set(tools.TOOL_EXECUTORS) == {d["name"] for d in tools.COMPUTER_TOOL_DEFS}


# ── the helper loop ──────────────────────────────────────────────────────────

class TestHelperLoop:
    def test_place_order_ref_ends_needs_approval_and_the_computer_never_receives_the_act(self, fake, monkeypatch):
        fake.elements["e10"] = element("Place order")
        tid = _queue()
        prov = FakeProvider([{"text": "Looking.", "tool_calls": [SNAP]}, {"text": "Ordering.", "tool_calls": [CLICK_ORDER]}, FINAL])
        outcome, t = _run(fake, prov, monkeypatch)
        assert outcome == "done"
        assert t["status"] == "needs_approval" and t["finish_reason"] == "stopped before buy: Place order"
        assert prov.calls == 2  # no model call after the gate
        assert fake.acts() == []  # the click never reached the computer
        gate = db.get_gate(t["gate_id"])
        assert gate["kind"] == "buy" and gate["name"] == "Place order" and gate["host"] == "shop.example"
        assert gate["status"] == "pending" and gate["rule"] == "1.buy" and gate["action"] == "act:click"
        assert json.loads(gate["total_json"])["amount"] == "45.00" and gate["context_fp"] == "abc"
        steps = db.list_steps(tid)
        assert [s["verdict"] for s in steps] == [None, "gated:buy"]
        assert t["result_text"] == "Ordering."  # the helper's progress travels with the report
        assert fake.submitted == [tid]
        # the lease was taken for this task and released
        assert ("POST", "/desktop/activate", {"agent": "tom", "task_id": tid}) in fake.calls
        assert fake.lease is None

    def test_free_click_carries_expect_and_action_id_then_task_finishes(self, fake, monkeypatch):
        fake.elements["e5"] = element("Add to cart", "e5", is_submit=False)
        tid = _queue()
        prov = FakeProvider([{"tool_calls": [SNAP]}, {"tool_calls": [CLICK_CART, ("shell", {"command": "ls"}),
                                                                      ("files", {"action": "write", "path": "notes.txt", "content": "hi"})]}, FINAL])
        outcome, t = _run(fake, prov, monkeypatch)
        assert t["status"] == "done" and t["result_text"] == FINAL["text"] and t["steps"] == 4
        act = fake.acts()[0]
        assert act["kind"] == "click" and act["ref"] == "e5" and len(act["action_id"]) == 26
        assert act["expect"] == {"action": "act:click", "host": "shop.example", "path": "/checkout", "frame_url": "https://shop.example/checkout",
                                 "role": "button", "name": "Add to cart", "form_action": None}
        assert act["lease"] == "lease-2" and act["epoch"] == "boot:2"
        assert fake.files["tom/notes.txt"] == b"hi"
        # tool results reach the model wrapped as untrusted content
        last_user = prov.seen[-1][-1]["content"]
        assert all("<untrusted_tool_result" in r["content"] for r in last_user)
        assert [s["verdict"] for s in db.list_steps(tid)] == [None, "free:3.legwork", None, None]
        assert t["cost_actual_usd"] > 0 and t["cost_reserved_usd"] == 0 and t["input_tokens"] == 3000

    def test_request_approval_tool_ends_the_task(self, fake, monkeypatch):
        tid = _queue()
        prov = FakeProvider([{"tool_calls": [("request_approval", {"kind": "send", "reason": "send the draft", "item": "email to Bob"})]}, FINAL])
        _, t = _run(fake, prov, monkeypatch)
        assert t["status"] == "needs_approval" and prov.calls == 1
        gate = db.get_gate(t["gate_id"])
        assert gate["kind"] == "send" and gate["rule"] == "helper" and gate["item"] == "email to Bob" and gate["element_json"] is None
        assert db.list_steps(tid)[0]["tool"] == "request_approval"

    def test_element_changed_is_reported_not_fatal(self, fake, monkeypatch):
        fake.elements["e5"] = element("Add to cart", "e5", is_submit=False)
        fake.element_changed = True
        _queue()
        prov = FakeProvider([{"tool_calls": [CLICK_CART]}, FINAL])
        _, t = _run(fake, prov, monkeypatch)
        assert t["status"] == "done"
        res = json.loads(prov.seen[1][-1]["content"][0]["content"].split("\n", 1)[1].rsplit("\n", 1)[0])
        assert res["code"] == "element_changed" and "new snapshot" in res["hint"]

    def test_human_in_control_waits_and_the_action_is_not_performed(self, fake, monkeypatch):
        fake.elements["e5"] = element("Add to cart", "e5", is_submit=False)
        _queue()

        def on_call(n):
            if n == 1:
                fake.human = True
                threading.Timer(0.05, lambda: setattr(fake, "human", False)).start()
        prov = FakeProvider([{"tool_calls": [CLICK_CART]}, FINAL], on_call=on_call)
        _, t = _run(fake, prov, monkeypatch)
        assert t["status"] == "done"
        assert fake.acts() == []  # refused before anything was journaled; never re-sent on its own
        assert ("GET", "/control/status", None) in fake.calls
        res = prov.seen[1][-1]["content"][0]["content"]
        assert "not performed" in res and "handed it back" in res and "snapshot" in res

    def test_lost_lease_fences_the_worker(self, fake, monkeypatch):
        monkeypatch.setattr(runner, "RENEW_EVERY_S", 0.01)
        _queue()
        fake.lose_lease = True
        prov = FakeProvider([{"tool_calls": [SNAP]}, FINAL], delay=0.05)
        _, t = _run(fake, prov, monkeypatch)
        assert t["status"] == "failed" and t["finish_reason"] == "lost the screen"
        assert not any(p == "/browser/snapshot" for _, p, _ in fake.calls)  # fenced: nothing sent after the lost renewal

    def test_provider_without_usage_is_settled_from_an_estimate(self, fake, monkeypatch):
        """Only Anthropic's stream carries usage; an OpenAI/Gemini/Together helper must not keep the
        worst-case reservation charged after every call (27 calls would exhaust $10)."""
        _queue()
        prov = FakeProvider([{"text": "x" * 400, "tool_calls": [("files", {"action": "list", "path": "."})]}, FINAL], usage=lambda p: {})
        _, t = _run(fake, prov, monkeypatch)
        assert t["status"] == "done" and t["cost_reserved_usd"] == 0
        # two calls: well under the two reservations (each ≥ 8192 output tokens × $15/M ≈ $0.12 + input)
        assert 0 < t["cost_actual_usd"] < 0.1 and t["output_tokens"] >= 200 and t["input_tokens"] > 0

    def test_model_error_fails_the_task(self, fake, monkeypatch):
        _queue()

        class ErrProvider(FakeProvider):
            async def stream_turn(self, messages, tools, system_prompt):
                self.calls += 1
                yield {"type": "error", "error": "rate limited"}
                yield {"type": "_turn_complete", "tool_calls": [], "stop_reason": "error"}
        _, t = _run(fake, ErrProvider([]), monkeypatch)
        assert t["status"] == "failed" and "rate limited" in t["finish_reason"]
        assert t["cost_reserved_usd"] > 0 and t["cost_actual_usd"] == 0  # usage unknown: the reservation stays charged


class TestBudgetAndCaps:
    def test_budget_stops_the_task_with_a_report_and_no_extra_call(self, fake, monkeypatch):
        tid = _queue()
        # Every call: 600K input tokens (reserved at $3 × 1.25) and max_tokens of output.
        async def count(self, provider, system, messages, tools):
            return 600_000
        monkeypatch.setattr(runner._Run, "count_input_tokens", count)
        prov = FakeProvider([{"text": "working", "tool_calls": [("files", {"action": "list", "path": "."})]}],
                            usage=lambda p: {"input_tokens": 600_000, "output_tokens": p.max_tokens})
        _, t = _run(fake, prov, monkeypatch)
        assert t["status"] == "failed" and t["finish_reason"].startswith("budget reached")
        assert prov.calls == 5  # the 6th reservation didn't fit; no call was made for it
        assert t["cost_reserved_usd"] == 0 and 9 < t["cost_actual_usd"] <= db.BUDGET_USD
        assert t["result_text"].startswith("working\n\n[Stopped: budget reached")
        assert "Last steps:" in t["result_text"] and "files" in t["result_text"]
        # the 5th call's max_tokens was cut to fit what was left
        assert prov.max_tokens < runner.DEFAULT_MAX_TOKENS
        assert db.list_steps(tid)[-1]["cost_so_far_usd"] > 0

        # ... and the budget holds across the follow-up chain: a follow-up can't afford one call.
        _queue("keep going", follow_up_of=tid)
        prov2 = FakeProvider([FINAL])
        _, f = _run(fake, prov2, monkeypatch)
        assert f["status"] == "failed" and f["finish_reason"].startswith("budget reached") and prov2.calls == 0
        assert f["root_task_id"] == tid

    def test_follow_up_refused_at_queue_time_once_the_chain_is_spent(self, fake):
        tid = _queue()
        db.execute("UPDATE tasks SET status = 'done', cost_actual_usd = ? WHERE id = ?", (db.BUDGET_USD, tid))
        r = asyncio.run(tools.computer_task("more", follow_up_of=tid, _ctx=_ctx()))
        assert "used its allowance" in r["error"]

    def test_step_cap_is_hard(self, fake, monkeypatch):
        tid = _queue()
        db.execute("UPDATE tasks SET steps = ? WHERE id = ?", (db.MAX_STEPS - 1, tid))
        prov = FakeProvider([{"tool_calls": [("files", {"action": "list", "path": "."}), ("files", {"action": "list", "path": "."})]}, FINAL])
        _, t = _run(fake, prov, monkeypatch)
        assert t["status"] == "failed" and t["finish_reason"].startswith("step cap") and prov.calls == 1
        assert t["steps"] == db.MAX_STEPS  # the second tool call of the batch never ran

    def test_time_cap_is_hard(self, fake, monkeypatch):
        tid = _queue()
        db.execute("UPDATE tasks SET running_seconds = ? WHERE id = ?", (db.MAX_SECONDS, tid))
        prov = FakeProvider([FINAL])
        _, t = _run(fake, prov, monkeypatch)
        assert t["status"] == "failed" and t["finish_reason"].startswith("time cap") and prov.calls == 0

    def test_unpriced_helper_model_is_refused_at_claim(self, fake, monkeypatch):
        tid = _queue()
        db.execute("UPDATE tasks SET helper_model = 'claude-sonnet-5-5-turbo' WHERE id = ?", (tid,))
        prov = FakeProvider([FINAL])
        _, t = _run(fake, prov, monkeypatch)
        assert t["status"] == "failed" and t["finish_reason"] == "helper model refused" and prov.calls == 0
        assert not any(p == "/desktop/activate" for _, p, _ in fake.calls)

    def test_reserve_is_atomic_per_chain(self, fake):
        tid = _queue()
        assert db.reserve(tid, tid, 6.0)
        assert not db.reserve(tid, tid, 4.5)  # 10.5 > 10
        assert db.reserve(tid, tid, 4.0)
        assert db.chain_totals(tid)["cost"] == 10.0
        db.settle(tid, 6.0, 1.5, 10, 10)
        assert db.chain_totals(tid)["cost"] == 5.5


class TestPolicyAtEveryBoundary:
    def test_excluded_agent_is_cancelled_at_claim(self, fake, monkeypatch):
        tid = _queue()
        save_credentials("computer", {"enabled": True, "helper_model": MODEL, "disabled_agents": ["tom"]})
        prov = FakeProvider([FINAL])
        _, t = _run(fake, prov, monkeypatch)
        assert t["status"] == "cancelled" and t["finish_reason"] == "disabled" and prov.calls == 0
        assert fake.submitted == [tid]

    def test_disable_mid_task_stops_at_the_next_step(self, fake, monkeypatch):
        tid = _queue()

        def on_call(n):
            if n == 2:
                save_credentials("computer", {"enabled": True, "helper_model": MODEL, "disabled_agents": ["tom"]})
        prov = FakeProvider([{"tool_calls": [("files", {"action": "list", "path": "."})]}, {"tool_calls": [SNAP]}, FINAL], on_call=on_call)
        _, t = _run(fake, prov, monkeypatch)
        assert t["status"] == "cancelled" and t["finish_reason"] == "disabled" and prov.calls == 2
        assert not any(p == "/browser/snapshot" for _, p, _ in fake.calls)
        assert fake.lease is None  # released on the way out
        assert tid in fake.submitted

    def test_sweep_cancels_queued_tasks_of_excluded_agents(self, fake, monkeypatch):
        monkeypatch.setattr(runner, "kick", lambda: False)
        tid = _queue()
        save_credentials("computer", {"enabled": False})
        completion.sweep()
        t = db.get_task(tid)
        assert t["status"] == "cancelled" and t["finish_reason"] == "disabled"

    def test_cancel_while_running_stops_the_loop(self, fake, monkeypatch):
        tid = _queue()

        def on_call(n):
            if n == 1:
                db.finish_task(tid, "cancelled", "cancelled by owner", notify=False, cancel_requested=1)
        prov = FakeProvider([{"tool_calls": [SNAP]}, FINAL], on_call=on_call)
        outcome, t = _run(fake, prov, monkeypatch)
        assert outcome == "done" and t["status"] == "cancelled" and prov.calls == 1
        assert not any(p == "/browser/snapshot" for _, p, _ in fake.calls)


class TestOneScreen:
    def test_two_runners_never_hold_the_screen_at_once(self, fake, monkeypatch):
        a, b = _queue("a", slug="tom"), _queue("b", slug="dana")
        prov = FakeProvider([{"tool_calls": [SNAP]}, FINAL], delay=0.05)
        monkeypatch.setattr(runner, "get_ai_provider", lambda **kw: prov)
        ta, tb = db.claim_next("w1"), db.claim_next("w2")
        assert {ta["id"], tb["id"]} == {a, b}
        results = {}
        held: list[tuple[float, float]] = []
        orig = fake._route

        def route(request, path, body):
            r = orig(request, path, body)
            if path == "/desktop/activate" and r.status_code == 200:
                held.append([time.monotonic(), None])
            if path == "/desktop/lease/release" and held and held[-1][1] is None:
                held[-1][1] = time.monotonic()
            return r
        fake._route = route
        ths = [threading.Thread(target=lambda t, w: results.__setitem__(w, asyncio.run(runner.run_task(t, w))), args=(ta, "w1")),
               threading.Thread(target=lambda t, w: results.__setitem__(w, asyncio.run(runner.run_task(t, w))), args=(tb, "w2"))]
        for th in ths:
            th.start()
        for th in ths:
            th.join(timeout=10)
        assert sorted(results.values()) == ["busy", "done"]
        busy_id = a if db.get_task(a)["status"] == "queued" else b
        assert db.get_task(busy_id)["status"] == "queued" and db.get_task(busy_id)["worker_id"] is None
        # the second runner picks the requeued task up once the screen is free
        t2 = db.claim_next("w3")
        assert t2["id"] == busy_id and asyncio.run(runner.run_task(t2, "w3")) == "done"
        assert db.get_task(busy_id)["status"] == "done"
        # lease windows never overlapped
        held.sort()
        assert len(held) == 2 and held[0][1] is not None and held[0][1] <= held[1][0]

    def test_runner_lock_is_exclusive(self, tmp_path, monkeypatch):
        monkeypatch.setattr(db, "DATA_DIR", tmp_path)
        monkeypatch.setattr(runner, "_started", False)
        monkeypatch.setattr(runner, "_lock_file", None)
        monkeypatch.setattr(runner, "kick", lambda: True)
        assert runner.start() is True
        other = open(tmp_path / "runner.lock", "a+")
        with pytest.raises(OSError):
            fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)  # a second process can't take it
        runner.stop()
        fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)  # released on stop
        other.close()
        assert runner.kick() is True and runner._started is False  # the patched kick; the real one refuses below

    def test_kick_is_a_no_op_outside_the_web_app(self, monkeypatch):
        monkeypatch.setattr(runner, "_started", False)
        assert runner.kick() is False


class TestSweepAndAccounting:
    def test_orphan_outcomes(self, fake, monkeypatch):
        monkeypatch.setattr(runner, "kick", lambda: False)
        a, b, c = _queue("a"), _queue("b"), _queue("c")
        for tid in (a, b, c):
            db.claim_next("dead")
        # a: died during a model call (reservation kept); b: between steps; c: during a dispatching consequential action
        db.execute("UPDATE tasks SET heartbeat_at = datetime('now', '-10 minutes'), phase = 'model', cost_reserved_usd = 1.5 WHERE id = ?", (a,))
        db.execute("UPDATE tasks SET heartbeat_at = datetime('now', '-10 minutes'), phase = '' WHERE id = ?", (b,))
        gid = db.insert_gate(db.get_task(c), kind="buy", reason="r")
        db.execute("UPDATE gates SET status = 'dispatching', action_id = 'ACT1' WHERE id = ?", (gid,))
        db.execute("UPDATE tasks SET heartbeat_at = datetime('now', '-10 minutes'), phase = 'action', pending_action_id = 'ACT1' WHERE id = ?", (c,))
        live = _queue("live")
        db.claim_next("alive")  # fresh heartbeat: not an orphan
        completion.sweep()
        assert (db.get_task(a)["status"], db.get_task(a)["finish_reason"], db.get_task(a)["cost_reserved_usd"]) == ("failed", "interrupted", 1.5)
        assert (db.get_task(b)["status"], db.get_task(b)["finish_reason"]) == ("failed", "interrupted")
        assert db.get_task(c)["status"] == "outcome_unknown"
        assert db.get_task(live)["status"] == "running"
        assert set(fake.submitted) == {a, b, c}  # (the sweep also re-submits pending completions)

    def test_usage_row_is_idempotent(self, fake, monkeypatch):
        from core.agents.reminders import db as reminders_mod
        reminders_db = reminders_mod.get_db()  # the activity log lives in the reminders DB (patched by conftest)
        monkeypatch.setattr(runner, "kick", lambda: False)
        tid = _queue()
        db.execute("UPDATE tasks SET input_tokens = 1200, output_tokens = 300, running_seconds = 42 WHERE id = ?", (tid,))
        db.finish_task(tid, "done", "finished", notify=True, result_text="ok")
        rows = reminders_db.execute("SELECT * FROM execution_history WHERE id = ?", (f"vc-{tid}",)).fetchall()
        assert len(rows) == 1 and rows[0]["event_type"] == "computer" and rows[0]["model_used"] == MODEL
        assert rows[0]["input_tokens"] == 1200 and rows[0]["duration_ms"] == 42000 and rows[0]["agent"] == "tom"
        assert db.get_task(tid)["accounting_pending"] == 0
        db.execute("UPDATE tasks SET accounting_pending = 1 WHERE id = ?", (tid,))
        completion.sweep()
        completion.sweep()
        assert reminders_db.execute("SELECT COUNT(*) FROM execution_history WHERE id = ?", (f"vc-{tid}",)).fetchone()[0] == 1
        assert db.get_task(tid)["accounting_pending"] == 0
        # the usage dashboard prices it as background spend
        from core.agents.usage.service import get_usage_summary
        s = get_usage_summary(days=0)
        assert s["totals"]["events"] == 1 and s["totals"]["cost"] > 0

    def test_finish_task_is_the_only_terminal_path_and_first_write_wins(self, fake):
        tid = _queue()
        assert db.finish_task(tid, "done", "finished", notify=True)
        assert not db.finish_task(tid, "failed", "late", notify=True)
        assert db.get_task(tid)["status"] == "done" and fake.submitted == [tid]
        with pytest.raises(AssertionError):
            db.finish_task(tid, "running", "x", notify=False)
        with pytest.raises(ValueError):
            db.finish_task(tid, "done", "x", notify=False, bogus=1)
        # system-origin tasks never get a report turn
        sid = db.insert_task(agent_slug="tom", origin="system", task="t", helper_provider="anthropic", helper_model=MODEL)
        assert db.finish_task(sid, "done", "finished", notify=True) and db.get_task(sid)["completion_status"] == "none"


class TestCompletion:
    def test_report_turn_runs_at_most_once(self, fake, monkeypatch):
        tid = _queue()
        db.finish_task(tid, "needs_approval", "stopped before buy: Place order", notify=True, result_text="cart is full",
                       gate_id=db.insert_gate(db.get_task(tid), kind="buy", reason="r", element=element("Place order")))
        turns: list[str] = []

        from core.agents.background_runner import BackgroundResult

        def fake_turn(agent, title, instructions, user_message, **kw):
            turns.append(user_message)
            return BackgroundResult(text="Stopped before buying the mug ($45). Want me to…"), None
        monkeypatch.setattr(processor, "run_agent_background_turn", fake_turn)
        monkeypatch.setattr(processor, "_resolve_agent", lambda slug: {"slug": slug, "agent_name": "Tom"})
        delivered: list = []
        monkeypatch.setattr(processor, "deliver_background_result", lambda *a, **kw: delivered.append((a, kw)))
        completion.complete_task(tid)
        completion.complete_task(tid)
        completion.sweep()
        assert len(turns) == 1
        assert "needs the owner's approval" in turns[0] and "buy: Place order on shop.example" in turns[0]
        assert "<untrusted_tool_result" in turns[0] and "cart is full" in turns[0]
        t = db.get_task(tid)
        assert t["completion_status"] == "done" and t["summary_text"].startswith("Stopped before buying")
        assert len(delivered) == 1 and delivered[0][1]["route"] == {"channel": "web"}

    def test_stale_completion_is_finalized_without_a_second_turn(self, fake, monkeypatch):
        tid = _queue()
        db.finish_task(tid, "done", "finished", notify=True, result_text="ok")
        assert completion._claim(tid)
        db.execute("UPDATE tasks SET completion_claimed_at = datetime('now', '-30 minutes') WHERE id = ?", (tid,))
        monkeypatch.setattr(processor, "run_agent_background_turn", lambda *a, **kw: pytest.fail("turn re-run"))
        delivered: list = []
        monkeypatch.setattr(processor, "deliver_background_result", lambda *a, **kw: delivered.append(a))
        monkeypatch.setattr(runner, "kick", lambda: False)
        completion.sweep()
        assert db.get_task(tid)["completion_status"] == "done"
        assert delivered and f"Computer task {tid} finished (done)" in delivered[0][2]


class TestDashboardRoutes:
    def test_tasks_steps_and_cancel(self, fake):
        tid = _queue()
        db.add_step(tid, "browser", {"action": "snapshot"}, '{"url": "x"}', url="https://shop.example/")
        r = fake.client.get("/api/computer/tasks").json()["tasks"]
        assert r[0]["id"] == tid and r[0]["cost_usd"] == 0 and r[0]["status"] == "queued"
        assert fake.client.get("/api/computer/tasks?agent=dana").json()["tasks"] == []
        one = fake.client.get(f"/api/computer/tasks/{tid}").json()
        assert one["task"] == "buy the blue mug" and one["gate"] is None
        assert fake.client.get(f"/api/computer/tasks/{tid}/steps").json()["steps"][0]["tool"] == "browser"
        assert fake.client.get("/api/computer/tasks/nope").status_code == 404
        assert fake.client.post(f"/api/computer/tasks/{tid}/cancel").json() == {"ok": True, "cancelled": True}
        assert db.get_task(tid)["status"] == "cancelled"
        assert fake.client.post(f"/api/computer/tasks/{tid}/cancel").json()["cancelled"] is False

    def test_helper_model_setting(self, fake):
        s = fake.client.get("/api/integrations/computer/status").json()
        assert s["helper_model"] == MODEL and any(m["model"] == MODEL for m in s["helper_models"])
        assert all(m["provider"] for m in s["helper_models"])
        r = fake.client.put("/api/integrations/computer/helper-model", json={"model": "claude-sonnet-5-5-turbo"})
        assert r.status_code == 400 and "no exact price" in r.json()["detail"]
        assert fake.client.put("/api/integrations/computer/helper-model", json={"model": "claude-haiku-4-5"}).status_code == 200
        assert card.helper_model() == "claude-haiku-4-5"
