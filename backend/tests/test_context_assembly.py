"""Tests for the server-side conversation assembler and provider tool-turn
reconstruction (context_assembly.assemble_messages + AIProvider.build_tool_turn).

These cover the persistence epic's core: rebuilding the provider `messages`
array from chat_history.db rows — faithful per-iteration reconstruction, the
NULL-tool_results preview fallback, pairing/stub integrity, malformed-row
degradation, the delimiter-safe oversized-row guard, and compaction-boundary
folding.
"""

import json

from core.agents.context_assembly import (
    assemble_messages, _truncate_wrapped, _gist_marker, HEAD_MSGS,
)
from core.providers.base import AIProvider


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------

class _AnthropicShapeProvider(AIProvider):
    """Minimal provider with Anthropic-native tool shaping and a configurable
    context window. Inherits build_tool_turn + _inject_assistant_text from the
    base, so it exercises the real reconstruction path."""

    def __init__(self, window=200_000):
        super().__init__(model="fake")
        self._window = window

    @property
    def context_window(self):
        return self._window

    @property
    def provider_name(self):
        return "fake"

    async def list_models(self):
        return ["fake"]

    async def validate(self):
        return True

    async def stream_turn(self, messages, tools, system_prompt):
        yield {}

    def add_tool_results(self, messages, tool_calls, results):
        messages = list(messages)
        messages.append({"role": "assistant", "content": [
            {"type": "tool_use", "id": tc["id"], "name": tc["name"], "input": tc.get("args", {})}
            for tc in tool_calls
        ]})
        messages.append({"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": r["tool_use_id"], "content": r["content"]}
            for r in results
        ]})
        return messages


class _FakeChatService:
    """Returns a canned conversation for the assembler to rebuild."""

    def __init__(self, rows, **conv_extra):
        self._conv = {"id": "c1", "messages": rows, **conv_extra}

    def get_conversation(self, conv_id):
        return self._conv if conv_id == "c1" else None


def _row(seq, role, content="", tool_calls=None, tool_results=None):
    return {
        "id": f"m{seq}", "conversation_id": "c1", "seq": seq, "role": role,
        "content": content,
        "tool_calls": json.dumps(tool_calls) if tool_calls is not None else None,
        "tool_results": json.dumps(tool_results) if tool_results is not None else None,
    }


def _assemble(rows, provider=None, **conv_extra):
    provider = provider or _AnthropicShapeProvider()
    return assemble_messages(_FakeChatService(rows, **conv_extra), provider, "c1")


# ---------------------------------------------------------------------------
# Plain turns
# ---------------------------------------------------------------------------

class TestPlainTurns:
    def test_user_and_assistant_text(self):
        rows = [_row(0, "user", "hi"), _row(1, "assistant", "hello")]
        msgs = _assemble(rows)
        assert msgs == [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]

    def test_empty_conversation_returns_empty(self):
        assert _assemble([]) == []

    def test_missing_conversation_returns_empty(self):
        prov = _AnthropicShapeProvider()
        assert assemble_messages(_FakeChatService([]), prov, "nope") == []

    def test_empty_assistant_row_skipped(self):
        # An assistant row with neither text nor tool calls produces no message.
        rows = [_row(0, "user", "hi"), _row(1, "assistant", "")]
        assert _assemble(rows) == [{"role": "user", "content": "hi"}]


# ---------------------------------------------------------------------------
# Tool-turn reconstruction
# ---------------------------------------------------------------------------

class TestToolReconstruction:
    def test_tool_iteration_reconstructs_natively(self):
        rows = [
            _row(0, "user", "fetch it"),
            _row(1, "assistant", "On it.",
                 tool_calls=[{"tool": "web_fetch", "tool_use_id": "tu1", "args": {"url": "u"}}],
                 tool_results=[{"tool_use_id": "tu1", "tool_name": "web_fetch", "content": "ARTICLE BODY"}]),
        ]
        msgs = _assemble(rows)
        # user, assistant[text+tool_use], user[tool_result]
        assert msgs[0] == {"role": "user", "content": "fetch it"}
        assert msgs[1]["role"] == "assistant"
        assert any(b.get("type") == "text" and b["text"] == "On it." for b in msgs[1]["content"])
        tu = next(b for b in msgs[1]["content"] if b.get("type") == "tool_use")
        assert tu["id"] == "tu1" and tu["name"] == "web_fetch"
        assert msgs[2]["role"] == "user"
        assert msgs[2]["content"][0]["content"] == "ARTICLE BODY"

    def test_full_tool_result_carried_across_a_following_turn(self):
        # The whole point of the epic: the article fetched on turn 1 is present
        # verbatim when assembling for turn 2 (not a 2000-char preview).
        big = "X" * 9000
        rows = [
            _row(0, "user", "fetch"),
            _row(1, "assistant", "",
                 tool_calls=[{"tool": "web_fetch", "tool_use_id": "tu1", "args": {}}],
                 tool_results=[{"tool_use_id": "tu1", "tool_name": "web_fetch", "content": big}]),
            _row(2, "assistant", "Here's the summary."),
            _row(3, "user", "now compare it to X"),
        ]
        msgs = _assemble(rows)
        tool_result = msgs[2]["content"][0]["content"]
        assert tool_result == big  # full, uncapped

    def test_null_tool_results_falls_back_to_preview(self):
        # Old/pre-persistence rows stored only a per-call result preview.
        rows = [
            _row(0, "user", "go"),
            _row(1, "assistant", "",
                 tool_calls=[{"tool": "x", "tool_use_id": "tu1", "args": {}, "result": "PREVIEW"}],
                 tool_results=None),
        ]
        msgs = _assemble(rows)
        assert msgs[1]["content"][0]["type"] == "tool_use"
        assert msgs[2]["content"][0]["content"] == "PREVIEW"

    def test_missing_result_is_stubbed(self):
        # Interrupted final: tool_use saved, no result preview, no tool_results.
        rows = [
            _row(0, "user", "go"),
            _row(1, "assistant", "", tool_calls=[{"tool": "x", "tool_use_id": "tu1", "args": {}}]),
        ]
        msgs = _assemble(rows)
        stub = msgs[2]["content"][0]["content"]
        assert "not recorded" in stub

    def test_parallel_tool_calls_each_missing_result_is_stubbed(self):
        # An iteration with two parallel tool calls and no results — BOTH must be
        # stubbed, or the provider sees an orphaned tool_use and rejects the turn.
        rows = [
            _row(0, "user", "go"),
            _row(1, "assistant", "",
                 tool_calls=[{"tool": "a", "tool_use_id": "t1", "args": {}},
                             {"tool": "b", "tool_use_id": "t2", "args": {}}]),
        ]
        msgs = _assemble(rows)
        results = msgs[2]["content"]
        assert [b["tool_use_id"] for b in results] == ["t1", "t2"]
        assert all("not recorded" in b["content"] for b in results)

    def test_malformed_tool_json_degrades_to_text(self):
        rows = [
            _row(0, "user", "go"),
            {"id": "m1", "conversation_id": "c1", "seq": 1, "role": "assistant",
             "content": "partial text", "tool_calls": "{not json", "tool_results": None},
        ]
        msgs = _assemble(rows)
        assert msgs[1] == {"role": "assistant", "content": "partial text"}

    def test_malformed_tool_results_degrades_to_text(self):
        # tool_calls parses but tool_results is corrupt — must degrade to plain
        # text (no orphaned tool_use that the provider would reject next turn).
        rows = [
            _row(0, "user", "go"),
            {"id": "m1", "conversation_id": "c1", "seq": 1, "role": "assistant",
             "content": "did a thing",
             "tool_calls": json.dumps([{"tool": "x", "tool_use_id": "t1", "args": {}}]),
             "tool_results": "{bad json"},
        ]
        msgs = _assemble(rows)
        assert msgs[1] == {"role": "assistant", "content": "did a thing"}
        assert not any(
            isinstance(m.get("content"), list)
            and any(b.get("type") == "tool_use" for b in m["content"])
            for m in msgs
        )

    def test_openai_provider_reconstructs_native_shape(self):
        # Provider-neutrality: continued under OpenAI, the same row reconstructs
        # as assistant.tool_calls + role:"tool" (no Anthropic blocks).
        from core.providers.openai_provider import OpenAIProvider
        p = OpenAIProvider.__new__(OpenAIProvider)
        p.model = "gpt-x"
        msgs = p.build_tool_turn(
            "narration",
            [{"tool": "web_fetch", "tool_use_id": "tu1", "args": {"url": "u"}}],
            [{"tool_use_id": "tu1", "tool_name": "web_fetch", "content": "BODY"}],
        )
        assert msgs[0]["role"] == "assistant"
        assert msgs[0]["content"] == "narration"        # text re-injected
        assert msgs[0]["tool_calls"][0]["id"] == "tu1"
        assert msgs[1]["role"] == "tool" and msgs[1]["tool_call_id"] == "tu1"


# ---------------------------------------------------------------------------
# Oversized-row guard (live context bounded; storage stays full)
# ---------------------------------------------------------------------------

class TestAlternation:
    def test_consecutive_user_rows_coalesced(self):
        # Telegram busy-skip saves several user rows with no assistant between.
        rows = [
            _row(0, "user", "first"),
            _row(1, "user", "second"),
            _row(2, "user", "third"),
            _row(3, "assistant", "reply"),
        ]
        msgs = _assemble(rows)
        assert [m["role"] for m in msgs] == ["user", "assistant"]
        assert msgs[0]["content"] == "first\n\nsecond\n\nthird"

    def test_no_consecutive_users_when_gist_follows_tool_result_head(self):
        # HEAD's 2nd row is a tool call → for Anthropic it ends in a user
        # tool_result; the folded gist must not produce two user turns in a row.
        rows = [
            _row(0, "user", "start"),
            _row(1, "assistant", "",
                 tool_calls=[{"tool": "x", "tool_use_id": "t1", "args": {}}],
                 tool_results=[{"tool_use_id": "t1", "tool_name": "x", "content": "R"}]),
            _row(2, "user", "m"), _row(3, "assistant", "m"),
            _row(4, "user", "recent"), _row(5, "assistant", "recent reply"),
        ]
        msgs = _assemble(rows, compaction_summary="GIST", compaction_first_kept_seq=4)
        roles = [m["role"] for m in msgs]
        assert all(roles[i] != roles[i + 1] for i in range(len(roles) - 1)), roles
        # The tool_result and the gist share one coalesced user turn.
        merged = next(m for m in msgs if m["role"] == "user" and isinstance(m["content"], list)
                      and any(b.get("type") == "tool_result" for b in m["content"]))
        assert any("GIST" in str(b.get("text", "")) for b in merged["content"])

    def test_openai_tool_messages_not_coalesced(self):
        from core.providers.openai_provider import OpenAIProvider
        p = OpenAIProvider.__new__(OpenAIProvider)
        p.model = "gpt-x"
        rows = [
            _row(0, "user", "go"),
            _row(1, "assistant", "",
                 tool_calls=[{"tool": "a", "tool_use_id": "t1", "args": {}},
                             {"tool": "b", "tool_use_id": "t2", "args": {}}],
                 tool_results=[{"tool_use_id": "t1", "tool_name": "a", "content": "r1"},
                               {"tool_use_id": "t2", "tool_name": "b", "content": "r2"}]),
        ]
        msgs = assemble_messages(_FakeChatService(rows), p, "c1")
        tool_msgs = [m for m in msgs if m.get("role") == "tool"]
        assert len(tool_msgs) == 2  # one per tool_call_id — never merged


class TestOversizedGuard:
    def test_oversized_user_text_truncated(self):
        prov = _AnthropicShapeProvider(window=400)  # max_row_chars = 400
        rows = [_row(0, "user", "Y" * 5000)]
        msgs = _assemble(rows, provider=prov)
        assert len(msgs[0]["content"]) < 5000
        assert "truncated" in msgs[0]["content"]

    def test_oversized_tool_result_truncated_delimiter_safe(self):
        prov = _AnthropicShapeProvider(window=400)
        wrapped = '<untrusted_tool_result id="ab" tool="web">\n' + ("Z" * 5000) + "\n</untrusted_tool_result>"
        rows = [
            _row(0, "user", "go"),
            _row(1, "assistant", "",
                 tool_calls=[{"tool": "web", "tool_use_id": "tu1", "args": {}}],
                 tool_results=[{"tool_use_id": "tu1", "tool_name": "web", "content": wrapped}]),
        ]
        msgs = _assemble(rows, provider=prov)
        out = msgs[2]["content"][0]["content"]
        assert out.startswith('<untrusted_tool_result id="ab"')
        assert out.rstrip().endswith("</untrusted_tool_result>")
        assert "truncated" in out
        assert len(out) < len(wrapped)

    def test_oversized_tool_call_args_truncated(self):
        prov = _AnthropicShapeProvider(window=400)
        rows = [
            _row(0, "user", "save"),
            _row(1, "assistant", "",
                 tool_calls=[{"tool": "write_context_file", "tool_use_id": "tu1",
                              "args": {"path": "a.md", "content": "B" * 5000}}],
                 tool_results=[{"tool_use_id": "tu1", "tool_name": "write_context_file", "content": "ok"}]),
        ]
        msgs = _assemble(rows, provider=prov)
        tu = next(b for b in msgs[1]["content"] if b.get("type") == "tool_use")
        assert len(tu["input"]["content"]) < 5000
        assert tu["input"]["path"] == "a.md"  # small field untouched

    def test_truncate_wrapped_keeps_xml_intact(self):
        wrapped = '<untrusted_tool_result id="zz" tool="web">\n' + ("X" * 5000) + "\n</untrusted_tool_result>"
        out = _truncate_wrapped(wrapped, 200)
        assert out.startswith('<untrusted_tool_result id="zz"')
        assert out.rstrip().endswith("</untrusted_tool_result>")
        # The injection-bearing close tag is never split.
        assert out.count("<untrusted_tool_result") == 1
        assert out.count("</untrusted_tool_result>") == 1


# ---------------------------------------------------------------------------
# Compaction boundary
# ---------------------------------------------------------------------------

class TestCompaction:
    def _threaded_rows(self):
        return [
            _row(0, "user", "open"),
            _row(1, "assistant", "hi"),
            _row(2, "user", "middle one"),
            _row(3, "assistant", "mid reply"),
            _row(4, "user", "recent question"),
            _row(5, "assistant", "recent answer"),
        ]

    def test_no_compaction_when_no_summary(self):
        msgs = _assemble(self._threaded_rows())
        assert len(msgs) == 6  # all rows verbatim

    def test_gist_folds_into_first_kept_user_turn(self):
        rows = self._threaded_rows()
        msgs = _assemble(rows, compaction_summary="GIST OF THE MIDDLE",
                         compaction_first_kept_seq=4)
        # HEAD (2 rows) + folded TAIL (user4 with gist, assistant5)
        assert msgs[0] == {"role": "user", "content": "open"}
        assert msgs[1] == {"role": "assistant", "content": "hi"}
        assert HEAD_MSGS == 2
        # The aged middle (seq 2,3) is gone…
        assert not any("middle one" in str(m.get("content")) for m in msgs)
        # …replaced by the gist, folded onto the first retained human turn.
        folded = msgs[2]
        assert folded["role"] == "user"
        assert "GIST OF THE MIDDLE" in folded["content"]
        assert 'reference_only="true"' in folded["content"]
        assert "recent question" in folded["content"]
        assert msgs[3] == {"role": "assistant", "content": "recent answer"}

    def test_compaction_noop_when_boundary_inside_head(self):
        rows = self._threaded_rows()
        # A boundary that doesn't clear the head leaves the thread intact.
        msgs = _assemble(rows, compaction_summary="G", compaction_first_kept_seq=1)
        assert len(msgs) == 6

    def test_gist_marker_is_trusted_and_distinct(self):
        marker = _gist_marker("S")
        assert marker.startswith('<conversation_summary reference_only="true">')
        assert "untrusted" not in marker
