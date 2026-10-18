"""The active-turn rules (Ctrl+C mutes, every submit waits), conversation threading, approvals and commands."""

import argparse
import asyncio
import json

from chatty_cli import commands, repl
from chatty_cli.main import open_session
from conftest import answer, gated, make_session, until

CONFIRM = {"type": "confirm", "tool": "gmail_send", "args": {"to": "bob@example.com"}, "tool_use_id": "tu-1",
           "msg_id": 42, "description": "Send an email"}


def test_conversation_id_threads_through_messages_and_approvals(fake, monkeypatch):
    fake.streams += [
        [{"type": "conversation_id", "id": "c1"}, {"type": "text", "text": "hi"}, {"type": "done", "model": "m"}],
        [{"type": "conversation_id", "id": "c1"}, CONFIRM, {"type": "done", "model": "m"}],
        [{"type": "text", "text": "Sent."}, {"type": "done", "model": "m"}],
    ]
    monkeypatch.setattr(repl, "ask", answer("y"))
    s = make_session(fake)

    async def go():
        await repl.submit(s, "hello")
        await repl.submit(s, "email bob")

    asyncio.run(go())
    first, second, follow_up = fake.chats()
    assert first["conversation_id"] is None
    assert second["conversation_id"] == "c1" and follow_up["conversation_id"] == "c1"
    assert second["messages"] == [{"role": "user", "content": "email bob"}]  # only the new message


def test_approval_round_trip_uses_camelcase(fake, monkeypatch):
    fake.streams += [[{"type": "conversation_id", "id": "c1"}, CONFIRM, {"type": "done", "model": "m"}],
                     [{"type": "done", "model": "m"}]]
    fake.execute = (200, {"ok": True, "message_id": "m-9"})
    monkeypatch.setattr(repl, "ask", answer("y"))
    asyncio.run(repl.submit(make_session(fake), "email bob"))
    execute = next(b for _, p, b in fake.requests if p.endswith("/tool/execute"))
    assert execute == {"tool": "gmail_send", "args": {"to": "bob@example.com"}}
    follow_up = fake.chats()[1]
    assert follow_up["messages"] == [{"role": "user", "content": "[Approved] gmail_send"}]
    assert follow_up["approved_tool"] == {"tool": "gmail_send", "args": {"to": "bob@example.com"},
                                          "toolUseId": "tu-1", "msgId": 42, "result": {"ok": True, "message_id": "m-9"}}


def test_refused_execute_reports_action_failed(fake, monkeypatch):
    fake.streams += [[CONFIRM, {"type": "done", "model": "m"}], [{"type": "done", "model": "m"}]]
    fake.execute = (403, {"detail": "Write operations are disabled for gmail (set to read-only)"})
    monkeypatch.setattr(repl, "ask", answer("y"))
    asyncio.run(repl.submit(make_session(fake), "email bob"))
    follow_up = fake.chats()[1]
    err = "HTTP 403: Write operations are disabled for gmail (set to read-only)"
    assert follow_up["messages"][0]["content"] == f"[Action failed] gmail_send: {err}"
    assert follow_up["approved_tool"]["result"] == {"error": err}


def test_deny_sends_nothing(fake, monkeypatch):
    fake.streams.append([CONFIRM, {"type": "done", "model": "m"}])
    monkeypatch.setattr(repl, "ask", answer(""))
    asyncio.run(repl.submit(make_session(fake), "email bob"))
    assert len(fake.chats()) == 1
    assert not any(p.endswith("/tool/execute") for _, p, _ in fake.requests)


def test_interrupted_turn_then_send_waits_and_keeps_its_conversation(fake, capsys):
    async def go():
        gate = asyncio.Event()
        fake.streams += [gated([{"type": "conversation_id", "id": "c1"}, {"type": "text", "text": "Hel"}], gate,
                               [{"type": "text", "text": "lo there"}, {"type": "done", "model": "m"}]),
                         [{"type": "text", "text": "again"}, {"type": "done", "model": "m"}]]
        s = make_session(fake)
        first = asyncio.create_task(repl.submit(s, "hi"))
        await until(lambda: s.conversation_id == "c1")
        s.on_sigint()  # Ctrl+C mid-reply
        assert await first is True  # the prompt is back...
        assert not s.turn.done()  # ...while the turn keeps draining
        second = asyncio.create_task(repl.submit(s, "next"))
        await asyncio.sleep(0.05)
        assert not second.done() and len(fake.chats()) == 1  # waiting for the previous reply
        gate.set()
        await second

    asyncio.run(go())
    assert fake.chats()[1]["conversation_id"] == "c1"
    out = capsys.readouterr().out
    assert "finishing the previous reply" in out
    assert "lo there" not in out  # muted: drained, not shown
    assert "again" in out


def test_muted_turn_state_still_processed_and_its_confirm_not_run(fake, capsys):
    async def go():
        gate = asyncio.Event()
        fake.streams.append(gated([{"type": "text", "text": "Let me"}], gate,
                                  [{"type": "conversation_id", "id": "c9"}, CONFIRM, {"type": "done", "model": "m"}]))
        s = make_session(fake)
        await asyncio.wait_for(asyncio.gather(_interrupt_soon(s), repl.submit(s, "email bob")), 2)
        gate.set()
        await until(s.turn.done)
        await repl.submit(s, "/new")  # any command settles the turn first
        return s

    s = asyncio.run(go())
    assert s.conversation_id is None  # /new ran after the muted turn set c9
    assert not any(p.endswith("/tool/execute") for _, p, _ in fake.requests)
    assert "wanted to run gmail_send. Not run." in capsys.readouterr().out


def test_second_ctrl_c_abandons_the_turn(fake, capsys):
    async def go():
        fake.streams += [gated([{"type": "conversation_id", "id": "c1"}], asyncio.Event(), []),
                         [{"type": "done", "model": "m"}]]
        s = make_session(fake)
        await asyncio.wait_for(asyncio.gather(_interrupt_soon(s), repl.submit(s, "hi")), 2)
        turn = s.turn
        second = asyncio.create_task(repl.submit(s, "next"))
        await until(lambda: s.on_sigint is not None)
        s.on_sigint()  # second Ctrl+C, during "finishing the previous reply…"
        await second
        return turn

    turn = asyncio.run(go())
    assert turn.cancelled()
    assert len(fake.chats()) == 2  # the new message still went out
    assert "Abandoned it" in capsys.readouterr().out


def test_quit_waits_for_the_turn(fake):
    async def go():
        gate = asyncio.Event()
        fake.streams.append(gated([], gate, [{"type": "done", "model": "m"}]))
        s = make_session(fake)
        await asyncio.wait_for(asyncio.gather(_interrupt_soon(s), repl.submit(s, "hi")), 2)
        quit_ = asyncio.create_task(repl.submit(s, "/quit"))
        await asyncio.sleep(0.05)
        assert not quit_.done()
        gate.set()
        assert await quit_ is False

    asyncio.run(go())


async def _interrupt_soon(s):
    await until(lambda: s.on_sigint is not None)
    s.on_sigint()


def test_attach_goes_through_upload(fake, tmp_path):
    (tmp_path / "notes.md").write_text("# notes")
    (tmp_path / "virus.exe").write_bytes(b"MZ")
    fake.streams.append([{"type": "done", "model": "m"}])
    s = make_session(fake)

    async def go():
        await repl.submit(s, f"/attach {tmp_path / 'notes.md'} {tmp_path / 'virus.exe'}")
        assert [p.name for p in s.staged] == ["notes.md"]
        assert "📎1" in repl.prompt_text(s)
        await repl.submit(s, "summarize")

    asyncio.run(go())
    method, path, body = fake.requests[-1]
    assert path == "/api/agents/a-uuid-1/chat/upload"
    assert b'filename="notes.md"' in body and b"# notes" in body
    assert b'"content": "summarize"' in body
    assert s.staged == []


def test_mode_is_remembered_and_shown(fake, isolated_config):
    s = make_session(fake)
    asyncio.run(repl.submit(s, "/mode power"))
    assert json.loads(isolated_config.read_text())["mode"] == "power"
    assert repl.prompt_text(s) == "[Tom ⚡] > "
    fake.streams.append([{"type": "done", "model": "m"}])
    asyncio.run(repl.submit(s, "hi"))
    assert fake.chats()[0]["tool_mode"] == "power"


CONVS = [  # what the server returns: pinned first
    {"id": "pinned-old", "title": "Pinned", "pinned": 1, "updated_at": "2026-01-02 08:00:00", "message_count": 4},
    {"id": "middle", "title": "Middle", "pinned": 0, "updated_at": "2026-10-16 09:00:00", "message_count": 2},
    {"id": "latest", "title": "Latest", "pinned": 0, "updated_at": "2026-10-17 21:30:00", "message_count": 6},
]


def test_continue_opens_the_most_recently_updated(fake, capsys):
    fake.conversations = CONVS
    fake.messages = [{"role": "user", "content": "what's on today?", "seq": 1, "tool_calls": "[]"},
                     {"role": "assistant", "content": "", "seq": 2, "tool_calls": "[{}]"},
                     {"role": "assistant", "content": "Two deliveries.", "seq": 3, "tool_calls": "[]"}]
    s = make_session(fake)
    args = argparse.Namespace(agent=None, cont=True)
    session = asyncio.run(open_session(s.api, args, s.cfg))
    assert session.conversation_id == "latest"
    out = capsys.readouterr().out
    assert "you: what's on today?" in out and "Tom: Two deliveries." in out


def test_resume_lists_by_updated_at_not_pinned(fake, monkeypatch, capsys):
    fake.conversations = CONVS
    monkeypatch.setattr(commands, "ask", answer("2"))
    s = make_session(fake)
    asyncio.run(repl.submit(s, "/resume"))
    out = capsys.readouterr().out
    assert out.index("Latest") < out.index("Middle") < out.index("Pinned")
    assert s.conversation_id == "middle"


def test_agent_is_remembered(fake, isolated_config, monkeypatch):
    fake.agents = [dict(fake.agents[0]), {"id": "a-uuid-2", "slug": "jordan", "agent_name": "Jordan"}]
    monkeypatch.setattr(commands, "ask", answer("2"))
    s = make_session(fake)
    s.cfg["last_agent_id"] = None
    session = asyncio.run(open_session(s.api, argparse.Namespace(agent=None, cont=False), s.cfg))
    assert session.agent["slug"] == "jordan"
    assert json.loads(isolated_config.read_text())["last_agent_id"] == "a-uuid-2"
    again = asyncio.run(open_session(s.api, argparse.Namespace(agent=None, cont=False), session.cfg))
    assert again.agent["slug"] == "jordan"  # no second question (answer() would raise StopIteration)
