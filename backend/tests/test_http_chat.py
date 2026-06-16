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

    # Patch at the source (tool_loader) so the stub flows through both the direct
    # load_integration_tools() callers and the load_all_dynamic_tools() wrapper.
    monkeypatch.setattr(
        "agents.tool_loader.load_integration_tools",
        lambda: ([SEND_EMAIL_DEF, LOOKUP_DEF], {"send_email": stub, "lookup_thing": stub}),
    )
    return calls


def chat(chat_client, agent, **extra):
    payload = {"messages": [{"role": "user", "content": "hello quixotic unicorn"}], **extra}
    return chat_client.post(f"/api/agents/{agent['id']}/chat", json=payload)


def _install_printed(slug="demo", mode="normal", method="POST"):
    """Create a synthetic printed-CLI install (no binary) in the isolated store."""
    from integrations.printing_press import store
    store.save_install(store.Install(
        slug=slug, category="x", ref="main", sha="a" * 40, api_name="Demo",
        tool_count=1, build_status=store.BUILD_READY, tool_mode=mode))
    store.save_manifest(slug, {"api_name": "Demo", "tools": [{
        "name": "things_create", "description": "Create a thing", "method": method,
        "params": [{"name": "name", "type": "string", "location": "body", "required": True}],
    }]})
    return f"{slug}__things_create"


def test_printed_write_tool_confirms(chat_client, mock_provider):
    tool = _install_printed(mode="normal")
    agent = make_agent(chat_client)
    mock_provider.set_responses([
        [
            {"type": "tool_start", "tool": tool, "tool_use_id": "tu1"},
            {"type": "_turn_complete", "tool_calls": [
                {"name": tool, "id": "tu1", "args": {"name": "widget"}},
            ], "stop_reason": "tool_use", "usage": {}},
        ],
        MockAIProvider._default_response(),
    ])
    events = parse_sse(chat(chat_client, agent, tool_mode="normal"))
    types = [e["type"] for e in events]
    assert "confirm" in types                                  # printed write → confirm
    assert next(e for e in events if e["type"] == "confirm")["tool"] == tool
    assert "tool_end" not in types                             # not executed before approval


def test_printed_write_readonly_rejected_by_tool_execute(chat_client):
    tool = _install_printed(mode="read-only")
    agent = make_agent(chat_client)
    resp = chat_client.post(
        f"/api/agents/{agent['id']}/tool/execute", json={"tool": tool, "args": {"name": "x"}}
    )
    assert resp.status_code == 403


def _install_bridge_cli(monkeypatch, name, method, mode="normal"):
    """Install a printed CLI and force the bridge on (cli_call is the surface)."""
    from integrations.printing_press import bridge, store
    monkeypatch.setattr(bridge, "PRINTED_TOOL_TOKEN_BUDGET", 1)
    store.save_install(store.Install(
        slug="crm", category="x", ref="main", sha="a" * 40, api_name="CRM",
        tool_count=1, build_status=store.BUILD_READY, tool_mode=mode))
    store.save_manifest("crm", {"api_name": "CRM", "tools": [{
        "name": name, "description": "A CRM command", "method": method,
        "params": [{"name": "name", "type": "string", "location": "body", "required": True}],
    }]})
    return f"crm__{name}"


def _cli_call_turn(mock_provider, command, arguments):
    mock_provider.set_responses([
        [
            {"type": "tool_start", "tool": "cli_call", "tool_use_id": "tu1"},
            {"type": "_turn_complete", "tool_calls": [
                {"name": "cli_call", "id": "tu1", "args": {"command": command, "arguments": arguments}},
            ], "stop_reason": "tool_use", "usage": {}},
        ],
        MockAIProvider._default_response(),
    ])


def test_cli_call_write_confirms(chat_client, mock_provider, monkeypatch):
    cmd = _install_bridge_cli(monkeypatch, "contacts_create", "POST")
    agent = make_agent(chat_client)
    _cli_call_turn(mock_provider, cmd, {"name": "Bob"})
    events = parse_sse(chat(chat_client, agent, tool_mode="normal"))
    types = [e["type"] for e in events]
    # cli_call is statically writes=False but resolves to a POST → must confirm.
    assert "confirm" in types
    assert next(e for e in events if e["type"] == "confirm")["tool"] == "cli_call"
    assert "tool_end" not in types


def test_cli_call_read_does_not_confirm(chat_client, mock_provider, monkeypatch):
    cmd = _install_bridge_cli(monkeypatch, "contacts_list", "GET")
    agent = make_agent(chat_client)
    _cli_call_turn(mock_provider, cmd, {})
    events = parse_sse(chat(chat_client, agent, tool_mode="normal"))
    types = [e["type"] for e in events]
    assert "confirm" not in types        # a read needs no approval
    assert "tool_end" in types           # it executed (binary missing → error result, but ran)


def test_cli_call_write_via_tool_execute_readonly_403(chat_client, monkeypatch):
    # cli_call is statically writes=False, but /tool/execute resolves it and must
    # reject a resolved write on a read-only CLI even post-confirm.
    cmd = _install_bridge_cli(monkeypatch, "contacts_create", "POST", mode="read-only")
    agent = make_agent(chat_client)
    resp = chat_client.post(
        f"/api/agents/{agent['id']}/tool/execute",
        json={"tool": "cli_call", "args": {"command": cmd, "arguments": {"name": "x"}}},
    )
    assert resp.status_code == 403


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
    # (Block shapes are the mock's Anthropic-style add_tool_results format —
    # per-provider wire shapes are each provider's own responsibility.)
    recording = RecordingProvider()
    monkeypatch.setattr("agents.router.get_ai_provider", lambda **kw: recording)

    agent = make_agent(client)
    # The frontend sends the approval turn as a "[Approved] <tool>" user
    # message; the engine must strip it and substitute the tool blocks.
    resp = client.post(f"/api/agents/{agent['id']}/chat", json={
        "messages": [
            {"role": "user", "content": "send the email"},
            {"role": "user", "content": "[Approved] send_email"},
        ],
        "tool_mode": "normal",
        "approved_tool": {
            "tool": "send_email",
            "args": {"to": "a@b.com"},
            "toolUseId": "tu1",
            "result": {"ok": True},
        },
    })
    events = parse_sse(resp)
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
    # The placeholder must not leak into provider history.
    assert not [m for m in sent
                if isinstance(m.get("content"), str) and m["content"].startswith("[Approved]")]


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
