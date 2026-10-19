"""The agent drives its computer directly (direct.py): sessions as driver='agent' task rows, gates in a
direct turn and their dispatch-only follow-up, the busy screen, release at turn end / when idle / on
hand-off, owner-only groups, the per-turn ceilings, refs pinned to the session's epoch, and approval
cards and takeover links that never go to a group. Same fakes as test_computer_tasks: no network."""

import asyncio
import base64
import json
import time

import pytest

from core.agents.background_runner import BackgroundResult
from core.agents.deferred_tools import build_provider_tools, build_tool_catalog
from core.agents.scheduled_actions import processor
from core.agents.tool_registry import ToolRegistry
from integrations.computer import approvals, client as client_mod, completion, db, direct, runner, tools
from integrations.registry import save_credentials

from tests.test_computer_approvals import _stop_at_gate, ap  # noqa: F401 (ap is a fixture)
from tests.test_computer_tasks import FINAL, MODEL, PNG, FakeProvider, _ctx, _queue, _run, element, fake  # noqa: F401


@pytest.fixture(autouse=True)
def fresh_turns(monkeypatch):
    monkeypatch.setattr(direct, "BUSY_POLL_S", 0.01)
    direct._turns.clear()
    yield
    direct._turns.clear()


@pytest.fixture
def dfake(fake, monkeypatch):  # noqa: F811 (fake is the imported fixture)
    monkeypatch.setattr(direct, "get_client", client_mod.get_client)  # the fake's, as patched by `fake`
    return fake


def _dctx(turn="turn-1", **kw):
    return _ctx(turn_id=turn, **kw)


async def call(ctx, tool="computer_browser", **args):
    return await tools.TOOL_EXECUTORS[tool](_ctx=ctx, **args)


def sessions() -> list[dict]:
    return [dict(r) for r in db.query("SELECT * FROM tasks WHERE driver = 'agent' ORDER BY rowid")]


def calls_after(fc, n) -> list[str]:
    return [p for _, p, _ in fc.calls[n:]]


def bump(fc):
    fc.epoch_n += 1  # control ended / the screen changed hands on the computer


class TestSession:
    def test_a_direct_snapshot_is_a_running_agent_row_with_a_step_and_releases_at_turn_end(self, dfake):
        reg = ToolRegistry(context_dir="/tmp/ctx", agent_slug="tom", integration_executors=tools.TOOL_EXECUTORS,
                           integration_tool_flags={"computer_browser": {"context_aware": True, "extends_turn": True}})
        reg._turn_origin, reg._turn_route = "user", {"channel": "web"}
        turn_id = reg.turn_id

        async def go():
            out = await reg.execute_tool("computer_browser", {"action": "snapshot"}, "integration")
            row = sessions()[0]
            assert row["status"] == "running" and row["worker_id"].startswith("direct:") and row["worker_id"].endswith(turn_id)
            assert dfake.lease is not None
            await reg.aclose()
            return out
        out = asyncio.run(go())
        assert "Place order" in out["snapshot"]
        row = sessions()[0]
        assert (row["driver"], row["origin"], row["status"], row["finish_reason"]) == ("agent", "user", "done", "direct session ended")
        assert [s["tool"] for s in db.list_steps(row["id"])] == ["browser"]
        assert dfake.lease is None and dfake.submitted == []  # released, and no report turn: the agent was there
        assert reg.turn_id != turn_id and direct._turns == {}

    def test_one_session_per_turn_across_calls_and_tools(self, dfake):
        ctx = _dctx()

        async def go():
            await call(ctx, action="snapshot")
            sh = await call(ctx, "computer_shell", command="ls")
            fl = await call(ctx, "computer_files", action="list", path=".")
            await direct.close_turn("turn-1")
            return sh, fl
        sh, fl = asyncio.run(go())
        assert sh["stdout"] == "ran: ls" and "entries" in fl
        assert len(sessions()) == 1 and [s["tool"] for s in db.list_steps(sessions()[0]["id"])] == ["browser", "shell", "files"]
        assert [p for _, p, _ in dfake.calls].count("/desktop/activate") == 1

    def test_a_busy_screen_hands_off_and_finishes_the_row(self, dfake, monkeypatch):
        monkeypatch.setattr(direct, "BUSY_WAIT_S", 0.05)
        dfake.lease = ("lease-x", "dana", "other-task")
        out = asyncio.run(call(_dctx(), action="snapshot"))
        assert "in use by another task" in out["error"] and "computer_task" in out["error"]
        row = sessions()[0]
        assert (row["status"], row["finish_reason"]) == ("failed", "screen busy") and dfake.submitted == []
        assert "/browser/snapshot" not in [p for _, p, _ in dfake.calls]

    def test_a_turn_cancelled_while_waiting_for_the_screen_leaves_no_running_row(self, dfake):
        dfake.lease = ("lease-x", "dana", "other-task")

        async def go():
            t = asyncio.create_task(call(_dctx(), action="snapshot"))
            await asyncio.sleep(0.05)
            t.cancel()
            with pytest.raises(asyncio.CancelledError):
                await t
        asyncio.run(go())
        assert sessions()[0]["status"] == "cancelled" and dfake.submitted == []

    def test_an_idle_session_releases_itself_and_the_next_call_opens_a_new_one(self, dfake, monkeypatch):
        monkeypatch.setattr(direct, "IDLE_S", 0.05)
        ctx = _dctx()

        async def go():
            await call(ctx, action="snapshot")
            s = direct._turns["turn-1"].session
            s.inflight = True  # a long shell command: never idle while in flight
            await asyncio.sleep(0.15)
            assert not s.closed and dfake.lease is not None
            s.inflight = False
            await asyncio.sleep(0.15)
            assert s.closed and dfake.lease is None
            await call(ctx, action="snapshot")
            await direct.close_turn("turn-1")
        asyncio.run(go())
        first, second = sessions()
        assert (first["status"], first["finish_reason"]) == ("done", "idle for 0.05 s")
        assert second["status"] == "done"

    def test_computer_task_frees_the_screen_first(self, dfake):
        ctx = _dctx()

        async def go():
            await call(ctx, action="snapshot")
            assert dfake.lease is not None
            out = await tools.computer_task("compare 40 suppliers' prices", _ctx=ctx)
            held = dfake.lease
            await direct.close_turn("turn-1")
            return out, held
        out, held = asyncio.run(go())
        assert out["status"] == "queued" and held is None
        assert (sessions()[0]["status"], sessions()[0]["finish_reason"]) == ("done", "handed to the helper")
        assert db.get_task(out["task_id"])["driver"] == "helper"

    def test_a_lost_lease_ends_the_session_and_the_next_call_starts_fresh(self, dfake):
        dfake.elements["e5"] = element("Add to cart", "e5", is_submit=False)
        ctx = _dctx()

        async def go():
            await call(ctx, action="snapshot")
            dfake.lease = None  # the computer no longer knows this lease
            lost = await call(ctx, action="snapshot")
            stale = await call(ctx, action="click", ref="e5")  # a new session: the old snapshot's refs are gone
            await direct.close_turn("turn-1")
            return lost, stale
        lost, stale = asyncio.run(go())
        assert "Lost the screen" in lost["error"] and stale["code"] == "stale_ref"
        first, second = sessions()
        assert (first["status"], first["finish_reason"]) == ("failed", "lost the screen") and second["status"] == "done"
        assert dfake.performed == []

    def test_the_turn_ceiling_counts_every_direct_call(self, dfake, monkeypatch):
        monkeypatch.setattr(direct, "MAX_ACTIONS", 2)
        ctx = _dctx()

        async def go():
            outs = [await call(ctx, action="snapshot") for _ in range(3)]
            await direct.close_turn("turn-1")
            return outs
        outs = asyncio.run(go())
        assert "error" not in outs[1] and outs[2]["error"] == "This turn has used 2 computer actions; hand the rest to computer_task."

    def test_cancelled_on_the_card_stops_the_turn(self, dfake):
        ctx = _dctx()

        async def go():
            await call(ctx, action="snapshot")
            db.finish_task(sessions()[0]["id"], "cancelled", "cancelled by user", notify=False)
            stopped = await call(ctx, action="snapshot")
            again = await call(ctx, action="snapshot")
            await direct.close_turn("turn-1")
            return stopped, again
        stopped, again = asyncio.run(go())
        assert "session ended (cancelled" in stopped["error"] and again["error"] == stopped["error"]
        assert len(sessions()) == 1 and dfake.lease is None

    def test_turning_the_computer_off_for_the_agent_ends_its_open_session(self, dfake):
        ctx = _dctx()

        async def go():
            await call(ctx, action="snapshot")
            save_credentials("computer", {"enabled": True, "helper_model": MODEL, "disabled_agents": ["tom"]})
            off = await call(ctx, action="snapshot")
            await direct.close_turn("turn-1")
            return off
        off = asyncio.run(go())
        row = sessions()[0]
        assert (row["status"], row["finish_reason"]) == ("cancelled", "disabled") and "(cancelled: disabled)" in off["error"]
        assert dfake.lease is None and [p for _, p, _ in dfake.calls].count("/browser/snapshot") == 1


class TestGates:
    def test_place_order_opens_a_gate_nothing_is_clicked_and_the_turn_stops(self, dfake):
        dfake.elements["e10"] = element("Place order")
        ctx = _dctx()

        async def go():
            await call(ctx, action="snapshot")
            gated = await call(ctx, action="click", ref="e10")
            after = await call(ctx, action="snapshot")
            task = await tools.computer_task("buy it", _ctx=ctx)
            await direct.close_turn("turn-1")
            return gated, after, task
        gated, after, task = asyncio.run(go())
        assert gated["stopped"] == ("Needs your approval (buy: Place order). I've sent the card. When it's approved, "
                                    "the click is made and you'll get the outcome as a new message.")
        assert dfake.acts() == []  # the click never reached the computer
        assert f"approval of gate {gated['gate_id']}" in after["error"] and after["error"] == task["error"]
        row = sessions()[0]
        assert (row["status"], row["finish_reason"], row["gate_id"]) == ("needs_approval", "stopped before buy: Place order", gated["gate_id"])
        assert [s["verdict"] for s in db.list_steps(row["id"])] == [None, "gated:buy"]
        assert dfake.submitted == [] and dfake.lease is None  # no report turn; the screen is free
        assert len(db.query("SELECT 1 FROM tasks")) == 1  # computer_task was refused too

    def test_approving_makes_the_one_click_and_gives_the_agent_one_turn(self, ap, monkeypatch):  # noqa: F811
        monkeypatch.setattr(direct, "get_client", client_mod.get_client)
        ap.fake.elements["e10"] = element("Place order")
        ctx = _dctx(conversation_id="conv-9", action_id="sa-3")

        async def go():
            await call(ctx, action="snapshot")
            await call(ctx, action="click", ref="e10")
            await direct.close_turn("turn-1")
        asyncio.run(go())
        session = sessions()[0]
        gate = db.get_gate(session["gate_id"])
        assert ap.sent[-1]["chat_id"] == "555"  # the approval card went to the owner on Telegram

        assert approvals.decide(gate["id"], "approve", "card", "user")["ok"]
        f = dict(db.query("SELECT * FROM tasks WHERE approved_gate_id = ?", (gate["id"],))[0])
        assert (f["driver"], f["origin"], f["conversation_id"], f["action_id"], f["parent_task_id"], f["root_task_id"]) == (
            "agent", "user", "conv-9", "sa-3", session["id"], session["id"])
        assert json.loads(f["route"]) == {"channel": "web"}

        # Helper caps don't apply to direct work, and no helper model runs: only the approved click.
        db.execute("UPDATE tasks SET steps = ? WHERE id = ?", (db.MAX_STEPS, session["id"]))
        monkeypatch.setattr(runner, "get_ai_provider", lambda **kw: pytest.fail("no helper model for a direct follow-up"))
        t = db.claim_next("w1")
        assert asyncio.run(runner.run_task(t, "w1")) == "done"
        f = db.get_task(f["id"])
        assert (f["status"], f["finish_reason"]) == ("done", "approved action performed")
        assert f["result_text"].startswith("## Approved action performed") and "untrusted_tool_result" in f["result_text"]
        assert len(ap.fake.performed) == 1 and ap.fake.performed[0]["ref"] == "e10" and ap.fake.performed[0]["expect"]
        assert db.get_gate(gate["id"])["status"] == "done"
        assert ap.fake.submitted == [f["id"]]

        turns: list = []
        monkeypatch.setattr(processor, "run_agent_background_turn",
                            lambda *a, **kw: turns.append(a) or (BackgroundResult(text="Ordered."), None))
        monkeypatch.setattr(processor, "_resolve_agent", lambda slug: {"slug": slug, "agent_name": "Tom"})
        monkeypatch.setattr(processor, "deliver_background_result", lambda *a, **kw: None)
        completion.complete_task(f["id"])
        completion.complete_task(f["id"])
        assert len(turns) == 1 and turns[0][2] == completion._INSTRUCTIONS["agent"]
        assert "Approved action performed" in turns[0][3]


    def test_a_scheduled_actions_preapproval_crosses_its_gate_in_a_direct_session(self, dfake, monkeypatch):
        from tests.test_computer_preapprovals import SUBMIT, _allow, _cron
        aid = _cron()
        _allow(aid)
        dfake.elements["e10"] = SUBMIT
        dfake.url = "https://time.example/week"
        asked: list = []
        monkeypatch.setattr(approvals, "request", lambda gid: asked.append(gid) or "card")
        ctx = _dctx(origin="background", action_id=aid)

        async def go():
            await call(ctx, action="snapshot")
            out = await call(ctx, action="click", ref="e10")
            await direct.close_turn("turn-1")
            return out
        out = asyncio.run(go())
        assert out["preapproved"].startswith("Chatty performed this submit") and "Do not repeat it" in out["preapproved"]
        assert asked == [] and len(dfake.performed) == 1
        assert (sessions()[0]["status"], sessions()[0]["action_id"]) == ("done", aid)


class TestGroups:
    def test_only_the_owner_uses_the_computer_from_a_group(self, dfake):
        route = {"channel": "telegram", "chat_id": "-100123", "group": True}
        member = _dctx(origin="group", route=route)
        helper_task = _queue("the owner's own task")  # a non-owner can't read or cancel it either

        async def go():
            outs = [await call(member, action="snapshot"), await call(member, "computer_shell", command="id"),
                    await call(member, "computer_screen", action="screenshot"),
                    await tools.computer_task("x", _ctx=member), await tools.computer_file_get("a.txt", _ctx=member),
                    await call(member, "computer_takeover", reason="sign in"),
                    tools.computer_task_get(helper_task, _ctx=member), tools.computer_task_list(_ctx=member),
                    tools.computer_task_cancel(helper_task, _ctx=member), tools.computer_info(_ctx=member)]
            owner = await call(_dctx("turn-2", origin="group", route=route, group_owner=True), action="snapshot")
            await direct.close_turn("turn-2")
            return outs, owner
        outs, owner = asyncio.run(go())
        assert all(o["error"] == "Only the owner can use the computer from a group." for o in outs)
        assert "snapshot" in owner
        row = sessions()[0]
        assert len(db.query("SELECT 1 FROM tasks")) == 2 and row["origin"] == "background" and json.loads(row["route"]) == route
        assert db.get_task(helper_task)["status"] == "queued"

    def test_a_delegated_group_task_its_follow_up_and_takeover_reach_the_owner_privately(self, ap, monkeypatch):  # noqa: F811
        route = {"channel": "telegram", "chat_id": "-100123", "group": True}
        t, gate = _stop_at_gate(ap, monkeypatch, origin="group", group_owner=True, route=route)
        assert [m["chat_id"] for m in ap.sent] == ["555"] and [p["chat_id"] for p in ap.photos] == ["555"]

        # Approved, but the total changed: the follow-up opens a new gate, asked privately too.
        assert approvals.decide(gate["id"], "approve", "card", "user")["ok"]
        ap.fake.elements["e10"] = element("Place order", total="99.00")
        _, f = _run(ap.fake, FakeProvider([FINAL]), monkeypatch)
        assert f["status"] == "needs_approval" and json.loads(f["route"]) == route
        assert [m["chat_id"] for m in ap.sent if m["markup"]] == ["555", "555"]

        # A takeover link, for the new route and for one saved before routes said "group".
        monkeypatch.setattr(runner, "takeover_url", lambda task_id, slug: "https://chatty.example/computer")
        for r in (route, {"channel": "telegram", "chat_id": -100123}):
            runner.notify_takeover({**f, "route": json.dumps(r)}, "sign in to shop.example")
        assert all(m["chat_id"] == "555" for m in ap.sent) and "needs you on the computer" in ap.sent[-1]["text"]


class TestEpochs:
    """A direct session never resends: a refused stale_epoch ends the operation, and refs need the
    latest snapshot of this session under the epoch the session holds now."""

    def test_the_epoch_advancing_before_the_act_refuses_it_once(self, dfake):
        dfake.elements["e5"] = element("Add to cart", "e5", is_submit=False)
        ctx = _dctx()

        async def go():
            await call(ctx, action="snapshot")
            dfake.before_call = lambda path, body: path == "/browser/act" and bump(dfake)
            n = len(dfake.calls)
            out = await call(ctx, action="click", ref="e5")
            dfake.before_call = None
            stale = await call(ctx, action="click", ref="e5")
            await direct.close_turn("turn-1")
            return out, calls_after(dfake, n), stale
        out, paths, stale = asyncio.run(go())
        assert out == runner.EPOCH_CHANGED
        assert paths.count("/browser/act") == 1 and dfake.performed == []  # refused, never sent again
        assert stale["code"] == "stale_ref"  # the snapshot from before the change is unusable
        assert db.list_steps(sessions()[0]["id"])[-1]["result_excerpt"].startswith('{"error": "not performed: the screen changed hands')

    def test_an_epoch_renew_saw_invalidates_the_snapshot_taken_before_it(self, dfake, monkeypatch):
        monkeypatch.setattr(runner, "RENEW_EVERY_S", 0.01)
        dfake.elements["e5"] = element("Add to cart", "e5", is_submit=False)
        ctx = _dctx()

        async def go():
            await call(ctx, action="snapshot")
            bump(dfake)  # control ended right after the snapshot was read
            await asyncio.sleep(0.05)  # renew_loop sees the new epoch, keeps it for the next call
            run = direct._turns["turn-1"].session.run
            assert run.latest_epoch == dfake.epoch and run.epoch != dfake.epoch
            n = len(dfake.calls)
            stale = await call(ctx, action="click", ref="e5")
            sent = [p for p in calls_after(dfake, n) if not p.startswith("/desktop/lease")]
            await call(ctx, action="snapshot")
            ok = await call(ctx, action="click", ref="e5")
            await direct.close_turn("turn-1")
            return stale, sent, ok
        stale, sent, ok = asyncio.run(go())
        assert stale["code"] == "stale_ref" and sent == []
        assert "error" not in ok and len(dfake.performed) == 1

    def test_a_snapshot_refused_for_a_new_epoch_leaves_no_usable_refs(self, dfake):
        dfake.elements["e5"] = element("Add to cart", "e5", is_submit=False)
        ctx = _dctx()

        async def go():
            await call(ctx, action="snapshot")
            dfake.before_call = lambda path, body: path == "/browser/snapshot" and bump(dfake)
            refused = await call(ctx, action="snapshot")
            dfake.before_call = None
            stale = await call(ctx, action="click", ref="e5")
            await direct.close_turn("turn-1")
            return refused, stale
        refused, stale = asyncio.run(go())
        assert refused == runner.EPOCH_CHANGED and stale["code"] == "stale_ref" and dfake.performed == []

    def test_pixel_action_stops_at_a_refused_preliminary_snapshot(self, dfake):
        tid = db.insert_task(agent_slug="tom", origin="user", task="direct session", helper_provider="", helper_model="",
                             driver="agent", worker_id="direct:1:t")
        run = runner._Run(db.get_task(tid), "direct:1:t", client_mod.get_client())
        run.retry_epoch = False

        async def go():
            await run.activate()
            dfake.before_call = lambda path, body: path == "/browser/snapshot" and bump(dfake)
            n = len(dfake.calls)
            out = await run.pixel("left_click", {"coordinate": [100, 100]})
            await run.release()
            return out, calls_after(dfake, n)
        out, paths = asyncio.run(go())
        assert out["is_error"] and "screen changed hands" in out["content"]
        assert "/browser/element" not in paths and "/actions" not in paths and run.epoch == dfake.epoch


class TestPerformedNeverFailed:
    def test_helper_click_then_a_failed_snapshot_still_says_performed(self, dfake, monkeypatch):
        dfake.elements["e5"] = element("Add to cart", "e5", is_submit=False)
        dfake.on_act = lambda body: setattr(dfake, "snapshot_error", "browser_failed")
        tid = _queue()
        prov = FakeProvider([{"tool_calls": [("browser", {"action": "click", "ref": "e5"})]}, FINAL])
        _, t = _run(dfake, prov, monkeypatch)
        assert t["status"] == "done" and len(dfake.performed) == 1
        seen = json.dumps(prov.seen[-1][-1])  # the tool result the helper got back
        assert '\\"performed\\": true' in seen and "snapshot_error" in seen and "take a fresh snapshot" in seen
        step = db.list_steps(tid)[0]
        assert '"performed": true' in step["result_excerpt"] and '"error"' not in step["result_excerpt"]

    def test_direct_click_then_a_failed_snapshot_keeps_the_result_and_drops_the_refs(self, dfake):
        dfake.elements["e5"] = element("Add to cart", "e5", is_submit=False)
        ctx = _dctx()

        async def go():
            await call(ctx, action="snapshot")
            dfake.on_act = lambda body: setattr(dfake, "snapshot_error", "browser_failed")
            out = await call(ctx, action="click", ref="e5")
            dfake.snapshot_error = None
            again = await call(ctx, action="click", ref="e5")
            await direct.close_turn("turn-1")
            return out, again
        out, again = asyncio.run(go())
        assert out["performed"] is True and out["snapshot_error"] == "browser failed" and "url" in out
        assert again["code"] == "stale_ref" and len(dfake.performed) == 1


class TestDefinitions:
    def test_direct_tools_and_computer_task_are_never_deferred_and_flags_stay_server_side(self, dfake):
        defs = tools.computer_tool_defs()
        filler = [{"name": f"odoo_t{i}", "description": "x", "input_schema": {"type": "object"}, "kind": "integration",
                   "integration": "odoo"} for i in range(120)]
        active, deferred, names, _ = build_tool_catalog(filler + defs)
        loaded = {d["name"] for d in active}
        assert {"computer_browser", "computer_shell", "computer_files", "computer_screen", "computer_task"} <= loaded
        assert "computer_task_get" in names  # the rest still waits behind find_tools
        assert all(set(t) <= {"name", "description", "input_schema"} for t in build_provider_tools(defs))

    def test_schemas_are_the_helpers_and_the_hand_off_names_the_helper_model(self, dfake):
        defs = {d["name"]: d for d in tools.computer_tool_defs()}
        helper = {d["name"]: d for d in runner.TOOL_DEFS}
        for name, h in (("computer_browser", "browser"), ("computer_shell", "shell"), ("computer_files", "files")):
            assert defs[name]["input_schema"] == helper[h]["input_schema"]
            assert defs[name]["extends_turn"] and defs[name]["always_loaded"] and MODEL in defs[name]["description"]

    def test_helper_model_change_shows_in_the_descriptions(self, dfake):
        save_credentials("computer", {"enabled": True, "helper_model": "claude-opus-4-8"})
        assert "claude-opus-4-8" in next(d for d in tools.computer_tool_defs() if d["name"] == "computer_task")["description"]


BUY_BOX = {"x": 300, "y": 287, "w": 200, "h": 60}   # mark 1; its point is (400, 317)
CART_BOX = {"x": 40, "y": 700, "w": 120, "h": 40}   # mark 2; its point is (100, 720)


@pytest.fixture
def scr(dfake):
    dfake.elements["e10"] = element("Buy now", box=dict(BUY_BOX))
    dfake.elements["e5"] = element("Add to cart", "e5", is_submit=False, box=dict(CART_BOX))
    return dfake


def screen(ctx, **args):
    return call(ctx, "computer_screen", **args)


def presses(fc, name="left_click") -> list[dict]:
    return [a for a in fc.actions if a["name"] == name]


class TestScreen:
    """computer_screen: marked screenshots are observations; a mark is pressed only from the latest one of
    this session and epoch, re-checked against the control under its pixel before it is classified and
    by the computer (expect.box) at the press; every action comes back with a fresh screenshot."""

    def test_a_screenshot_is_an_observation_with_numbered_marks_the_image_and_a_step(self, scr):
        async def go():
            out = await screen(_dctx(), action="screenshot")
            await direct.close_turn("turn-1")
            return out
        out = asyncio.run(go())
        assert out["observation"] == "o1" and out["marks"] == ["1 button: Buy now", "2 button: Add to cart"]
        assert out["images"] == [{"media_type": "image/png", "data": base64.b64encode(PNG).decode()}]
        [step] = db.list_steps(sessions()[0]["id"])
        assert step["tool"] == "screenshot" and (db.DATA_DIR / step["screenshot"]).read_bytes() == PNG

    def test_no_marks_when_another_window_is_in_front(self, scr):
        scr.window_in_front = True
        out = asyncio.run(screen(_dctx(), action="screenshot"))
        asyncio.run(direct.close_turn("turn-1"))
        assert out["marks"] == direct.NO_MARKS and out["images"]

    def test_a_marked_click_presses_the_marks_point_with_its_box_and_returns_a_new_observation(self, scr):
        ctx = _dctx()

        async def go():
            first = await screen(ctx, action="screenshot")
            out = await screen(ctx, action="click", observation=first["observation"], mark=2)
            again = await screen(ctx, action="click", observation=first["observation"], mark=2)
            await direct.close_turn("turn-1")
            return out, again
        out, again = asyncio.run(go())
        [click] = presses(scr)
        assert click["input"] == {"coordinate": [100, 720]}
        assert click["expect"]["box"] == CART_BOX and click["expect"]["name"] == "Add to cart"
        assert out["performed"] is True and out["observation"] == "o2" and out["images"]
        assert again["code"] == "stale_mark" and len(presses(scr)) == 1  # o1 isn't the latest any more
        steps = db.list_steps(sessions()[0]["id"])
        assert [s["tool"] for s in steps] == ["screenshot", "left_click", "screenshot"]
        assert steps[1]["verdict"] == "free:3.legwork"

    def test_a_marked_click_on_buy_now_is_gated_at_press_with_no_screenshot_after(self, scr):
        ctx = _dctx()

        async def go():
            first = await screen(ctx, action="screenshot")
            gated = await screen(ctx, action="click", observation=first["observation"], mark=1)
            after = await screen(ctx, action="screenshot")
            await direct.close_turn("turn-1")
            return gated, after
        gated, after = asyncio.run(go())
        assert gated["stopped"].startswith("Needs your approval (buy: Buy now).")
        assert [a["name"] for a in scr.actions] == ["screenshot"]  # the gate's own picture; nothing was clicked
        assert scr.observations == 1 and "approval of gate" in after["error"]
        row = sessions()[0]
        assert row["status"] == "needs_approval" and db.get_gate(row["gate_id"])["action"] == "left_click"

    def test_a_different_control_under_the_mark_is_refused_before_it_is_classified(self, scr):
        ctx = _dctx()

        async def go():
            outs = []
            for changed in (element("Remove item", "e5", is_submit=False, box=dict(CART_BOX)),        # re-rendered
                            element("Add to cart", "e5", is_submit=False, box={**CART_BOX, "x": 50})):  # 10 px off
                scr.elements["e5"] = element("Add to cart", "e5", is_submit=False, box=dict(CART_BOX))
                first = await screen(ctx, action="screenshot")
                scr.elements["e5"] = changed  # still under the mark's point
                outs.append(await screen(ctx, action="click", observation=first["observation"], mark=2))
            await direct.close_turn("turn-1")
            return outs
        outs = asyncio.run(go())
        assert all(o["code"] == "mark_changed" and "changed under that mark" in o["error"] for o in outs)
        assert presses(scr) == [] and scr.observations == 2  # nothing pressed, no screenshot after a refusal
        assert [s["verdict"] for s in db.list_steps(sessions()[0]["id"]) if s["tool"] == "left_click"] == [None, None]

    def test_the_target_moving_between_the_check_and_the_press_is_refused_by_the_computer(self, scr):
        ctx = _dctx()

        def move(path, body):
            if path == "/actions" and body.get("name") == "left_click":
                scr.elements["e5"]["screen_box"] = {**CART_BOX, "x": 50}  # still under the point, 10 px off

        async def go():
            first = await screen(ctx, action="screenshot")
            scr.before_call = move
            out = await screen(ctx, action="click", observation=first["observation"], mark=2)
            await direct.close_turn("turn-1")
            return out
        out = asyncio.run(go())
        [click] = presses(scr)
        assert out["code"] == "element_changed" and scr.journal[click["action_id"]]["status"] == "failed"
        assert scr.observations == 1

    def test_marks_need_the_latest_screenshot_of_this_session_and_epoch(self, scr, monkeypatch):
        monkeypatch.setattr(runner, "RENEW_EVERY_S", 0.01)
        ctx = _dctx()

        async def go():
            a = await screen(ctx, action="screenshot")
            b = await screen(ctx, action="screenshot")
            outs = [await screen(ctx, action="click", observation=a["observation"], mark=2),  # not the latest
                    await screen(ctx, action="click", mark=2)]                                  # no observation
            bump(scr)  # control ended after b was taken; renew_loop sees the new epoch
            await asyncio.sleep(0.05)
            n = len(scr.calls)
            outs.append(await screen(ctx, action="click", observation=b["observation"], mark=2))
            sent = [p for p in calls_after(scr, n) if not p.startswith("/desktop/lease")]
            await direct.close_turn("turn-1")
            return outs, sent
        outs, sent = asyncio.run(go())
        assert all(o["code"] == "stale_mark" for o in outs) and sent == [] and presses(scr) == []

    def test_the_epoch_advancing_before_the_preliminary_snapshot_aborts_the_marked_click(self, scr):
        ctx = _dctx()

        async def go():
            first = await screen(ctx, action="screenshot")
            scr.before_call = lambda path, body: path == "/browser/snapshot" and bump(scr)
            n = len(scr.calls)
            out = await screen(ctx, action="click", observation=first["observation"], mark=2)
            scr.before_call = None
            paths = calls_after(scr, n)
            await direct.close_turn("turn-1")
            return out, paths
        out, paths = asyncio.run(go())
        assert out == runner.EPOCH_CHANGED
        assert not {"/browser/element", "/actions", "/screen/marked"} & set(paths)

    def test_a_failed_screenshot_after_the_click_still_says_it_was_performed(self, scr):
        ctx = _dctx()

        def fail_after_click(path, body):
            if path == "/actions" and body.get("name") == "left_click":
                scr.marked_error = "browser_failed"

        async def go():
            first = await screen(ctx, action="screenshot")
            scr.before_call = fail_after_click
            out = await screen(ctx, action="click", observation=first["observation"], mark=2)
            scr.before_call = scr.marked_error = None
            again = await screen(ctx, action="click", observation=first["observation"], mark=2)
            await direct.close_turn("turn-1")
            return out, again
        out, again = asyncio.run(go())
        assert out["performed"] is True and out["screenshot_error"] == "browser failed" and "images" not in out
        assert "take a screenshot before acting again" in out["hint"]
        assert again["code"] == "stale_mark" and len(presses(scr)) == 1

    def test_pixels_text_scroll_and_drag(self, scr):
        scr.elements["list"] = {**element("Wish list", "e7", is_submit=False), "tag": "div", "role": "generic",
                                "screen_box": {"x": 560, "y": 760, "w": 200, "h": 30}}  # mark 3: where the drag drops
        ctx = _dctx()

        async def go():
            outs = [await screen(ctx, action="click", x=100, y=720), await screen(ctx, action="type", text="blue mug"),
                    await screen(ctx, action="scroll", dy=-3)]
            outs.append(await screen(ctx, action="drag", observation=outs[-1]["observation"], mark=2, to_x=600, to_y=770))
            outs += [await screen(ctx, action="type", text="x", x=1, y=1), await screen(ctx, action="click"),
                     await screen(ctx, action="drag", x=1, y=1)]
            await direct.close_turn("turn-1")
            return outs
        outs = asyncio.run(go())
        assert all(o["performed"] for o in outs[:4])
        [click], [typed], [scroll], [drag] = (presses(scr, n) for n in ("left_click", "type", "scroll", "left_click_drag"))
        assert click["input"] == {"coordinate": [100, 720]} and "box" not in click["expect"]  # no mark, no box
        assert typed["input"] == {"text": "blue mug"} and "expect" not in typed
        assert scroll["input"] == {"scroll_direction": "up", "scroll_amount": 3}
        assert drag["input"] == {"start_coordinate": [100, 720], "coordinate": [600, 770]} and drag["expect"]["box"] == CART_BOX
        assert [o["error"] for o in outs[4:]] == ["type and key go to the focused element; click the field first",
                                                  "click needs a mark (with its observation) or x and y",
                                                  "drag needs to_x and to_y"]

    @pytest.mark.parametrize("drop", [{**element("Delete", "e8", is_submit=False), "tag": "div", "role": "generic"},
                                      None])  # a delete zone, or off the page (unidentified)
    def test_a_drag_that_drops_on_something_consequential_is_gated_before_it_starts(self, scr, drop):
        if drop:
            scr.elements["bin"] = {**drop, "screen_box": {"x": 560, "y": 380, "w": 200, "h": 100}}

        async def go():
            out = await screen(_dctx(), action="drag", x=100, y=720, to_x=600, to_y=400)
            await direct.close_turn("turn-1")
            return out
        out = asyncio.run(go())
        assert out["stopped"].startswith("Needs your approval") and presses(scr, "left_click_drag") == []
        row = sessions()[0]
        assert row["status"] == "needs_approval" and db.list_steps(row["id"])[-1]["verdict"] == (
            "gated:delete" if drop else "gated:submit")


LOGIN = "https://shop.example/signin?next=%2Fcheckout"


@pytest.fixture
def notices(monkeypatch):
    """A web-route takeover notice goes to every notification channel; capture it instead."""
    import core.agents.notifications.delivery as delivery
    sent: list = []
    monkeypatch.setattr(delivery, "deliver_notification", lambda slug, title, text: sent.append(text) or {"ok": True})
    return sent


def _hand_over(fc, reason="sign in to shop.example") -> tuple[dict, dict]:
    """A direct turn on the sign-in page that calls computer_takeover: (its result, the queued takeover task)."""
    ctx = _dctx()
    fc.url = LOGIN

    async def go():
        await call(ctx, action="snapshot")
        out = await call(ctx, "computer_takeover", reason=reason)
        await direct.close_turn("turn-1")
        return out
    out = asyncio.run(go())
    return out, db.get_task(out["task_id"]) if "task_id" in out else {}


def _run_takeover(fc, monkeypatch, hook=None) -> tuple[dict, list]:
    """Claim and run the queued takeover task (`hook(n)` before the n-th /control/status poll), then its
    completion: (the finished row, the completion turns' (instructions, message))."""
    from tests.test_computer_takeover import on_status
    if hook:
        on_status(fc, hook)
    t = db.claim_next("w1")
    assert asyncio.run(runner.run_task(t, "w1")) == "done"
    turns: list = []
    monkeypatch.setattr(processor, "run_agent_background_turn",
                        lambda *a, **kw: turns.append((a[2], a[3])) or (BackgroundResult(text="ok"), None))
    monkeypatch.setattr(processor, "_resolve_agent", lambda slug: {"slug": slug, "agent_name": "Tom"})
    monkeypatch.setattr(processor, "deliver_background_result", lambda *a, **kw: None)
    assert fc.submitted == [t["id"]]  # finished with notify=True: one completion turn
    completion.complete_task(t["id"])
    completion.complete_task(t["id"])
    return db.get_task(t["id"]), turns


class TestTakeover:
    """computer_takeover: the agent hands the screen to the owner; a driver='agent' takeover task holds its
    page for them and gives the agent one turn, telling it how control ended."""

    def test_it_notes_the_page_frees_the_screen_and_queues_the_owners_turn(self, dfake):
        out, task = _hand_over(dfake)
        assert out["stopped"] == "I've sent you a link to the screen; I'll continue when you press I'm done."
        session = db.get_task(task["parent_task_id"])
        assert (session["status"], session["finish_reason"], session["driver"]) == ("done", "handed to the owner", "agent")
        assert (task["driver"], task["status"], task["takeover_url"], task["takeover_reason"], task["approved_gate_id"]) == (
            "agent", "queued", LOGIN, "sign in to shop.example", None)
        assert task["task"] == "Owner takeover: sign in to shop.example" and dfake.lease is None

    def test_no_computer_calls_after_it_and_none_after_a_gate(self, dfake):
        dfake.elements["e10"] = element("Place order")
        ctx = _dctx()

        async def go():
            await call(ctx, action="snapshot")
            await call(ctx, "computer_takeover", reason="sign in")
            after = await call(ctx, "computer_screen", action="screenshot")
            await direct.close_turn("turn-1")
            await call(_dctx("turn-2"), action="snapshot")
            await call(_dctx("turn-2"), action="click", ref="e10")  # a gate opens
            refused = await call(_dctx("turn-2"), "computer_takeover", reason="place the order yourself")
            await direct.close_turn("turn-2")
            return after, refused
        after, refused = asyncio.run(go())
        assert "waiting for the owner to take over" in after["error"]
        assert "approval of gate" in refused["error"]
        assert len(db.query("SELECT 1 FROM tasks WHERE takeover_reason IS NOT NULL")) == 1

    @pytest.mark.parametrize("ending, status, reason, says", [
        ("done", "done", "handed back after takeover", "and handed it back (I'm done)"),
        ("disconnected", "done", "control ended without I'm done", "but control ended without I'm done (disconnected)"),
        ("timeout", "done", "control ended without I'm done", "but control ended without I'm done (timeout)"),
    ])
    def test_each_ending_gives_the_agent_one_turn_that_says_how_it_ended(
            self, dfake, monkeypatch, notices, ending, status, reason, says):
        _, task = _hand_over(dfake)
        dfake.url = "https://shop.example/"  # the browser drifted before the takeover task got the screen
        dfake.end_reason = ending

        def hook(n):
            if n == 2:
                dfake.human = True   # the owner pressed Take control
            if n == 4:
                dfake.human = False  # and control ended
        t, turns = _run_takeover(dfake, monkeypatch, hook)
        assert (t["status"], t["finish_reason"], t["takeover_state"]) == (status, reason, "")
        assert says in t["result_text"] and "performed nothing itself" in t["result_text"]
        [(instructions, message)] = turns
        assert instructions == completion._INSTRUCTIONS["takeover"] and reason in message
        # the recorded page was reopened, and the notice names what's on screen and the agent's own reason
        navs = [b for b in dfake.acts() if b["kind"] == "navigate"]
        assert [n["url"] for n in navs] == [LOGIN] and dfake.performed == navs
        [text] = notices
        assert text.startswith("sign in to shop.example\n\nThe screen shows Checkout (https://shop.example/); Chatty reopened it")
        assert f"/computer?task={t['id']}&agent=tom" in text

    @pytest.mark.parametrize("for_task", [True, False])  # through the link (task id), or the card's own Take control
    def test_control_that_started_and_ended_between_two_polls_still_counts(self, dfake, monkeypatch, notices, for_task):
        _, task = _hand_over(dfake)

        def hook(n):
            if n == 2:
                dfake.control_ended = {"at": time.time(), "reason": "done", "agent": "tom",
                                       "task_id": dfake.lease[2] if for_task else None}
        t, turns = _run_takeover(dfake, monkeypatch, hook)
        assert (t["status"], t["finish_reason"]) == ("done", "handed back after takeover") and len(turns) == 1
        assert sum(1 for _, p, _ in dfake.calls if p == "/control/status") == 2

    @pytest.mark.parametrize("record", [
        {"reason": "done", "agent": "tom", "task_id": "another-task"},  # someone else's hand-back
        {"reason": "done", "agent": "dana", "task_id": None},           # another agent's
        {"reason": "done", "agent": "tom", "task_id": None, "old": True},  # before the wait started
        None,                                                           # nobody came
    ])
    def test_nobody_taking_the_screen_in_time_is_its_own_ending(self, dfake, monkeypatch, notices, record):
        monkeypatch.setattr(runner, "TAKEOVER_WAIT_S", 0.1)
        _, task = _hand_over(dfake)

        def hook(n):
            if record and n == 1:
                dfake.control_ended = {**record, "at": time.time() - (600 if record.get("old") else 0)}
        t, turns = _run_takeover(dfake, monkeypatch, hook)
        assert (t["status"], t["finish_reason"]) == ("failed", "nobody took over within 0 min")
        assert "nobody took control within 0 minutes. Nothing was done" in t["result_text"]
        [(instructions, message)] = turns
        assert instructions == completion._INSTRUCTIONS["takeover"] and "nobody took over" in message

    def test_a_handback_done_while_the_link_was_still_being_sent_counts(self, dfake, monkeypatch):
        import core.agents.notifications.delivery as delivery
        monkeypatch.setattr(runner, "TAKEOVER_WAIT_S", 0.3)

        def quick(slug, title, text):  # the owner used the first channel's link before the rest were sent
            dfake.human = True
            dfake.human = False
            return {"ok": True}
        monkeypatch.setattr(delivery, "deliver_notification", quick)
        _hand_over(dfake)
        t, turns = _run_takeover(dfake, monkeypatch)
        assert (t["status"], t["finish_reason"]) == ("done", "handed back after takeover") and len(turns) == 1

    def test_an_unrelated_control_session_that_ends_doesnt_finish_it(self, dfake, monkeypatch, notices):
        monkeypatch.setattr(runner, "TAKEOVER_WAIT_S", 0.2)
        _hand_over(dfake)

        def hook(n):
            if n == 1:
                dfake.human = True
            if n == 2:
                dfake.human = False
                dfake.control_ended["task_id"] = "another-task"  # not this takeover's session
        t, _ = _run_takeover(dfake, monkeypatch, hook)
        assert (t["status"], t["finish_reason"]) == ("failed", "nobody took over within 0 min")
        assert sum(1 for _, p, _ in dfake.calls if p == "/control/status") > 3  # it went back to waiting

    def test_definition_is_always_loaded_and_never_extends_the_turn(self, dfake):
        d = next(d for d in tools.computer_tool_defs() if d["name"] == "computer_takeover")
        assert d["always_loaded"] and not d.get("extends_turn") and d["writes"] is False
        assert d["input_schema"]["required"] == ["reason"]


class TestVision:
    def test_the_screen_tool_goes_only_to_models_that_take_images(self):
        from types import SimpleNamespace

        from core.providers.anthropic_provider import ANTHROPIC_MODELS
        from core.providers.base import drop_image_tools, takes_images
        from core.providers.google_provider import GOOGLE_MODELS
        from core.providers.openai_provider import OPENAI_MODELS
        from core.providers.together_provider import TOGETHER_MODELS

        def sees(provider, model):
            return takes_images(SimpleNamespace(provider_name=provider, model=model))
        assert all(sees("anthropic", m) for m in ANTHROPIC_MODELS) and all(sees("google", m) for m in GOOGLE_MODELS)
        assert all(sees("openai", m) for m in [*OPENAI_MODELS, "gpt-4o", "gpt-4o-mini", "gpt-4.1-mini", "gpt-6"])
        assert not any(sees("openai", m) for m in ("o3-mini", "o4-mini", "o1", "gpt-3.5-turbo", "gpt-4-turbo"))
        assert not any(sees("together", m) for m in TOGETHER_MODELS)
        assert not any(sees("ollama", m) for m in ("llava", "gemma3", "claude-sonnet-4-6", "gpt-5"))
        names = {d["name"] for d in tools.computer_tool_defs()}
        kept = {d["name"] for d in drop_image_tools(tools.computer_tool_defs(), SimpleNamespace(provider_name="ollama", model="llava"))}
        assert "computer_screen" in names and kept == names - {"computer_screen"}

    def test_a_turn_on_a_text_only_model_never_offers_it(self, dfake, monkeypatch):
        from core.agents import background_runner

        class Seer:
            def __init__(self, provider_name, model):
                self.provider_name, self.model, self.tools = provider_name, model, None

            async def stream_turn(self, messages, tools_, system_prompt):
                self.tools = [t["name"] for t in tools_]
                yield {"type": "text", "text": "ok"}
                yield {"type": "_turn_complete", "tool_calls": [], "stop_reason": "end_turn", "usage": {}}

        for seer, offered in ((Seer("together", "Qwen/Qwen3.5-9B"), False), (Seer("google", "gemini-2.5-pro"), True)):
            monkeypatch.setattr(background_runner, "get_ai_provider", lambda **kw: seer)
            reg = ToolRegistry(context_dir="/tmp/ctx", agent_slug="tom", integration_executors=tools.TOOL_EXECUTORS)
            asyncio.run(background_runner._run_turn("sys", "hi", tools.computer_tool_defs(), reg))
            assert ("computer_screen" in seer.tools) is offered and "computer_browser" in seer.tools


def test_an_orphaned_direct_session_is_swept_without_a_report_turn(dfake):
    tid = db.insert_task(agent_slug="tom", origin="user", task="direct session", helper_provider="", helper_model="",
                         driver="agent", worker_id="direct:1:t")
    hid = _queue()
    db.execute("UPDATE tasks SET status = 'running', worker_id = 'w1' WHERE id = ?", (hid,))
    db.execute("UPDATE tasks SET heartbeat_at = datetime('now', '-10 minutes')")
    completion.sweep()
    assert db.get_task(tid)["status"] == "failed" and db.get_task(hid)["status"] == "failed"
    assert set(dfake.submitted) == {hid}  # the helper task reports (the sweep re-submits pending ones); the session never
