"""SSE parsing, the event -> display mapping, and the token / retry rules."""

import asyncio

import httpx
import pytest
from chatty_cli import repl
from chatty_cli.api import ApiError, Revoked, parse_sse
from chatty_cli.render import Renderer
from conftest import answer, make_session, sse


def test_parse_sse():
    assert parse_sse('data: {"type": "text", "text": "hi"}') == {"type": "text", "text": "hi"}
    assert parse_sse("") is None
    assert parse_sse(": comment") is None
    assert parse_sse("data: not json") is None


def test_render_maps_events(fake, capsys):
    s = make_session(fake)
    r = Renderer(s)
    for e in [{"type": "conversation_id", "id": "c1"}, {"type": "text", "text": "Hello "}, {"type": "text", "text": "there"},
              {"type": "tool_start", "tool": "web_search", "tool_use_id": "t1"},
              {"type": "tool_args", "tool": "web_search", "tool_use_id": "t1", "args": {"q": "x"}},
              {"type": "tool_end", "tool": "web_search", "tool_use_id": "t1", "result": {"ok": True}, "elapsed_ms": 1234},
              {"type": "tool_end", "tool": "gmail_send", "tool_use_id": "t2", "result": {"error": "nope"}, "elapsed_ms": 5},
              {"type": "usage", "input_tokens": 1000, "output_tokens": 20},
              {"type": "title_update", "title": "Greetings", "conversation_id": "c1"},
              {"type": "plan_ready", "plan_text": "x", "status": "ok"},
              {"type": "done", "model": "claude-x"}]:
        r.handle(e)
    r.finish()
    out = capsys.readouterr().out
    assert s.conversation_id == "c1"
    assert "Hello there\n" in out
    assert "▸ web_search ✓ 1.2s" in out
    assert "▸ gmail_send ✗ 5ms" in out
    assert '"q"' not in out  # arguments only with /verbose
    assert "title: Greetings" in out
    assert "claude-x · 1,000 in / 20 out" in out
    assert r.error is None


def test_error_ends_the_turn_without_done(fake, capsys):
    fake.streams.append([{"type": "conversation_id", "id": "c1"}, {"type": "text", "text": "partial"},
                         {"type": "error", "error": "Write budget exceeded. Turn terminated."}])
    s = make_session(fake)
    asyncio.run(repl.send(s, "hi"))
    out = capsys.readouterr().out
    assert "Error: Write budget exceeded" in out
    assert "ended before it finished" not in out  # error is a proper ending
    assert s.conversation_id == "c1"


def test_stream_that_stops_without_done_or_error_says_so(fake, capsys):
    fake.streams.append([{"type": "text", "text": "partial"}])
    asyncio.run(repl.send(make_session(fake), "hi"))
    assert "ended before it finished" in capsys.readouterr().out


def test_verbose_shows_args_and_result(fake, capsys):
    r = Renderer(make_session(fake, verbose=True))
    r.handle({"type": "tool_args", "tool": "web_search", "tool_use_id": "t1", "args": {"q": "cheesecake"}})
    r.handle({"type": "tool_end", "tool": "web_search", "tool_use_id": "t1", "result": {"hits": 3}, "elapsed_ms": 10})
    out = capsys.readouterr().out
    assert '"q": "cheesecake"' in out and '"hits": 3' in out


def test_401_status_reswaps_once_and_retries(fake):
    fake.stale = {"jwt-1"}  # e.g. a redeploy rotated JWT_SECRET
    s = make_session(fake)
    assert asyncio.run(s.api.agents())[0]["slug"] == "tom"
    assert fake.swaps == 2
    assert [p for _, p, _ in fake.requests].count("/api/agents") == 2


def test_401_twice_is_an_error_not_a_loop(fake):
    fake.reject_all = True
    s = make_session(fake)
    with pytest.raises(ApiError, match="401"):
        asyncio.run(s.api.agents())
    assert fake.swaps == 2
    assert [p for _, p, _ in fake.requests].count("/api/agents") == 2


def test_token_401_means_revoked(fake):
    fake.revoked = True
    with pytest.raises(Revoked, match="chatty login"):
        asyncio.run(make_session(fake).api.agents())


def test_mid_stream_transport_error_is_not_retried(fake, capsys):
    async def broken():
        yield sse({"type": "conversation_id", "id": "c1"}, {"type": "text", "text": "par"})
        raise httpx.ReadError("connection reset")

    fake.streams.append(broken())
    s = make_session(fake)
    asyncio.run(repl.send(s, "hi"))
    assert len(fake.chats()) == 1 and fake.swaps == 1
    assert "Connection lost (connection reset). Not retried." in capsys.readouterr().out
    assert s.conversation_id == "c1"


def test_execute_transport_error_is_not_retried_or_followed_up(fake, monkeypatch, capsys):
    fake.streams.append([{"type": "confirm", "tool": "gmail_send", "args": {}, "tool_use_id": "t1", "msg_id": 1},
                         {"type": "done", "model": "m"}])
    fake.execute = httpx.ReadError("reset")
    monkeypatch.setattr(repl, "ask", answer("y"))
    asyncio.run(repl.send(make_session(fake), "send it"))
    assert [p for _, p, _ in fake.requests].count("/api/agents/a-uuid-1/tool/execute") == 1
    assert len(fake.chats()) == 1
    assert "Not retried" in capsys.readouterr().out
