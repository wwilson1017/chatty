"""A brain-backed agent takes its LONG-TERM memory from the brain and keeps short-term memory local:
the prompt's MEMORY section comes from GET /context, daily notes / topic files / persona stay in context/,
background turns lose the brain write tools, and the nightly job promotes durable items to the brain."""

import re
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx

from core.agents.context_manager import ContextManager
from core.agents.memory.brain_backend import BRAIN_SKIP_TEXT, CONTEXT_UNAVAILABLE, BrainBackend

BRAIN_TEXT = "# MEMORY\n\n- Will runs TNC\n\n## Recent days\n- 2026-09-24 · shipped the brain"


def _brain(handler_or_status, calls: list | None = None, memory: str = "") -> BrainBackend:
    def handler(request: httpx.Request) -> httpx.Response:
        body = request.read()
        if calls is not None:
            calls.append((request.method, request.url.path, dict(request.url.params), body))
        if isinstance(handler_or_status, int):
            return httpx.Response(handler_or_status, json={"error": "down"})
        if request.url.path == "/memory":
            return httpx.Response(200, json={"text": memory})
        if request.url.path == "/daily" and request.method == "POST":
            return httpx.Response(200, json={"date": "2026-09-26", "ok": True})
        return httpx.Response(200, json={"text": handler_or_status, "chars": len(handler_or_status), "truncated": False})
    return BrainBackend("http://brain.test", "k", agent_slug="tom", transport=httpx.MockTransport(handler))


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
        cm = ContextManager(ctx, "", brain=_brain(BRAIN_TEXT, calls))

        text = cm.load_all_context()
        assert "## MEMORY (second brain)" in text and "Will runs TNC" in text
        assert "STALE LOCAL SNAPSHOT" not in text
        # short-term / persona context is untouched: persona, topic notes, daily manifests
        assert "I am Tom." in text and "Will." in text and "LOCAL TOPIC NOTE" in text
        assert text.index("I am Tom.") < text.index("Will runs TNC") < text.index("LOCAL TOPIC NOTE")
        assert calls == [("GET", "/context", {"max_chars": "8000", "agent": "tom"}, b"")]
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
        b = _brain(BRAIN_TEXT, calls)
        assert b.context_text() == b.context_text() == BRAIN_TEXT
        assert len(calls) == 1
        import core.agents.memory.brain_backend as mod
        later = mod.time.monotonic() + 120
        monkeypatch.setattr(mod.time, "monotonic", lambda: later)
        b.context_text()
        assert len(calls) == 2

    def test_memory_instructions_for_brain(self):
        from core.agents.ai_service import _memory_instructions
        brain = _memory_instructions(brain=True)
        assert "`update_memory` is not available" in brain and "Daily Notes (local)" in brain
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
        brain = _brain(BRAIN_TEXT)
        monkeypatch.setattr(engine_mod, "get_brain_backend", lambda slug: brain if slug == "tom" else None)

        tom = engine_mod.get_context_manager("tom").load_all_context()
        assert "Will runs TNC" in tom and "STALE LOCAL SNAPSHOT" not in tom and "LOCAL TOPIC NOTE" in tom
        assert engine_mod.get_context_manager("other").brain is None


class TestToolPolicy:
    def test_background_turns_drop_brain_write_tools(self):
        from core.agents.tool_definitions import get_tool_definitions

        def names(**kw):
            return {t["name"] for t in get_tool_definitions(**kw)}
        builtin = names(background_mode=True)
        assert {"add_fact", "update_memory", "invalidate_fact", "append_daily_note"} <= builtin
        heartbeat = names(background_mode=True, memory_backend="brain")
        assert builtin - heartbeat == {"add_fact", "update_memory", "invalidate_fact"}
        assert {"append_daily_note", "read_daily_note", "list_daily_notes", "search_memory", "query_facts"} <= heartbeat
        # proposals are brain-only; a proposal is not a write, so background turns keep it
        assert {"propose_change", "list_proposals"} <= heartbeat and not {"propose_change", "list_proposals"} & builtin
        assert {"propose_change", "list_proposals"} <= names(memory_backend="brain")

    def test_heartbeat_runs_drop_propose_change_but_crons_keep_it(self, monkeypatch):
        import agents.engine as engine_mod
        import agents.tool_loader as tool_loader_mod
        from core.agents.scheduled_actions import processor

        monkeypatch.setattr(engine_mod, "memory_backend_for", lambda slug: "brain")
        monkeypatch.setattr(tool_loader_mod, "load_integration_tools", lambda: ([], {}))
        monkeypatch.setattr(tool_loader_mod, "build_agent_handlers", lambda slug: ({}, {}))
        agent = {"slug": "tom", "id": "1", "agent_name": "Tom", "google_accounts": {}}
        heartbeat = {t["name"] for t in processor._build_tools("tom", agent, background_mode=True, heartbeat=True)[0]}
        cron = {t["name"] for t in processor._build_tools("tom", agent, background_mode=True)[0]}
        assert "propose_change" not in heartbeat and "list_proposals" in heartbeat
        assert "propose_change" in cron and cron - heartbeat == {"propose_change"}

    def test_chat_turns_keep_them_with_skip_text(self):
        from core.agents.tool_definitions import MEMORY_TOOLS, get_tool_definitions
        by_name = {t["name"]: t for t in get_tool_definitions(memory_backend="brain")}
        for name in ("add_fact", "update_memory", "invalidate_fact"):
            assert by_name[name]["description"].endswith(BRAIN_SKIP_TEXT)
        assert not by_name["append_daily_note"]["description"].endswith(BRAIN_SKIP_TEXT)
        assert not any(BRAIN_SKIP_TEXT in t["description"] for t in MEMORY_TOOLS)  # originals untouched

    def test_search_merges_brain_and_local_hits(self, monkeypatch, tmp_path):
        import asyncio
        import agents.engine as engine_mod
        from core.agents.tool_registry import ToolRegistry

        ctx = tmp_path / "context"
        _seed(ctx)

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/search"
            return httpx.Response(200, json={"results": [{"path": "tnc/x.md", "title": "X", "snippet": "brain hit"}]})
        brain = BrainBackend("http://brain.test", "k", agent_slug="tom", transport=httpx.MockTransport(handler))
        monkeypatch.setattr(engine_mod, "get_brain_backend", lambda slug: brain)

        reg = ToolRegistry(context_dir=str(ctx), gcs_prefix="", agent_slug="tom")
        out = asyncio.run(reg.execute_tool("search_memory", {"query": "cheesecake"}, "memory"))
        assert [r["snippet"] for r in out["results"]] == ["brain hit"] and out["total"] == 1
        assert sorted((r["source_type"], r["title"]) for r in out["local_results"]) == [
            ("daily", "2026-09-20"), ("topic", "projects.md"),
        ]
        assert out["local_total"] == 2 and all("cheesecake" in r["snippet"] for r in out["local_results"])


class TestNightlyPromotion:
    def test_only_new_lines_go_to_the_brain(self, monkeypatch, tmp_path):
        from core.agents.memory.processor import new_memory_lines, process_brain_promotion

        known = "## Key People\n- Will — owner\n## Decisions\n- ship the brain"
        snapshot = "## Key People\n- Will — owner\n- Ashley — freezer board\n## Active Projects\n## Decisions\n- ship the brain\n- Tom uses the brain"
        assert new_memory_lines(snapshot, known) == "## Key People\n- Ashley — freezer board\n## Decisions\n- Tom uses the brain"
        assert new_memory_lines(known, known) == ""

        ctx = tmp_path / "tom" / "context"
        _seed(ctx)
        calls: list = []
        brain = _brain(BRAIN_TEXT, calls, memory=known)

        # consolidate_memory does `import anthropic` at call time: a fake module whose
        # messages.create returns the scripted snapshot
        reply = {"text": snapshot}
        resp = SimpleNamespace(content=[SimpleNamespace(type="text", text="")], usage=SimpleNamespace(input_tokens=10, output_tokens=5))

        def create(**kw):
            resp.content[0].text = reply["text"]
            return resp
        fake_anthropic = SimpleNamespace(Anthropic=lambda api_key: SimpleNamespace(messages=SimpleNamespace(create=create)))
        monkeypatch.setitem(sys.modules, "anthropic", fake_anthropic)

        result = process_brain_promotion("Tom", ContextManager(ctx, "", brain=brain), brain, api_key="k", days=1)
        assert result["ok"] and result["promoted"] == 2 and result["agent"] == "Tom"
        post = [c for c in calls if c[0] == "POST"]
        assert len(post) == 1 and post[0][1] == "/daily"
        body = post[0][3].decode()
        assert "Ashley" in body and "Tom uses the brain" in body and "Will — owner" not in body
        assert '"type":"consolidation"' in body and "[chatty:tom]" in body
        assert (ctx / "MEMORY.md").read_text().endswith("STALE LOCAL SNAPSHOT")  # local MEMORY.md untouched

        # nothing new → nothing posted
        calls.clear()
        reply["text"] = known
        result = process_brain_promotion("Tom", ContextManager(ctx, "", brain=brain), brain, api_key="k", days=1)
        assert result["ok"] and result["promoted"] == 0 and not [c for c in calls if c[0] == "POST"]
