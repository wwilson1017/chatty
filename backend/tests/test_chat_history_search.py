"""Tests for FTS5-based conversation history search."""

import uuid

import pytest

from core.agents.chat_history.db import ChatHistoryDB
from core.agents.chat_history.service import ChatHistoryService
from core.agents.fts import sanitize_fts_query


@pytest.fixture
def chat_db(tmp_path):
    """Create an initialized ChatHistoryDB in a temp directory."""
    db = ChatHistoryDB(data_dir=tmp_path, gcs_prefix="test/", db_filename="chat.db")
    db._setup_connection()
    return db


@pytest.fixture
def chat_service(chat_db):
    return ChatHistoryService(chat_db)


def _insert_message(db: ChatHistoryDB, conv_id: str, role: str, content: str, seq: int):
    """Insert a message directly (bypasses service layer for test setup)."""
    conn = db.get_db()
    with db.write_lock():
        conn.execute(
            "INSERT INTO messages (id, conversation_id, role, content, seq) VALUES (?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), conv_id, role, content, seq),
        )
        conn.commit()


def _create_conversation(db: ChatHistoryDB, title: str = "Test conversation") -> str:
    conn = db.get_db()
    conv_id = str(uuid.uuid4())
    with db.write_lock():
        conn.execute(
            "INSERT INTO conversations (id, title) VALUES (?, ?)",
            (conv_id, title),
        )
        conn.commit()
    return conv_id


# ── FTS availability ─────────────────────────────────────────────────────────


class TestFTSInit:
    def test_fts_available(self, chat_db):
        assert chat_db.fts_available is True

    def test_messages_searchable_immediately(self, chat_db, chat_service):
        conv_id = _create_conversation(chat_db, "Budget Discussion")
        _insert_message(chat_db, conv_id, "user", "Let's discuss the quarterly budget", 0)
        _insert_message(chat_db, conv_id, "assistant", "I'd be happy to help with the budget review", 1)

        results = chat_service.search_conversations("budget")
        assert len(results) == 1
        assert results[0]["id"] == conv_id

    def test_system_messages_not_indexed(self, chat_db, chat_service):
        conv_id = _create_conversation(chat_db)
        _insert_message(chat_db, conv_id, "system", "You are a helpful assistant", 0)
        _insert_message(chat_db, conv_id, "user", "Hello", 1)

        results = chat_service.search_conversations("helpful assistant")
        assert len(results) == 0

    def test_empty_content_not_indexed(self, chat_db, chat_service):
        conv_id = _create_conversation(chat_db)
        _insert_message(chat_db, conv_id, "user", "", 0)

        results = chat_service.search_conversations("")
        assert len(results) == 0


# ── Backfill / rebuild ───────────────────────────────────────────────────────


class TestBackfill:
    def test_rebuild_after_fts_table_recreated(self, chat_db, chat_service):
        """Drop FTS table (simulating upgrade), verify _setup_fts rebuilds."""
        conv_id = _create_conversation(chat_db, "Backfill Test")
        _insert_message(chat_db, conv_id, "user", "historical data for backfill", 0)
        assert len(chat_service.search_conversations("historical")) == 1

        conn = chat_db.get_db()
        conn.execute("DROP TABLE IF EXISTS messages_fts")
        conn.execute("DROP TRIGGER IF EXISTS messages_fts_ai")
        conn.execute("DROP TRIGGER IF EXISTS messages_fts_ad")
        conn.execute("DROP TRIGGER IF EXISTS messages_fts_au")
        conn.commit()
        chat_db._fts_available = False

        chat_db._setup_fts(conn)
        assert chat_db.fts_available is True
        assert len(chat_service.search_conversations("historical")) == 1


# ── INSERT OR REPLACE consistency ────────────────────────────────────────────


class TestInsertOrReplace:
    def test_replace_updates_fts(self, chat_db, chat_service):
        """INSERT OR REPLACE with same ID should update the FTS index."""
        conv_id = _create_conversation(chat_db)
        msg_id = str(uuid.uuid4())

        chat_service.save_message(conv_id, msg_id, "user", "original text about apples", seq=0)
        results = chat_service.search_conversations("apples")
        assert len(results) == 1

        chat_service.save_message(conv_id, msg_id, "user", "updated text about oranges", seq=0)

        old_results = chat_service.search_conversations("apples")
        assert len(old_results) == 0

        new_results = chat_service.search_conversations("oranges")
        assert len(new_results) == 1

        conn = chat_db.get_db()
        msg_count = conn.execute(
            "SELECT COUNT(*) FROM messages WHERE role IN ('user','assistant') AND content != ''"
        ).fetchone()[0]
        fts_count = conn.execute("SELECT COUNT(*) FROM messages_fts").fetchone()[0]
        assert msg_count == fts_count


# ── Cascade delete ───────────────────────────────────────────────────────────


class TestCascadeDelete:
    def test_delete_conversation_removes_fts_entries(self, chat_db, chat_service):
        conv_id = _create_conversation(chat_db)
        _insert_message(chat_db, conv_id, "user", "secret project details", 0)
        _insert_message(chat_db, conv_id, "assistant", "I understand the secret project", 1)

        assert len(chat_service.search_conversations("secret project")) == 1

        chat_service.delete_conversation(conv_id)

        assert len(chat_service.search_conversations("secret project")) == 0


# ── Sidebar search ───────────────────────────────────────────────────────────


class TestSidebarSearch:
    def test_dedup_one_row_per_conversation(self, chat_db, chat_service):
        """Multiple matching messages in one conversation = one result row."""
        conv_id = _create_conversation(chat_db, "Meeting Notes")
        _insert_message(chat_db, conv_id, "user", "The meeting was about budgets", 0)
        _insert_message(chat_db, conv_id, "assistant", "Yes, we discussed budgets extensively", 1)
        _insert_message(chat_db, conv_id, "user", "What were the budget conclusions?", 2)

        results = chat_service.search_conversations("budget")
        assert len(results) == 1
        assert results[0]["title"] == "Meeting Notes"

    def test_recency_order(self, chat_db, chat_service):
        """Results should be ordered by conversation updated_at DESC."""
        conv1 = _create_conversation(chat_db, "Old Discussion")
        _insert_message(chat_db, conv1, "user", "testing recency order", 0)

        conn = chat_db.get_db()
        conn.execute(
            "UPDATE conversations SET updated_at = '2024-01-01' WHERE id = ?", (conv1,)
        )
        conn.commit()

        conv2 = _create_conversation(chat_db, "New Discussion")
        _insert_message(chat_db, conv2, "user", "testing recency order again", 0)

        results = chat_service.search_conversations("recency")
        assert len(results) == 2
        assert results[0]["title"] == "New Discussion"
        assert results[1]["title"] == "Old Discussion"

    def test_no_highlight_markers(self, chat_db, chat_service):
        """Sidebar snippets should not contain ** markers."""
        conv_id = _create_conversation(chat_db)
        _insert_message(chat_db, conv_id, "user", "important quarterly report", 0)

        results = chat_service.search_conversations("quarterly")
        assert len(results) == 1
        assert "**" not in results[0]["snippet"]

    def test_result_shape(self, chat_db, chat_service):
        conv_id = _create_conversation(chat_db, "Shape Test")
        _insert_message(chat_db, conv_id, "user", "checking result shape", 0)

        results = chat_service.search_conversations("shape")
        assert len(results) == 1
        result = results[0]
        assert "id" in result
        assert "title" in result
        assert "updated_at" in result
        assert "snippet" in result

    def test_empty_query_returns_empty(self, chat_service):
        assert chat_service.search_conversations("") == []
        assert chat_service.search_conversations("   ") == []

    def test_limit_respected(self, chat_db, chat_service):
        for i in range(5):
            conv_id = _create_conversation(chat_db, f"Conv {i}")
            _insert_message(chat_db, conv_id, "user", "common search term", 0)

        results = chat_service.search_conversations("common", limit=3)
        assert len(results) == 3


# ── Agent tool search ────────────────────────────────────────────────────────


class TestAgentSearch:
    def test_grouped_shape(self, chat_db, chat_service):
        conv_id = _create_conversation(chat_db, "Project Planning")
        _insert_message(chat_db, conv_id, "user", "Let's plan the project timeline", 0)
        _insert_message(chat_db, conv_id, "assistant", "The project has three phases", 1)

        results = chat_service.search_history("project")
        assert len(results) == 1
        conv = results[0]
        assert conv["conversation_id"] == conv_id
        assert conv["title"] == "Project Planning"
        assert "updated_at" in conv
        assert "matches" in conv
        assert len(conv["matches"]) >= 1
        match = conv["matches"][0]
        assert "role" in match
        assert "date" in match
        assert "snippet" in match

    def test_highlight_markers(self, chat_db, chat_service):
        conv_id = _create_conversation(chat_db)
        _insert_message(chat_db, conv_id, "user", "discussion about revenue projections", 0)

        results = chat_service.search_history("revenue")
        assert len(results) == 1
        snippet = results[0]["matches"][0]["snippet"]
        assert "**" in snippet

    def test_exclude_current_conversation(self, chat_db, chat_service):
        conv1 = _create_conversation(chat_db, "Past Conversation")
        _insert_message(chat_db, conv1, "user", "unique keyword xylophone", 0)

        conv2 = _create_conversation(chat_db, "Current Conversation")
        _insert_message(chat_db, conv2, "user", "also mentions xylophone", 0)

        results_all = chat_service.search_history("xylophone")
        assert len(results_all) == 2

        results_excluding = chat_service.search_history(
            "xylophone", exclude_conversation_id=conv2
        )
        assert len(results_excluding) == 1
        assert results_excluding[0]["conversation_id"] == conv1

    def test_per_conversation_cap(self, chat_db, chat_service):
        conv_id = _create_conversation(chat_db)
        for i in range(10):
            _insert_message(chat_db, conv_id, "user", f"repeated keyword alpha iteration {i}", i)

        results = chat_service.search_history("alpha")
        assert len(results) == 1
        assert len(results[0]["matches"]) <= 3

    def test_limit_clamped(self, chat_db, chat_service):
        for i in range(5):
            conv_id = _create_conversation(chat_db, f"Conv {i}")
            _insert_message(chat_db, conv_id, "user", "findable term", 0)

        results = chat_service.search_history("findable", limit=2)
        assert len(results) == 2

    def test_empty_query(self, chat_service):
        assert chat_service.search_history("") == []


# ── LIKE fallback ────────────────────────────────────────────────────────────


class TestLIKEFallback:
    def test_sidebar_fallback(self, chat_db, chat_service):
        conv_id = _create_conversation(chat_db, "Fallback Test")
        _insert_message(chat_db, conv_id, "user", "fallback test content", 0)

        chat_db._fts_available = False
        results = chat_service.search_conversations("fallback")
        assert len(results) == 1
        assert results[0]["title"] == "Fallback Test"

    def test_agent_search_fallback(self, chat_db, chat_service):
        conv_id = _create_conversation(chat_db, "Agent Fallback")
        _insert_message(chat_db, conv_id, "user", "agent fallback content", 0)

        chat_db._fts_available = False
        results = chat_service.search_history("agent fallback")
        assert len(results) == 1
        assert results[0]["title"] == "Agent Fallback"
        assert "matches" in results[0]


# ── Shared sanitizer ────────────────────────────────────────────────────────


class TestSanitizer:
    def test_special_chars_escaped(self):
        result = sanitize_fts_query('test "quoted" value')
        assert result == '"test" "quoted" "value"'
        result = sanitize_fts_query("test* wildcard")
        assert result == '"test" "wildcard"'
        result = sanitize_fts_query("test(paren)")
        assert result == '"test" "paren"'

    def test_empty_input(self):
        assert sanitize_fts_query("") == '""'
        assert sanitize_fts_query("   ") == '""'

    def test_tokens_quoted(self):
        result = sanitize_fts_query("hello world")
        assert result == '"hello" "world"'

    def test_single_token(self):
        result = sanitize_fts_query("budget")
        assert result == '"budget"'


# ── Tool definition ──────────────────────────────────────────────────────────


class TestToolDefinition:
    def test_tool_present_in_definitions(self):
        from core.agents.tool_definitions import get_tool_definitions

        tools = get_tool_definitions()
        names = [t["name"] for t in tools]
        assert "search_conversation_history" in names

        tool = next(t for t in tools if t["name"] == "search_conversation_history")
        assert tool["kind"] == "chat_history"
        assert tool["writes"] is False

    def test_tool_absent_in_import_mode(self):
        from core.agents.tool_definitions import get_tool_definitions

        tools = get_tool_definitions(import_mode=True)
        names = [t["name"] for t in tools]
        assert "search_conversation_history" not in names

    def test_always_loaded_kind(self):
        from core.agents.deferred_tools import ALWAYS_LOADED_KINDS

        assert "chat_history" in ALWAYS_LOADED_KINDS


# ── Additional coverage from review ──────────────────────────────────────────


class TestUpdateTrigger:
    def test_direct_update_reindexes(self, chat_db, chat_service):
        """SQL UPDATE on a message reindexes via the _au/_au_ins triggers."""
        conv_id = _create_conversation(chat_db)
        _insert_message(chat_db, conv_id, "user", "original content about giraffes", 0)
        assert len(chat_service.search_conversations("giraffes")) == 1

        conn = chat_db.get_db()
        with chat_db.write_lock():
            conn.execute(
                "UPDATE messages SET content = 'new content about elephants' WHERE conversation_id = ?",
                (conv_id,),
            )
            conn.commit()

        assert len(chat_service.search_conversations("giraffes")) == 0
        assert len(chat_service.search_conversations("elephants")) == 1


class TestLIKEFallbackExclude:
    def test_exclude_works_in_like_mode(self, chat_db, chat_service):
        conv1 = _create_conversation(chat_db, "Past")
        _insert_message(chat_db, conv1, "user", "unique zebra keyword", 0)
        conv2 = _create_conversation(chat_db, "Current")
        _insert_message(chat_db, conv2, "user", "also zebra keyword", 0)

        chat_db._fts_available = False
        results = chat_service.search_history("zebra", exclude_conversation_id=conv2)
        assert len(results) == 1
        assert results[0]["conversation_id"] == conv1


class TestSpecialCharQuery:
    def test_all_special_chars_returns_empty(self, chat_db, chat_service):
        _create_conversation(chat_db)
        _insert_message(chat_db, _create_conversation(chat_db), "user", "some content", 0)

        assert chat_service.search_conversations("*** (()) --") == []
        assert chat_service.search_history("*** (()) --") == []


class TestLimitBounds:
    def test_limit_clamped_above_max(self, chat_db, chat_service):
        for i in range(25):
            conv_id = _create_conversation(chat_db, f"Conv {i}")
            _insert_message(chat_db, conv_id, "user", "bounded term", 0)

        results = chat_service.search_conversations("bounded", limit=100)
        assert len(results) <= 20

    def test_limit_clamped_below_min(self, chat_db, chat_service):
        conv_id = _create_conversation(chat_db)
        _insert_message(chat_db, conv_id, "user", "minimum limit test", 0)

        results = chat_service.search_conversations("minimum", limit=0)
        assert len(results) == 1
