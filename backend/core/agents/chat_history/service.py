"""
Chatty — Chat history CRUD + search service.

All write operations acquire the DB's write lock to prevent
concurrent-write races (e.g. two requests computing the same seq).

Each agent instantiates its own ChatHistoryService backed by a
separate ChatHistoryDB instance, so conversations are fully isolated.
"""

import logging
import uuid

from .db import ChatHistoryDB

logger = logging.getLogger(__name__)


class ChatHistoryService:
    """Per-agent chat history CRUD backed by a ChatHistoryDB instance."""

    def __init__(self, db: ChatHistoryDB):
        self._db = db

    def create_conversation(self, source: str | None = None) -> dict:
        """Create a new conversation and return it.

        Args:
            source: Optional platform identifier ('telegram', 'whatsapp').
                    Messaging conversations are auto-pinned.
        """
        conv_id = str(uuid.uuid4())
        pinned = 1 if source else 0
        title = {"telegram": "Telegram", "whatsapp": "WhatsApp"}.get(source or "", "New conversation")
        db = self._db.get_db()
        with self._db.write_lock():
            db.execute(
                "INSERT INTO conversations (id, title, title_edited_by_user, source, pinned) VALUES (?, ?, ?, ?, ?)",
                (conv_id, title, 1 if source else 0, source, pinned),
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
    ) -> None:
        """Insert or replace a message and bump conversation updated_at.

        If seq is None, atomically computes the next sequence number under
        the write lock so concurrent callers never collide.
        tool_calls is an optional JSON string of tool call data for assistant messages.
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
                   (id, conversation_id, role, content, seq, tool_calls)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (msg_id, conversation_id, role, content, seq, tool_calls),
            )
            db.execute(
                "UPDATE conversations SET updated_at = datetime('now') WHERE id = ?",
                (conversation_id,),
            )
            db.commit()

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

    def search_conversations(self, query: str, limit: int = 20) -> list[dict]:
        """Search message content (case-insensitive), return matching conversations with snippets."""
        db = self._db.get_db()
        lower_query = query.lower()
        like_query = f"%{lower_query}%"
        rows = db.execute(
            """
            SELECT DISTINCT c.id, c.title, c.updated_at,
                   SUBSTR(m.content, MAX(1, INSTR(LOWER(m.content), ?) - 40), 120) AS snippet
            FROM messages m
            JOIN conversations c ON c.id = m.conversation_id
            WHERE LOWER(m.content) LIKE ?
            ORDER BY c.updated_at DESC
            LIMIT ?
            """,
            (lower_query, like_query, limit),
        ).fetchall()
        return [dict(r) for r in rows]

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
