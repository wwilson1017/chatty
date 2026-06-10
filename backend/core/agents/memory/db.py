"""Per-agent memory database — FTS5 full-text search + semantic vectors + temporal facts.

Follows the same patterns as ChatHistoryDB: single shared SQLite connection,
WAL mode, threading write-lock, GCS backup/restore.  Each agent gets its own
memory.db alongside its chat_history.db.

Vector search via sqlite-vec (optional — graceful degradation if unavailable).
"""

import hashlib
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
    content_hash TEXT,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE(source_type, source_id)
);

CREATE INDEX IF NOT EXISTS idx_memdoc_source ON memory_documents(source_type, source_id);
CREATE INDEX IF NOT EXISTS idx_memdoc_type   ON memory_documents(memory_type) WHERE memory_type IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_memdoc_date   ON memory_documents(date)        WHERE date IS NOT NULL;

-- Chunks for vector embeddings (one document → many chunks)
CREATE TABLE IF NOT EXISTS memory_chunks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id      INTEGER NOT NULL,
    chunk_index INTEGER NOT NULL,
    content     TEXT    NOT NULL,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE(doc_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS idx_chunks_doc ON memory_chunks(doc_id);

-- Embedding provider/model config (singleton row)
CREATE TABLE IF NOT EXISTS memory_embedding_config (
    id          INTEGER PRIMARY KEY CHECK (id = 1),
    provider    TEXT    NOT NULL,
    model       TEXT    NOT NULL,
    dimensions  INTEGER NOT NULL,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- Skill packs (reusable prompt recipes)
CREATE TABLE IF NOT EXISTS skill_packs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT    NOT NULL UNIQUE,
    description     TEXT    NOT NULL DEFAULT '',
    prompt          TEXT    NOT NULL,
    category        TEXT,
    tags            TEXT,
    trigger_pattern TEXT,
    usage_count     INTEGER NOT NULL DEFAULT 0,
    auto_generated  INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);

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

# Chunking constants
CHUNK_SIZE = 2000  # ~500 tokens
CHUNK_OVERLAP = 100


def _chunk_text(text: str) -> list[str]:
    """Split text into chunks for embedding. Prefers paragraph/sentence boundaries."""
    if len(text) <= CHUNK_SIZE:
        return [text]

    chunks = []
    start = 0
    while start < len(text):
        end = start + CHUNK_SIZE

        if end >= len(text):
            chunks.append(text[start:])
            break

        # Try to break at paragraph boundary
        para_break = text.rfind("\n\n", start + CHUNK_SIZE // 2, end)
        if para_break > start:
            end = para_break + 2
        else:
            # Try sentence boundary
            sent_break = text.rfind(". ", start + CHUNK_SIZE // 2, end)
            if sent_break > start:
                end = sent_break + 2
            else:
                # Try newline
                nl_break = text.rfind("\n", start + CHUNK_SIZE // 2, end)
                if nl_break > start:
                    end = nl_break + 1

        chunks.append(text[start:end])
        # Advance by at least half the chunk size to avoid near-duplicate chunks
        start = max(start + CHUNK_SIZE // 2, end - CHUNK_OVERLAP)

    return chunks

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
    """Per-agent memory database with FTS5 search, vector embeddings, and temporal facts."""

    def __init__(self, data_dir: Path, gcs_prefix: str, db_filename: str = "memory.db"):
        self.data_dir = data_dir
        self.db_path = data_dir / db_filename
        self.gcs_key = gcs_prefix + db_filename
        self._connection: sqlite3.Connection | None = None
        self._write_lock = threading.Lock()
        self._backup_mutex = threading.Lock()
        self._vec_available = False

    def get_db(self) -> sqlite3.Connection:
        if self._connection is None:
            raise RuntimeError("MemoryDB not initialized — call init_db() first")
        return self._connection

    @property
    def write_lock(self) -> threading.Lock:
        return self._write_lock

    @property
    def vec_available(self) -> bool:
        return self._vec_available

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
        self._connection.execute("PRAGMA synchronous=FULL")

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

        self._load_sqlite_vec()
        self._migrate_schema()

        _instances[str(self.data_dir)] = self
        logger.info("MemoryDB initialized at %s (vec=%s)", self.db_path, self._vec_available)

    def _load_sqlite_vec(self) -> None:
        """Attempt to load sqlite-vec extension."""
        try:
            import sqlite_vec  # noqa: F401
            conn = self.get_db()
            conn.enable_load_extension(True)
            try:
                sqlite_vec.load(conn)
                self._vec_available = True
            finally:
                conn.enable_load_extension(False)
        except ImportError:
            logger.info("sqlite-vec not installed — vector search disabled")
        except Exception as e:
            logger.warning("sqlite-vec failed to load: %s", e)

    def _migrate_schema(self) -> None:
        """Apply incremental schema migrations."""
        conn = self.get_db()
        # Add content_hash column if missing
        try:
            conn.execute("SELECT content_hash FROM memory_documents LIMIT 0")
        except sqlite3.OperationalError:
            conn.execute("ALTER TABLE memory_documents ADD COLUMN content_hash TEXT")
            conn.commit()

        # Create vector table if sqlite-vec available
        if self._vec_available:
            try:
                conn.execute("SELECT chunk_id FROM memory_vectors LIMIT 0")
            except sqlite3.OperationalError:
                from .embeddings import DIMENSIONS
                conn.execute(
                    f"CREATE VIRTUAL TABLE IF NOT EXISTS memory_vectors USING vec0("
                    f"chunk_id INTEGER PRIMARY KEY, "
                    f"embedding float[{DIMENSIONS}] distance_metric=cosine)"
                )
                conn.commit()

        # Create observations table if missing
        try:
            conn.execute("SELECT 1 FROM observations LIMIT 0")
        except sqlite3.OperationalError:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS observations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    agent_slug TEXT NOT NULL,
                    observation TEXT NOT NULL,
                    source_conversation_id TEXT,
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    last_referenced_at TEXT,
                    reference_count INTEGER DEFAULT 0
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_obs_agent ON observations(agent_slug)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_obs_created ON observations(created_at DESC)")
            conn.commit()

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
        embed: bool = True,
    ) -> None:
        """Upsert a document into memory_documents and optionally create chunks/vectors.

        If embed=False, chunks are still created (for later backfill) but no
        embeddings are computed.
        """
        memory_type = validate_memory_type(memory_type)
        conn = self.get_db()
        content_hash = hashlib.sha256(content.encode()).hexdigest()

        with self._write_lock:
            # Check if content is unchanged
            existing = conn.execute(
                "SELECT id, content_hash FROM memory_documents WHERE source_type=? AND source_id=?",
                (source_type, source_id),
            ).fetchone()

            if existing and existing["content_hash"] == content_hash:
                # Content unchanged — check if chunks exist
                chunk_count = conn.execute(
                    "SELECT COUNT(*) FROM memory_chunks WHERE doc_id=?", (existing["id"],)
                ).fetchone()[0]
                if chunk_count > 0:
                    return  # Nothing to do

            # Upsert the document
            conn.execute(
                """INSERT INTO memory_documents
                       (source_type, source_id, title, content, memory_type, date, content_hash, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
                   ON CONFLICT(source_type, source_id)
                   DO UPDATE SET title=excluded.title,
                                 content=excluded.content,
                                 memory_type=excluded.memory_type,
                                 date=excluded.date,
                                 content_hash=excluded.content_hash,
                                 updated_at=datetime('now')""",
                (source_type, source_id, title, content, memory_type, date, content_hash),
            )
            conn.commit()

            # Get the doc_id
            row = conn.execute(
                "SELECT id FROM memory_documents WHERE source_type=? AND source_id=?",
                (source_type, source_id),
            ).fetchone()
            doc_id = row["id"]

            # Delete old chunks and their vectors
            old_chunks = conn.execute(
                "SELECT id FROM memory_chunks WHERE doc_id=?", (doc_id,)
            ).fetchall()
            if old_chunks and self._vec_available:
                for c in old_chunks:
                    try:
                        conn.execute("DELETE FROM memory_vectors WHERE chunk_id=?", (c["id"],))
                    except Exception:
                        pass
            conn.execute("DELETE FROM memory_chunks WHERE doc_id=?", (doc_id,))

            # Create new chunks
            chunks = _chunk_text(content)
            for i, chunk_text in enumerate(chunks):
                conn.execute(
                    "INSERT INTO memory_chunks (doc_id, chunk_index, content) VALUES (?, ?, ?)",
                    (doc_id, i, chunk_text),
                )
            conn.commit()

        # Embedding happens via backfill (avoids thread-safety issues with
        # fire-and-forget async tasks accessing the SQLite connection).

    def remove_document(self, source_type: str, source_id: str) -> None:
        """Remove a document and its chunks/vectors from all indexes."""
        conn = self.get_db()
        with self._write_lock:
            doc = conn.execute(
                "SELECT id FROM memory_documents WHERE source_type=? AND source_id=?",
                (source_type, source_id),
            ).fetchone()
            if doc:
                # Explicit vector deletion (virtual tables don't honor CASCADE)
                if self._vec_available:
                    chunks = conn.execute(
                        "SELECT id FROM memory_chunks WHERE doc_id=?", (doc["id"],)
                    ).fetchall()
                    for c in chunks:
                        try:
                            conn.execute("DELETE FROM memory_vectors WHERE chunk_id=?", (c["id"],))
                        except Exception:
                            pass
                conn.execute("DELETE FROM memory_chunks WHERE doc_id=?", (doc["id"],))
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
        """Rebuild FTS5 index from files on disk, preserving chunks/vectors for unchanged content.

        *ctx_manager* is a ContextManager instance for this agent.
        Called on startup after init_db().
        """
        conn = self.get_db()
        stats = {"documents_indexed": 0, "unchanged": 0, "removed": 0, "facts_reindexed": 0}

        # 1. Collect all files that should exist
        expected: dict[tuple[str, str], tuple[str, str, str | None, str | None]] = {}
        # Format: (source_type, source_id) → (title, content, memory_type, date)

        # MEMORY.md
        memory = ctx_manager.read_memory()
        if memory:
            expected[("memory", "MEMORY.md")] = ("MEMORY.md", memory, None, None)

        # Daily notes
        daily_dir = ctx_manager.daily_dir
        if daily_dir.exists():
            for f in sorted(daily_dir.glob("*.md")):
                note_date = f.stem
                content = f.read_text(encoding="utf-8", errors="replace")
                if content.strip():
                    expected[("daily", note_date)] = (note_date, content, None, note_date)

        # Topic files (skip soul.md, MEMORY.md, _-prefixed)
        skip = {"soul.md", "memory.md"}
        for f in sorted(ctx_manager.data_dir.glob("*.md")):
            if f.name.startswith("_") or f.name.lower() in skip:
                continue
            content = f.read_text(encoding="utf-8", errors="replace")
            if content.strip():
                expected[("topic", f.name)] = (f.name, content, None, None)

        # 2. Upsert expected docs (skipping unchanged ones)
        for (src_type, src_id), (title, content, mem_type, doc_date) in expected.items():
            new_hash = hashlib.sha256(content.encode()).hexdigest()
            existing = conn.execute(
                "SELECT id, content_hash FROM memory_documents WHERE source_type=? AND source_id=?",
                (src_type, src_id),
            ).fetchone()

            if existing and existing["content_hash"] == new_hash:
                stats["unchanged"] += 1
                continue

            self.index_document(src_type, src_id, title, content, memory_type=mem_type, date=doc_date, embed=False)
            stats["documents_indexed"] += 1

        # 3. Remove docs that no longer exist on disk
        all_docs = conn.execute(
            "SELECT source_type, source_id FROM memory_documents WHERE source_type != 'fact'"
        ).fetchall()
        for row in all_docs:
            key = (row["source_type"], row["source_id"])
            if key not in expected:
                self.remove_document(row["source_type"], row["source_id"])
                stats["removed"] += 1

        # 4. Re-index active facts
        fact_rows = conn.execute(
            "SELECT id, subject, predicate, object, valid_from, memory_type FROM facts WHERE valid_to IS NULL"
        ).fetchall()
        for row in fact_rows:
            self.index_document(
                "fact",
                str(row["id"]),
                f"{row['subject']} {row['predicate']}",
                f"{row['subject']} {row['predicate']} {row['object']}",
                memory_type=row["memory_type"],
                date=row["valid_from"],
                embed=False,
            )
            stats["facts_reindexed"] += 1

        logger.info("MemoryDB reindex complete: %s", stats)
        return stats

    # ------------------------------------------------------------------
    # Hybrid search (FTS5 + vector)
    # ------------------------------------------------------------------

    def hybrid_search(
        self,
        query: str,
        query_embedding: list[float] | None = None,
        source_type: str | None = None,
        memory_type: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 20,
    ) -> list[dict]:
        """Hybrid search combining FTS5 keyword + vector similarity via RRF."""
        # FTS5 results
        fts_results = self.search(
            query, source_type=source_type, memory_type=memory_type,
            date_from=date_from, date_to=date_to, limit=50,
        )

        # If no vector search possible, return FTS5 only
        if not self._vec_available or not query_embedding:
            return fts_results[:limit]

        # Vector results
        vec_results = self._vector_search(
            query_embedding, source_type=source_type, memory_type=memory_type,
            date_from=date_from, date_to=date_to, limit=50,
        )

        # RRF merge
        return self._rrf_merge(fts_results, vec_results, limit)

    def _vector_search(
        self,
        query_embedding: list[float],
        source_type: str | None = None,
        memory_type: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """KNN vector search with post-filtering."""
        conn = self.get_db()
        try:
            import sqlite_vec
            query_blob = sqlite_vec.serialize_float32(query_embedding)

            # Over-fetch to account for post-filtering
            rows = conn.execute(
                """SELECT v.chunk_id, v.distance, mc.doc_id
                   FROM memory_vectors v
                   JOIN memory_chunks mc ON mc.id = v.chunk_id
                   WHERE v.embedding MATCH ? AND k = 200""",
                (query_blob,),
            ).fetchall()

            # Post-filter and deduplicate by doc_id
            seen_docs: dict[int, float] = {}  # doc_id → best distance
            for row in rows:
                doc_id = row["doc_id"]
                distance = row["distance"]
                if doc_id not in seen_docs or distance < seen_docs[doc_id]:
                    seen_docs[doc_id] = distance

            if not seen_docs:
                return []

            # Hydrate document metadata and apply filters
            placeholders = ",".join("?" * len(seen_docs))
            sql = f"SELECT id, source_type, source_id, title, memory_type, date FROM memory_documents WHERE id IN ({placeholders})"
            params: list = list(seen_docs.keys())

            docs = conn.execute(sql, params).fetchall()

            results = []
            for doc in docs:
                # Apply filters
                if source_type and doc["source_type"] != source_type:
                    continue
                if memory_type and doc["memory_type"] != memory_type:
                    continue
                if date_from:
                    if not doc["date"] or doc["date"] < date_from:
                        continue
                if date_to:
                    if not doc["date"] or doc["date"] > date_to:
                        continue

                # Get snippet from best matching chunk
                chunk_snippet = self._get_chunk_snippet(doc["id"])
                results.append({
                    "id": doc["id"],
                    "source_type": doc["source_type"],
                    "source_id": doc["source_id"],
                    "title": doc["title"],
                    "memory_type": doc["memory_type"],
                    "date": doc["date"],
                    "snippet": chunk_snippet,
                    "rank": -1.0 / (1.0 + seen_docs[doc["id"]]),  # Convert distance to negative rank
                })

            # Sort by distance (best first)
            results.sort(key=lambda r: seen_docs[r["id"]])
            return results[:limit]

        except Exception as e:
            logger.warning("Vector search failed: %s", e)
            return []

    def _get_chunk_snippet(self, doc_id: int) -> str:
        """Get a 200-char snippet from the first chunk of a document."""
        conn = self.get_db()
        row = conn.execute(
            "SELECT content FROM memory_chunks WHERE doc_id=? ORDER BY chunk_index LIMIT 1",
            (doc_id,),
        ).fetchone()
        if row:
            text = row["content"]
            return text[:200] + "…" if len(text) > 200 else text
        return ""

    def _rrf_merge(self, fts_results: list[dict], vec_results: list[dict], limit: int) -> list[dict]:
        """Reciprocal Rank Fusion merge of FTS5 and vector results."""
        K = 60  # RRF constant
        scores: dict[int, float] = {}
        docs_by_id: dict[int, dict] = {}

        for rank, doc in enumerate(fts_results):
            doc_id = doc["id"]
            scores[doc_id] = scores.get(doc_id, 0) + 1.0 / (K + rank)
            docs_by_id[doc_id] = doc

        for rank, doc in enumerate(vec_results):
            doc_id = doc["id"]
            scores[doc_id] = scores.get(doc_id, 0) + 1.0 / (K + rank)
            if doc_id not in docs_by_id:
                docs_by_id[doc_id] = doc

        # Sort by RRF score descending
        sorted_ids = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)

        results = []
        for doc_id in sorted_ids[:limit]:
            doc = docs_by_id[doc_id]
            doc["rank"] = -scores[doc_id]  # Negative for BM25 compatibility
            results.append(doc)

        return results

    # ------------------------------------------------------------------
    # Vector backfill
    # ------------------------------------------------------------------

    async def backfill_embeddings(self, batch_size: int = 32) -> dict:
        """Embed chunks that are missing vectors. Returns {processed, remaining}."""
        if not self._vec_available:
            return {"processed": 0, "remaining": 0, "error": "sqlite-vec not available"}

        from .embeddings import get_embedding_service
        service = get_embedding_service()
        if not await service.is_available():
            return {"processed": 0, "remaining": 0, "error": "no embedding provider"}

        conn = self.get_db()

        # Find chunks without vectors
        rows = conn.execute(
            """SELECT mc.id, mc.content
               FROM memory_chunks mc
               LEFT JOIN memory_vectors mv ON mv.chunk_id = mc.id
               WHERE mv.chunk_id IS NULL
               LIMIT ?""",
            (batch_size,),
        ).fetchall()

        if not rows:
            return {"processed": 0, "remaining": 0}

        texts = [r["content"] for r in rows]
        embeddings = await service.embed(texts)
        if not embeddings:
            return {"processed": 0, "remaining": len(rows), "error": "embedding call failed"}

        import sqlite_vec
        processed = 0
        with self._write_lock:
            for row, embedding in zip(rows, embeddings):
                try:
                    conn.execute(
                        "INSERT OR REPLACE INTO memory_vectors (chunk_id, embedding) VALUES (?, ?)",
                        (row["id"], sqlite_vec.serialize_float32(embedding)),
                    )
                    processed += 1
                except Exception as e:
                    logger.debug("Vector insert failed for chunk %d: %s", row["id"], e)
            conn.commit()

        # Count remaining
        remaining = conn.execute(
            """SELECT COUNT(*) FROM memory_chunks mc
               LEFT JOIN memory_vectors mv ON mv.chunk_id = mc.id
               WHERE mv.chunk_id IS NULL""",
        ).fetchone()[0]

        result = {"processed": processed, "remaining": remaining}
        if processed == 0 and remaining > 0:
            result["error"] = "all row inserts failed"
        return result

    async def check_embedding_config(self) -> None:
        """Check if embedding provider changed; invalidate vectors if so."""
        if not self._vec_available:
            return

        from .embeddings import get_embedding_service
        service = get_embedding_service()
        if not await service.is_available():
            return

        info = service.get_provider_info()
        if not info:
            return

        conn = self.get_db()
        stored = conn.execute("SELECT provider, model FROM memory_embedding_config WHERE id=1").fetchone()

        if stored:
            if stored["provider"] != info["provider"] or stored["model"] != info["model"]:
                logger.info(
                    "Embedding provider changed (%s/%s → %s/%s) — invalidating vectors",
                    stored["provider"], stored["model"], info["provider"], info["model"],
                )
                with self._write_lock:
                    # Drop and recreate vector table (dimensions may have changed)
                    conn.execute("DROP TABLE IF EXISTS memory_vectors")
                    conn.execute(
                        f"CREATE VIRTUAL TABLE memory_vectors USING vec0("
                        f"chunk_id INTEGER PRIMARY KEY, "
                        f"embedding float[{info['dimensions']}] distance_metric=cosine)"
                    )
                    conn.execute("DELETE FROM memory_embedding_config WHERE id=1")
                    conn.execute(
                        "INSERT INTO memory_embedding_config (id, provider, model, dimensions) VALUES (1, ?, ?, ?)",
                        (info["provider"], info["model"], info["dimensions"]),
                    )
                    conn.commit()
        else:
            with self._write_lock:
                conn.execute(
                    "INSERT OR REPLACE INTO memory_embedding_config (id, provider, model, dimensions) VALUES (1, ?, ?, ?)",
                    (info["provider"], info["model"], info["dimensions"]),
                )
                conn.commit()

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

    # ------------------------------------------------------------------
    # Observations
    # ------------------------------------------------------------------

    def get_observations(self, agent_slug: str, limit: int = 50) -> list[dict]:
        conn = self.get_db()
        rows = conn.execute(
            "SELECT * FROM observations WHERE agent_slug = ? ORDER BY created_at DESC LIMIT ?",
            (agent_slug, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def add_observation(
        self, agent_slug: str, observation: str, source_conversation_id: str | None = None,
    ) -> dict | None:
        observation = observation[:200]
        # Reject observations carrying prompt-injection patterns before they can
        # be persisted and later injected into the system prompt.
        try:
            from core.agents.security.scanner import scan_content
            clean = scan_content(observation).clean
        except Exception as e:
            # Fail closed: if the scanner is unavailable we cannot vouch for the
            # observation, and it would otherwise land in the system prompt.
            logger.warning("add_observation: scanner unavailable, rejecting for %s: %s", agent_slug, e)
            return None
        if not clean:
            logger.warning("add_observation: rejected injection pattern for %s", agent_slug)
            return None
        normalized = " ".join(observation.lower().strip().split())
        conn = self.get_db()

        with self._write_lock:
            existing = conn.execute(
                "SELECT observation FROM observations WHERE agent_slug = ?", (agent_slug,),
            ).fetchall()
            for row in existing:
                if " ".join(row["observation"].lower().strip().split()) == normalized:
                    return None

            cursor = conn.execute(
                "INSERT INTO observations (agent_slug, observation, source_conversation_id) VALUES (?, ?, ?)",
                (agent_slug, observation, source_conversation_id),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM observations WHERE id = ?", (cursor.lastrowid,)).fetchone()
            return dict(row) if row else None

    def delete_observation(self, obs_id: int, agent_slug: str | None = None) -> bool:
        conn = self.get_db()
        with self._write_lock:
            if agent_slug:
                cursor = conn.execute(
                    "DELETE FROM observations WHERE id = ? AND agent_slug = ?",
                    (obs_id, agent_slug),
                )
            else:
                cursor = conn.execute("DELETE FROM observations WHERE id = ?", (obs_id,))
            conn.commit()
        if cursor.rowcount > 0:
            self.backup_to_gcs()
            return True
        return False

    def increment_observation_references(self, obs_ids: list[int], min_interval_minutes: int = 60) -> None:
        """Bump usage metadata for the given observations, throttled to at most
        once per min_interval_minutes each. Runs on every interactive prompt
        build, so the cheap read avoids a synchronous(FULL) fsync commit on
        turns where nothing is due for an update."""
        if not obs_ids:
            return
        conn = self.get_db()
        placeholders = ",".join("?" for _ in obs_ids)
        # Cheap read (no fsync) to find which observations are actually due.
        due = conn.execute(
            f"SELECT id FROM observations WHERE id IN ({placeholders}) "
            f"AND (last_referenced_at IS NULL OR last_referenced_at < datetime('now', ?))",
            (*obs_ids, f"-{min_interval_minutes} minutes"),
        ).fetchall()
        if not due:
            return
        due_ids = [r["id"] for r in due]
        due_placeholders = ",".join("?" for _ in due_ids)
        with self._write_lock:
            conn.execute(
                f"UPDATE observations SET reference_count = reference_count + 1, "
                f"last_referenced_at = datetime('now') WHERE id IN ({due_placeholders})",
                due_ids,
            )
            conn.commit()

    def prune_stale_observations(self, max_age_days: int = 90, min_idle_days: int = 30) -> int:
        """Delete observations older than max_age_days, unless they have been
        referenced (surfaced in a prompt) within the last min_idle_days — so
        durable, actively-used knowledge is preserved past the age cutoff."""
        conn = self.get_db()
        with self._write_lock:
            cursor = conn.execute(
                "DELETE FROM observations "
                "WHERE created_at < datetime('now', ?) "
                "AND (last_referenced_at IS NULL OR last_referenced_at < datetime('now', ?))",
                (f"-{max_age_days} days", f"-{min_idle_days} days"),
            )
            conn.commit()
        return cursor.rowcount
