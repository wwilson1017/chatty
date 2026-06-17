"""
Chatty — Chat history CRUD + search service.

All write operations acquire the DB's write lock to prevent
concurrent-write races (e.g. two requests computing the same seq).

Each agent instantiates its own ChatHistoryService backed by a
separate ChatHistoryDB instance, so conversations are fully isolated.
"""

import json
import logging
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from core.agents.fts import sanitize_fts_query
from .db import ChatHistoryDB

logger = logging.getLogger(__name__)

CT_TZ = ZoneInfo("America/Chicago")


class ChatHistoryService:
    """Per-agent chat history CRUD backed by a ChatHistoryDB instance."""

    def __init__(self, db: ChatHistoryDB):
        self._db = db

    def create_conversation(
        self,
        source: str | None = None,
        title: str | None = None,
        mode: str = "normal",
    ) -> dict:
        """Create a new conversation and return it.

        Args:
            source: Optional platform identifier ('telegram', 'whatsapp').
                    Messaging conversations are auto-pinned.
            title: Optional custom title. Defaults based on source.
            mode: 'normal' or 'import'. Import-mode conversations expose
                  import tools to the agent.
        """
        conv_id = str(uuid.uuid4())
        pinned = 1 if source else 0
        if title is None:
            title = {"telegram": "Telegram", "telegram-group": "Telegram Group", "whatsapp": "WhatsApp"}.get(source or "", "New conversation")
        db = self._db.get_db()
        with self._db.write_lock():
            db.execute(
                "INSERT INTO conversations (id, title, title_edited_by_user, source, pinned, mode) VALUES (?, ?, ?, ?, ?, ?)",
                (conv_id, title, 1 if source else 0, source, pinned, mode),
            )
            db.commit()
        row = db.execute("SELECT * FROM conversations WHERE id = ?", (conv_id,)).fetchone()
        return dict(row)

    def list_conversations(self, limit: int = 50, offset: int = 0) -> list[dict]:
        """List conversations ordered by most recent, with message count and preview."""
        db = self._db.get_db()
        rows = db.execute(
            """
            SELECT c.*,
                   COUNT(m.id) AS message_count,
                   (SELECT m2.content FROM messages m2
                    WHERE m2.conversation_id = c.id AND m2.role = 'user'
                    ORDER BY m2.seq DESC LIMIT 1) AS preview
            FROM conversations c
            LEFT JOIN messages m ON m.conversation_id = c.id
            GROUP BY c.id
            ORDER BY c.pinned DESC, c.updated_at DESC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_conversation(self, conv_id: str) -> dict | None:
        """Return conversation + all messages, or None if not found."""
        db = self._db.get_db()
        conv = db.execute("SELECT * FROM conversations WHERE id = ?", (conv_id,)).fetchone()
        if not conv:
            return None
        result = dict(conv)
        msgs = db.execute(
            "SELECT * FROM messages WHERE conversation_id = ? ORDER BY seq",
            (conv_id,),
        ).fetchall()
        result["messages"] = [dict(m) for m in msgs]
        return result

    def delete_conversation(self, conv_id: str) -> bool:
        """Delete a conversation and its messages. Returns True if found."""
        db = self._db.get_db()
        with self._db.write_lock():
            cursor = db.execute("DELETE FROM conversations WHERE id = ?", (conv_id,))
            db.commit()
        if cursor.rowcount > 0:
            self._db.backup_to_gcs()
            return True
        return False

    def save_message(
        self,
        conversation_id: str,
        msg_id: str,
        role: str,
        content: str,
        seq: int | None = None,
        tool_calls: str | None = None,
        model: str = "",
        tool_results: str | None = None,
    ) -> None:
        """Insert or replace a message and bump conversation updated_at.

        If seq is None, atomically computes the next sequence number under
        the write lock so concurrent callers never collide.
        tool_calls is an optional JSON string of tool call data for assistant messages.
        tool_results is an optional JSON string of FULL tool-result content
        ([{tool_use_id, content}]) used to rebuild tool exchanges across turns.
        model is the AI model ID that generated this message.
        """
        db = self._db.get_db()
        with self._db.write_lock():
            if seq is None:
                row = db.execute(
                    "SELECT COALESCE(MAX(seq), -1) + 1 AS next_seq FROM messages WHERE conversation_id = ?",
                    (conversation_id,),
                ).fetchone()
                seq = row["next_seq"]
            db.execute(
                """INSERT OR REPLACE INTO messages
                   (id, conversation_id, role, content, seq, tool_calls, tool_results, model)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (msg_id, conversation_id, role, content, seq, tool_calls, tool_results, model),
            )
            db.execute(
                "UPDATE conversations SET updated_at = datetime('now') WHERE id = ?",
                (conversation_id,),
            )
            db.commit()

    # ── Persistent-context helpers ────────────────────────────────────────

    def update_message_tool_results(self, msg_id: str, tool_results: str) -> None:
        """Attach full tool-result JSON to an already-saved assistant row.

        A true UPDATE (not the INSERT OR REPLACE save path) so seq/created_at
        and FTS rows stay intact. Results are produced after the assistant row
        is saved at _turn_complete, so they're attached here.
        """
        db = self._db.get_db()
        with self._db.write_lock():
            db.execute("UPDATE messages SET tool_results = ? WHERE id = ?", (tool_results, msg_id))
            db.commit()

    def find_pending_tool_message(self, conversation_id: str, tool_use_id: str) -> str | None:
        """Return the msg_id of the most recent assistant row that called
        tool_use_id AND whose result for it is still pending/absent — so an
        approval reconciles only a genuinely-pending row. Requiring "still
        pending" matters because providers like Gemini regenerate ids (call_0,
        call_1) every turn, so id alone could match a completed/older row.
        The frontend sends tool_use_id, not the DB msg_id, hence the lookup."""
        db = self._db.get_db()
        rows = db.execute(
            "SELECT id, tool_calls, tool_results FROM messages "
            "WHERE conversation_id = ? AND role = 'assistant' AND tool_calls IS NOT NULL "
            "ORDER BY seq DESC",
            (conversation_id,),
        ).fetchall()
        for r in rows:
            try:
                tcs = json.loads(r["tool_calls"]) or []
            except Exception:
                continue
            if not any((tc.get("tool_use_id") or tc.get("id")) == tool_use_id for tc in tcs):
                continue
            try:
                results = json.loads(r["tool_results"]) if r["tool_results"] else []
            except Exception:
                results = []
            res = next((x for x in results if x.get("tool_use_id") == tool_use_id), None)
            if res is None or "pending_user_approval" in (res.get("content") or ""):
                return r["id"]
        return None

    def merge_tool_result(self, msg_id: str, tool_use_id: str, tool_name: str, content: str) -> None:
        """Set/replace one tool_use_id's result on an assistant row, preserving
        sibling results (e.g. a read executed in the same iteration as a write
        that was awaiting approval). Result order is irrelevant — reconstruction
        pairs by id from tool_calls."""
        db = self._db.get_db()
        with self._db.write_lock():
            row = db.execute("SELECT tool_results FROM messages WHERE id = ?", (msg_id,)).fetchone()
            existing = []
            if row and row["tool_results"]:
                try:
                    existing = json.loads(row["tool_results"]) or []
                except Exception:
                    existing = []
            merged = [r for r in existing if r.get("tool_use_id") != tool_use_id]
            merged.append({"tool_use_id": tool_use_id, "tool_name": tool_name, "content": content})
            db.execute("UPDATE messages SET tool_results = ? WHERE id = ?",
                       (json.dumps(merged), msg_id))
            db.commit()

    def count_user_messages(self, conversation_id: str) -> int:
        """Count human user turns. DB user rows are always human — tool results
        live on the assistant row's tool_results column, and synthetic
        tool_result/gist messages exist only at assembly time, never in the DB."""
        db = self._db.get_db()
        row = db.execute(
            "SELECT COUNT(*) AS n FROM messages WHERE conversation_id = ? AND role = 'user'",
            (conversation_id,),
        ).fetchone()
        return row["n"] if row else 0

    def get_clean_history(self, conversation_id: str, limit: int | None = None) -> list[dict]:
        """Return the clean human/assistant TEXT transcript ([{role, content}])
        for consumers (smart-title, knowledge checkpoint, fact extraction) that
        must NOT see reconstructed provider-native blocks or synthetic messages."""
        db = self._db.get_db()
        rows = db.execute(
            "SELECT role, content FROM messages WHERE conversation_id = ? ORDER BY seq",
            (conversation_id,),
        ).fetchall()
        out = [{"role": r["role"], "content": r["content"]} for r in rows]
        return out[-limit:] if limit else out

    def set_turn_usage(self, conversation_id: str, context_tokens: int,
                       context_window: int | None, model: str) -> None:
        """Persist the latest main-turn context fullness so compaction can trigger
        durably (and for Telegram, which has no SSE meter)."""
        db = self._db.get_db()
        with self._db.write_lock():
            db.execute(
                "UPDATE conversations SET last_context_tokens = ?, last_context_window = ?, "
                "last_model = ? WHERE id = ?",
                (context_tokens, context_window, model, conversation_id),
            )
            db.commit()

    def get_turn_usage(self, conversation_id: str) -> tuple[int | None, int | None, str | None]:
        db = self._db.get_db()
        row = db.execute(
            "SELECT last_context_tokens, last_context_window, last_model "
            "FROM conversations WHERE id = ?",
            (conversation_id,),
        ).fetchone()
        if not row:
            return (None, None, None)
        return (row["last_context_tokens"], row["last_context_window"], row["last_model"])

    def get_compaction(self, conversation_id: str) -> tuple[str | None, int | None]:
        db = self._db.get_db()
        row = db.execute(
            "SELECT compaction_summary, compaction_first_kept_seq FROM conversations WHERE id = ?",
            (conversation_id,),
        ).fetchone()
        if not row:
            return (None, None)
        return (row["compaction_summary"], row["compaction_first_kept_seq"])

    def set_compaction(self, conversation_id: str, summary: str, first_kept_seq: int) -> None:
        # CAS on the boundary: only advance it. If two turns on the same
        # conversation compact concurrently, the slower summarizer must not
        # regress a newer, farther boundary. Backup OUTSIDE the write lock so a
        # slow GCS upload can't block all chat-history writes.
        db = self._db.get_db()
        with self._db.write_lock():
            cur = db.execute(
                "UPDATE conversations SET compaction_summary = ?, compaction_first_kept_seq = ? "
                "WHERE id = ? AND COALESCE(compaction_first_kept_seq, -1) < ?",
                (summary, first_kept_seq, conversation_id, first_kept_seq),
            )
            db.commit()
            changed = cur.rowcount > 0
        if changed:
            self._db.backup_to_gcs()

    def get_messages_on_date(self, date: str) -> list[dict]:
        """Return all messages from a given date (YYYY-MM-DD), ordered by conversation then sequence.

        Each row includes conversation_id, conversation_title, role, content.
        Used by the daily note summarization job.
        """
        db = self._db.get_db()
        rows = db.execute(
            """SELECT m.conversation_id, c.title AS conversation_title, m.role, m.content
               FROM messages m
               JOIN conversations c ON c.id = m.conversation_id
               WHERE DATE(m.created_at) = ?
               ORDER BY m.conversation_id, m.seq""",
            (date,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_qualifying_conversations(
        self, date: str, min_user_messages: int = 4,
    ) -> list[dict]:
        """Return conversations from a CT date with enough user messages for observation extraction.

        Each result has conversation_id, conversation_title, and the last 10 user messages
        (the extractor only consumes user text, so assistant turns are excluded at the source).
        """
        y, m, d = (int(p) for p in date.split("-"))
        local_start = datetime(y, m, d, tzinfo=CT_TZ)
        local_end = local_start + timedelta(days=1)
        utc_start = local_start.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        utc_end = local_end.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

        db = self._db.get_db()
        qualifying = db.execute(
            """SELECT m.conversation_id, c.title AS conversation_title,
                      COUNT(CASE WHEN m.role = 'user' THEN 1 END) AS user_msg_count
               FROM messages m
               JOIN conversations c ON c.id = m.conversation_id
               WHERE m.created_at >= ? AND m.created_at < ?
               GROUP BY m.conversation_id, c.title
               HAVING user_msg_count >= ?""",
            (utc_start, utc_end, min_user_messages),
        ).fetchall()

        results = []
        for conv in qualifying:
            msgs = db.execute(
                """SELECT role, content FROM messages
                   WHERE conversation_id = ? AND role = 'user'
                     AND created_at >= ? AND created_at < ?
                   ORDER BY seq DESC LIMIT 10""",
                (conv["conversation_id"], utc_start, utc_end),
            ).fetchall()
            results.append({
                "conversation_id": conv["conversation_id"],
                "conversation_title": conv["conversation_title"],
                "messages": [dict(m) for m in reversed(msgs)],
            })
        return results

    def search_conversations(self, query: str, limit: int = 20) -> list[dict]:
        """FTS5 search over message content, returning matching conversations with snippets.

        Falls back to LIKE-based search if FTS5 is unavailable.
        """
        if not query.strip():
            return []
        query = query[:500]
        limit = max(1, min(limit, 20))

        if not self._db.fts_available:
            return self._search_conversations_like(query, limit)

        safe_query = sanitize_fts_query(query)
        if not safe_query or safe_query == '""':
            return []

        db = self._db.get_db()
        try:
            rows = db.execute(
                """
                SELECT c.id, c.title, c.updated_at,
                       snippet(messages_fts, 0, '', '', '...', 20) AS snippet
                FROM messages_fts
                JOIN messages m ON m.rowid = messages_fts.rowid
                JOIN conversations c ON c.id = m.conversation_id
                WHERE messages_fts MATCH ?
                ORDER BY c.updated_at DESC
                LIMIT ?
                """,
                (safe_query, limit * 10),
            ).fetchall()
        except sqlite3.OperationalError as e:
            logger.warning("FTS sidebar search failed, using LIKE fallback: %s", e)
            return self._search_conversations_like(query, limit)

        seen: dict[str, dict] = {}
        for row in rows:
            cid = row["id"]
            if cid not in seen:
                seen[cid] = dict(row)
                if len(seen) >= limit:
                    break
        return list(seen.values())

    def _search_conversations_like(self, query: str, limit: int = 20) -> list[dict]:
        """Fallback LIKE-based search."""
        db = self._db.get_db()
        lower_query = query.lower()
        escaped = lower_query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        like_query = f"%{escaped}%"
        rows = db.execute(
            """
            SELECT c.id, c.title, c.updated_at,
                   SUBSTR(m.content, MAX(1, INSTR(LOWER(m.content), ?) - 40), 120) AS snippet
            FROM messages m
            JOIN conversations c ON c.id = m.conversation_id
            WHERE m.role IN ('user', 'assistant') AND m.content != ''
              AND LOWER(m.content) LIKE ? ESCAPE '\\'
            GROUP BY c.id
            ORDER BY c.updated_at DESC
            LIMIT ?
            """,
            (lower_query, like_query, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def search_history(
        self,
        query: str,
        limit: int = 10,
        exclude_conversation_id: str | None = None,
    ) -> list[dict]:
        """FTS5 search returning grouped results for the agent tool.

        Returns conversations with up to 3 matching messages each,
        ranked by BM25 relevance. Falls back to LIKE if FTS5 unavailable.
        """
        if not query.strip():
            return []
        query = query[:500]
        limit = max(1, min(limit, 20))

        if not self._db.fts_available:
            return self._search_history_like(query, limit, exclude_conversation_id)

        safe_query = sanitize_fts_query(query)
        if not safe_query or safe_query == '""':
            return []

        db = self._db.get_db()
        params: list = [safe_query]
        exclude_clause = ""
        if exclude_conversation_id:
            exclude_clause = "AND m.conversation_id != ?"
            params.append(exclude_conversation_id)
        params.append(limit * 10)

        try:
            rows = db.execute(
                f"""
                SELECT c.id AS conversation_id, c.title, c.updated_at,
                       m.role, m.created_at AS message_date,
                       snippet(messages_fts, 0, '**', '**', '...', 40) AS snippet,
                       bm25(messages_fts) AS rank
                FROM messages_fts
                JOIN messages m ON m.rowid = messages_fts.rowid
                JOIN conversations c ON c.id = m.conversation_id
                WHERE messages_fts MATCH ?
                {exclude_clause}
                ORDER BY rank
                LIMIT ?
                """,
                params,
            ).fetchall()
        except sqlite3.OperationalError as e:
            logger.warning("FTS search_history failed, using LIKE fallback: %s", e)
            return self._search_history_like(query, limit, exclude_conversation_id)

        return self._group_search_results(rows, limit, preserve_order=True)

    def _search_history_like(
        self,
        query: str,
        limit: int = 10,
        exclude_conversation_id: str | None = None,
    ) -> list[dict]:
        """Fallback LIKE-based search for the agent tool."""
        db = self._db.get_db()
        lower_query = query.lower()
        escaped = lower_query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        like_query = f"%{escaped}%"
        params: list = [lower_query, like_query]
        exclude_clause = ""
        if exclude_conversation_id:
            exclude_clause = "AND m.conversation_id != ?"
            params.append(exclude_conversation_id)
        params.append(limit * 10)

        rows = db.execute(
            f"""
            SELECT c.id AS conversation_id, c.title, c.updated_at,
                   m.role, m.created_at AS message_date,
                   SUBSTR(m.content, MAX(1, INSTR(LOWER(m.content), ?) - 40), 120) AS snippet
            FROM messages m
            JOIN conversations c ON c.id = m.conversation_id
            WHERE m.role IN ('user', 'assistant') AND m.content != ''
              AND LOWER(m.content) LIKE ? ESCAPE '\\'
            {exclude_clause}
            ORDER BY c.updated_at DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
        return self._group_search_results(rows, limit)

    @staticmethod
    def _group_search_results(
        rows, limit: int, per_conversation: int = 3, preserve_order: bool = False,
    ) -> list[dict]:
        """Group message-level search results by conversation.

        When preserve_order is True, keeps the SQL ordering (e.g. BM25 rank).
        When False, re-sorts by conversation recency.
        """
        conversations: dict[str, dict] = {}
        for row in rows:
            cid = row["conversation_id"]
            if cid not in conversations:
                conversations[cid] = {
                    "conversation_id": cid,
                    "title": row["title"],
                    "updated_at": row["updated_at"],
                    "matches": [],
                }
            if len(conversations[cid]["matches"]) < per_conversation:
                conversations[cid]["matches"].append({
                    "role": row["role"],
                    "date": row["message_date"],
                    "snippet": row["snippet"],
                })

        if preserve_order:
            return list(conversations.values())[:limit]
        results = sorted(
            conversations.values(), key=lambda c: c["updated_at"], reverse=True
        )
        return results[:limit]

    def rename_conversation(self, conv_id: str, title: str) -> str | None:
        """Rename a conversation (user-initiated). Returns title or None if not found."""
        title = title.strip()
        if not title:
            return None
        if len(title) > 100:
            title = title[:100]
        db = self._db.get_db()
        with self._db.write_lock():
            row = db.execute("SELECT id FROM conversations WHERE id = ?", (conv_id,)).fetchone()
            if not row:
                return None
            db.execute(
                "UPDATE conversations SET title = ?, title_edited_by_user = 1, updated_at = datetime('now') WHERE id = ?",
                (title, conv_id),
            )
            db.commit()
        self._db.backup_to_gcs()
        return title

    def auto_title(self, conversation_id: str, first_message: str) -> str:
        """Set conversation title from first user message (truncated to 60 chars)."""
        title = first_message.strip().replace("\n", " ")
        if len(title) > 60:
            title = title[:57] + "..."
        db = self._db.get_db()
        with self._db.write_lock():
            db.execute(
                "UPDATE conversations SET title = ?, title_edited_by_user = 0 WHERE id = ?",
                (title, conversation_id),
            )
            db.commit()
        return title

    def update_title(self, conversation_id: str, title: str, edited_by_user: bool = False) -> str | None:
        """Update a conversation title (AI-generated). Returns title or None if not found."""
        title = title.strip()
        if not title:
            return None
        if len(title) > 100:
            title = title[:100]
        db = self._db.get_db()
        with self._db.write_lock():
            row = db.execute(
                "SELECT id, title_edited_by_user FROM conversations WHERE id = ?",
                (conversation_id,),
            ).fetchone()
            if not row:
                return None
            # Don't overwrite user-edited titles with AI-generated ones
            if row["title_edited_by_user"] and not edited_by_user:
                return None
            db.execute(
                "UPDATE conversations SET title = ?, title_edited_by_user = ?, updated_at = datetime('now') WHERE id = ?",
                (title, 1 if edited_by_user else 0, conversation_id),
            )
            db.commit()
        self._db.backup_to_gcs()
        return title

    def generate_smart_title(self, conversation_id: str, messages: list[dict], api_key: str) -> str | None:
        """Generate a descriptive title using Claude Haiku. Skips if user already renamed."""
        db = self._db.get_db()
        row = db.execute(
            "SELECT title_edited_by_user FROM conversations WHERE id = ?",
            (conversation_id,),
        ).fetchone()
        if not row or row["title_edited_by_user"]:
            return None

        import anthropic

        summary_messages = []
        for m in messages[-6:]:
            role = m.get("role", "user")
            content = m.get("content", "")[:500]
            if role in ("user", "assistant") and content:
                summary_messages.append({"role": role, "content": content})

        if not summary_messages:
            return None

        try:
            client = anthropic.Anthropic(api_key=api_key)
            response = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=30,
                system="Generate a concise 4-8 word title summarizing this conversation. Return ONLY the title, no quotes or punctuation unless part of the topic.",
                messages=summary_messages,
            )
            title = response.content[0].text.strip().strip("\"'")
            if not title:
                return None
            if len(title) > 80:
                title = title[:77] + "..."
        except Exception as e:
            logger.warning("Smart title generation failed: %s", e)
            return None

        with self._db.write_lock():
            db.execute(
                "UPDATE conversations SET title = ? WHERE id = ? AND title_edited_by_user = 0",
                (title, conversation_id),
            )
            db.commit()
        return title
