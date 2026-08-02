"""Tests for the agent-facing todo tool executors (core/todo/tools.py).

The service and REST layers have their own suites; this is the layer an
agent's tool call actually hits, including the source anti-spoofing guard.
"""

import pytest

import core.todo.db as tododb
from core.todo.tools import TODO_TOOL_DEFS, TODO_TOOL_EXECUTORS


@pytest.fixture()
def todo_db(tmp_path, monkeypatch):
    monkeypatch.setattr(tododb, "DATA_DIR", tmp_path / "todo")
    monkeypatch.setattr(tododb, "DB_PATH", tmp_path / "todo" / "todo.db")
    (tmp_path / "todo").mkdir()
    tododb.close_db()
    tododb._setup_connection()
    yield
    tododb.close_db()


class TestExecutors:
    def test_every_def_has_an_executor(self):
        assert {t["name"] for t in TODO_TOOL_DEFS} == set(TODO_TOOL_EXECUTORS)

    def test_create_cannot_spoof_source(self, todo_db):
        # Agents must not be able to fabricate capture_web/telegram provenance.
        result = TODO_TOOL_EXECUTORS["todo_create"](title="sneaky", source="capture_web")
        assert result["todo"]["source"] == "agent"

    def test_create_list_get_roundtrip(self, todo_db):
        created = TODO_TOOL_EXECUTORS["todo_create"](
            title="call bank", project="Ops", context="@calls", tags=["quick"], star=True,
        )["todo"]
        listed = TODO_TOOL_EXECUTORS["todo_list"](status="inbox")
        assert listed["count"] == 1
        got = TODO_TOOL_EXECUTORS["todo_get"](id=created["id"])
        assert got["todo"]["project_name"] == "Ops"
        assert got["todo"]["star"] is True

    def test_update_and_bulk_update(self, todo_db):
        a = TODO_TOOL_EXECUTORS["todo_create"](title="a")["todo"]
        b = TODO_TOOL_EXECUTORS["todo_create"](title="b")["todo"]
        updated = TODO_TOOL_EXECUTORS["todo_update"](id=a["id"], status="done")
        assert updated["todo"]["completed_at"] is not None
        bulk = TODO_TOOL_EXECUTORS["todo_bulk_update"](
            ids=[a["id"], b["id"], 999], fields={"status": "someday_maybe"},
        )
        assert bulk["updated"] == [a["id"], b["id"]]
        assert bulk["not_found"] == [999]

    def test_delete_and_missing_ids_return_errors(self, todo_db):
        a = TODO_TOOL_EXECUTORS["todo_create"](title="a")["todo"]
        assert TODO_TOOL_EXECUTORS["todo_delete"](id=a["id"])["ok"] is True
        assert "error" in TODO_TOOL_EXECUTORS["todo_delete"](id=a["id"])
        assert "error" in TODO_TOOL_EXECUTORS["todo_get"](id=a["id"])
        assert "error" in TODO_TOOL_EXECUTORS["todo_update"](id=a["id"], title="x")

    def test_validation_errors_are_returned_not_raised(self, todo_db):
        assert "error" in TODO_TOOL_EXECUTORS["todo_create"](title="x", status="bogus")
        assert "error" in TODO_TOOL_EXECUTORS["todo_list"](status="bogus")
        assert "error" in TODO_TOOL_EXECUTORS["todo_bulk_update"](ids=[1], fields={"nope": 1})

    def test_project_crud(self, todo_db):
        p = TODO_TOOL_EXECUTORS["todo_create_project"](name="Reno", notes="kitchen")["project"]
        assert "error" in TODO_TOOL_EXECUTORS["todo_create_project"](name="reno")
        renamed = TODO_TOOL_EXECUTORS["todo_update_project"](id=p["id"], name="Renovation")
        assert renamed["project"]["name"] == "Renovation"
        listed = TODO_TOOL_EXECUTORS["todo_list_projects"]()
        assert listed["count"] == 1
        assert TODO_TOOL_EXECUTORS["todo_delete_project"](id=p["id"])["ok"] is True


class TestRegistryDispatch:
    @pytest.mark.asyncio
    async def test_execute_tool_routes_kind_todo(self, todo_db, tmp_path):
        from core.agents.tool_registry import ToolRegistry

        registry = ToolRegistry(context_dir=str(tmp_path / "ctx"), gcs_prefix="test")
        result = await registry.execute_tool("todo_create", {"title": "via registry"}, "todo")
        assert result["todo"]["title"] == "via registry"
        result = await registry.execute_tool("todo_list", {}, "todo")
        assert result["count"] == 1
        result = await registry.execute_tool("todo_nonexistent", {}, "todo")
        assert "error" in result
