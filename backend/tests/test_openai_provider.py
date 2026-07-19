"""Tests for OpenAIProvider's handling of reasoning models that reject function
tools + an implicit reasoning_effort on /v1/chat/completions (e.g. gpt-5.6-sol)."""

import httpx
import openai
import pytest

from core.providers import openai_provider as op
from core.providers.openai_provider import OpenAIProvider, _is_reasoning_effort_tool_conflict


def _make_bad_request_error(param: str, wrapped: bool = True) -> openai.BadRequestError:
    """Build a real openai.BadRequestError shaped like the SDK builds it from an
    actual HTTP response (body parsed from response.text, message formatted as
    "Error code: {status} - {body}")."""
    error_obj = {
        "message": (
            "Function tools with reasoning_effort are not supported for "
            "gpt-5.6-sol in /v1/chat/completions. To use function tools, use "
            "/v1/responses or set reasoning_effort to 'none'."
        ),
        "type": "invalid_request_error",
        "param": param,
        "code": None,
    }
    body = {"error": error_obj} if wrapped else error_obj
    req = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    resp = httpx.Response(400, request=req, json=body)
    message = f"Error code: {resp.status_code} - {body}"
    return openai.BadRequestError(message, response=resp, body=body)


class _FakeStream:
    """Minimal async-iterable stand-in for the SDK's streaming response."""

    def __init__(self, chunks):
        self._chunks = chunks

    def __aiter__(self):
        return self._gen()

    async def _gen(self):
        for c in self._chunks:
            yield c


def _fake_chunk(text: str):
    from types import SimpleNamespace
    return SimpleNamespace(
        choices=[SimpleNamespace(delta=SimpleNamespace(content=text, tool_calls=None))]
    )


@pytest.fixture(autouse=True)
def _reset_reasoning_none_cache():
    op._NEEDS_REASONING_NONE.clear()
    yield
    op._NEEDS_REASONING_NONE.clear()


# ---------------------------------------------------------------------------
# _is_reasoning_effort_tool_conflict
# ---------------------------------------------------------------------------

def test_conflict_detected_via_nested_body_shape():
    err = _make_bad_request_error("reasoning_effort", wrapped=True)
    assert _is_reasoning_effort_tool_conflict(err) is True


def test_conflict_detected_via_unwrapped_body_shape():
    err = _make_bad_request_error("reasoning_effort", wrapped=False)
    assert _is_reasoning_effort_tool_conflict(err) is True


def test_conflict_detected_via_message_fallback_when_no_body():
    err = Exception(
        "Function tools with reasoning_effort are not supported for some-model."
    )
    assert _is_reasoning_effort_tool_conflict(err) is True


def test_unrelated_bad_request_is_not_a_conflict():
    error_obj = {
        "message": "Invalid model 'nope'.",
        "type": "invalid_request_error",
        "param": "model",
        "code": None,
    }
    body = {"error": error_obj}
    req = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    resp = httpx.Response(400, request=req, json=body)
    err = openai.BadRequestError(f"Error code: 400 - {body}", response=resp, body=body)
    assert _is_reasoning_effort_tool_conflict(err) is False


# ---------------------------------------------------------------------------
# OpenAIProvider.stream_turn retry + cache behavior
# ---------------------------------------------------------------------------

def _install_fake_client(monkeypatch, create_mock):
    from unittest.mock import MagicMock

    fake_client = MagicMock()
    fake_client.chat.completions.create = create_mock
    monkeypatch.setattr(op.openai, "AsyncOpenAI", lambda **kwargs: fake_client)


async def _drain(provider, tools):
    messages = [{"role": "user", "content": "hi"}]
    events = []
    async for event in provider.stream_turn(messages, tools, "system prompt"):
        events.append(event)
    return events


TOOLS = [{"name": "foo", "description": "d", "input_schema": {"type": "object", "properties": {}}}]


async def test_retries_with_reasoning_effort_none_and_populates_cache(monkeypatch):
    from unittest.mock import AsyncMock

    create_mock = AsyncMock(
        side_effect=[_make_bad_request_error("reasoning_effort"), _FakeStream([_fake_chunk("hi")])]
    )
    _install_fake_client(monkeypatch, create_mock)

    provider = OpenAIProvider(access_token="fake-token", model="gpt-5.6-sol")
    events = await _drain(provider, TOOLS)

    assert any(e.get("type") == "text" for e in events)
    assert create_mock.await_count == 2

    first_kwargs = create_mock.await_args_list[0].kwargs
    assert "reasoning_effort" not in first_kwargs
    assert first_kwargs["tools"]

    retry_kwargs = create_mock.await_args_list[1].kwargs
    assert retry_kwargs["reasoning_effort"] == "none"

    assert "gpt-5.6-sol" in op._NEEDS_REASONING_NONE


async def test_cache_not_populated_when_retry_also_fails(monkeypatch):
    from unittest.mock import AsyncMock

    create_mock = AsyncMock(
        side_effect=[
            _make_bad_request_error("reasoning_effort"),
            _make_bad_request_error("reasoning_effort"),
        ]
    )
    _install_fake_client(monkeypatch, create_mock)

    provider = OpenAIProvider(access_token="fake-token", model="gpt-5.6-sol")
    events = await _drain(provider, TOOLS)

    assert any(e.get("type") == "error" for e in events)
    assert create_mock.await_count == 2
    assert "gpt-5.6-sol" not in op._NEEDS_REASONING_NONE


async def test_unrelated_bad_request_does_not_retry(monkeypatch):
    from unittest.mock import AsyncMock

    error_obj = {
        "message": "Invalid model 'nope'.",
        "type": "invalid_request_error",
        "param": "model",
        "code": None,
    }
    body = {"error": error_obj}
    req = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    resp = httpx.Response(400, request=req, json=body)
    unrelated_error = openai.BadRequestError(f"Error code: 400 - {body}", response=resp, body=body)

    create_mock = AsyncMock(side_effect=[unrelated_error])
    _install_fake_client(monkeypatch, create_mock)

    provider = OpenAIProvider(access_token="fake-token", model="gpt-5.6-sol")
    events = await _drain(provider, TOOLS)

    assert any(e.get("type") == "error" for e in events)
    assert create_mock.await_count == 1
    assert "gpt-5.6-sol" not in op._NEEDS_REASONING_NONE


async def test_second_call_preempts_using_cache(monkeypatch):
    from unittest.mock import AsyncMock

    op._NEEDS_REASONING_NONE.add("gpt-5.6-sol")
    create_mock = AsyncMock(return_value=_FakeStream([_fake_chunk("hi")]))
    _install_fake_client(monkeypatch, create_mock)

    provider = OpenAIProvider(access_token="fake-token", model="gpt-5.6-sol")
    events = await _drain(provider, TOOLS)

    assert any(e.get("type") == "text" for e in events)
    assert create_mock.await_count == 1
    assert create_mock.await_args_list[0].kwargs["reasoning_effort"] == "none"
