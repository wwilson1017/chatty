"""HTTP tests: chat SSE streaming, confirm flow, tool execute, conversations."""

import pytest

from tests.conftest import parse_sse
from tests.test_ai_service import MockAIProvider
from tests.test_http_agents import make_agent

SEND_EMAIL_DEF = {
    "name": "send_email",
    "kind": "integration",
    "writes": True,
    "input_schema": {"type": "object", "properties": {}},
    "description": "Send an email",
}

LOOKUP_DEF = {
    "name": "lookup_thing",
    "kind": "integration",
    "writes": False,
    "input_schema": {"type": "object", "properties": {}},
    "description": "Look something up",
}


class RecordingProvider(MockAIProvider):
    """MockAIProvider that records the messages sent to each stream_turn call."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.seen_messages = []

    async def stream_turn(self, messages, tools, system_prompt):
        self.seen_messages.append(messages)
        async for event in super().stream_turn(messages, tools, system_prompt):
            yield event


@pytest.fixture
def mock_provider():
    return MockAIProvider()


@pytest.fixture
def chat_client(client, mock_provider, monkeypatch):
    monkeypatch.setattr("agents.router.get_ai_provider", lambda **kw: mock_provider)
    return client


@pytest.fixture
def email_tool(monkeypatch):
    """Expose a stub write tool through the integration loader."""
    calls = []

    def stub(**kwargs):
        calls.append(kwargs)
        return {"ok": True}

    monkeypatch.setattr(
        "agents.router.load_integration_tools",
        lambda: ([SEND_EMAIL_DEF, LOOKUP_DEF], {"send_email": stub, "lookup_thing": stub}),
    )
    return calls


def chat(chat_client, agent, **extra):
    payload = {"messages": [{"role": "user", "content": "hello quixotic unicorn"}], **extra}
    return chat_client.post(f"/api/agents/{agent['id']}/chat", json=payload)


def test_chat_text_turn_event_order(chat_client):
    agent = make_agent(chat_client)
    resp = chat(chat_client, agent)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")

    events = parse_sse(resp)
    types = [e["type"] for e in events]
    assert types[0] == "conversation_id"
    assert "text" in types
    text = "".join(e["text"] for e in events if e["type"] == "text")
    assert text == "Hello from mock"
    assert types[-1] == "done"
    assert events[-1]["model"] == "mock-model"


def test_chat_persists_conversation_and_fts_search(chat_client):
    agent = make_agent(chat_client)
    events = parse_sse(chat(chat_client, agent))
    conv_id = events[0]["id"]

    listed = chat_client.get(f"/api/agents/{agent['id']}/conversations").json()
    assert [c["id"] for c in listed["conversations"]] == [conv_id]

    found = chat_client.get(
        f"/api/agents/{agent['id']}/conversations/search", params={"q": "quixotic"}
    ).json()["results"]
    assert any(r["id"] == conv_id for r in found)


def test_chat_unknown_agent_404(chat_client):
    resp = chat_client.post(
        "/api/agents/nope/chat", json={"messages": [{"role": "user", "content": "hi"}]}
    )
    assert resp.status_code == 404


def test_chat_write_tool_confirm_flow(chat_client, mock_provider, email_tool):
    agent = make_agent(chat_client)
    mock_provider.set_responses([
        [
            {"type": "tool_start", "tool": "send_email", "tool_use_id": "tu1"},
            {"type": "_turn_complete", "tool_calls": [
                {"name": "send_email", "id": "tu1",
                 "args": {"to": "a@b.com", "subject": "hi", "body": "test"}},
            ], "stop_reason": "tool_use", "usage": {}},
        ],
        MockAIProvider._default_response(),
    ])

    events = parse_sse(chat(chat_client, agent, tool_mode="normal"))
    types = [e["type"] for e in events]
    assert "confirm" in types
    confirm = next(e for e in events if e["type"] == "confirm")
    assert confirm["tool"] == "send_email"
    assert confirm["tool_use_id"] == "tu1"
    assert confirm["args"] == {"to": "a@b.com", "subject": "hi", "body": "test"}
    assert confirm["description"] == "Send an email"
    # The frontend spinner keys off tool_start arriving before the confirm.
    assert types.index("tool_start") < types.index("confirm")
    # Confirmation means no execution: no tool_end, stub untouched.
    assert "tool_end" not in types
    assert email_tool == []
    assert types[-1] == "done"


def test_chat_approved_tool_resume(client, email_tool, monkeypatch):
    # Record what reaches the provider: the engine must reconstruct the
    # approved tool as tool_use/tool_result blocks, not silently drop it.
    recording = RecordingProvider()
    monkeypatch.setattr("agents.router.get_ai_provider", lambda **kw: recording)

    agent = make_agent(client)
    events = parse_sse(chat(
        client, agent,
        tool_mode="normal",
        approved_tool={
            "tool": "send_email",
            "args": {"to": "a@b.com"},
            "toolUseId": "tu1",
            "result": {"ok": True},
        },
    ))
    types = [e["type"] for e in events]
    assert "confirm" not in types
    assert "text" in types
    assert types[-1] == "done"

    sent = recording.seen_messages[0]
    tool_uses = [b for m in sent if isinstance(m.get("content"), list)
                 for b in m["content"] if b.get("type") == "tool_use"]
    tool_results = [b for m in sent if isinstance(m.get("content"), list)
                    for b in m["content"] if b.get("type") == "tool_result"]
    assert any(b["name"] == "send_email" and b["id"] == "tu1" for b in tool_uses)
    assert any(b["tool_use_id"] == "tu1" and '"ok": true' in b["content"] for b in tool_results)


def test_tool_execute_approved_write(chat_client, email_tool):
    agent = make_agent(chat_client)
    resp = chat_client.post(
        f"/api/agents/{agent['id']}/tool/execute",
        json={"tool": "send_email", "args": {"to": "a@b.com"}},
    )
    assert resp.status_code == 200
    assert email_tool == [{"to": "a@b.com"}]


def test_tool_execute_rejects_non_write(chat_client, email_tool):
    agent = make_agent(chat_client)
    resp = chat_client.post(
        f"/api/agents/{agent['id']}/tool/execute",
        json={"tool": "lookup_thing", "args": {}},
    )
    assert resp.status_code == 400
