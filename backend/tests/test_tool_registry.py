"""Tests for ToolRegistry — tool dispatch and context file operations."""

import asyncio
from pathlib import Path


from core.agents.tool_registry import ToolRegistry


def _make_registry(context_dir: str) -> ToolRegistry:
    """Create a minimal ToolRegistry pointing at a real context directory."""
    return ToolRegistry(context_dir=context_dir, gcs_prefix="")


def _run(coro):
    return asyncio.run(coro)


# ── Context tools: real filesystem ──────────────────────────────────────────


class TestListContextFiles:
    def test_empty_dir_returns_empty_list(self, tmp_path):
        ctx_dir = str(tmp_path / "context")
        Path(ctx_dir).mkdir()
        reg = _make_registry(ctx_dir)
        result = _run(reg.execute_tool("list_context_files", {}, "context"))
        assert result == {"files": []}

    def test_lists_written_files(self, tmp_path):
        ctx_dir = str(tmp_path / "context")
        Path(ctx_dir).mkdir()
        reg = _make_registry(ctx_dir)
        _run(reg.execute_tool(
            "write_context_file",
            {"filename": "notes.md", "content": "hello"},
            "context",
        ))
        result = _run(reg.execute_tool("list_context_files", {}, "context"))
        names = [f["name"] for f in result["files"]]
        assert "notes.md" in names


class TestWriteReadRoundTrip:
    def test_write_then_read_returns_content(self, tmp_path):
        ctx_dir = str(tmp_path / "context")
        reg = _make_registry(ctx_dir)
        write_result = _run(reg.execute_tool(
            "write_context_file",
            {"filename": "profile.md", "content": "# My Profile\nName: Test"},
            "context",
        ))
        assert write_result["ok"] is True

        read_result = _run(reg.execute_tool(
            "read_context_file",
            {"filename": "profile.md"},
            "context",
        ))
        assert read_result["content"] == "# My Profile\nName: Test"
        assert read_result["filename"] == "profile.md"


class TestAppendToContextFile:
    def test_append_adds_content(self, tmp_path):
        ctx_dir = str(tmp_path / "context")
        reg = _make_registry(ctx_dir)
        _run(reg.execute_tool(
            "write_context_file",
            {"filename": "log.md", "content": "Line 1"},
            "context",
        ))
        append_result = _run(reg.execute_tool(
            "append_to_context_file",
            {"filename": "log.md", "content": "Line 2"},
            "context",
        ))
        assert append_result["ok"] is True

        read_result = _run(reg.execute_tool(
            "read_context_file",
            {"filename": "log.md"},
            "context",
        ))
        assert "Line 1" in read_result["content"]
        assert "Line 2" in read_result["content"]


class TestDeleteContextFile:
    def test_delete_removes_file(self, tmp_path):
        ctx_dir = str(tmp_path / "context")
        reg = _make_registry(ctx_dir)
        _run(reg.execute_tool(
            "write_context_file",
            {"filename": "temp.md", "content": "temporary"},
            "context",
        ))
        del_result = _run(reg.execute_tool(
            "delete_context_file",
            {"filename": "temp.md"},
            "context",
        ))
        assert del_result["deleted"] is True

        read_result = _run(reg.execute_tool(
            "read_context_file",
            {"filename": "temp.md"},
            "context",
        ))
        assert "error" in read_result


class TestPathTraversal:
    def test_write_traversal_blocked(self, tmp_path):
        ctx_dir = str(tmp_path / "context")
        Path(ctx_dir).mkdir()
        reg = _make_registry(ctx_dir)
        result = _run(reg.execute_tool(
            "write_context_file",
            {"filename": "../escape.md", "content": "pwned"},
            "context",
        ))
        assert "error" in result

    def test_read_traversal_blocked(self, tmp_path):
        ctx_dir = str(tmp_path / "context")
        Path(ctx_dir).mkdir()
        reg = _make_registry(ctx_dir)
        result = _run(reg.execute_tool(
            "read_context_file",
            {"filename": "../../etc/passwd.md"},
            "context",
        ))
        assert "error" in result


# ── Routing errors ──────────────────────────────────────────────────────────


class TestRouting:
    def test_unknown_kind_returns_error(self, tmp_path):
        reg = _make_registry(str(tmp_path))
        result = _run(reg.execute_tool("anything", {}, "nonexistent_kind"))
        assert "error" in result
        assert "Unknown tool kind" in result["error"]

    def test_unknown_tool_within_kind_returns_error(self, tmp_path):
        reg = _make_registry(str(tmp_path))
        result = _run(reg.execute_tool("bogus_tool", {}, "context"))
        assert "error" in result
        assert "Unknown context tool" in result["error"]


# ── Error handling ──────────────────────────────────────────────────────────


class TestErrorHandling:
    def test_exception_returns_error_dict(self, tmp_path):
        """An exception inside a handler is caught and returned as an error dict."""
        reg = _make_registry(str(tmp_path))
        # read_context_file with missing required arg triggers a KeyError
        result = _run(reg.execute_tool("read_context_file", {}, "context"))
        assert "error" in result
        assert "Tool error" in result["error"]
