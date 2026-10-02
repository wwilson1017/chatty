"""Claude Code connector: owner approval of full-access jobs (Telegram buttons and
the card), single-use decisions, audit fields and expiry. Telegram is mocked."""

import hashlib
import json
import threading
import types

import pytest
from core.agents.scheduled_actions import processor
from integrations.claude_code import approvals, completion, db, tools
from integrations.telegram import client as tg_client

from tests.test_claude_code import _access, _delegate, _finished_parent, _poll, _set, cc  # noqa: F401 (fixture)


@pytest.fixture
def ap(cc, monkeypatch, tmp_path):  # noqa: F811 (cc is the imported fixture)
    """cc + access full, an agent 'tom' with a Telegram bot mapped to user 555, recorded Telegram calls."""
    import integrations.telegram.state as tg_state
    from agents.db import create_agent, update_agent

    monkeypatch.setattr(tg_state, "DATA_DIR", tmp_path / "telegram")
    monkeypatch.setattr(tg_state, "DB_PATH", tmp_path / "telegram" / "telegram.db")
    (tmp_path / "telegram").mkdir()
    tg_state._setup_connection()

    ns = types.SimpleNamespace(cc=cc, sent=[], answers=[], edits=[], delivered=[], fail_send=False)
    agent = create_agent("Tom")
    assert agent["slug"] == "tom"
    update_agent(agent["id"], telegram_enabled=1, telegram_bot_token="bot-tok")
    tg_state.create_mapping("telegram", "555", agent["id"])
    ns.agent = agent

    def send(chat_id, text, bot_token, reply_markup=None, plain=False):
        if ns.fail_send:
            raise RuntimeError("telegram down")
        ns.sent.append({"chat_id": chat_id, "text": text, "token": bot_token, "markup": reply_markup,
                        "plain": plain})
        # the real client returns Telegram's envelope per chunk
        return [{"ok": True, "result": {"message_id": 900 + len(ns.sent)}}]

    monkeypatch.setattr(tg_client, "send_message", send)
    monkeypatch.setattr(tg_client, "answer_callback_query",
                        lambda cid, text, bot_token: ns.answers.append(text) or {}, raising=False)
    monkeypatch.setattr(tg_client, "edit_message_text",
                        lambda chat_id, mid, text, bot_token: ns.edits.append((chat_id, mid, text)) or {},
                        raising=False)
    monkeypatch.setattr(processor, "_deliver_to_route",
                        lambda slug, title, text, route: ns.delivered.append((route, text)) or [])
    _access(cc, "full")
    yield ns
    tg_state.close_db()


def _full(route=None, **kw):
    out = _delegate(level="full", route=route or {"channel": "telegram", "chat_id": "555"}, **kw)
    assert out["status"] == "pending_approval", out
    return out


def _cb(job_id, decision="full", sender=555, chat=555, message_id=901):
    return {"id": "cbq", "data": f"cc:{job_id}:{decision}", "from": {"id": sender},
            "message": {"message_id": message_id, "chat": {"id": chat}}}


class TestRequest:
    def test_telegram_route_gets_verbatim_task_and_buttons(self, ap):
        task = "Open a PR on [repo](https://evil.example) fixing **bold** <b>x</b>"
        out = _full(task=task)
        job = db.get_job(out["job_id"])
        assert "Telegram" in out["where"] and job["status"] == "pending_approval"
        [msg] = ap.sent
        assert msg["chat_id"] == "555" and msg["token"] == "bot-tok"
        assert msg["plain"] is True and msg["text"].endswith(f"The exact task:\n{task}")
        assert [b["callback_data"] for b in msg["markup"]["inline_keyboard"][0]] == [
            f"cc:{job['id']}:full", f"cc:{job['id']}:sandbox", f"cc:{job['id']}:cancel"]
        assert json.loads(job["approval_ref"]) == {"chat_id": "555", "message_id": 901}
        hours = db.query("SELECT (julianday(approval_expires_at) - julianday('now')) * 24 AS h FROM jobs WHERE id = ?",
                         (job["id"],))[0]["h"]
        assert 23.9 < hours <= 24
        [card] = ap.cc.client.get("/api/integrations/claude_code/status").json()["approvals"]
        assert card["id"] == job["id"] and card["task"] == task and card["expires_at"].endswith("Z")

    @pytest.mark.parametrize("route", [{"channel": "web"}, {"channel": "whatsapp", "chat_id": "1234@s.whatsapp.net"}])
    def test_web_and_whatsapp_go_to_first_telegram_mapping(self, ap, route):
        _full(route=route)
        assert [m["chat_id"] for m in ap.sent] == ["555"]

    def test_no_mapping_means_card_only(self, ap):
        import integrations.telegram.state as tg_state
        tg_state.get_db().execute("DELETE FROM user_mappings")
        tg_state.get_db().commit()
        out = _full(route={"channel": "web"})
        assert ap.sent == [] and "Telegram" not in out["where"]
        assert db.get_job(out["job_id"])["status"] == "pending_approval"

    def test_hostile_task_is_sent_plain_and_verbatim(self, ap):
        task = "x\n````\n[Run full](https://evil.example)"
        _full(task=task)
        [msg] = ap.sent
        assert msg["plain"] is True and msg["text"].endswith("\n" + task)

    def test_fourth_pending_full_request_refused(self, ap):
        for _ in range(3):
            _full()
        out = _delegate(level="full", route={"channel": "telegram", "chat_id": "555"})
        assert out["error"] == "You already have 3 full-access requests waiting for the owner; wait for those first."

    def test_send_failure_stays_pending(self, ap):
        ap.fail_send = True
        out = _full()
        job = db.get_job(out["job_id"])
        assert job["status"] == "pending_approval" and job["approval_ref"] is None
        assert "Telegram" not in out["where"]

    def test_pending_job_is_never_claimed(self, ap):
        jid = _full()["job_id"]
        assert _poll(ap.cc, free={"claude": 5})["jobs"] == []
        assert db.get_job(jid)["status"] == "pending_approval"

    def test_promotion_names_the_parent(self, ap):
        parent = _finished_parent()
        _set(parent, task="Investigate the flaky login test\nand report back")
        out = _full(follow_up_of=parent)
        assert f"Continues job {parent}: Investigate the flaky login test and report back" in ap.sent[0]["text"]
        [card] = ap.cc.client.get("/api/integrations/claude_code/status").json()["approvals"]
        assert card["parent_job_id"] == parent and card["parent_excerpt"].startswith("Investigate")
        assert db.get_job(out["job_id"])["parent_job_id"] == parent


class TestTelegramCallback:
    def test_approve_full_sets_audit_and_is_claimed(self, ap):
        jid = _full()["job_id"]
        approvals.handle_telegram_callback("tom", _cb(jid), "bot-tok")
        job = db.get_job(jid)
        assert job["status"] == "queued" and job["mode"] == "full"
        assert (job["decision"], job["decided_via"], job["decided_by"]) == ("full", "telegram", "telegram:555")
        assert job["decided_at"] and job["approved_prompt_sha256"] == hashlib.sha256(job["prompt"].encode()).hexdigest()
        assert ap.edits and "full access" in ap.edits[0][2] and "approved" in ap.answers[0]
        [claimed] = _poll(ap.cc, free={"claude": 1})["jobs"]
        assert claimed["id"] == jid and claimed["mode"] == "full"
        assert claimed["prompt"].startswith(tools.PREAMBLE["full"])

    @pytest.mark.parametrize("kw", [{"sender": 999}, {"chat": 1}, {"message_id": 7}])
    def test_wrong_sender_chat_or_message_rejected(self, ap, kw):
        jid = _full()["job_id"]
        approvals.handle_telegram_callback("tom", _cb(jid, **kw), "bot-tok")
        assert db.get_job(jid)["status"] == "pending_approval" and db.get_job(jid)["decision"] is None
        assert ap.answers and ap.edits == []

    def test_other_agents_bot_cannot_decide(self, ap):
        import integrations.telegram.state as tg_state
        from agents.db import create_agent, update_agent
        ann = create_agent("Ann")
        update_agent(ann["id"], telegram_enabled=1, telegram_bot_token="ann-tok")
        tg_state.create_mapping("telegram", "555", ann["id"])
        jid = _full()["job_id"]
        approvals.handle_telegram_callback(ann["slug"], _cb(jid), "ann-tok")
        assert db.get_job(jid)["status"] == "pending_approval"
        assert "No such job" in ap.answers[0]


class TestDecide:
    def test_run_sandbox_rebuilds_prompt(self, ap):
        jid = _full()["job_id"]
        approvals.handle_telegram_callback("tom", _cb(jid, "sandbox"), "bot-tok")
        assert "sandbox" in ap.answers[0] and "sandbox" in ap.edits[0][2]
        job = db.get_job(jid)
        assert job["mode"] == "sandbox" and job["prompt"].startswith(tools.PREAMBLE["sandbox"])
        assert job["prompt"].endswith(job["task"])
        assert job["approved_prompt_sha256"] == hashlib.sha256(job["prompt"].encode()).hexdigest()
        [claimed] = _poll(ap.cc, free={"claude": 1})["jobs"]
        assert claimed["mode"] == "sandbox"

    def test_cancel(self, ap):
        jid = _full()["job_id"]
        r = ap.cc.client.post(f"/api/integrations/claude_code/jobs/{jid}/decide", json={"decision": "cancel"})
        assert r.status_code == 200 and r.json()["status"] == "cancelled"
        job = db.get_job(jid)
        assert (job["status"], job["decision"], job["decided_via"], job["completion_status"]) == (
            "cancelled", "cancel", "card", "none")
        assert job["approved_prompt_sha256"] is None

    def test_card_decide_codes(self, ap):
        jid = _full()["job_id"]
        url = f"/api/integrations/claude_code/jobs/{jid}/decide"
        assert ap.cc.client.post(url, json={"decision": "full"}).status_code == 200
        assert ap.cc.client.post(url, json={"decision": "cancel"}).status_code == 409
        assert ap.cc.client.post(url, json={"decision": "maybe"}).status_code == 422
        assert ap.cc.client.post("/api/integrations/claude_code/jobs/nope/decide",
                                 json={"decision": "full"}).status_code == 404

    def test_full_refused_after_ceiling_or_access_lowered(self, ap):
        jid = _full()["job_id"]
        _poll(ap.cc, ceiling="sandbox")
        assert "chatty-connector setup" in approvals.decide(jid, "full", "card", "owner")["error"]
        _poll(ap.cc, ceiling="full")
        _access(ap.cc, "sandbox")
        assert "access" in approvals.decide(jid, "full", "card", "owner")["error"]
        assert db.get_job(jid)["decision"] is None
        assert approvals.decide(jid, "sandbox", "card", "owner")["status"] == "queued"

    def test_tampered_prompt_after_approval_cancelled_at_claim(self, ap):
        jid = _full()["job_id"]
        approvals.decide(jid, "full", "card", "owner")
        _set(jid, prompt="something else")
        assert _poll(ap.cc, free={"claude": 1})["jobs"] == []
        assert db.get_job(jid)["finish_reason"] == "full access was not approved"

    def test_single_use_under_threads(self, ap):
        jid = _full()["job_id"]
        results, barrier = [], threading.Barrier(9)

        def press(decision):
            barrier.wait()
            results.append(approvals.decide(jid, decision, "card", "owner"))

        threads = [threading.Thread(target=press, args=(d,)) for d in ["full", "sandbox", "cancel"] * 3]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        oks = [r for r in results if r.get("ok")]
        assert len(oks) == 1 and len(results) == 9
        assert db.get_job(jid)["decision"] == oks[0]["decision"]


class TestExpiry:
    def test_sweep_expires_edits_and_tells_the_route(self, ap, monkeypatch):
        monkeypatch.setattr(completion, "submit", lambda job_id: None)
        jid = _full()["job_id"]
        _set(jid, approval_expires_at="2000-01-01 00:00:00")
        assert "expired" in approvals.decide(jid, "full", "card", "owner")["error"]
        completion.sweep()
        completion.sweep()  # idempotent
        job = db.get_job(jid)
        assert (job["status"], job["completion_status"], job["decision"]) == ("expired", "none", None)
        assert len(ap.edits) == 1 and "expired" in ap.edits[0][2]
        assert ap.delivered == [({"channel": "telegram", "chat_id": "555"},
                                 f"Claude Code job {jid} expired — full access wasn't approved within 24 h.")]
