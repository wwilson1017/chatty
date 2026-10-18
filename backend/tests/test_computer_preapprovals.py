"""Pre-approved actions for scheduled actions (PR 7): a cron action's {host, button_text} list lets
its computer tasks cross that one gate without a card, bound to the prompt's sha256. Purchases,
heartbeats, reminders, edited prompts, near-misses and every other write path never pre-approve.
Fake computer + scripted helper from test_computer_tasks."""

import json

import pytest

from core.agents import tool_definitions
from core.agents.scheduled_actions import service
from core.agents.scheduled_actions import tools as sa_tools
from integrations.computer import approvals, db, preapprovals

from tests.test_computer_tasks import (  # noqa: F401 (fake is a fixture)
    CLICK_ORDER, FINAL, SNAP, FakeProvider, _queue, _run, element, fake,
)



@pytest.fixture
def fc(fake):  # noqa: F811 (the imported fixture, under a name no test parameter shadows)
    return fake


HOST = "time.example"
ALLOWED = {"host": HOST, "button_text": "Submit timesheet"}
# A plain form submission on a non-checkout page: rule 6 gates it as `submit`.
SUBMIT = {**element("Submit timesheet", host=HOST, path="/week", total=None, form_action="https://time.example/submit"),
          "page": {"host": HOST, "path": "/week", "title": "Weekly timesheet"}}


def _cron(prompt="Submit this week's timesheet on time.example."):
    r = service.create_action("tom", "cron", name="Timesheet", cron_expression="0 9 * * 5", prompt=prompt)
    assert r.get("ok"), r
    return r["id"]


def _heartbeat():
    return service.create_action("tom", "interval", name="Heartbeat", interval_minutes=30, prompt="hb", action_type="heartbeat")["id"]


def _allow(action_id, host=HOST, text="Submit timesheet"):
    r = service.set_preapproved(action_id, [{"host": host, "button_text": text}])
    assert r.get("ok"), r


def _submit_run(fc, monkeypatch, action_id, el=SUBMIT):
    """A background task of that scheduled action: look, click the control, report. Returns
    (task, gate ids the owner was asked about, provider)."""
    fc.elements[el["ref"]] = el
    fc.url = "https://time.example/week"
    asked: list[str] = []
    monkeypatch.setattr(approvals, "request", lambda gid: asked.append(gid) or "card")
    _queue("submit the timesheet", action_id=action_id, origin="background")
    prov = FakeProvider([{"text": "Submitting.", "tool_calls": [SNAP, CLICK_ORDER]}, FINAL])
    _, t = _run(fc, prov, monkeypatch)
    return t, asked, prov


class TestPreapprovedRun:
    def test_matching_host_and_button_proceeds_without_a_card(self, fc, monkeypatch):
        aid = _cron()
        _allow(aid)
        t, asked, prov = _submit_run(fc, monkeypatch, aid)
        assert t["status"] == "done" and t["result_text"] == FINAL["text"], t
        assert asked == [] and db.query("SELECT * FROM gates WHERE status = 'pending'") == []
        [act] = fc.performed  # one activation, bound like an owner's approval would be
        assert act["kind"] == "click" and act["ref"] == "e10"
        assert (act["expect"]["host"], act["expect"]["name"], act["expect"]["context_fp"]) == (HOST, "Submit timesheet", "abc")
        gate = db.get_gate(t["gate_id"])
        assert (gate["status"], gate["decision"], gate["decided_via"], gate["decided_by"]) == (
            "done", "preapproved", "preapproved", f"scheduled_action:{aid}")
        assert gate["action_id"] == act["action_id"] and gate["decided_at"] and gate["kind"] == "submit"
        assert f"pre-approved for scheduled action {aid}: {HOST} / 'Submit timesheet' (6.form)" in gate["note"]
        assert [(s["tool"], s["verdict"]) for s in db.list_steps(t["id"])] == [
            ("browser", None), ("approved_action", "preapproved:submit"), ("browser", "preapproved:submit")]
        note = prov.seen[1][-1]["content"][1]["content"]  # the click's result: Chatty's note, then the page
        assert note.startswith("Chatty performed this submit ('Submit timesheet' on time.example) ONCE")
        assert "<untrusted_tool_result" in note and "Do not repeat it" in note.split("<untrusted_tool_result")[0]

    def test_an_edited_prompt_clears_the_pre_approval(self, fc, monkeypatch):
        aid = _cron()
        original = service.get_action(aid)["prompt"]
        _allow(aid)
        assert service.update_action(aid, prompt="Submit the timesheet AND approve the team's expenses.")["ok"]
        row = service.get_action(aid)
        assert row["preapproved_json"] is None and row["preapproved_prompt_sha256"] is None
        assert service.update_action(aid, prompt=original)["ok"]  # editing it back doesn't revive the list
        assert service.preapproved_for(service.get_action(aid)) == []
        t, asked, _ = _submit_run(fc, monkeypatch, aid)
        assert t["status"] == "needs_approval" and asked == [t["gate_id"]] and fc.performed == []
        assert db.get_gate(t["gate_id"])["status"] == "pending"
        # the sha256 still guards any other write path: a list bound to a different prompt is dead
        _allow(aid)
        from core.agents.reminders import db as rdb
        rdb.get_db().execute("UPDATE scheduled_actions SET prompt = 'edited behind the service''s back' WHERE id = ?", (aid,))
        rdb.get_db().commit()
        assert service.preapproved_for(service.get_action(aid)) == []

    def test_a_declared_purchase_is_never_pre_approved_even_when_the_classifier_says_submit(self, fc, monkeypatch):
        aid = _cron()
        _allow(aid, text="Confirm")
        confirm = {**SUBMIT, "name": "Confirm"}  # rule 5: a generic confirmation, gated as `submit`
        assert preapprovals.match(aid, "submit", "act:click", confirm)  # the list alone would let it through
        fc.elements["e10"] = confirm
        asked: list[str] = []
        monkeypatch.setattr(approvals, "request", lambda gid: asked.append(gid) or "card")
        _queue("pay the invoice", action_id=aid, origin="background")
        declare = ("request_approval", {"kind": "buy", "reason": "paying the invoice"})
        prov = FakeProvider([{"tool_calls": [SNAP, declare]}, {"tool_calls": [CLICK_ORDER]}, FINAL])
        _, t = _run(fc, prov, monkeypatch)
        assert t["status"] == "needs_approval" and asked == [t["gate_id"]] and fc.performed == []
        assert db.get_gate(t["gate_id"])["reason"] == "paying the invoice"

    def test_a_purchase_is_never_pre_approved(self, fc, monkeypatch):
        aid = _cron()
        _allow(aid, host="shop.example", text="Place order")
        t, asked, _ = _submit_run(fc, monkeypatch, aid, el=element("Place order"))
        assert t["status"] == "needs_approval" and asked == [t["gate_id"]] and fc.performed == []
        assert db.get_gate(t["gate_id"])["kind"] == "buy"

    def test_heartbeat_and_reminder_turns_never_pre_approve(self, fc, monkeypatch):
        hb = _heartbeat()
        assert "Only scheduled" in service.set_preapproved(hb, [ALLOWED])["error"]
        from core.agents.reminders import db as rdb  # even a row forced into the table doesn't count for a heartbeat
        rdb.get_db().execute("UPDATE scheduled_actions SET preapproved_json = ?, preapproved_prompt_sha256 = ? WHERE id = ?",
                             (json.dumps([ALLOWED]), service._prompt_sha256("hb"), hb))
        rdb.get_db().commit()
        assert service.preapproved_for(service.get_action(hb)) == []
        t, asked, _ = _submit_run(fc, monkeypatch, hb)
        assert t["status"] == "needs_approval" and asked == [t["gate_id"]] and fc.performed == []
        # a reminder turn (or any turn without a scheduled action behind it) has no action_id at all
        t, asked, _ = _submit_run(fc, monkeypatch, None)
        assert t["status"] == "needs_approval" and asked == [t["gate_id"]] and fc.performed == []

    def test_a_page_that_changed_under_the_pre_approved_click_asks_the_owner(self, fc, monkeypatch):
        aid = _cron()
        _allow(aid)
        fc.element_changed = True  # the computer's own re-check refuses the click
        t, asked, _ = _submit_run(fc, monkeypatch, aid)
        assert t["status"] == "needs_approval" and asked == [t["gate_id"]] and fc.performed == []
        new = db.get_gate(t["gate_id"])
        assert new["status"] == "pending" and "changed under the click" in new["note"]
        [pre] = db.query("SELECT * FROM gates WHERE decision = 'preapproved'")
        assert pre["status"] == "cancelled"  # spent; nothing happened on the site


class TestMatching:
    @pytest.mark.parametrize("host,text", [
        ("www.time.example", "Submit timesheet"),
        ("TIME.EXAMPLE", "SUBMIT TIMESHEET"),
        ("https://www.time.example/week?x=1", "Submit  timesheet"),
    ])
    def test_host_and_button_normalisation(self, fc, host, text):
        aid = _cron()
        _allow(aid, host, text)
        el = {**SUBMIT, "name": "Submit\n   Timesheet ", "page": {**SUBMIT["page"], "host": "WWW.Time.example"}}
        assert preapprovals.match(aid, "submit", "act:click", el) == {"host": HOST, "button_text": service.normalize_text(text)}

    @pytest.mark.parametrize("host,text", [
        (HOST, "Submit timesheets"), (HOST, "Submit"), (HOST, "timesheet"), (HOST, "Submit timesheet now"),
        ("time.example.com", "Submit timesheet"), ("sub.time.example", "Submit timesheet"), ("example", "Submit timesheet"),
    ])
    def test_near_misses_do_not_match(self, fc, host, text):
        aid = _cron()
        _allow(aid, host, text)
        assert preapprovals.match(aid, "submit", "act:click", SUBMIT) is None

    def test_only_single_activations_on_identified_targets_of_a_real_cron_action(self, fc):
        aid = _cron()
        _allow(aid)
        assert preapprovals.match(aid, "submit", "act:click", SUBMIT) == ALLOWED
        assert preapprovals.match(aid, "send", "act:press:Enter", SUBMIT) == ALLOWED
        assert preapprovals.match(aid, "submit", "act:type", SUBMIT) is None    # a typed newline
        assert preapprovals.match(aid, "submit", "act:select", SUBMIT) is None
        assert preapprovals.match(aid, "submit", "act:click", {"found": False, "page": SUBMIT["page"]}) is None
        assert preapprovals.match(aid, "buy", "act:click", SUBMIT) is None
        assert preapprovals.match(None, "submit", "act:click", SUBMIT) is None
        assert preapprovals.match("no-such-action", "submit", "act:click", SUBMIT) is None


class TestOnlyTheDashboardWrites:
    def test_update_action_and_the_agent_tools_cannot_set_the_fields(self, fc):
        aid = _cron()
        bad = {"preapproved_json": json.dumps([ALLOWED]),
               "preapproved_prompt_sha256": service._prompt_sha256(service.get_action(aid)["prompt"])}
        assert service.update_action(aid, **bad) == {"error": "No valid fields to update"}
        assert sa_tools.update_scheduled_action_handler("tom", action_id=aid, **bad) == {"error": "No valid fields to update"}
        created = sa_tools.create_scheduled_action_handler("tom", name="x", schedule_type="cron", cron_expression="0 9 * * 1", prompt="p", **bad)
        assert created["ok"] and service.get_action(created["id"])["preapproved_json"] is None
        assert fc.client.patch(f"/api/scheduled-actions/{aid}", json=bad).status_code == 400  # unknown fields to the PATCH model
        row = service.get_action(aid)
        assert row["preapproved_json"] is None and row["preapproved_prompt_sha256"] is None
        for d in tool_definitions.SCHEDULED_ACTION_TOOLS:
            assert not any("preapprov" in k for k in d["input_schema"]["properties"]), d["name"]

    def test_endpoint_saves_normalised_rows_and_the_list_shows_the_live_ones(self, fc):
        aid = _cron()
        c = fc.client
        url = f"/api/scheduled-actions/{aid}/preapproved"
        r = c.put(url, json={"items": [{"host": "https://WWW.Time.Example/week", "button_text": "  Submit   timesheet "},
                                       {"host": "www.time.example", "button_text": "Submit timesheet"}]})
        assert r.status_code == 200 and r.json()["preapproved"] == [ALLOWED]  # normalised, de-duplicated
        [a] = [a for a in c.get("/api/scheduled-actions/tom").json()["actions"] if a["id"] == aid]
        assert a["preapproved"] == [ALLOWED] and a["preapproved_prompt_sha256"]
        assert service.update_action(aid, prompt="changed")["ok"]
        [a] = [a for a in c.get("/api/scheduled-actions/tom").json()["actions"] if a["id"] == aid]
        assert a["preapproved"] == [] and a["preapproved_json"] is None  # cleared by the prompt edit
        assert c.put(url, json={"items": [ALLOWED]}).json()["preapproved"] == [ALLOWED]  # saving again binds to the new prompt
        assert service.preapproved_for(service.get_action(aid)) == [ALLOWED]
        assert c.put(url, json={"items": []}).status_code == 200  # clears both columns
        row = service.get_action(aid)
        assert row["preapproved_json"] is None and row["preapproved_prompt_sha256"] is None
        assert c.put("/api/scheduled-actions/nope/preapproved", json={"items": []}).status_code == 404
        assert c.put(url, json={"items": [{"host": "", "button_text": "x"}]}).status_code == 400
        assert c.put(url, json={"items": [{"host": HOST}]}).status_code == 422
        assert c.put(f"/api/scheduled-actions/{_heartbeat()}/preapproved", json={"items": [ALLOWED]}).status_code == 400
        too_many = [{"host": f"h{i}.example", "button_text": "Go"} for i in range(service.MAX_PREAPPROVED + 1)]
        assert c.put(url, json={"items": too_many}).status_code == 400
