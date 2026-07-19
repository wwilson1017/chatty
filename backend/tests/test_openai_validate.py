"""OpenAIProvider.validate() must not depend on a chat completion.

Regression: the old probe (gpt-5.4-nano with max_completion_tokens=1) always
400'd — reasoning models burn thinking tokens before any output — so every
VALID key was rejected as "Invalid OpenAI API key" at connect time.
"""

import asyncio

from core.providers import openai_provider


class _StubModels:
    def __init__(self, calls, fail=False):
        self._calls, self._fail = calls, fail

    def list(self):
        self._calls.append("models.list")
        if self._fail:
            raise RuntimeError("401 invalid key")
        return []


class _StubCompletions:
    def __init__(self, calls):
        self._calls = calls

    def create(self, **kwargs):
        self._calls.append(("chat", kwargs.get("max_completion_tokens")))
        return {}


class _StubChat:
    def __init__(self, calls):
        self.completions = _StubCompletions(calls)


def _stub_client(calls, models_fail=False):
    class _Client:
        def __init__(self, **kwargs):
            self.models = _StubModels(calls, fail=models_fail)
            self.chat = _StubChat(calls)
    return _Client


def test_validate_api_key_uses_models_list(monkeypatch):
    calls = []
    monkeypatch.setattr(openai_provider.openai, "OpenAI", _stub_client(calls))
    p = openai_provider.OpenAIProvider(access_token="sk-proj-x")
    assert asyncio.run(p.validate()) is True
    assert calls == ["models.list"]  # zero-token probe; no chat call


def test_validate_api_key_invalid_returns_false(monkeypatch):
    calls = []
    monkeypatch.setattr(openai_provider.openai, "OpenAI", _stub_client(calls, models_fail=True))
    p = openai_provider.OpenAIProvider(access_token="sk-bad")
    assert asyncio.run(p.validate()) is False


def test_validate_chatgpt_proxy_uses_chat_probe(monkeypatch):
    """The chat-only proxy may not implement /models — chat probe with a
    token budget that reasoning models can actually satisfy."""
    calls = []
    monkeypatch.setattr(openai_provider.openai, "OpenAI", _stub_client(calls))
    p = openai_provider.OpenAIProvider(access_token="oauth-tok", use_chatgpt_api=True)
    assert asyncio.run(p.validate()) is True
    assert len(calls) == 1 and calls[0][0] == "chat"
    assert calls[0][1] > 1  # never a 1-token budget
