"""Screenshot-and-click (PR 5): the Anthropic backend behind the real SDK (an httpx MockTransport
scripts the Messages API, so the request shapes are the SDK's own), pixel actions classified at
press time, batches that stop at the first gated or failed call, screenshots kept for the record
and swept after 14 days, reservations from count_tokens, and an approved pixel gate replayed as
one left_click. The computer is the fake from test_computer_tasks. No network, no real model."""

import asyncio
import json

import anthropic
import httpx
import pytest

from core.providers.anthropic_provider import AnthropicProvider
from integrations.computer import approvals, card, completion, db, gates, runner
from integrations.registry import save_credentials

from tests.test_computer_tasks import PNG, _ctx, _queue, element, fake  # noqa: F401 (fake is a fixture)

SHOT_MODEL = "claude-sonnet-5-5"                   # exactly priced ($2 / $10), takes the computer toolset
BOX = {"x": 300, "y": 287, "w": 200, "h": 60}      # where "Buy now" is on screen; (400, 317) is its centre
CART_BOX = {"x": 40, "y": 700, "w": 120, "h": 40}  # "Add to cart"
THINK = {"type": "thinking", "thinking": "", "signature": "sig-1"}


def tool(name, inp=None, tid=None, toolset="computer"):
    """A tool_use block as the API returns it: toolset members carry toolset_name, custom tools don't."""
    b = {"type": "tool_use", "id": tid or f"tu-{name}", "name": name, "input": inp or {}}
    if toolset:
        b["toolset_name"] = toolset
    return b


def custom(name, args, tid=None):
    return tool(name, args, tid, toolset=None)


def text(t):
    return {"type": "text", "text": t}


SHOT = tool("screenshot")
CLICK_ORDER = tool("left_click", {"coordinate": [400, 317]})
CLICK_CART = tool("left_click", {"coordinate": [100, 720]})
EXPECT_CART = {"action": "left_click", "host": "shop.example", "path": "/checkout", "frame_url": "https://shop.example/checkout",
               "role": "button", "name": "Add to cart", "form_action": None}


class FakeAnthropic:
    """The Messages API behind the real SDK. `turns` is a list of content-block lists (the last one
    repeats; the string "refusal" is a refused turn); every request body is recorded. count_tokens
    answers `count`."""

    def __init__(self, turns, *, count=1000, status=200):
        self.turns, self.count, self.status = turns, count, status
        self.usage = {"input_tokens": 1000, "output_tokens": 50, "cache_creation_input_tokens": 200, "cache_read_input_tokens": 300}
        self.requests: list[dict] = []
        self.headers: list[dict] = []
        self.count_requests: list[dict] = []
        self._client = None

    def handle(self, req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        if req.url.path.endswith("/count_tokens"):
            self.count_requests.append(body)
            return httpx.Response(200, json={"input_tokens": self.count})
        self.requests.append(body)
        self.headers.append(dict(req.headers))
        if self.status != 200:
            return httpx.Response(self.status, json={"type": "error", "error": {"type": "api_error", "message": "boom"}})
        blocks = self.turns[min(len(self.requests) - 1, len(self.turns) - 1)]
        if blocks == "refusal":
            blocks, stop = [], "refusal"
        elif blocks == "max_tokens":  # cut off mid-thought: a partial text, no tool calls
            blocks, stop = [THINK, text("I was about to")], "max_tokens"
        else:
            stop = "tool_use" if any(b["type"] == "tool_use" for b in blocks) else "end_turn"
        return httpx.Response(200, json={"id": f"msg_{len(self.requests)}", "type": "message", "role": "assistant", "model": SHOT_MODEL,
                                         "content": blocks, "stop_reason": stop, "stop_sequence": None, "usage": self.usage})

    def client(self):
        if self._client is None:
            self._client = anthropic.AsyncAnthropic(api_key="k", max_retries=0,
                                                    http_client=httpx.AsyncClient(transport=httpx.MockTransport(self.handle)))
        return self._client

    def results(self, i):
        """The tool_result blocks request `i` carried in its last (user) message."""
        return self.requests[i]["messages"][-1]["content"]


@pytest.fixture
def shot(fake, monkeypatch):  # noqa: F811 (fake is the imported fixture)
    """The fake computer with 'Buy now' at BOX and 'Add to cart' at CART_BOX; the helper is Sonnet 5.5."""
    save_credentials("computer", {"enabled": True, "helper_model": SHOT_MODEL})
    fake.elements["e10"] = element("Buy now", box=BOX)
    fake.elements["e5"] = element("Add to cart", "e5", is_submit=False, box=CART_BOX)
    fake.snapshot = '- heading "Shop" [level=1]\n- button "Add to cart" [ref=e5]\n- button "Buy now" [ref=e10]'
    monkeypatch.setattr(runner, "get_ai_provider", lambda **kw: AnthropicProvider(api_key="k", model=SHOT_MODEL))
    monkeypatch.setattr(card, "get_client", runner.get_client)
    return fake


def _run(fc, monkeypatch, turns, **kw):
    """Claim and run the next task (the fake computer `fc` holds the page) against a scripted Messages API."""
    fa = FakeAnthropic(turns, **kw)
    monkeypatch.setattr(runner, "anthropic_client", lambda provider: fa.client())
    task = db.claim_next("w1")
    assert task
    asyncio.run(runner.run_task(task, "w1"))
    return fa, db.get_task(task["id"])


def _live_run():
    """A _Run holding the screen, for driving batch() directly (the task stays running)."""
    task = db.claim_next("w1")
    run = runner._Run(task, "w1", runner.get_client())
    asyncio.run(run.activate())
    return run


def _end(run):
    asyncio.run(run.release())
    asyncio.run(run.client.aclose())


# ── mode ─────────────────────────────────────────────────────────────────────

class TestMode:
    def test_mode_is_chosen_by_model(self, shot):
        for m in ("claude-sonnet-5-5", "claude-opus-5-5", "claude-haiku-5-5", "claude-opus-4-8", "claude-fable-5-1"):
            assert card.mode_for(m) == "screenshot", m
        for m in ("claude-sonnet-4-6", "claude-opus-4-6", "gpt-5", "gemini-2.5-pro", "meta-llama/x"):
            assert card.mode_for(m) == "text", m
        assert db.get_task(_queue())["mode"] == "screenshot"
        assert shot.client.get("/api/integrations/computer/status").json()["mode"] == "screenshot"
        save_credentials("computer", {"enabled": True, "helper_model": "claude-sonnet-4-6"})
        assert db.get_task(_queue())["mode"] == "text"
        assert "1280×800" in runner.build_system_prompt("Tom", "tom", "screenshot")
        assert "1280×800" not in runner.build_system_prompt("Tom", "tom")

    def test_the_estimate_counts_a_screenshot_as_a_screenshot_not_as_base64(self):
        msgs = [{"role": "user", "content": [{"type": "tool_result", "tool_use_id": "x", "toolset_name": "computer", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "A" * 200_000}}]}]}]
        assert 3000 < len(json.dumps(runner._countable(msgs))) < 3200
        assert runner._countable([{"role": "user", "content": "hi"}]) == [{"role": "user", "content": "hi"}]


# ── the loop ─────────────────────────────────────────────────────────────────

class TestScreenshotLoop:
    def test_screenshot_then_a_free_click_then_the_report(self, shot, monkeypatch):
        tid = _queue()
        fa, t = _run(shot, monkeypatch, [[THINK, text("Looking."), SHOT], [CLICK_CART], [text("Done: the mug is in the cart.")]])
        assert t["status"] == "done" and t["result_text"] == "Done: the mug is in the cart." and t["mode"] == "screenshot"
        # the request: the toolset entry plus our tools, adaptive thinking, context editing, a cached system prompt
        req = fa.requests[0]
        assert req["tools"][0] == runner.TOOLSET and [x["name"] for x in req["tools"][1:]] == [d["name"] for d in runner.TOOL_DEFS]
        assert req["thinking"] == {"type": "adaptive"} and req["context_management"] == {"edits": runner.CONTEXT_EDITS}
        assert fa.headers[0]["anthropic-beta"] == runner.CONTEXT_BETA
        assert req["system"][0]["cache_control"] == {"type": "ephemeral"} and "1280×800" in req["system"][0]["text"]
        assert req["model"] == SHOT_MODEL and 0 < req["max_tokens"] <= runner.DEFAULT_MAX_TOKENS
        # the assistant turn went back verbatim, thinking block included; the screenshot result is an image echoing toolset_name
        second = fa.requests[1]["messages"]
        assert second[0] == {"role": "user", "content": "buy the blue mug"}
        assert second[1] == {"role": "assistant", "content": [THINK, text("Looking."), SHOT]}
        [r] = second[2]["content"]
        assert r["tool_use_id"] == SHOT["id"] and r["toolset_name"] == "computer" and r["is_error"] is False
        assert r["content"] == [{"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": fa_png()}}]
        # the click was described by pixel, classified free, and sent with expect and an action id
        assert ("POST", "/browser/element", {"x": 100, "y": 720, "lease": "lease-2", "epoch": "boot:2"}) in shot.calls
        [click] = [a for a in shot.actions if a["name"] == "left_click"]
        assert click["input"] == {"coordinate": [100, 720]} and len(click["action_id"]) == 26 and click["expect"] == EXPECT_CART
        assert fa.results(2) == [{"type": "tool_result", "tool_use_id": CLICK_CART["id"], "toolset_name": "computer",
                                  "content": "OK", "is_error": False}]
        # the step log: the screenshot file, the verdicts, and usage settled from the response (cache fields included)
        steps = db.list_steps(tid)
        assert [s["tool"] for s in steps] == ["screenshot", "left_click"]
        assert steps[0]["screenshot"] == f"shots/{tid}/1.png" and (db.DATA_DIR / steps[0]["screenshot"]).read_bytes() == PNG
        assert steps[1]["verdict"] == "free:3.legwork" and steps[1]["screenshot"] is None
        assert len(fa.count_requests) == 3 == len(fa.requests)  # a count_tokens reservation before every call
        assert fa.count_requests[0]["tools"][0] == runner.TOOLSET and fa.count_requests[0]["thinking"] == {"type": "adaptive"}
        assert t["cost_reserved_usd"] == 0 and t["input_tokens"] == 3000 and t["output_tokens"] == 150
        assert abs(t["cost_actual_usd"] - 3 * (1000 * 2 + 200 * 2 * 1.25 + 300 * 2 * 0.1 + 50 * 10) / 1e6) < 1e-9
        assert shot.submitted == [tid] and shot.lease is None
        # the card's step view fetches the screenshot through an authed route
        r = shot.client.get(f"/api/computer/tasks/{tid}/steps/1/screenshot")
        assert r.status_code == 200 and r.content == PNG and r.headers["content-type"] == "image/png"
        assert shot.client.get(f"/api/computer/tasks/{tid}/steps/2/screenshot").status_code == 404

    def test_a_pixel_click_on_buy_now_is_refused_at_press_time_and_recorded_as_a_gate(self, shot, monkeypatch):
        tid = _queue()
        fa, t = _run(shot, monkeypatch, [[SHOT], [text("Buying."), CLICK_ORDER], [text("never reached")]])
        assert t["status"] == "needs_approval" and t["finish_reason"] == "stopped before buy: Buy now"
        assert len(fa.requests) == 2 and t["result_text"] == "Buying."  # no model call after the gate
        assert [a["name"] for a in shot.actions] == ["screenshot", "screenshot"]  # the helper's, then the gate's — no click
        gate = db.get_gate(t["gate_id"])
        assert (gate["kind"], gate["rule"], gate["action"], gate["name"], gate["host"]) == ("buy", "1.buy", "left_click", "Buy now", "shop.example")
        assert json.loads(gate["total_json"])["amount"] == "45.00" and json.loads(gate["element_json"])["screen_box"] == BOX
        assert gate["screenshot"] == f"shots/{tid}/{gate['id']}.png" and (db.DATA_DIR / gate["screenshot"]).read_bytes() == PNG
        assert gates.unbindable_reason(gate) is None  # approving replays one left_click
        assert [s["verdict"] for s in db.list_steps(tid)] == [None, "gated:buy"]
        assert shot.submitted == [tid]

    def test_mouse_down_on_a_pointerdown_purchase_is_refused_and_a_double_click_never_gets_a_gate(self, shot, monkeypatch):
        shot.elements["e10"] = element("Buy now", is_submit=False, box=BOX)  # a JS button that orders on pointerdown
        _queue()
        turns = [[tool("double_click", {"coordinate": [400, 317]})], [tool("left_mouse_down", {"coordinate": [400, 317]})], [text("x")]]
        fa, t = _run(shot, monkeypatch, turns)
        assert t["status"] == "needs_approval"
        [dbl] = fa.results(1)
        assert dbl["is_error"] and "more than once" in dbl["content"] and dbl["toolset_name"] == "computer"
        assert db.query("SELECT COUNT(*) AS n FROM gates")[0]["n"] == 1  # the double click was refused, not gated
        gate = db.get_gate(t["gate_id"])
        assert gate["action"] == "left_mouse_down" and gate["kind"] == "buy" and gate["rule"] == "1.buy"
        assert "can't be re-sent" in gates.unbindable_reason(gate)  # a press, not a click: the owner does it themselves
        assert [a["name"] for a in shot.actions] == ["screenshot"]  # only the gate's screenshot reached the computer

    @pytest.mark.parametrize("member, inp, action, rule", [
        ("key", {"text": "Return"}, "key:Return", "7.composer"),
        ("key", {"text": "ctrl+Return"}, "key:ctrl+Return", "1.send"),
        ("type", {"text": "hi there\n"}, "type", "7.composer"),
        ("hold_key", {"text": "Return", "duration": 1}, "hold_key:Return", None),  # multi: refused, no gate
    ])
    def test_keys_and_typing_are_checked_on_the_focused_element(self, shot, monkeypatch, member, inp, action, rule):
        shot.focused = {"found": True, "ref": "e20", "tag": "textarea", "role": "textbox", "name": "Message", "type": "", "form": None,
                        "frame_url": "https://mail.example/compose", "page": {"host": "mail.example", "path": "/compose", "title": "Compose"},
                        "context_kind": "composer", "context_fp": "cfp", "total": None, "screen_box": None}
        _queue()
        run = _live_run()
        results = asyncio.run(run.batch([tool("type", {"text": "hello"}, "a"), tool("key", {"text": "Tab"}, "b"), tool(member, inp, "c"),
                                         tool("screenshot", tid="d")]))
        assert [r["content"] for r in results[:2]] == ["OK", "OK"] and all(r["toolset_name"] == "computer" for r in results)
        assert [a["name"] for a in shot.actions[:2]] == ["type", "key"] and all("expect" not in a for a in shot.actions[:2])  # free, never checked
        assert ("POST", "/browser/element", {"focused": True, "lease": "lease-2", "epoch": "boot:2"}) in shot.calls
        assert results[3] == {"type": "tool_result", "tool_use_id": "d", "toolset_name": "computer", "is_error": True, "content": runner.SKIPPED}
        assert len(shot.actions) == 3 if rule else 2  # the gate's screenshot; nothing else after the stop
        if rule:
            assert results[2]["content"].startswith("needs approval (send)") and run.finished
            gate = db.get_gate(run.gate_id)
            assert (gate["kind"], gate["action"], gate["rule"], gate["host"]) == ("send", action, rule, "mail.example")
            assert db.get_task(run.id)["status"] == "needs_approval"
        else:
            assert results[2]["is_error"] and "more than once" in results[2]["content"] and not run.finished
            _end(run)

    def test_a_declared_free_click_is_gated_and_a_changed_page_refuses_the_click(self, shot, monkeypatch):
        """The helper's request_approval declaration gates the next pixel click whatever the classifier says;
        and when the page changes between our read and the click, the computer's 409 comes back as an error."""
        _queue()
        run = _live_run()
        shot.element_changed = True  # the computer's expect check fails on the (free) cart click
        [r] = asyncio.run(run.batch([CLICK_CART]))
        assert r["is_error"] and "take a screenshot" in r["content"] and shot.actions[-1]["name"] == "left_click"
        shot.element_changed = False
        results = asyncio.run(run.batch([custom("request_approval", {"kind": "post", "reason": "the cart button posts a review"}, "d"), CLICK_CART]))
        assert "Declared" in results[0]["content"] and results[1]["content"].startswith("needs approval (post)")
        gate = db.get_gate(run.gate_id)
        assert (gate["kind"], gate["rule"], gate["action"], gate["reason"]) == ("post", "declared", "left_click", "the cart button posts a review")
        assert [a["name"] for a in shot.actions] == ["left_click", "screenshot"] and run.finished

    def test_a_click_the_page_cannot_identify_is_a_gate_fail_closed(self, shot, monkeypatch):
        """A click with no coordinate lands where the cursor is; nothing of the page is there (a desktop app, say)."""
        _queue()
        run = _live_run()
        [r] = asyncio.run(run.batch([tool("left_click", {}, "a")]))
        assert r["content"].startswith("needs approval (submit)") and run.finished
        assert [a["name"] for a in shot.actions] == ["cursor_position", "screenshot"]
        assert ("POST", "/browser/element", {"x": 640, "y": 400, "lease": "lease-2", "epoch": "boot:2"}) in shot.calls
        gate = db.get_gate(run.gate_id)
        assert gate["rule"] == "unidentified" and gate["action"] == "left_click"
        assert "no page element" in gates.unbindable_reason(gate)  # approving = take over and press it yourself

    def test_a_batch_stops_at_the_first_failure_and_the_next_request_is_a_valid_conversation(self, shot, monkeypatch):
        tid = _queue()
        turns = [[SHOT, custom("files", {"action": "read", "path": "missing.txt"}, "f1"), CLICK_CART, tool("zoom", {"region": [0, 0, 100, 100]}, "z1")],
                 [text("Gave up.")]]
        fa, t = _run(shot, monkeypatch, turns)
        assert t["status"] == "done"
        results = fa.results(1)
        uses = [b["id"] for b in fa.requests[1]["messages"][1]["content"] if b["type"] == "tool_use"]
        assert uses == [r["tool_use_id"] for r in results] == ["tu-screenshot", "f1", "tu-left_click", "z1"]
        assert results[0]["toolset_name"] == "computer" and results[0]["content"][0]["type"] == "image" and not results[0]["is_error"]
        assert "toolset_name" not in results[1] and results[1]["is_error"] and "not found" in results[1]["content"]
        assert results[2] == {"type": "tool_result", "tool_use_id": "tu-left_click", "toolset_name": "computer", "is_error": True, "content": runner.SKIPPED}
        assert results[3] == {"type": "tool_result", "tool_use_id": "z1", "toolset_name": "computer", "is_error": True, "content": runner.SKIPPED}
        assert [a["name"] for a in shot.actions] == ["screenshot"]  # nothing ran past the failure
        assert [s["tool"] for s in db.list_steps(tid)] == ["screenshot", "files"]

    def test_screenshots_are_never_pruned_client_side(self, shot, monkeypatch):
        tid = _queue()
        fa, t = _run(shot, monkeypatch, [[SHOT], [SHOT], [SHOT], [SHOT], [text("done")]])
        assert t["status"] == "done"
        last = fa.requests[-1]
        images = [c for m in last["messages"] if isinstance(m["content"], list) for b in m["content"]
                  if b["type"] == "tool_result" for c in b["content"] if c["type"] == "image"]
        assert len(images) == 4 and len(last["messages"]) == 9  # opening + 4 × (assistant, user): append-only
        assert all(r["context_management"] == {"edits": runner.CONTEXT_EDITS} for r in fa.requests)  # the API clears, not us
        assert sorted(p.name for p in (db.DATA_DIR / "shots" / tid).iterdir()) == ["1.png", "2.png", "3.png", "4.png"]

    def test_reservations_come_from_count_tokens_and_stop_a_call_that_breaks_the_budget(self, shot, monkeypatch):
        _queue()
        fa, t = _run(shot, monkeypatch, [[text("x")]], count=10_000_000)  # $25 of input at Sonnet's rate
        assert t["status"] == "failed" and t["finish_reason"].startswith("budget reached")
        assert len(fa.count_requests) == 1 and fa.requests == []

    def test_model_errors_and_refusals_end_the_task(self, shot, monkeypatch):
        _queue()
        fa, t = _run(shot, monkeypatch, [[text("x")]], status=500)
        assert t["status"] == "failed" and t["finish_reason"].startswith("model error")
        assert t["cost_reserved_usd"] > 0  # usage unknown: the reservation stays charged
        _queue()
        fa, t = _run(shot, monkeypatch, ["refusal"])
        assert (t["status"], t["finish_reason"]) == ("failed", "model refused the task") and t["cost_reserved_usd"] == 0
        _queue()
        fa, t = _run(shot, monkeypatch, [[SHOT], "max_tokens"])  # a reply cut off with no tool calls is not a finished task
        assert (t["status"], t["finish_reason"]) == ("failed", runner.CUT_OFF) and len(fa.requests) == 2
        assert t["result_text"].startswith("I was about to") and "[Stopped: the model's reply was cut off" in t["result_text"]

    def test_screenshots_are_deleted_14_days_after_the_task_finishes(self, shot, monkeypatch):
        tid = _queue()
        _run(shot, monkeypatch, [[SHOT], [text("done")]])
        folder = db.DATA_DIR / "shots" / tid
        orphan = db.DATA_DIR / "shots" / "no-such-task"
        orphan.mkdir(parents=True)
        (orphan / "1.png").write_bytes(PNG)
        running = _queue()
        db.claim_next("w2")
        (db.DATA_DIR / "shots" / running).mkdir()
        assert (folder / "1.png").is_file()
        assert runner.prune_shots() == 1 and folder.is_dir() and not orphan.exists()  # only the folder with no task
        db.execute("UPDATE tasks SET finished_at = datetime('now', '-13 days') WHERE id = ?", (tid,))
        assert runner.prune_shots() == 0
        db.execute("UPDATE tasks SET finished_at = datetime('now', '-15 days') WHERE id = ?", (tid,))
        completion.sweep()  # the 60 s sweep prunes
        assert not folder.exists() and (db.DATA_DIR / "shots" / running).is_dir()


# ── approved pixel gates ─────────────────────────────────────────────────────

class TestApprovedPixelGate:
    def _gate(self, shot, monkeypatch):
        monkeypatch.setattr(runner, "kick", lambda: False)
        _queue()
        _, t = _run(shot, monkeypatch, [[SHOT], [CLICK_ORDER], [text("x")]])
        gate = db.get_gate(t["gate_id"])
        r = approvals.decide(gate["id"], "approve", "card", "owner")
        assert r["ok"] and not r["takeover"]
        f = db.get_task(r["task_id"])
        assert f["mode"] == "screenshot" and f["approved_gate_id"] == gate["id"] and f["status"] == "queued"
        shot.actions.clear()
        return gate

    def test_an_approved_pixel_gate_replays_as_one_left_click_with_the_stored_expect(self, shot, monkeypatch):
        gate = self._gate(shot, monkeypatch)
        fa, done = _run(shot, monkeypatch, [[text("Order placed, #123.")]])
        assert done["status"] == "done" and done["result_text"] == "Order placed, #123."
        [click] = [a for a in shot.actions if a["name"] == "left_click"]
        assert click["input"] == {"coordinate": [400, 317]}  # the located control's centre
        assert click["expect"] == {"action": "left_click", "host": "shop.example", "path": "/checkout", "frame_url": "https://shop.example/checkout",
                                   "role": "button", "name": "Buy now", "form_action": "https://shop.example/order", "context_fp": "abc",
                                   "total": {"amount": "45.00", "currency": "USD"}}
        g = db.get_gate(gate["id"])
        assert g["status"] == "done" and g["action_id"] == click["action_id"]
        assert "performed it ONCE (one left_click)" in fa.requests[0]["messages"][0]["content"]
        [step, *_] = db.list_steps(done["id"])
        assert step["tool"] == "approved_action" and step["verdict"] == "approved:buy" and json.loads(step["args_excerpt"])["coordinate"] == [400, 317]
        assert shot.performed == []  # nothing went through /browser/act

    def test_a_located_control_without_a_screen_position_opens_a_new_gate(self, shot, monkeypatch):
        gate = self._gate(shot, monkeypatch)
        shot.elements["e10"] = element("Buy now")  # same facts, but no screen_box to aim at
        _, f = _run(shot, monkeypatch, [[text("x")]])
        assert f["status"] == "needs_approval" and [a["name"] for a in shot.actions] == ["screenshot"]  # the new gate's shot; no click
        assert db.get_gate(gate["id"])["status"] == "cancelled"
        new = db.get_gate(f["gate_id"])
        assert new["rule"] == "rebind" and new["note"].startswith("the control's position on the screen couldn't be read")

    def test_a_changed_total_under_a_pixel_gate_opens_a_new_gate_and_clicks_nothing(self, shot, monkeypatch):
        gate = self._gate(shot, monkeypatch)
        shot.elements["e10"] = element("Buy now", box=BOX, total="50.00")
        _, f = _run(shot, monkeypatch, [[text("x")]])
        assert f["status"] == "needs_approval" and [a["name"] for a in shot.actions] == ["screenshot"]
        assert db.get_gate(f["gate_id"])["note"].startswith("total changed 45.00 USD → 50.00 USD")
        assert db.get_gate(gate["id"])["status"] == "cancelled"


def fa_png() -> str:
    import base64
    return base64.b64encode(PNG).decode()
