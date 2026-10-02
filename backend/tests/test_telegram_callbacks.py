"""Telegram inline-button plumbing: reply_markup, allowed_updates, callback_query dispatch."""

import json
import sys
import types
from unittest.mock import MagicMock, patch

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from integrations.telegram import client as tg_client
from integrations.telegram import lifecycle as tg_lifecycle
from integrations.telegram import router as tg_router

AGENT = {"id": "a1", "slug": "ally", "telegram_bot_token": "bot:tok", "telegram_enabled": 1}
SECRET = "s3cret"


def _ok():
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 200
    resp.text = ""
    resp.json.return_value = {"ok": True, "result": []}
    resp.raise_for_status = MagicMock()
    return resp


# ── client ─────────────────────────────────────────────────────────────

class TestReplyMarkup:
    @patch("integrations.telegram.client.httpx.post")
    def test_markup_only_on_last_chunk(self, mock_post):
        mock_post.return_value = _ok()
        markup = {"inline_keyboard": [[{"text": "Run", "callback_data": "cc:1:full"}]]}
        long_text = ("a" * 3000 + "\n\n") * 3
        tg_client.send_message(1, long_text, "bot:tok", reply_markup=markup)

        bodies = [c[1]["json"] for c in mock_post.call_args_list]
        assert len(bodies) > 1
        assert all("reply_markup" not in b for b in bodies[:-1])
        assert bodies[-1]["reply_markup"] == markup

    @patch("integrations.telegram.client.httpx.post")
    def test_plain_fallback_keeps_markup(self, mock_post):
        parse_error = _ok()
        parse_error.status_code = 400
        parse_error.text = "can't parse entities"
        mock_post.side_effect = [parse_error, _ok()]
        markup = {"inline_keyboard": []}
        tg_client.send_message(1, "**x**", "bot:tok", reply_markup=markup)
        assert mock_post.call_args_list[1][1]["json"]["reply_markup"] == markup

    @patch("integrations.telegram.client.httpx.post")
    def test_no_markup_by_default(self, mock_post):
        mock_post.return_value = _ok()
        tg_client.send_message(1, "hi", "bot:tok")
        assert "reply_markup" not in mock_post.call_args[1]["json"]


class TestAllowedUpdates:
    @patch("integrations.telegram.client.httpx.get")
    def test_get_updates(self, mock_get):
        mock_get.return_value = _ok()
        tg_client.get_updates("bot:tok")
        sent = json.loads(mock_get.call_args[1]["params"]["allowed_updates"])
        assert sent == ["message", "callback_query"]

    @patch("integrations.telegram.client.httpx.post")
    def test_set_webhook(self, mock_post):
        mock_post.return_value = _ok()
        tg_client.set_webhook("https://x/hook", "bot:tok", secret_token="s")
        assert mock_post.call_args[1]["json"]["allowed_updates"] == ["message", "callback_query"]


class TestCallbackHelpers:
    @patch("integrations.telegram.client.httpx.post")
    def test_answer_and_edit(self, mock_post):
        mock_post.return_value = _ok()
        tg_client.answer_callback_query("cq1", "done", "bot:tok")
        assert mock_post.call_args[0][0].endswith("/answerCallbackQuery")
        assert mock_post.call_args[1]["json"] == {"callback_query_id": "cq1", "text": "done"}

        tg_client.edit_message_text(5, 9, "edited", "bot:tok")
        assert mock_post.call_args[0][0].endswith("/editMessageText")
        body = mock_post.call_args[1]["json"]
        assert body == {"chat_id": 5, "message_id": 9, "text": "edited"}


# ── dispatch ───────────────────────────────────────────────────────────

@pytest.fixture()
def dispatch_env(monkeypatch):
    calls = {"cc": [], "answered": []}
    fake = types.ModuleType("integrations.claude_code.approvals")
    fake.handle_telegram_callback = lambda slug, cq, token: calls["cc"].append((slug, cq["id"], token))
    monkeypatch.setitem(sys.modules, "integrations.claude_code.approvals", fake)
    monkeypatch.setattr(
        tg_router, "answer_callback_query",
        lambda cq_id, text, token: calls["answered"].append((cq_id, text, token)),
    )
    return calls


@pytest.fixture()
def webhook(monkeypatch, dispatch_env):
    monkeypatch.setattr(tg_router.agent_db, "get_agent_by_slug", lambda slug: AGENT)
    monkeypatch.setattr(tg_router.state, "get_webhook_secret", lambda agent_id: SECRET)
    # Run executor work inline so assertions see it.
    monkeypatch.setattr(tg_router, "_executor", types.SimpleNamespace(submit=lambda fn, *a: fn(*a)))
    processed = []
    monkeypatch.setattr(tg_router, "_safe_process_telegram", lambda *a: processed.append(a))
    app = FastAPI()
    app.include_router(tg_router.router)
    return TestClient(app), dispatch_env, processed


def _cb(data, cq_id="cq1"):
    return {"update_id": 1, "callback_query": {"id": cq_id, "data": data, "from": {"id": 42}}}


class TestWebhookCallbacks:
    def test_cc_callback_dispatched(self, webhook):
        client, calls, _ = webhook
        r = client.post("/webhook/ally", json=_cb("cc:7:full"),
                        headers={"X-Telegram-Bot-Api-Secret-Token": SECRET})
        assert r.status_code == 200
        assert calls["cc"] == [("ally", "cq1", "bot:tok")]
        assert calls["answered"] == []

    def test_other_callback_answered_and_ignored(self, webhook):
        client, calls, processed = webhook
        client.post("/webhook/ally", json=_cb("other:1"),
                    headers={"X-Telegram-Bot-Api-Secret-Token": SECRET})
        assert calls["answered"] == [("cq1", "", "bot:tok")]
        assert calls["cc"] == [] and processed == []

    def test_bad_secret_rejected(self, webhook):
        client, calls, _ = webhook
        r = client.post("/webhook/ally", json=_cb("cc:7:full"),
                        headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"})
        assert r.status_code == 200
        assert calls["cc"] == [] and calls["answered"] == []

    def test_missing_approvals_module_answers(self, webhook, monkeypatch):
        client, calls, _ = webhook
        monkeypatch.setitem(sys.modules, "integrations.claude_code.approvals", None)  # → ImportError
        client.post("/webhook/ally", json=_cb("cc:7:full"),
                    headers={"X-Telegram-Bot-Api-Secret-Token": SECRET})
        assert calls["cc"] == []
        assert calls["answered"] == [("cq1", "Not available", "bot:tok")]

    def test_messages_still_flow(self, webhook):
        client, _, processed = webhook
        update = {"update_id": 2, "message": {"text": "hi", "chat": {"id": 5}, "from": {"id": 42}}}
        client.post("/webhook/ally", json=update,
                    headers={"X-Telegram-Bot-Api-Secret-Token": SECRET})
        assert len(processed) == 1


class TestPollingCallbacks:
    def test_poll_loop_dispatches_callback(self, monkeypatch, dispatch_env):
        batches = [[_cb("cc:7:sandbox"), _cb("nope", cq_id="cq2")]]

        def fake_get_updates(token, offset=None, timeout=30):
            if batches:
                return batches.pop()
            tg_lifecycle.stop_polling("a1")
            return []

        class InlineThread:
            def __init__(self, target, **kw):
                self.target = target

            def start(self):
                self.target()

        monkeypatch.setattr(tg_lifecycle, "get_updates", fake_get_updates)
        monkeypatch.setattr(tg_lifecycle.threading, "Thread", InlineThread)
        tg_lifecycle.start_polling("a1", "ally", "bot:tok")

        assert dispatch_env["cc"] == [("ally", "cq1", "bot:tok")]
        assert dispatch_env["answered"] == [("cq2", "", "bot:tok")]
