"""Computer approvals and resume (PR 4): the Telegram card and dashboard routes, single-use
decisions, the follow-up that performs the approved action exactly once with every binding
re-checked, new gates on any change, lost responses → outcome_unknown (never re-sent), takeover
tasks for unbindable gates, expiry, and policy. Telegram is mocked; the computer is the fake from
test_computer_tasks."""

import asyncio
import json
import threading
import types

import pytest

from core.agents.scheduled_actions import processor
from integrations.computer import approvals, completion, db, gates, runner
from integrations.registry import save_credentials
from integrations.telegram import client as tg_client

from tests.test_computer_tasks import (  # noqa: F401 (fake is a fixture)
    CLICK_ORDER, FINAL, MODEL, PNG, SNAP, FakeProvider, _ctx, _queue, _run, element, fake,
)


@pytest.fixture
def ap(fake, monkeypatch, tmp_path):  # noqa: F811 (fake is the imported fixture)
    """fake computer + an agent 'tom' whose Telegram bot is mapped to user 555, with recorded Telegram calls."""
    import integrations.telegram.state as tg_state
    from agents.db import create_agent, update_agent

    monkeypatch.setattr(tg_state, "DATA_DIR", tmp_path / "telegram")
    monkeypatch.setattr(tg_state, "DB_PATH", tmp_path / "telegram" / "telegram.db")
    (tmp_path / "telegram").mkdir()
    tg_state._setup_connection()

    ns = types.SimpleNamespace(fake=fake, client=fake.client, sent=[], photos=[], answers=[], edits=[], delivered=[], notices=[])
    agent = create_agent("Tom")
    assert agent["slug"] == "tom"
    update_agent(agent["id"], telegram_enabled=1, telegram_bot_token="bot-tok")
    tg_state.create_mapping("telegram", "555", agent["id"])
    ns.agent = agent

    def send(chat_id, text, bot_token, reply_markup=None, plain=False):
        ns.sent.append({"chat_id": chat_id, "text": text, "token": bot_token, "markup": reply_markup, "plain": plain})
        return [{"ok": True, "result": {"message_id": 900 + len(ns.sent)}}]

    monkeypatch.setattr(tg_client, "send_message", send)
    monkeypatch.setattr(tg_client, "send_photo",
                        lambda chat_id, photo, bot_token, caption="": ns.photos.append({"chat_id": chat_id, "photo": photo, "caption": caption}) or {"ok": True})
    monkeypatch.setattr(tg_client, "answer_callback_query", lambda cid, text, bot_token: ns.answers.append(text) or {})
    monkeypatch.setattr(tg_client, "edit_message_text", lambda chat_id, mid, text, bot_token: ns.edits.append((chat_id, mid, text)) or {})
    monkeypatch.setattr(processor, "_deliver_to_route", lambda slug, title, text, route: ns.delivered.append((route, text)) or [])
    from core.agents.notifications import delivery
    monkeypatch.setattr(delivery, "deliver_notification",  # notify_takeover's web/no-route path
                        lambda slug, title, text: ns.notices.append((slug, title, text)) or {"ok": True})
    monkeypatch.setattr(runner, "RECONCILE_WAIT_S", 0.01)
    yield ns
    tg_state.close_db()


def _stop_at_gate(ap, monkeypatch, el=None, click=CLICK_ORDER, text="Ordering.", **queue_kw):
    """Run a task that stops at the click; returns (task, gate)."""
    ap.fake.elements[el["ref"] if el else "e10"] = el or element("Place order")
    _queue(**queue_kw)
    prov = FakeProvider([{"text": text, "tool_calls": [SNAP, click]}, FINAL])  # look, then act, as a helper does
    _, t = _run(ap.fake, prov, monkeypatch)
    assert t["status"] == "needs_approval", t
    return t, db.get_gate(t["gate_id"])


def _cb(gate_id, decision="approve", sender=555, chat=555, message_id=901):
    return {"id": "cbq", "data": f"vc:{gate_id}:{decision}", "from": {"id": sender},
            "message": {"message_id": message_id, "chat": {"id": chat}}}


def _approve(ap, gate_id, **kw):
    approvals.handle_telegram_callback("tom", _cb(gate_id, **kw), "bot-tok")
    return db.query("SELECT * FROM tasks WHERE approved_gate_id = ?", (gate_id,))


def _follow_up(ap, monkeypatch, turns=None):
    """Claim and run the queued follow-up with a helper that just reports."""
    outcome, t = _run(ap.fake, FakeProvider(turns or [FINAL]), monkeypatch)
    assert outcome == "done"
    return t


# ── the request ──────────────────────────────────────────────────────────────

class TestRequest:
    def test_telegram_gets_the_screenshot_then_checked_facts_with_buttons(self, ap, monkeypatch):
        t, gate = _stop_at_gate(ap, monkeypatch)
        assert gate["screenshot"] == f"shots/{t['id']}/{gate['id']}.png" and (db.DATA_DIR / gate["screenshot"]).read_bytes() == PNG
        [photo] = ap.photos
        assert photo["chat_id"] == "555" and photo["photo"] == PNG and gate["id"] in photo["caption"]
        [msg] = ap.sent
        assert msg["chat_id"] == "555" and msg["token"] == "bot-tok" and msg["plain"] is True
        assert "Checked on the page" in msg["text"] and "shop.example/checkout" in msg["text"]
        assert 'button "Place order"' in msg["text"] and "Total $45.00" in msg["text"]
        assert "not verified" not in msg["text"]  # no helper account on a classifier-only gate
        assert msg["markup"]["inline_keyboard"][0] == [{"text": "Approve", "callback_data": f"vc:{gate['id']}:approve"},
                                                        {"text": "Deny", "callback_data": f"vc:{gate['id']}:deny"}]
        assert json.loads(db.get_gate(gate["id"])["approval_ref"]) == {"chat_id": "555", "message_id": 901}
        hours = db.query("SELECT (julianday(expires_at) - julianday('now')) * 24 AS h FROM gates WHERE id = ?", (gate["id"],))[0]["h"]
        assert 23.9 < hours <= 24

    def test_card_lists_pending_gates_and_serves_the_screenshot(self, ap, monkeypatch):
        _, gate = _stop_at_gate(ap, monkeypatch)
        [g] = ap.client.get("/api/computer/gates").json()["gates"]
        assert g["id"] == gate["id"] and g["takeover_reason"] is None and g["has_screenshot"] and g["total"]["amount"] == "45.00"
        assert g["name"] == "Place order" and g["host"] == "shop.example" and g["expires_at"].endswith("Z")
        r = ap.client.get(f"/api/computer/gates/{gate['id']}/screenshot")
        assert r.status_code == 200 and r.content == PNG and r.headers["content-type"] == "image/png"
        assert ap.client.get("/api/computer/gates/nope/screenshot").status_code == 404
        assert ap.client.get("/api/computer/gates?status=done").json()["gates"] == []

    def test_helper_account_is_shown_apart_from_checked_facts(self, ap, monkeypatch):
        ap.fake.elements["e10"] = element("Place order")
        _queue()
        declare = ("request_approval", {"kind": "buy", "reason": "ordering the mug", "item": "blue mug", "store": "shop.example", "total": "$45.00"})
        _, t = _run(ap.fake, FakeProvider([{"tool_calls": [declare]}, {"tool_calls": [CLICK_ORDER]}, FINAL]), monkeypatch)
        assert t["status"] == "needs_approval"
        text = ap.sent[0]["text"]
        checked, helper = text.split("Helper's own account (not verified): ")
        assert "Total $45.00" in checked and "reason: ordering the mug" in helper and "item: blue mug" in helper and "total: $45.00" in helper

    def test_no_telegram_means_card_only_and_the_gate_still_waits(self, ap, monkeypatch):
        import integrations.telegram.state as tg_state
        tg_state.get_db().execute("DELETE FROM user_mappings")
        tg_state.get_db().commit()
        _, gate = _stop_at_gate(ap, monkeypatch)
        assert ap.sent == [] and ap.photos == [] and gate["status"] == "pending" and gate["approval_ref"] is None

    def test_completion_note_says_where_to_approve(self, ap, monkeypatch):
        t, gate = _stop_at_gate(ap, monkeypatch)
        turns: list[str] = []
        from core.agents.background_runner import BackgroundResult
        monkeypatch.setattr(processor, "run_agent_background_turn", lambda *a, **kw: turns.append(a[3]) or (BackgroundResult(text="ok"), None))
        monkeypatch.setattr(processor, "_resolve_agent", lambda slug: {"slug": slug, "agent_name": "Tom"})
        monkeypatch.setattr(processor, "deliver_background_result", lambda *a, **kw: None)
        completion.complete_task(t["id"])
        assert "waiting for the owner's approval" in turns[0] and "Approve or deny on Telegram" in turns[0]
        assert "Do NOT try to perform it yourself" in turns[0] and '"takeover_reason": null' in turns[0]


# ── the decision ─────────────────────────────────────────────────────────────

class TestDecide:
    def test_approve_queues_the_follow_up_and_edits_the_card(self, ap, monkeypatch):
        t, gate = _stop_at_gate(ap, monkeypatch, route={"channel": "telegram", "chat_id": "555"})
        [f] = _approve(ap, gate["id"])
        g = db.get_gate(gate["id"])
        assert (g["status"], g["decision"], g["decided_via"], g["decided_by"]) == ("approved", "approve", "telegram", "telegram:555")
        assert g["decided_at"]
        assert f["status"] == "queued" and f["origin"] == "user" and f["parent_task_id"] == t["id"] and f["root_task_id"] == t["id"]
        assert f["approved_gate_id"] == gate["id"] and f["helper_model"] == MODEL and json.loads(f["route"]) == {"channel": "telegram", "chat_id": "555"}
        assert f["task"].startswith("Approved by the owner: buy — button \"Place order\" on shop.example/checkout")
        assert ap.edits and "approved" in ap.edits[0][2] and "approved" in ap.answers[0]
        assert ap.delivered == []  # an approval speaks through the follow-up's report, not a fixed line

    def test_double_approve_yields_one_follow_up(self, ap, monkeypatch):
        _, gate = _stop_at_gate(ap, monkeypatch)
        results, barrier = [], threading.Barrier(8)

        def press(decision):
            barrier.wait()
            results.append(approvals.decide(gate["id"], decision, "card", "owner"))

        threads = [threading.Thread(target=press, args=(d,)) for d in ["approve", "deny"] * 4]
        for th in threads:
            th.start()
        for th in threads:
            th.join()
        oks = [r for r in results if r.get("ok")]
        assert len(oks) == 1 and len(results) == 8
        assert db.query("SELECT COUNT(*) AS n FROM tasks WHERE approved_gate_id = ?", (gate["id"],))[0]["n"] == (1 if oks[0]["decision"] == "approve" else 0)
        assert "no longer waiting" in approvals.decide(gate["id"], "approve", "card", "owner")["error"]

    def test_deny_edits_the_message_and_sends_one_fixed_line(self, ap, monkeypatch):
        t, gate = _stop_at_gate(ap, monkeypatch, route={"channel": "telegram", "chat_id": "555"})
        r = ap.client.post(f"/api/computer/gates/{gate['id']}/decide", json={"decision": "deny"})
        assert r.status_code == 200 and r.json()["decision"] == "deny" and r.json()["task_id"] is None
        g = db.get_gate(gate["id"])
        assert (g["status"], g["decision"], g["decided_via"]) == ("denied", "deny", "card")
        assert len(ap.edits) == 1 and "denied" in ap.edits[0][2]
        assert ap.delivered == [({"channel": "telegram", "chat_id": "555"},
                                 f"Computer task {t['id']}: the buy (button \"Place order\" on shop.example) was denied; nothing was done.")]
        assert db.query("SELECT COUNT(*) AS n FROM tasks")[0]["n"] == 1

    def test_card_decide_codes(self, ap, monkeypatch):
        _, gate = _stop_at_gate(ap, monkeypatch)
        url = f"/api/computer/gates/{gate['id']}/decide"
        assert ap.client.post(url, json={"decision": "maybe"}).status_code == 422
        assert ap.client.post("/api/computer/gates/nope/decide", json={"decision": "approve"}).status_code == 404
        assert ap.client.post(url, json={"decision": "approve"}).status_code == 200
        assert ap.client.post(url, json={"decision": "deny"}).status_code == 409

    def test_non_linked_telegram_user_wrong_chat_or_message_is_ignored(self, ap, monkeypatch):
        _, gate = _stop_at_gate(ap, monkeypatch)
        for kw in ({"sender": 999}, {"chat": 1}, {"message_id": 7}):
            assert _approve(ap, gate["id"], **kw) == []
            g = db.get_gate(gate["id"])
            assert g["status"] == "pending" and g["decision"] is None
        assert "can't decide" in ap.answers[0] and "doesn't match" in ap.answers[1] and ap.edits == []
        # another agent's bot can't decide this agent's gate
        import integrations.telegram.state as tg_state
        from agents.db import create_agent, update_agent
        ann = create_agent("Ann")
        update_agent(ann["id"], telegram_enabled=1, telegram_bot_token="ann-tok")
        tg_state.create_mapping("telegram", "555", ann["id"])
        approvals.handle_telegram_callback("ann", _cb(gate["id"]), "ann-tok")
        assert db.get_gate(gate["id"])["status"] == "pending" and "No such approval" in ap.answers[-1]

    def test_expired_gate_does_nothing_and_the_sweep_expires_it(self, ap, monkeypatch):
        monkeypatch.setattr(runner, "kick", lambda: False)
        t, gate = _stop_at_gate(ap, monkeypatch, route={"channel": "telegram", "chat_id": "555"})
        db.execute("UPDATE gates SET expires_at = '2000-01-01 00:00:00' WHERE id = ?", (gate["id"],))
        assert "expired" in approvals.decide(gate["id"], "approve", "card", "owner")["error"]
        completion.sweep()
        completion.sweep()  # idempotent
        g = db.get_gate(gate["id"])
        assert g["status"] == "expired" and g["decision"] is None
        assert len(ap.edits) == 1 and "expired" in ap.edits[0][2]
        assert ap.delivered == [({"channel": "telegram", "chat_id": "555"},
                                 f"Computer task {t['id']}: the approval for the buy (button \"Place order\" on shop.example) expired after 24 h; nothing was done.")]
        assert db.query("SELECT COUNT(*) AS n FROM tasks")[0]["n"] == 1

    def test_approval_after_the_integration_was_disabled_or_agent_excluded_does_nothing(self, ap, monkeypatch):
        _, gate = _stop_at_gate(ap, monkeypatch)
        save_credentials("computer", {"enabled": True, "helper_model": MODEL, "disabled_agents": ["tom"]})
        assert "turned off for this agent" in approvals.decide(gate["id"], "approve", "card", "owner")["error"]
        save_credentials("computer", {"enabled": False, "helper_model": MODEL})
        assert _approve(ap, gate["id"]) == [] and "not set up" in ap.answers[0]
        g = db.get_gate(gate["id"])
        assert g["status"] == "pending" and g["decision"] is None and ap.edits == []
        # ... but the owner can still dismiss it: a deny is safe whatever the policy says
        assert approvals.decide(gate["id"], "deny", "card", "owner")["ok"]
        assert db.get_gate(gate["id"])["status"] == "denied" and len(ap.edits) == 1

    def test_follow_up_cancelled_before_dispatch_spends_the_approval(self, ap, monkeypatch):
        monkeypatch.setattr(runner, "kick", lambda: False)
        _, gate = _stop_at_gate(ap, monkeypatch)
        [f] = _approve(ap, gate["id"])
        save_credentials("computer", {"enabled": False})
        completion.sweep()
        assert db.get_task(f["id"])["status"] == "cancelled" and db.get_gate(gate["id"])["status"] == "cancelled"
        assert ap.fake.performed == []


# ── resume: the follow-up performs the approved action once ──────────────────

class TestResume:
    def test_follow_up_performs_exactly_once_with_the_stored_binding_then_the_helper_continues(self, ap, monkeypatch):
        t, gate = _stop_at_gate(ap, monkeypatch)
        [f] = _approve(ap, gate["id"])
        prov = FakeProvider([{"text": "Order placed, confirmation #123.", "tool_calls": []}])
        monkeypatch.setattr(runner, "get_ai_provider", lambda **kw: prov)
        claimed = db.claim_next("w1")
        assert claimed["id"] == f["id"]
        asyncio.run(runner.run_task(claimed, "w1"))
        done = db.get_task(f["id"])
        assert done["status"] == "done" and done["result_text"] == "Order placed, confirmation #123."
        [act] = ap.fake.performed
        assert act["kind"] == "click" and act["ref"] == "e10" and len(act["action_id"]) == 26
        assert act["expect"] == {"action": "act:click", "host": "shop.example", "path": "/checkout",
                                 "frame_url": "https://shop.example/checkout", "role": "button", "name": "Place order",
                                 "form_action": "https://shop.example/order", "context_fp": "abc",
                                 "total": {"amount": "45.00", "currency": "USD"}}
        g = db.get_gate(gate["id"])
        assert g["status"] == "done" and g["action_id"] == act["action_id"]
        assert ("POST", "/desktop/activate", {"agent": "tom", "task_id": f["id"]}) in ap.fake.calls
        opening = prov.seen[0][0]["content"]
        assert f"follow-up of task {t['id']}" in opening and "Approved action performed" in opening
        assert "performed it ONCE (one click)" in opening and "<untrusted_tool_result" in opening
        steps = db.list_steps(f["id"])
        assert steps[0]["tool"] == "approved_action" and steps[0]["verdict"] == "approved:buy" and steps[0]["action_id"] == act["action_id"]
        assert done["gate_id"] == gate["id"] and done["cost_actual_usd"] > 0

    @pytest.mark.parametrize("change, reason", [
        ({"total": "50.00"}, "total changed 45.00 USD → 50.00 USD"),
        ({"context_fp": "recipient-changed"}, "form changed"),
        ({"host": "evil.example"}, "page changed"),
        ({"path": "/pay"}, "page changed"),
        ({"frame_url": "https://ads.example/frame"}, "page changed"),
        ({"form_action": "https://shop.example/subscribe"}, "page changed"),
    ])
    def test_a_changed_binding_field_opens_a_new_gate_and_sends_nothing(self, ap, monkeypatch, change, reason):
        _, gate = _stop_at_gate(ap, monkeypatch)
        _approve(ap, gate["id"])
        fresh = element("Place order", **{k: v for k, v in change.items() if k != "frame_url"})
        if "frame_url" in change:
            fresh["frame_url"] = change["frame_url"]
        ap.fake.elements["e10"] = fresh
        f = _follow_up(ap, monkeypatch)
        assert ap.fake.performed == [] and f["status"] == "needs_approval"
        assert db.get_gate(gate["id"])["status"] == "cancelled"
        new = db.get_gate(f["gate_id"])
        assert new["id"] != gate["id"] and new["status"] == "pending" and new["rule"] == "rebind" and new["kind"] == "buy"
        assert new["note"].startswith(reason) and f"(replaces gate {gate['id']})" in new["note"]
        assert len(ap.sent) == 2  # a second card for the new gate

    def test_the_computer_is_the_last_check(self, ap, monkeypatch):
        """Even when Chatty's locate step matches, the computer re-reads the element inside the click request."""
        _, gate = _stop_at_gate(ap, monkeypatch)
        _approve(ap, gate["id"])
        ap.fake.element_changed = True  # the fake's /browser/act refuses with 409 element_changed

        def page_changes_under_the_click(path, body):
            if path == "/browser/act":  # locate saw $45.00; by the click the page shows $50.00
                ap.fake.elements["e10"] = element("Place order", total="50.00")
        ap.fake.before_call = page_changes_under_the_click
        f = _follow_up(ap, monkeypatch)
        assert ap.fake.performed == [] and f["status"] == "needs_approval"
        new = db.get_gate(f["gate_id"])
        assert db.get_gate(gate["id"])["status"] == "cancelled" and new["note"].startswith("changed under the click: name")
        assert json.loads(new["total_json"])["amount"] == "50.00"  # the replacement gate carries the re-read facts, not the rejected ones

    def test_an_old_total_still_visible_as_a_subtotal_does_not_satisfy_the_check(self, ap, monkeypatch):
        _, gate = _stop_at_gate(ap, monkeypatch)
        _approve(ap, gate["id"])
        ap.fake.snapshot = ('- heading "Review" [level=1]\n- text "Subtotal $45.00"\n- text "Shipping $5.00"\n'
                            '- text "Total $50.00"\n- button "Place order" [ref=e10]')
        ap.fake.elements["e10"] = element("Place order", total="50.00")  # the single order-total line is $50.00
        f = _follow_up(ap, monkeypatch)
        assert ap.fake.performed == [] and f["status"] == "needs_approval"
        assert db.get_gate(f["gate_id"])["note"].startswith("total changed 45.00 USD → 50.00 USD")

    def test_the_control_gone_from_the_page_becomes_a_takeover_gate(self, ap, monkeypatch):
        _, gate = _stop_at_gate(ap, monkeypatch)
        _approve(ap, gate["id"])
        ap.fake.snapshot = '- heading "Thanks" [level=1]\n- button "Continue shopping" [ref=e20]'
        f = _follow_up(ap, monkeypatch)
        assert ap.fake.performed == [] and f["status"] == "needs_approval"
        new = db.get_gate(f["gate_id"])
        assert new["note"].startswith("page changed") and gates.unbindable_reason(new)
        assert ap.sent[-1]["markup"]["inline_keyboard"][0][0]["text"] == "Take over to do this yourself"

    def test_two_identical_send_buttons_with_different_recipients_are_not_interchangeable(self, ap, monkeypatch):
        def send_button(ref, fp):
            return {"found": True, "ref": ref, "tag": "button", "role": "button", "name": "Send", "type": "button", "href": None,
                    "is_submit": False, "form": None, "frame_url": "https://mail.example/inbox",
                    "page": {"host": "mail.example", "path": "/inbox", "title": "Mail"}, "context_kind": "composer",
                    "context_fp": fp, "total": None}
        ap.fake.url = "https://mail.example/inbox"
        ap.fake.snapshot = '- button "Send" [ref=e1]\n- button "Send" [ref=e2]'
        ap.fake.elements["e1"] = send_button("e1", "to:bob|hi bob")
        _, gate = _stop_at_gate(ap, monkeypatch, el=send_button("e2", "to:eve|hi eve"), click=("browser", {"action": "click", "ref": "e2"}))
        assert gate["kind"] == "send" and gate["context_fp"] == "to:eve|hi eve" and gates.unbindable_reason(gate) is None
        _approve(ap, gate["id"])
        # the page re-rendered: the approved message is now the FIRST Send button, the other one is Bob's
        ap.fake.elements["e1"], ap.fake.elements["e2"] = send_button("e1", "to:eve|hi eve"), send_button("e2", "to:bob|hi bob")
        f = _follow_up(ap, monkeypatch)
        assert f["status"] == "done"
        [act] = ap.fake.performed
        assert act["ref"] == "e1" and act["expect"]["context_fp"] == "to:eve|hi eve"
        # ... and when neither carries the approved recipients, nothing is sent
        _, gate2 = _stop_at_gate(ap, monkeypatch, el=send_button("e2", "to:eve|hi eve"), click=("browser", {"action": "click", "ref": "e2"}))
        _approve(ap, gate2["id"], message_id=902)  # the second card sent
        ap.fake.elements["e1"], ap.fake.elements["e2"] = send_button("e1", "to:bob|hi"), send_button("e2", "to:mallory|hi")
        f2 = _follow_up(ap, monkeypatch)
        assert f2["status"] == "needs_approval" and len(ap.fake.performed) == 1
        assert db.get_gate(f2["gate_id"])["note"].startswith("form changed")

    def test_an_approved_enter_stays_an_enter(self, ap, monkeypatch):
        field = {"found": True, "ref": "e3", "tag": "input", "role": "textbox", "name": "Email", "type": "email", "href": None,
                 "is_submit": False, "form": {"action": "https://shop.example/newsletter", "method": "post"},
                 "frame_url": "https://shop.example/newsletter", "page": {"host": "shop.example", "path": "/newsletter", "title": "News"},
                 "context_kind": "form", "context_fp": "email:me@x", "total": None}
        ap.fake.snapshot = '- textbox "Email" [ref=e3]\n- button "Subscribe" [ref=e4]'
        _, gate = _stop_at_gate(ap, monkeypatch, el=field, click=("browser", {"action": "press", "ref": "e3", "key": "Enter"}))
        assert gate["kind"] == "submit" and gate["action"] == "act:press:Enter"
        _approve(ap, gate["id"])
        f = _follow_up(ap, monkeypatch)
        assert f["status"] == "done"
        [act] = ap.fake.performed
        assert act["kind"] == "press" and act["key"] == "Enter" and act["ref"] == "e3" and act["expect"]["action"] == "act:press:Enter"

    def test_lost_response_becomes_outcome_unknown_and_nothing_is_resent(self, ap, monkeypatch):
        t, gate = _stop_at_gate(ap, monkeypatch)
        _approve(ap, gate["id"])
        ap.fake.lose_response = True    # the click happens; the response never arrives
        ap.fake.journal_hidden = True   # ... and the journal can't confirm it (as after a restart)
        f = _follow_up(ap, monkeypatch)
        assert f["status"] == "outcome_unknown" and "couldn't confirm the outcome" in f["finish_reason"]
        assert "check the site" in f["error"] and f["gate_id"] == gate["id"]
        g = db.get_gate(gate["id"])
        assert g["status"] == "outcome_unknown" and g["screenshot"] == f"shots/{f['id']}/{gate['id']}-unknown.png"
        assert len(ap.fake.performed) == 1
        assert ("GET", f"/actions/{g['action_id']}", None) in ap.fake.calls
        monkeypatch.setattr(runner, "kick", lambda: False)
        completion.sweep()
        completion.sweep()
        assert len(ap.fake.performed) == 1 and db.query("SELECT COUNT(*) AS n FROM tasks WHERE status = 'queued'")[0]["n"] == 0
        # the report tells the agent to have the user check the site
        turns: list[str] = []
        from core.agents.background_runner import BackgroundResult
        monkeypatch.setattr(processor, "run_agent_background_turn", lambda *a, **kw: turns.append(a[3]) or (BackgroundResult(text="ok"), None))
        monkeypatch.setattr(processor, "_resolve_agent", lambda slug: {"slug": slug, "agent_name": "Tom"})
        monkeypatch.setattr(processor, "deliver_background_result", lambda *a, **kw: None)
        completion.complete_task(f["id"])
        assert "could NOT confirm" in turns[0] and "check the site" in turns[0] and "nothing will be retried" in turns[0]

    def test_lost_response_confirmed_by_the_journal_continues(self, ap, monkeypatch):
        _, gate = _stop_at_gate(ap, monkeypatch)
        _approve(ap, gate["id"])
        ap.fake.lose_response = True  # the journal still says done
        f = _follow_up(ap, monkeypatch)
        assert f["status"] == "done" and db.get_gate(gate["id"])["status"] == "done" and len(ap.fake.performed) == 1

    def test_a_stale_epoch_on_dispatch_retries_once_with_a_fresh_action_id(self, ap, monkeypatch):
        _, gate = _stop_at_gate(ap, monkeypatch)
        [f] = _approve(ap, gate["id"])
        acts: list[dict] = []

        def bump_once(path, body):
            if path == "/browser/act":
                acts.append(body)
                if len(acts) == 1:
                    ap.fake.epoch_n += 1  # the computer restarted: the first act is refused before journaling
        ap.fake.before_call = bump_once
        done = _follow_up(ap, monkeypatch)
        [act] = ap.fake.performed
        assert len(acts) == 2 and acts[0]["action_id"] != acts[1]["action_id"] and act["action_id"] == acts[1]["action_id"]
        g = db.get_gate(gate["id"])
        assert g["status"] == "done" and g["action_id"] == act["action_id"] and done["status"] == "done" and done["id"] == f["id"]
        assert db.list_steps(f["id"])[0]["action_id"] == act["action_id"]

    def test_a_person_taking_control_before_the_act_opens_a_new_gate_and_sends_nothing(self, ap, monkeypatch):
        _, gate = _stop_at_gate(ap, monkeypatch)
        _approve(ap, gate["id"])

        def take_control(path, body):
            if path == "/browser/act" and not ap.fake.human:
                ap.fake.human = True
                threading.Timer(0.05, lambda: setattr(ap.fake, "human", False)).start()
        ap.fake.before_call = take_control
        f = _follow_up(ap, monkeypatch)
        assert ap.fake.performed == [] and f["status"] == "needs_approval"
        assert db.get_gate(gate["id"])["status"] == "cancelled"
        new = db.get_gate(f["gate_id"])
        assert new["status"] == "pending" and new["note"].startswith("a person took control")

    def test_a_person_holding_the_screen_during_locate_is_waited_out_then_the_action_proceeds(self, ap, monkeypatch):
        _, gate = _stop_at_gate(ap, monkeypatch)
        _approve(ap, gate["id"])

        def take_control(path, body):
            if path == "/browser/snapshot" and not getattr(take_control, "done", False):
                take_control.done = True
                ap.fake.human = True
                threading.Timer(0.05, lambda: setattr(ap.fake, "human", False)).start()
        ap.fake.before_call = take_control
        f = _follow_up(ap, monkeypatch)
        assert len(ap.fake.performed) == 1 and f["status"] == "done" and db.get_gate(gate["id"])["status"] == "done"

    def test_a_journal_that_says_failed_after_a_lost_response_opens_a_new_gate(self, ap, monkeypatch):
        _, gate = _stop_at_gate(ap, monkeypatch)
        _approve(ap, gate["id"])
        ap.fake.lose_response = True
        ap.fake.on_act = lambda body: ap.fake.journal.__setitem__(body["action_id"], {"status": "failed"})
        f = _follow_up(ap, monkeypatch)
        assert len(ap.fake.performed) == 1 and f["status"] == "needs_approval"
        assert db.get_gate(gate["id"])["status"] == "cancelled"
        assert db.get_gate(f["gate_id"])["note"].startswith("the computer refused the action")

    def test_a_journal_still_executing_on_the_first_read_is_waited_for(self, ap, monkeypatch):
        _, gate = _stop_at_gate(ap, monkeypatch)
        _approve(ap, gate["id"])

        class Executing(dict):
            reads = 0

            def __getitem__(self, k):
                if k == "status":
                    Executing.reads += 1
                    return "executing" if Executing.reads == 1 else "done"
                return super().__getitem__(k)
        ap.fake.lose_response = True
        ap.fake.on_act = lambda body: ap.fake.journal.__setitem__(body["action_id"], Executing(status="x"))
        f = _follow_up(ap, monkeypatch)
        assert Executing.reads == 2 and f["status"] == "done" and db.get_gate(gate["id"])["status"] == "done"

    def test_unreachable_computer_is_outcome_unknown_too(self, ap, monkeypatch):
        _, gate = _stop_at_gate(ap, monkeypatch)
        _approve(ap, gate["id"])
        ap.fake.lose_unjournaled = True
        f = _follow_up(ap, monkeypatch)
        assert f["status"] == "outcome_unknown" and db.get_gate(gate["id"])["status"] == "outcome_unknown"
        assert ap.fake.performed == []

    def test_cancel_during_dispatching_keeps_the_gates_outcome(self, ap, monkeypatch):
        _, gate = _stop_at_gate(ap, monkeypatch)
        [f] = _approve(ap, gate["id"])
        ap.fake.on_act = lambda body: db.finish_task(f["id"], "cancelled", "cancelled by owner", notify=False, cancel_requested=1)
        done = _follow_up(ap, monkeypatch)
        assert done["status"] == "cancelled" and db.get_gate(gate["id"])["status"] == "done" and len(ap.fake.performed) == 1

    def test_orphaned_dispatch_is_outcome_unknown_for_task_and_gate(self, ap, monkeypatch):
        monkeypatch.setattr(runner, "kick", lambda: False)
        _, gate = _stop_at_gate(ap, monkeypatch)
        [f] = _approve(ap, gate["id"])
        db.claim_next("dead")
        db.execute("UPDATE gates SET status = 'dispatching', action_id = 'ACT9' WHERE id = ?", (gate["id"],))
        db.execute("UPDATE tasks SET heartbeat_at = datetime('now', '-10 minutes'), phase = 'action', pending_action_id = 'ACT9' WHERE id = ?", (f["id"],))
        completion.sweep()
        assert db.get_task(f["id"])["status"] == "outcome_unknown" and db.get_gate(gate["id"])["status"] == "outcome_unknown"

    def test_a_task_ended_while_waiting_for_the_screen_leaves_no_gate_dispatching(self, ap, monkeypatch):
        """human_in_control is refused before journaling: a cancel during that wait sent nothing, so the
        gate marked dispatching is spent, not parked in flight forever."""
        _, gate = _stop_at_gate(ap, monkeypatch)
        [f] = _approve(ap, gate["id"])

        def take_control_and_cancel(path, body):
            if path == "/browser/act" and not ap.fake.human:
                ap.fake.human = True
                db.finish_task(f["id"], "cancelled", "cancelled by owner", notify=False, cancel_requested=1)
                threading.Timer(0.05, lambda: setattr(ap.fake, "human", False)).start()
        ap.fake.before_call = take_control_and_cancel
        done = _follow_up(ap, monkeypatch)
        assert done["status"] == "cancelled" and ap.fake.performed == []
        assert db.get_gate(gate["id"])["status"] == "cancelled"

    def test_orphan_that_died_waiting_not_sending_spends_its_dispatching_gate(self, ap, monkeypatch):
        monkeypatch.setattr(runner, "kick", lambda: False)
        _, gate = _stop_at_gate(ap, monkeypatch)
        [f] = _approve(ap, gate["id"])
        db.claim_next("dead")
        db.execute("UPDATE gates SET status = 'dispatching', action_id = 'ACT9' WHERE id = ?", (gate["id"],))
        db.execute("UPDATE tasks SET heartbeat_at = datetime('now', '-10 minutes'), phase = 'wait' WHERE id = ?", (f["id"],))
        completion.sweep()
        assert (db.get_task(f["id"])["status"], db.get_task(f["id"])["finish_reason"]) == ("failed", "interrupted")
        assert db.get_gate(gate["id"])["status"] == "cancelled"

    def test_multi_activation_is_refused_without_a_gate(self, ap, monkeypatch):
        """Text mode can't produce one, but the branch guards PR 5's double clicks and held keys."""
        ap.fake.elements["e10"] = element("Place order")
        tid = _queue()
        task = db.claim_next("w1")
        run = runner._Run(task, "w1", runner.get_client())
        asyncio.run(run.activate())
        out = asyncio.run(run.act("click", {"ref": "e10"}, label="double_click", verdict_out=[]))
        assert "refused" in out["error"] and "more than once" in out["error"]
        assert db.query("SELECT COUNT(*) AS n FROM gates")[0]["n"] == 0 and not run.finished and db.get_task(tid)["status"] == "running"
        asyncio.run(run.release())
        asyncio.run(run.client.aclose())


# ── takeover: an approval we can't bind ──────────────────────────────────────

class TestTakeover:
    @pytest.mark.parametrize("el, why", [
        (element("Place order", total="ambiguous"), "no single order total"),
        (element("Send", is_submit=False, total=None), "no form or message composer"),
    ])
    def test_unbindable_gate_is_a_takeover_card(self, ap, monkeypatch, el, why):
        _, gate = _stop_at_gate(ap, monkeypatch, el=el)
        assert why in gates.unbindable_reason(gate)
        [g] = ap.client.get("/api/computer/gates").json()["gates"]
        assert why in g["takeover_reason"]
        [msg] = ap.sent
        assert "won't press this for you" in msg["text"] and why in msg["text"] and "Checked on the page" not in msg["text"]
        assert msg["markup"]["inline_keyboard"][0][0]["text"] == "Take over to do this yourself"

    def test_takeover_task_opens_the_agents_page_waits_for_the_owner_and_never_clicks(self, ap, monkeypatch):
        monkeypatch.setattr(runner, "TAKEOVER_WAIT_S", 2)
        t, gate = _stop_at_gate(ap, monkeypatch, el=element("Place order", total="ambiguous"))
        # nothing holds the screen during the approval window
        activations = lambda: [b for m, p, b in ap.fake.calls if p == "/desktop/activate"]  # noqa: E731
        assert [a["task_id"] for a in activations()] == [t["id"]] and ap.fake.lease is None
        [f] = _approve(ap, gate["id"])
        assert f["task"].startswith("Owner takeover") and "screen opens" in ap.answers[0] and "screen opens" in ap.edits[0][2]
        assert [a["task_id"] for a in activations()] == [t["id"]]
        ap.fake.url = "https://shop.example/"  # the browser drifted; the task must open the gate's page
        threading.Timer(0.05, lambda: setattr(ap.fake, "human", True)).start()
        threading.Timer(0.15, lambda: setattr(ap.fake, "human", False)).start()
        prov = FakeProvider([FINAL])
        done = _follow_up(ap, monkeypatch, [FINAL])
        assert prov.calls == 0  # no helper model call in a takeover task
        assert done["status"] == "done" and done["finish_reason"] == "handed back after takeover" and done["takeover_state"] == ""
        assert done["takeover_reason"].startswith("you approved doing the buy") and "performed nothing itself" in done["result_text"]
        assert [a for a in activations() if a["task_id"] == f["id"]] == [{"agent": "tom", "task_id": f["id"]}]
        acts = [b for m, p, b in ap.fake.calls if p == "/browser/act"]
        assert [a["kind"] for a in acts] == ["navigate"] and acts[0]["url"] == "https://shop.example/checkout"
        assert not [a for a in ap.fake.performed if a["kind"] != "navigate"]  # no click, no key press
        [(slug, title, text)] = ap.notices  # a web route: notify_takeover goes through deliver_notification
        assert slug == "tom" and "needs you on the computer" in title and f"/computer?task={f['id']}&agent=tom" in text
        # the lease is released and the approval is spent: it can never be dispatched by Chatty later
        assert ap.fake.lease is None and db.get_gate(gate["id"])["status"] == "cancelled"

    def test_takeover_nobody_comes(self, ap, monkeypatch):
        monkeypatch.setattr(runner, "TAKEOVER_WAIT_S", 0.05)
        _, gate = _stop_at_gate(ap, monkeypatch, el=element("Place order", total="ambiguous"))
        _approve(ap, gate["id"])
        f = _follow_up(ap, monkeypatch)
        assert f["status"] == "failed" and f["finish_reason"] == "nobody took over within 0 min" and ap.fake.performed == []

    def test_completion_note_for_a_takeover_gate(self, ap, monkeypatch):
        t, _ = _stop_at_gate(ap, monkeypatch, el=element("Place order", total="ambiguous"))
        turns: list[str] = []
        from core.agents.background_runner import BackgroundResult
        monkeypatch.setattr(processor, "run_agent_background_turn", lambda *a, **kw: turns.append(a[3]) or (BackgroundResult(text="ok"), None))
        monkeypatch.setattr(processor, "_resolve_agent", lambda slug: {"slug": slug, "agent_name": "Tom"})
        monkeypatch.setattr(processor, "deliver_background_result", lambda *a, **kw: None)
        completion.complete_task(t["id"])
        assert "press it themselves" in turns[0] and "no single order total" in turns[0]


def test_telegram_prefix_routes_to_the_computer_handler(monkeypatch):
    from integrations.telegram import router as tg_router
    seen = []
    monkeypatch.setattr(approvals, "handle_telegram_callback", lambda slug, cq, tok: seen.append((slug, cq["data"], tok)))
    tg_router._CALLBACK_HANDLERS["vc:"]("tom", {"id": "c", "data": "vc:g1:approve"}, "tok")
    assert seen == [("tom", "vc:g1:approve", "tok")]
