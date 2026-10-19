"""Images in tool results: each provider's add_tool_results shape, prune_images, and the three
loops (chat, run_sync, background _run_turn) handing images to the model only — never to the
stored chat row, the SSE tool_end event or the activity/tool log."""

import base64
import copy
import json

import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from core.agents import background_runner
from core.agents.ai_service import chat, run_sync
from core.providers.anthropic_provider import AnthropicProvider
from core.providers.base import IMAGES_NOTE, PRUNED_NOTE, split_images
from core.providers.google_provider import GoogleProvider, _to_parts
from core.providers.ollama_provider import OllamaProvider
from core.providers.openai_provider import OpenAIProvider
from core.providers.together_provider import TogetherProvider
from tests.conftest import collect_events
from tests.test_ai_service import MockAIProvider
from tests.test_persistence_chronology import (  # noqa: F401 — fixtures
    _patch_externals, chat_service, fake_config, mock_ctx, mock_registry,
)

B64 = "iVBORw0KGgoUNIQUEPIXEL"  # 22 chars: + a 2-char suffix stays valid base64
IMG = {"media_type": "image/png", "data": B64}
PROVIDERS = {
    "anthropic": lambda: AnthropicProvider(api_key="k"),
    "openai": lambda: OpenAIProvider("k"),
    "ollama": lambda: OllamaProvider(model="m"),
    "together": lambda: TogetherProvider(api_key="k"),
    "google": lambda: GoogleProvider(api_key="k"),
}


def _batch(n: int):
    """Three tool calls; the first and last return an image (the middle one is text only)."""
    calls = [{"id": f"c{n}-{i}", "name": "screen", "args": {}} for i in range(3)]
    results = [{"tool_use_id": c["id"], "tool_name": "screen", "content": f"r{n}-{i}",
                **({"images": [{**IMG, "data": f"{B64}{n}{i}"}]} if i != 1 else {})}
               for i, c in enumerate(calls)]
    return calls, results


def _image_data(messages) -> list[str]:
    """Every image payload left in the messages, oldest first, in any provider's shape."""
    out = []

    def walk(parts):
        for p in parts:
            if not isinstance(p, dict):
                continue
            if p.get("type") == "image":
                out.append(p["source"]["data"])
            elif p.get("type") == "image_url":
                out.append(p["image_url"]["url"].split(",", 1)[1])
            elif p.get("_type") == "inline_data":
                out.append(p["data"])
            elif isinstance(p.get("content"), list):
                walk(p["content"])
    for m in messages:
        if isinstance(m.get("content"), list):
            walk(m["content"])
    return out


def test_split_images_takes_only_image_payloads():
    assert split_images({"ok": 1, "images": [IMG]}) == ({"ok": 1, "images": IMAGES_NOTE}, [IMG])
    for other in ({"images": ["https://x/a.png"]}, {"images": "a.png"}, {"images": []}, ["x"], "text"):
        assert split_images(other) == (other, None)  # someone else's `images` field is plain data


# ── add_tool_results shapes ──────────────────────────────────────────────────

def test_anthropic_tool_result_holds_text_and_image_blocks():
    calls, results = _batch(0)
    msgs = AnthropicProvider(api_key="k").add_tool_results([], calls, results)
    first, plain = msgs[1]["content"][0], msgs[1]["content"][1]
    assert first["type"] == "tool_result" and first["tool_use_id"] == "c0-0"
    assert first["content"] == [
        {"type": "text", "text": "r0-0"},
        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": f"{B64}00"}},
    ]
    assert plain["content"] == "r0-1"  # results without images are unchanged


@pytest.mark.parametrize("name", ["openai", "ollama", "together"])
def test_openai_style_images_follow_the_tool_messages_in_one_user_message(name):
    calls, results = _batch(0)
    msgs = PROVIDERS[name]().add_tool_results([], calls, results)
    assert [m["role"] for m in msgs] == ["assistant", "tool", "tool", "tool", "user"]
    assert [m["content"] for m in msgs[1:4]] == ["r0-0", "r0-1", "r0-2"]  # tool messages stay text
    parts = msgs[4]["content"]
    assert [p["type"] for p in parts] == ["text", "image_url", "text", "image_url"]
    assert parts[1]["image_url"]["url"] == f"data:image/png;base64,{B64}00"
    assert "screen" in parts[0]["text"] and "not a message from the user" in parts[0]["text"]


@pytest.mark.parametrize("name", ["openai", "google"])
def test_no_images_means_no_extra_parts(name):
    calls, results = _batch(0)
    for r in results:
        r.pop("images", None)
    msgs = PROVIDERS[name]().add_tool_results([], calls, results)
    assert len(msgs) == (4 if name == "openai" else 2) and not _image_data(msgs)


def test_gemini_inline_data_in_the_function_response_turn():
    calls, results = _batch(0)
    msgs = GoogleProvider(api_key="k").add_tool_results([], calls, results)
    assert len(msgs) == 2  # still one model turn + one user turn
    parts = msgs[1]["content"]
    assert [p.get("_type") or p["type"] for p in parts] == [
        "function_response", "function_response", "function_response",
        "text", "inline_data", "text", "inline_data"]
    assert parts[4] == {"_type": "inline_data", "mime_type": "image/png", "data": f"{B64}00"}
    # Recording stand-in for google.generativeai.protos: importing the real SDK here would
    # leave it bound on the `google` package and defeat test_transcription's sys.modules fake.
    protos = SimpleNamespace(**{n: (lambda **k: k) for n in ("Part", "Blob", "FunctionCall", "FunctionResponse")})
    assert _to_parts(parts, protos)[4] == {
        "inline_data": {"mime_type": "image/png", "data": base64.b64decode(f"{B64}00")}}


# ── prune_images ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name", list(PROVIDERS))
def test_prune_keeps_newest_three_and_never_removes_a_message(name):
    p = PROVIDERS[name]()
    msgs = [{"role": "user", "content": "go"}]
    for n in range(2):  # two mixed batches → four images
        calls, results = _batch(n)
        msgs = p.add_tool_results(msgs, calls, results)
    before = copy.deepcopy(msgs)
    pruned = p.prune_images(msgs)
    assert msgs == before  # input untouched
    assert len(pruned) == len(msgs)
    assert [m["role"] for m in pruned] == [m["role"] for m in msgs]
    assert _image_data(pruned) == [f"{B64}02", f"{B64}10", f"{B64}12"]  # oldest one swapped
    assert PRUNED_NOTE in json.dumps(pruned)
    if name == "anthropic":  # every tool_use still has its tool_result
        uses = [b["id"] for m in pruned if m["role"] == "assistant" for b in m["content"]]
        res = [b["tool_use_id"] for m in pruned[1:] if m["role"] == "user" for b in m["content"]]
        assert uses == res
    assert p.prune_images(pruned) == pruned  # idempotent


# ── the loops ────────────────────────────────────────────────────────────────

_SCREEN_TOOL = [{"name": "screen", "kind": "integration", "writes": False,
                 "description": "Screenshot", "input_schema": {"type": "object", "properties": {}}}]


class _ImageProvider(MockAIProvider):
    """Real Anthropic tool-result shapes; records what the model was sent each call."""
    add_tool_results = AnthropicProvider.add_tool_results

    def __init__(self):
        super().__init__()
        self.sent = []
        self.set_responses([
            [{"type": "_turn_complete", "tool_calls": [{"name": "screen", "id": "tu1", "args": {}}],
              "stop_reason": "tool_use", "usage": {}}],
            MockAIProvider._default_response(),
        ])

    async def stream_turn(self, messages, tools, system_prompt):
        self.sent.append(copy.deepcopy(messages))
        async for ev in super().stream_turn(messages, tools, system_prompt):
            yield ev


def _assert_model_saw_image(provider):
    result = provider.sent[1][-1]["content"][0]
    assert result["type"] == "tool_result"
    text, image = result["content"]
    assert text["text"].startswith("<untrusted_tool_result")  # wrapping still applies to the text
    assert IMAGES_NOTE in text["text"] and B64 not in text["text"]
    assert image["source"]["data"] == B64


@pytest.fixture
def env(fake_config, mock_registry, mock_ctx, chat_service, monkeypatch):  # noqa: F811 (imported fixtures)
    mock_registry.execute_tool = AsyncMock(return_value={"ok": True, "images": [IMG]})
    log = []
    monkeypatch.setattr("core.agents.ai_service._log_chat_completion", lambda *a, **k: log.append((a, k)))
    return SimpleNamespace(config=fake_config, registry=mock_registry, ctx=mock_ctx, chats=chat_service, log=log)


def _assert_nothing_stored(env, cid):
    rows = env.chats.get_conversation(cid)["messages"]
    assert B64 not in json.dumps(rows)
    assert IMAGES_NOTE in next(r["tool_results"] for r in rows if r["tool_results"])
    assert env.log and B64 not in repr(env.log)  # activity log


async def test_chat_images_reach_the_model_only(env):
    provider = _ImageProvider()
    cid = env.chats.create_conversation()["id"]
    raw = []

    async def _tee(gen):
        async for line in gen:
            raw.append(line)
            yield line
    events = await collect_events(_tee(chat(
        env.config, provider, env.registry, env.ctx, [{"role": "user", "content": "look"}],
        tool_mode="power", chat_service=env.chats, conversation_id=cid, integration_tool_defs=_SCREEN_TOOL)))

    _assert_model_saw_image(provider)
    end = next(e for e in events if e["type"] == "tool_end")
    assert end["result"] == {"ok": True, "images": IMAGES_NOTE}
    assert B64 not in "".join(raw)  # no SSE event carries the image
    _assert_nothing_stored(env, cid)


async def test_plan_mode_wrapup_still_sees_the_image(env):
    provider = _ImageProvider()
    provider.set_responses([
        [{"type": "_turn_complete", "stop_reason": "tool_use", "usage": {}, "tool_calls": [
            {"name": "screen", "id": "tu1", "args": {}},
            {"name": "exit_plan_mode", "id": "tu2", "args": {"plan": "p"}}]}],
        MockAIProvider._default_response(),
    ])
    await collect_events(chat(
        env.config, provider, env.registry, env.ctx, [{"role": "user", "content": "plan"}],
        tool_mode="power", plan_mode=True, integration_tool_defs=_SCREEN_TOOL))
    _assert_model_saw_image(provider)


async def test_run_sync_images_reach_the_model_only(env):
    provider = _ImageProvider()
    cid = env.chats.create_conversation()["id"]
    await run_sync(env.config, provider, env.registry, env.ctx, [{"role": "user", "content": "look"}],
                   conversation_id=cid, chat_service=env.chats, integration_tool_defs=_SCREEN_TOOL)

    _assert_model_saw_image(provider)
    _assert_nothing_stored(env, cid)


async def test_background_turn_images_reach_the_model_only(env, monkeypatch):
    provider = _ImageProvider()
    monkeypatch.setattr(background_runner, "get_ai_provider", lambda **k: provider)
    monkeypatch.setattr("core.admin_settings.load_admin_settings", lambda: {})
    res = await background_runner._run_turn("sys", "look", _SCREEN_TOOL, env.registry)

    assert not res.error
    _assert_model_saw_image(provider)
    assert B64 not in json.dumps(res.tool_log) and IMAGES_NOTE in res.tool_log[0]["result"]
