"""Per-agent memory database — FTS5 full-text search + temporal facts.

Follows the same patterns as ChatHistoryDB: single shared SQLite connection,
WAL mode, threading write-lock, GCS backup/restore.  Each agent gets its own
memory.db alongside its chat_history.db.

Zero new dependencies — FTS5 is built into Python's sqlite3.
"""

import logging
import re
import sqlite3
import threading
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from core.storage import safe_backup_sqlite, safe_init_sqlite

from .types import validate_memory_type

logger = logging.getLogger(__name__)

CT_TZ = ZoneInfo("America/Chicago")

# Module-level cache: one MemoryDB per data_dir (string key).
_instances: dict[str, "MemoryDB"] = {}


def get_instance(data_dir: str) -> "MemoryDB | None":
    """Return the cached MemoryDB for *data_dir*, or None if not yet initialized."""
    return _instances.get(data_dir)


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_SCHEMA = """\
-- Content table backing the FTS5 index
CREATE TABLE IF NOT EXISTS memory_documents (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source_type TEXT    NOT NULL CHECK(source_type IN ('daily','memory','topic','fact')),
    source_id   TEXT    NOT NULL,
    title       TEXT    NOT NULL DEFAULT '',
    content     TEXT    NOT NULL,
    memory_type TEXT,
    date        TEXT,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE(source_type, source_id)
);

CREATE INDEX IF NOT EXISTS idx_memdoc_source ON memory_documents(source_type, source_id);
CREATE INDEX IF NOT EXISTS idx_memdoc_type   ON memory_documents(memory_type) WHERE memory_type IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_memdoc_date   ON memory_documents(date)        WHERE date IS NOT NULL;

-- Temporal facts (entity-relationship triples with validity windows)
CREATE TABLE IF NOT EXISTS facts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    subject     TEXT    NOT NULL,
    predicate   TEXT    NOT NULL,
    object      TEXT    NOT NULL,
    valid_from  TEXT    NOT NULL DEFAULT (date('now')),
    valid_to    TEXT,
    created_by  TEXT    NOT NULL DEFAULT '',
    source      TEXT    NOT NULL DEFAULT '',
    confidence  REAL    NOT NULL DEFAULT 1.0 CHECK(confidence >= 0.0 AND confidence <= 1.0),
    memory_type TEXT,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_facts_subject ON facts(subject);
CREATE INDEX IF NOT EXISTS idx_facts_valid   ON facts(valid_from, valid_to);
CREATE INDEX IF NOT EXISTS idx_facts_type    ON facts(memory_type) WHERE memory_type IS NOT NULL;
"""

# FTS5 setup is separate because CREATE VIRTUAL TABLE doesn't support IF NOT EXISTS
# inside executescript cleanly on all Python/SQLite combos.
_FTS5_SETUP = """\
CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
    title, content, memory_type, source_type,
    content='memory_documents',
    content_rowid='id',
    tokenize='porter unicode61'
);

-- Triggers to keep FTS5 in sync with the content table
CREATE TRIGGER IF NOT EXISTS memory_fts_ai AFTER INSERT ON memory_documents BEGIN
    INSERT INTO memory_fts(rowid, title, content, memory_type, source_type)
    VALUES (new.id, new.title, new.content, COALESCE(new.memory_type,''), new.source_type);
END;

CREATE TRIGGER IF NOT EXISTS memory_fts_ad AFTER DELETE ON memory_documents BEGIN
    INSERT INTO memory_fts(memory_fts, rowid, title, content, memory_type, source_type)
    VALUES ('delete', old.id, old.title, old.content, COALESCE(old.memory_type,''), old.source_type);
END;

CREATE TRIGGER IF NOT EXISTS memory_fts_au AFTER UPDATE ON memory_documents BEGIN
    INSERT INTO memory_fts(memory_fts, rowid, title, content, memory_type, source_type)
    VALUES ('delete', old.id, old.title, old.content, COALESCE(old.memory_type,''), old.source_type);
    INSERT INTO memory_fts(rowid, title, content, memory_type, source_type)
    VALUES (new.id, new.title, new.content, COALESCE(new.memory_type,''), new.source_type);
END;
"""


# ---------------------------------------------------------------------------
# FTS5 query sanitizer
# ---------------------------------------------------------------------------

_FTS_SPECIAL = re.compile(r'["\*\(\)\+\-\^~:]')


def _sanitize_fts_query(raw: str) -> str:
    """Escape special FTS5 characters and wrap each token in quotes for safety."""
    raw = _FTS_SPECIAL.sub(" ", raw)
    tokens = raw.split()
    if not tokens:
        return '""'
    # Quote each token individually so multi-word queries use implicit AND
    return " ".join(f'"{t}"' for t in tokens if t.strip())


# ---------------------------------------------------------------------------
# MemoryDB
# ---------------------------------------------------------------------------

class MemoryDB:
    """Per-agent memory database with FTS5 search and temporal facts."""

    def __init__(self, data_dir: Path, gcs_prefix: str, db_filename: str = "memory.db"):
        self.data_dir = data_dir
        self.db_path = data_dir / db_filename
        self.gcs_key = gcs_prefix + db_filename
        self._connection: sqlite3.Connection | None = None
        self._write_lock = threading.Lock()
        self._backup_mutex = threading.Lock()

    def get_db(self) -> sqlite3.Connection:
        if self._connection is None:
            raise RuntimeError("MemoryDB not initialized — call init_db() first")
        return self._connection

    @property
    def write_lock(self) -> threading.Lock:
        return self._write_lock

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def _setup_connection(self) -> None:
        """Open connection, set PRAGMAs, create schema."""
        self._connection = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA foreign_keys=ON")
        self._connection.execute("PRAGMA busy_timeout=5000")

        self._connection.executescript(_SCHEMA)

        try:
            self._connection.executescript(_FTS5_SETUP)
        except sqlite3.OperationalError as e:
            if "fts5" in str(e).lower():
                logger.error(
                    "FTS5 is not available in this SQLite build. "
                    "Memory search will be disabled.  Error: %s", e,
                )
            else:
                raise

        _instances[str(self.data_dir)] = self
        logger.info("MemoryDB initialized at %s", self.db_path)

    def init_db(self) -> dict:
        """Initialize with integrity check and GCS restore."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        return safe_init_sqlite(
            self.db_path, self.gcs_key, init_fn=self._setup_connection,
        )

    def backup_to_gcs(self) -> None:
        """Create a consistent snapshot and upload to GCS."""
        safe_backup_sqlite(
            self._connection, self.db_path, self.gcs_key,
            backup_mutex=self._backup_mutex,
        )

    # ------------------------------------------------------------------
    # FTS5 indexing
    # ------------------------------------------------------------------

    def index_document(
        self,
        source_type: str,
        source_id: str,
        title: str,
        content: str,
        memory_type: str | None = None,
        date: str | None = None,
    ) -> None:
        """Upsert a document into memory_documents (FTS5 triggers handle the index)."""
        memory_type = validate_memory_type(memory_type)
        conn = self.get_db()
        with self._write_lock:
            conn.execute(
                """INSERT INTO memory_documents
                       (source_type, source_id, title, content, memory_type, date, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
                   ON CONFLICT(source_type, source_id)
                   DO UPDATE SET title=excluded.title,
                                 content=excluded.content,
                                 memory_type=excluded.memory_type,
                                 date=excluded.date,
                                 updated_at=datetime('now')""",
                (source_type, source_id, title, content, memory_type, date),
            )
            conn.commit()

    def remove_document(self, source_type: str, source_id: str) -> None:
        """Remove a document from the index."""
        conn = self.get_db()
        with self._write_lock:
            conn.execute(
                "DELETE FROM memory_documents WHERE source_type=? AND source_id=?",
                (source_type, source_id),
            )
            conn.commit()

    def search(
        self,
        query: str,
        source_type: str | None = None,
        memory_type: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 20,
    ) -> list[dict]:
        """FTS5 search with optional filters.  Returns ranked result dicts."""
        conn = self.get_db()
        limit = max(1, min(int(limit), 100))

        safe_query = _sanitize_fts_query(query)
        if not safe_query or safe_query == '""':
            return []

        # Build the MATCH expression with optional column filters
        match_parts: list[str] = []
        if source_type:
            match_parts.append(f'source_type:"{source_type}"')
        if memory_type:
            match_parts.append(f'memory_type:"{memory_type}"')
        match_parts.append(f"({safe_query})")
        match_expr = " ".join(match_parts)

        sql = """
            SELECT d.id, d.source_type, d.source_id, d.title, d.memory_type, d.date,
                   snippet(memory_fts, 1, '**', '**', '…', 40) AS snippet,
                   bm25(memory_fts, 5.0, 1.0, 3.0, 2.0)       AS rank
            FROM memory_fts
            JOIN memory_documents d ON d.id = memory_fts.rowid
            WHERE memory_fts MATCH ?
        """
        params: list = [match_expr]

        if date_from:
            sql += " AND d.date >= ?"
            params.append(date_from)
        if date_to:
            sql += " AND d.date <= ?"
            params.append(date_to)

        sql += " ORDER BY rank LIMIT ?"
        params.append(limit)

        try:
            rows = conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]
        except sqlite3.OperationalError as e:
            logger.warning("FTS5 search failed for query=%r: %s", query, e)
            return []

    # ------------------------------------------------------------------
    # Reindex from files on disk
    # ------------------------------------------------------------------

    def reindex_all(self, ctx_manager) -> dict:
        """Full rebuild of FTS5 index from files on disk.

        *ctx_manager* is a ContextManager instance for this agent.
        Called on startup after init_db().
        """
        conn = self.get_db()
        stats = {"documents_indexed": 0, "facts_reindexed": 0}

        with self._write_lock:
            # Clear existing document index (facts survive in their own table)
            conn.execute("DELETE FROM memory_documents WHERE source_type != 'fact'")
            conn.commit()

        # 1. Index MEMORY.md
        memory = ctx_manager.read_memory()
        if memory:
            self.index_document("memory", "MEMORY.md", "MEMORY.md", memory)
            stats["documents_indexed"] += 1

        # 2. Index daily notes
        daily_dir = ctx_manager.daily_dir
        if daily_dir.exists():
            for f in sorted(daily_dir.glob("*.md")):
                note_date = f.stem  # e.g. "2026-04-12"
                content = f.read_text(encoding="utf-8", errors="replace")
                if content.strip():
                    self.index_document("daily", note_date, note_date, content, date=note_date)
                    stats["documents_indexed"] += 1

        # 3. Index topic files (skip soul.md, MEMORY.md, _-prefixed)
        skip = {"soul.md", "memory.md"}
        for f in sorted(ctx_manager.data_dir.glob("*.md")):
            if f.name.startswith("_") or f.name.lower() in skip:
                continue
            content = f.read_text(encoding="utf-8", errors="replace")
            if content.strip():
                self.index_document("topic", f.name, f.name, content)
                stats["documents_indexed"] += 1

        # 4. Re-index existing facts from the facts table
        rows = conn.execute("SELECT id, subject, predicate, object, valid_from, memory_type FROM facts WHERE valid_to IS NULL").fetchall()
        for row in rows:
            self.index_document(
                "fact",
                str(row["id"]),
                f"{row['subject']} {row['predicate']}",
                f"{row['subject']} {row['predicate']} {row['object']}",
                memory_type=row["memory_type"],
                date=row["valid_from"],
            )
            stats["facts_reindexed"] += 1

        logger.info("MemoryDB reindex complete: %s", stats)
        return stats

    # ------------------------------------------------------------------
    # Temporal facts
    # ------------------------------------------------------------------

    def add_fact(
        self,
        subject: str,
        predicate: str,
        object_: str,
        valid_from: str | None = None,
        created_by: str = "agent",
        source: str = "",
        confidence: float = 1.0,
        memory_type: str | None = None,
    ) -> dict:
        """Insert a new fact and index it in FTS5.  Returns the fact dict."""
        valid_from = valid_from or date.today().isoformat()
        memory_type = validate_memory_type(memory_type)
        confidence = max(0.0, min(float(confidence), 1.0))

        conn = self.get_db()
        with self._write_lock:
            cursor = conn.execute(
                """INSERT INTO facts
                       (subject, predicate, object, valid_from, created_by, source, confidence, memory_type)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (subject, predicate, object_, valid_from, created_by, source, confidence, memory_type),
            )
            conn.commit()
            fact_id = cursor.lastrowid

        # Index in FTS5 (outside write lock — index_document acquires its own)
        self.index_document(
            "fact",
            str(fact_id),
            f"{subject} {predicate}",
            f"{subject} {predicate} {object_}",
            memory_type=memory_type,
            date=valid_from,
        )
        return {
            "id": fact_id,
            "subject": subject,
            "predicate": predicate,
            "object": object_,
            "valid_from": valid_from,
            "memory_type": memory_type,
            "ok": True,
        }

    def query_facts(
        self,
        subject: str | None = None,
        predicate: str | None = None,
        as_of: str | None = None,
        memory_type: str | None = None,
        include_expired: bool = False,
        limit: int = 50,
    ) -> list[dict]:
        """Query facts with optional filters.  *as_of* gives a point-in-time view."""
        conn = self.get_db()
        limit = max(1, min(int(limit), 500))

        sql = "SELECT * FROM facts WHERE 1=1"
        params: list = []

        if subject:
            sql += " AND subject LIKE ?"
            params.append(f"%{subject}%")
        if predicate:
            sql += " AND predicate LIKE ?"
            params.append(f"%{predicate}%")
        if memory_type:
            sql += " AND memory_type = ?"
            params.append(memory_type)
        if as_of:
            sql += " AND valid_from <= ? AND (valid_to IS NULL OR valid_to >= ?)"
            params.extend([as_of, as_of])
        elif not include_expired:
            sql += " AND valid_to IS NULL"

        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def invalidate_fact(self, fact_id: int, valid_to: str | None = None) -> dict:
        """Set valid_to on a fact.  Removes it from the FTS5 search index."""
        valid_to = valid_to or date.today().isoformat()
        conn = self.get_db()
        with self._write_lock:
            cursor = conn.execute(
                "UPDATE facts SET valid_to=?, updated_at=datetime('now') WHERE id=?",
                (valid_to, fact_id),
            )
            conn.commit()
            if cursor.rowcount == 0:
                return {"error": f"Fact {fact_id} not found"}

        self.remove_document("fact", str(fact_id))
        return {"id": fact_id, "valid_to": valid_to, "ok": True}
