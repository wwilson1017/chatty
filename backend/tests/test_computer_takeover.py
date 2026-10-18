"""Computer takeover (PR 6): request_takeover holds the screen for the owner, the notice and its
link, the handback with a fresh snapshot under the new epoch, the 15-minute "sign-in needed"
timeout, the phone-disconnect grace, cancels and lost leases during the waits, and the clock
stopping meanwhile. Same fakes as test_computer_tasks: no network, no real model."""

import json
import time

import httpx
import pytest

from core.agents.scheduled_actions import processor
from core.config import settings
from integrations.computer import completion, db, runner
from tests.test_computer_tasks import FINAL, SNAP, FakeProvider, _queue, _run
from tests.test_computer_tasks import fake as _computer_fake  # noqa: F401 — a fixture, re-exposed below

TAKEOVER = ("request_takeover", {"reason": "sign in to shop.example"})


@pytest.fixture
def fake(_computer_fake):  # noqa: F811 — pytest resolves the parameter by fixture name
    return _computer_fake


@pytest.fixture
def notices(monkeypatch):
    """Web-origin tasks notify every channel; capture instead of pushing."""
    sent: list = []
    import core.agents.notifications.delivery as delivery
    monkeypatch.setattr(delivery, "deliver_notification", lambda slug, title, text: sent.append((slug, title, text)) or {"ok": True})
    return sent


def status_calls(fake):
    return sum(1 for _, p, _ in fake.calls if p == "/control/status")


def snapshots(fake):
    return [b for _, p, b in fake.calls if p == "/browser/snapshot"]


def on_status(fake, hook):
    """Run `hook(n)` on the n-th /control/status poll, before the fake answers it."""
    orig = fake._route

    def route(request, path, body):
        if path == "/control/status":
            hook(status_calls(fake))
        return orig(request, path, body)
    fake._route = route


class TestTakeover:
    def test_done_resumes_with_the_new_epoch_and_a_fresh_snapshot(self, fake, monkeypatch, notices):
        tid = _queue()
        states: list = []

        def hook(n):
            states.append(db.get_task(tid)["takeover_state"])
            if n == 2:
                fake.human = True  # the owner pressed Take control
            if n == 4:
                fake.human, fake.epoch_n = False, fake.epoch_n + 1  # pressed I'm done: control ended, epoch bumped
        on_status(fake, hook)
        prov = FakeProvider([{"tool_calls": [SNAP]}, {"tool_calls": [TAKEOVER]}, FINAL])
        _, t = _run(fake, prov, monkeypatch)
        assert t["status"] == "done" and prov.calls == 3
        assert t["takeover_state"] == "" and t["takeover_reason"] == "sign in to shop.example"
        assert states == ["waiting", "waiting", "active", "active"]
        # the handback snapshot carries the new epoch at the first try (no stale_epoch round trip)
        assert [s["epoch"] for s in snapshots(fake)] == ["boot:2", "boot:3"]
        handback = prov.seen[2][-1]["content"][0]["content"]
        assert handback.startswith(runner.HANDBACK_NOTE)
        assert "Never ask for or type the password yourself" in handback
        assert handback.index("<untrusted_tool_result") > len(runner.HANDBACK_NOTE)  # our words outside the wrapper
        assert "Place order" in handback  # the fresh page
        steps = db.list_steps(tid)
        assert [s["tool"] for s in steps] == ["browser", "request_takeover", "request_takeover"]
        assert steps[1]["result_excerpt"] == "waiting for the owner: sign in to shop.example"
        # the owner was told why, by whom, and where
        assert len(notices) == 1
        slug, title, text = notices[0]
        assert slug == "tom" and title == "tom needs you on the computer"
        assert "sign in to shop.example" in text and "sees nothing you type" in text
        assert f"{settings.frontend_url}/computer?task={tid}&agent=tom" in text

    def test_nobody_comes_within_the_limit_ends_the_task_sign_in_needed(self, fake, monkeypatch, notices):
        monkeypatch.setattr(runner, "TAKEOVER_WAIT_S", 0.05)
        tid = _queue()
        prov = FakeProvider([{"text": "Found the login page.", "tool_calls": [TAKEOVER]}, FINAL])
        _, t = _run(fake, prov, monkeypatch)
        assert t["status"] == "failed" and t["finish_reason"] == "sign-in needed" and prov.calls == 1
        assert t["result_text"].startswith("Found the login page.\n\n[Stopped: sign-in needed — sign in to shop.example; nobody took the screen")
        assert t["takeover_state"] == "" and t["takeover_reason"] == "sign in to shop.example"
        assert snapshots(fake) == [] and fake.lease is None and fake.submitted == [tid]
        assert status_calls(fake) >= 2  # it did wait, polling
        assert len(notices) == 1

    def test_phone_disconnect_releases_control_after_the_grace_period(self, fake, monkeypatch, notices):
        """The computer owns the grace: status keeps human_in_control through the dropped socket and
        reports control_ended (disconnected) with a new epoch when it runs out. The helper waits it out."""
        tid = _queue()
        cs = {"control_session_id": "cs-1", "agent": "tom", "task_id": tid}
        script = [
            (False, None, None),
            (True, {**cs, "connected": True}, None),
            (True, {**cs, "connected": False}, None),  # the phone dropped: the 60 s grace is running
            (True, {**cs, "connected": False}, None),
            (False, None, {"reason": "disconnected", "epoch": "boot:3"}),
        ]

        def hook(n):
            human, control, ended = script[min(n, len(script)) - 1]
            fake.human = human
            if ended:
                fake.epoch_n = 3
            fake.status_extra = {"control": control, "control_ended": ended}
        on_status(fake, hook)
        orig = fake._route

        def route(request, path, body):
            r = orig(request, path, body)
            if path == "/control/status":
                return httpx.Response(200, json={**json.loads(r.content), **fake.status_extra})
            return r
        fake._route = route
        prov = FakeProvider([{"tool_calls": [TAKEOVER]}, FINAL])
        _, t = _run(fake, prov, monkeypatch)
        assert t["status"] == "done" and status_calls(fake) == 5
        assert [s["epoch"] for s in snapshots(fake)] == ["boot:3"]  # nothing sent during the grace; resumed under the new epoch

    @pytest.mark.parametrize("when", ["waiting", "active"])
    def test_cancel_during_the_wait_ends_the_task(self, fake, monkeypatch, notices, when):
        tid = _queue()

        def hook(n):
            if when == "active" and n == 1:
                fake.human = True
            if n == 3:
                assert db.get_task(tid)["takeover_state"] == when
                db.finish_task(tid, "cancelled", "cancelled by owner", notify=False, cancel_requested=1)
        on_status(fake, hook)
        prov = FakeProvider([{"tool_calls": [TAKEOVER]}, FINAL])
        outcome, t = _run(fake, prov, monkeypatch)
        assert outcome == "done" and t["status"] == "cancelled" and prov.calls == 1
        assert t["takeover_state"] == "" and snapshots(fake) == [] and fake.lease is None
        assert status_calls(fake) == 3  # stopped at the next liveness check, no further polling

    def test_waiting_time_does_not_count_toward_the_time_cap(self, fake, monkeypatch, notices):
        monkeypatch.setattr(runner, "TAKEOVER_WAIT_S", 0.3)
        _queue()
        prov = FakeProvider([{"tool_calls": [TAKEOVER]}, FINAL])
        t0 = time.monotonic()
        _, t = _run(fake, prov, monkeypatch)
        wall = time.monotonic() - t0
        assert t["finish_reason"] == "sign-in needed" and wall >= 0.3
        assert t["running_seconds"] < wall - 0.25  # the wait itself was not counted

    def test_lease_lost_during_the_wait_fences_the_worker(self, fake, monkeypatch, notices):
        monkeypatch.setattr(runner, "RENEW_EVERY_S", 0.02)
        _queue()

        def hook(n):
            if n == 2:
                fake.lose_lease = True  # the next renewal answers lease_lost
        on_status(fake, hook)
        prov = FakeProvider([{"tool_calls": [TAKEOVER]}, FINAL])
        _, t = _run(fake, prov, monkeypatch)
        assert t["status"] == "failed" and t["finish_reason"] == "lost the screen"
        assert t["takeover_state"] == "" and snapshots(fake) == []

    def test_viewer_control_before_a_task_makes_it_wait_not_fail(self, fake, monkeypatch):
        """PR 3 behaviour, verified: "Take control" with no task running holds the screen, and the next
        task waits for the handback (takeover_state 'active' meanwhile) instead of failing."""
        fake.human = True
        tid = _queue()
        states: list = []

        def hook(n):
            states.append(db.get_task(tid)["takeover_state"])
            if n == 2:
                fake.human, fake.epoch_n = False, fake.epoch_n + 1
        on_status(fake, hook)
        _, t = _run(fake, FakeProvider([FINAL]), monkeypatch)
        assert t["status"] == "done" and states == ["active", "active"] and t["takeover_state"] == ""
        assert [p for _, p, _ in fake.calls if p == "/desktop/activate"] == ["/desktop/activate"] * 2  # refused once, then granted


class TestNotice:
    def _task(self, route):
        return {"id": "t1", "agent_slug": "tom", "route": json.dumps(route) if route else None}

    def test_telegram_has_a_url_button_only_for_https(self, fake, monkeypatch):
        import agents.db as agents_db
        import integrations.telegram.client as tg
        sent: list = []
        monkeypatch.setattr(tg, "send_message", lambda chat_id, text, bot_token, reply_markup=None, plain=False:
                            sent.append({"chat_id": chat_id, "text": text, "token": bot_token, "markup": reply_markup, "plain": plain}) or [{"ok": True}])
        monkeypatch.setattr(agents_db, "get_agent_by_slug", lambda slug: {"slug": slug, "agent_name": "Tom", "telegram_bot_token": "tok"})
        task = self._task({"channel": "telegram", "chat_id": 42})
        monkeypatch.setattr(settings, "frontend_url", "https://chatty.example/")
        runner.notify_takeover(task, "sign in to shop.example")
        m = sent[0]
        assert m["chat_id"] == 42 and m["token"] == "tok" and m["plain"] is True  # the reason is the helper's words about a page: never rendered
        assert m["markup"] == {"inline_keyboard": [[{"text": "Open the screen", "url": "https://chatty.example/computer?task=t1&agent=tom"}]]}
        assert m["text"].startswith("Tom needs you on the computer\n\nsign in to shop.example")
        assert "https://chatty.example/computer?task=t1&agent=tom" in m["text"]
        monkeypatch.setattr(settings, "frontend_url", "http://localhost:5173")
        runner.notify_takeover(task, "sign in to shop.example")
        assert sent[1]["markup"] is None and "http://localhost:5173/computer?task=t1&agent=tom" in sent[1]["text"]

    def test_whatsapp_route_and_web_fallback_and_failures_are_not_fatal(self, fake, monkeypatch, notices):
        import integrations.whatsapp.client as wa
        sent: list = []
        monkeypatch.setattr(wa, "send_message", lambda chat_id, text: sent.append((chat_id, text)))
        runner.notify_takeover(self._task({"channel": "whatsapp", "chat_id": "+1555"}), "solve the CAPTCHA")
        assert len(sent) == 1 and sent[0][0] == "+1555"
        assert sent[0][1].startswith("*tom needs you on the computer*\n\nsolve the CAPTCHA")
        runner.notify_takeover(self._task({"channel": "web"}), "solve the CAPTCHA")
        runner.notify_takeover(self._task(None), "solve the CAPTCHA")
        assert [n[0] for n in notices] == ["tom", "tom"]
        # a Telegram agent without a bot falls back too; a failing channel is logged, not raised
        runner.notify_takeover(self._task({"channel": "telegram", "chat_id": 1}), "x")
        assert len(notices) == 3
        monkeypatch.setattr(wa, "send_message", lambda chat_id, text: 1 / 0)
        runner.notify_takeover(self._task({"channel": "whatsapp", "chat_id": "+1555"}), "x")


class TestSurfaces:
    def test_task_api_exposes_takeover_state_and_reason(self, fake):
        tid = _queue()
        db.set_takeover(tid, "waiting", "sign in to shop.example")
        r = fake.client.get(f"/api/computer/tasks/{tid}").json()
        assert r["takeover_state"] == "waiting" and r["takeover_reason"] == "sign in to shop.example"
        db.set_takeover(tid, "")
        r = fake.client.get(f"/api/computer/tasks/{tid}").json()
        assert r["takeover_state"] == "" and r["takeover_reason"] == "sign in to shop.example"  # the reason stays

    def test_completion_turn_explains_sign_in_needed(self, fake, monkeypatch):
        tid = _queue()
        db.set_takeover(tid, "", "sign in to shop.example")
        db.finish_task(tid, "failed", "sign-in needed", notify=True, result_text="Found the login page.")
        turns: list = []
        from core.agents.background_runner import BackgroundResult
        monkeypatch.setattr(processor, "run_agent_background_turn", lambda agent, title, instr, msg, **kw: turns.append(msg) or (BackgroundResult(text="ok"), None))
        monkeypatch.setattr(processor, "_resolve_agent", lambda slug: {"slug": slug, "agent_name": "Tom"})
        monkeypatch.setattr(processor, "deliver_background_result", lambda *a, **kw: None)
        completion.complete_task(tid)
        assert len(turns) == 1
        msg = turns[0]
        assert "status 'failed' (sign-in needed)" in msg
        assert "take over the screen and nobody did within 15 minutes" in msg
        assert "Never ask the user for a password" in msg
        # the helper's reason reaches the agent only inside the untrusted wrapper, never in the note
        assert msg.index("sign in to shop.example") > msg.index("<untrusted_tool_result")
        assert msg.count("sign in to shop.example") == 1

    def test_old_db_gains_the_takeover_reason_column(self, fake):
        conn = db.get_db()
        conn.execute("ALTER TABLE tasks DROP COLUMN takeover_reason")
        conn.commit()
        db.close_db()
        db._setup_connection()
        assert "takeover_reason" in {r[1] for r in db.get_db().execute("PRAGMA table_info(tasks)")}

    def test_tool_definition_and_rules(self):
        names = [d["name"] for d in runner.TOOL_DEFS]
        assert "request_takeover" in names
        assert "request_takeover" in runner.build_system_prompt("Tom", "tom")
        assert "never ask the owner for them" in runner.build_system_prompt("Tom", "tom")
