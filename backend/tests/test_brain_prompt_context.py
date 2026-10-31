"""A brain-backed agent takes its LONG-TERM memory from Common Brain and keeps short-term memory local:
the prompt's MEMORY section is brain_start's rules and memories, daily notes / topic files / persona stay
in context/, its long-term tools are Common Brain's own (background turns get only the read-only ones),
and the nightly job appends durable items to the brain's daily/<date> page."""

import re
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx

from core.agents.context_manager import ContextManager
from core.agents.memory.brain_backend import CONTEXT_UNAVAILABLE, TRUNCATED, BrainBackend

START = {
    "you_are": "chatty",
    "rules": ["Call brain_start at the start of every conversation.", "Every claim names its source."],
    "memories": [{"id": 1, "text": "Will runs TNC", "locked": True},
                 {"id": 4, "text": "Ashley runs the freezer board", "locked": False}],
    "pages": {"count": 3, "folders": [], "recent": []},
}
TOOLS = [
    {"name": n, "description": n, "read_only": ro, "input_schema": {"type": "object", "properties": {}}}
    for n, ro in (("brain_start", True), ("brain_search", True), ("brain_page_get", True), ("brain_remember", False),
                  ("brain_page_append", False), ("brain_history", True))
]


def _brain(start: dict | int = START, calls: list | None = None) -> BrainBackend:
    def handler(request: httpx.Request) -> httpx.Response:
        body = request.read()
        if calls is not None:
            calls.append((request.method, request.url.path, body))
        if isinstance(start, int):
            return httpx.Response(start, json={"error": "down"})
        if request.url.path == "/api/v1":
            return httpx.Response(200, json={"tools": TOOLS})
        if request.url.path == "/api/v1/tools/brain_page_append":
            return httpx.Response(200, json={"page": {"path": "daily/2026-10-30", "version": 1}})
        return httpx.Response(200, json=start)
    return BrainBackend("http://cb.test", "cb_test", transport=httpx.MockTransport(handler))


def _seed(ctx: Path) -> None:
    ctx.mkdir(parents=True)
    (ctx / "soul.md").write_text("# soul\n\nI am Tom.")
    (ctx / "user.md").write_text("# user\n\nWill.")
    (ctx / "MEMORY.md").write_text("# MEMORY\n\nSTALE LOCAL SNAPSHOT")
    (ctx / "projects.md").write_text("# projects\n\nLOCAL TOPIC NOTE about cheesecake")
    (ctx / "daily").mkdir()
    (ctx / "daily" / "2026-09-20.md").write_text("# 2026-09-20\n\nLOCAL DAILY about cheesecake")


class TestPromptBlock:
    def test_brain_block_replaces_local_memory_only(self, tmp_path):
        ctx = tmp_path / "context"
        _seed(ctx)
        calls: list = []
        cm = ContextManager(ctx, "", brain=_brain(calls=calls))

        text = cm.load_all_context()
        assert "## MEMORY (second brain)" in text and "STALE LOCAL SNAPSHOT" not in text
        assert "- Every claim names its source." in text
        assert "- Will runs TNC (#1, locked)" in text and "- Ashley runs the freezer board (#4)" in text
        # short-term / persona context is untouched: persona, topic notes, daily manifests
        assert "I am Tom." in text and "Will." in text and "LOCAL TOPIC NOTE" in text
        assert text.index("I am Tom.") < text.index("Will runs TNC") < text.index("LOCAL TOPIC NOTE")
        assert calls == [("POST", "/api/v1/tools/brain_start", b"{}")]
        assert "2026-09-20" in cm.daily_notes_manifest() and "projects.md" in cm.topic_files_manifest()
        assert sorted(h["kind"] for h in cm.relevance_prefetch("cheesecake")) == ["daily", "topic"]

        local = ContextManager(ctx, "").load_all_context()
        assert "STALE LOCAL SNAPSHOT" in local and "second brain" not in local

    def test_unavailable_brain_gives_one_line_notice(self, tmp_path):
        ctx = tmp_path / "context"
        _seed(ctx)
        text = ContextManager(ctx, "", brain=_brain(503)).load_all_context()
        assert CONTEXT_UNAVAILABLE in text and "STALE LOCAL SNAPSHOT" not in text and "I am Tom." in text
        assert CONTEXT_UNAVAILABLE in ContextManager(ctx, "", brain=BrainBackend("", "")).load_all_context()

    def test_context_is_cached_for_a_minute(self, monkeypatch):
        calls: list = []
        b = _brain(calls=calls)
        assert b.context_text() == b.context_text()
        assert len(calls) == 1
        import core.agents.memory.brain_backend as mod
        later = mod.time.monotonic() + 120
        monkeypatch.setattr(mod.time, "monotonic", lambda: later)
        b.context_text()
        assert len(calls) == 2

    def test_block_is_capped_at_a_line(self):
        many = {**START, "memories": [{"id": i, "text": f"fact number {i} " + "x" * 60} for i in range(200)],
                "more_memories": "12 more memories are not shown here: brain_search finds them."}
        text = _brain(many).context_text()
        assert len(text) <= 8_000 and text.endswith(TRUNCATED)
        assert text.removesuffix(TRUNCATED).splitlines()[-1].endswith(")")  # a whole memory line, not half of one
        assert _brain(many).context_text(max_chars=100_000).endswith("brain_search finds them.")
        assert "(none yet)" in _brain({**START, "memories": []}).context_text()

    def test_memory_instructions_for_brain(self):
        from core.agents.ai_service import _memory_instructions
        brain = _memory_instructions(brain=True)
        assert "`brain_search`" in brain and "Daily Notes (local)" in brain and "daily/<date>" in brain
        assert "update_memory" not in brain and "add_fact" not in brain and "propose_change" not in brain
        assert "update with `update_memory`" in _memory_instructions(brain=False)


class TestEveryPromptPathSharesTheBuilder:
    """Heartbeats, crons, reminders, WhatsApp and the coach all get their knowledge block
    from agents.engine.get_context_manager(slug).load_all_context() — the one place the
    brain switch lives — and pass the agent's memory backend to get_tool_definitions."""

    PROMPT_PATHS = (
        "core/agents/scheduled_actions/processor.py",
        "core/agents/reminders/heartbeat.py",
        "integrations/whatsapp/service.py",
        "core/agents/live/coach.py",
    )

    def test_no_prompt_path_bypasses_the_builder(self):
        backend = Path(__file__).resolve().parent.parent
        for rel in self.PROMPT_PATHS:
            src = (backend / rel).read_text(encoding="utf-8")
            assert "load_all_context" in src and "memory_backend=memory_backend_for(" in src, rel
            assert not re.search(r"\bContextManager\(", src), f"{rel} builds its own ContextManager"

    def test_get_context_manager_carries_the_brain(self, monkeypatch, tmp_path):
        import agents.engine as engine_mod
        monkeypatch.setattr(engine_mod, "DATA_DIR", tmp_path)
        _seed(tmp_path / "tom" / "context")
        brain = _brain()
        monkeypatch.setattr(engine_mod, "get_brain_backend", lambda slug: brain if slug == "tom" else None)

        tom = engine_mod.get_context_manager("tom").load_all_context()
        assert "Will runs TNC" in tom and "STALE LOCAL SNAPSHOT" not in tom and "LOCAL TOPIC NOTE" in tom
        assert engine_mod.get_context_manager("other").brain is None


class TestToolPolicy:
    REPLACED = {"read_memory", "update_memory", "add_fact", "query_facts", "invalidate_fact", "consolidate_memory"}

    def _names(self, monkeypatch, **kw):
        import agents.engine as engine_mod
        from core.agents.tool_definitions import get_tool_definitions
        brain = _brain()
        monkeypatch.setattr(engine_mod, "brain_backend", lambda: brain)
        return {t["name"]: t for t in get_tool_definitions(**kw)}

    def test_brain_agents_get_common_brains_tools_instead_of_the_builtin_long_term_ones(self, monkeypatch):
        builtin = self._names(monkeypatch)
        brain = self._names(monkeypatch, memory_backend="brain")
        assert self.REPLACED <= set(builtin) and not self.REPLACED & set(brain)
        assert set(brain) - set(builtin) == {"brain_search", "brain_page_get", "brain_remember", "brain_page_append"}
        assert {"append_daily_note", "read_daily_note", "list_daily_notes", "search_memory"} <= set(brain)
        # search_memory is the local-only one; the builtin's is untouched
        assert "brain_search" in brain["search_memory"]["description"]
        assert "brain_search" not in builtin["search_memory"]["description"]
        assert not any(n.startswith("brain_") for n in builtin)

    def test_background_turns_get_only_the_read_only_brain_tools(self, monkeypatch):
        bg = self._names(monkeypatch, memory_backend="brain", background_mode=True)
        assert {n for n in bg if n.startswith("brain_")} == {"brain_search", "brain_page_get"}
        assert "append_daily_note" in bg  # heartbeat findings go to the local daily note

    def test_scheduled_runs_build_the_read_only_set(self, monkeypatch):
        import agents.engine as engine_mod
        import agents.tool_loader as tool_loader_mod
        from core.agents.scheduled_actions import processor

        brain = _brain()
        monkeypatch.setattr(engine_mod, "memory_backend_for", lambda slug: "brain")
        monkeypatch.setattr(engine_mod, "brain_backend", lambda: brain)
        monkeypatch.setattr(tool_loader_mod, "load_integration_tools", lambda: ([], {}))
        monkeypatch.setattr(tool_loader_mod, "build_agent_handlers", lambda slug: ({}, {}))
        agent = {"slug": "tom", "id": "1", "agent_name": "Tom", "google_accounts": {}}
        names = {t["name"] for t in processor._build_tools("tom", agent, background_mode=True)[0]}
        assert {n for n in names if n.startswith("brain_")} == {"brain_search", "brain_page_get"}


class TestNightlyPromotion:
    def test_only_new_lines_are_appended_to_the_brains_daily_page(self, monkeypatch, tmp_path):
        import json

        from core.agents.memory.processor import new_memory_lines, process_brain_promotion

        known = "- Will runs TNC\n- Ashley runs the freezer board"
        snapshot = "## Key People\n- Will runs TNC\n- Becca likes lemon\n## Active Projects\n## Decisions\n- Tom uses the brain"
        assert new_memory_lines(snapshot, known) == "## Key People\n- Becca likes lemon\n## Decisions\n- Tom uses the brain"
        assert new_memory_lines(known, known) == ""

        ctx = tmp_path / "tom" / "context"
        _seed(ctx)
        calls: list = []
        brain = _brain(calls=calls)

        # consolidate_memory does `import anthropic` at call time: a fake module whose
        # messages.create returns the scripted snapshot, and records the corpus it was given
        reply, seen = {"text": snapshot}, {}
        resp = SimpleNamespace(content=[SimpleNamespace(type="text", text="")], usage=SimpleNamespace(input_tokens=10, output_tokens=5))

        def create(**kw):
            seen["corpus"] = kw["messages"][0]["content"]
            resp.content[0].text = reply["text"]
            return resp
        fake_anthropic = SimpleNamespace(Anthropic=lambda api_key: SimpleNamespace(messages=SimpleNamespace(create=create)))
        monkeypatch.setitem(sys.modules, "anthropic", fake_anthropic)

        cm = ContextManager(ctx, "", brain=brain)
        result = process_brain_promotion("Tom", cm, brain, api_key="k", days=1)
        assert result["ok"] and result["promoted"] == 2 and result["agent"] == "Tom"
        assert "- Ashley runs the freezer board" in seen["corpus"]  # it starts from the brain's memories
        posts = [c for c in calls if c[1] == "/api/v1/tools/brain_page_append"]
        assert len(posts) == 1
        body = json.loads(posts[0][2])
        assert body["path"] == f"daily/{cm._today_str()}" and body["text"].startswith("[chatty:tom] ")
        assert "Becca likes lemon" in body["text"] and "Tom uses the brain" in body["text"]
        assert "Will runs TNC" not in body["text"]
        assert (ctx / "MEMORY.md").read_text().endswith("STALE LOCAL SNAPSHOT")  # local MEMORY.md untouched

        # nothing new → nothing appended
        calls.clear()
        reply["text"] = "## Key People\n- Will runs TNC"
        result = process_brain_promotion("Tom", cm, brain, api_key="k", days=1)
        assert result["ok"] and result["promoted"] == 0
        assert not [c for c in calls if c[1] == "/api/v1/tools/brain_page_append"]

    def test_an_unreachable_brain_writes_nothing(self, tmp_path):
        from core.agents.memory.processor import process_brain_promotion

        ctx = tmp_path / "tom" / "context"
        _seed(ctx)
        brain = _brain(503)
        result = process_brain_promotion("Tom", ContextManager(ctx, "", brain=brain), brain, api_key="k")
        assert result == {"ok": False, "error": "brain error (503): down", "agent": "Tom"}
