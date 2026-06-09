"""Tests for fact trust scoring: retrieval tracking, confidence decay, sort order."""

import sqlite3
from pathlib import Path
from unittest.mock import patch

from core.agents.memory.db import MemoryDB, _SCHEMA


def _make_db(tmp_path: Path) -> MemoryDB:
    db = MemoryDB(tmp_path, "test")
    conn = sqlite3.connect(str(tmp_path / "memory.db"), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(_SCHEMA)
    conn.commit()
    db._connection = conn
    db._vec_available = False
    db._migrate_schema()
    return db


def test_retrieval_count_increments(tmp_path):
    db = _make_db(tmp_path)
    result = db.add_fact("Alice", "works at", "Acme")
    fact_id = result["id"]

    # Query twice
    db.query_facts(subject="Alice")
    db.query_facts(subject="Alice")

    conn = db.get_db()
    row = conn.execute("SELECT retrieval_count, last_retrieved_at FROM facts WHERE id=?", (fact_id,)).fetchone()
    assert row["retrieval_count"] == 2
    assert row["last_retrieved_at"] is not None


def test_query_sorts_by_confidence(tmp_path):
    db = _make_db(tmp_path)
    db.add_fact("A", "is", "low", confidence=0.3)
    db.add_fact("B", "is", "high", confidence=0.9)
    db.add_fact("C", "is", "medium", confidence=0.6)

    results = db.query_facts()
    objects = [r["object"] for r in results]
    assert objects == ["high", "medium", "low"]


def test_decay_stale_confidence(tmp_path):
    db = _make_db(tmp_path)
    db.add_fact("Old", "is", "stale", confidence=0.8)

    # Backdate created_at and ensure no retrieval
    conn = db.get_db()
    conn.execute("UPDATE facts SET created_at = datetime('now', '-90 days')")
    conn.commit()

    result = db.decay_stale_confidence(stale_days=60, decay_amount=0.1, floor=0.3)
    assert result["decayed"] == 1

    row = conn.execute("SELECT confidence FROM facts WHERE subject='Old'").fetchone()
    assert abs(row["confidence"] - 0.7) < 0.01


def test_decay_respects_floor(tmp_path):
    db = _make_db(tmp_path)
    db.add_fact("Bottom", "is", "low", confidence=0.35)

    conn = db.get_db()
    conn.execute("UPDATE facts SET created_at = datetime('now', '-90 days')")
    conn.commit()

    db.decay_stale_confidence(stale_days=60, decay_amount=0.1, floor=0.3)

    row = conn.execute("SELECT confidence FROM facts WHERE subject='Bottom'").fetchone()
    assert row["confidence"] >= 0.3


def test_decay_skips_recently_retrieved(tmp_path):
    db = _make_db(tmp_path)
    db.add_fact("Active", "is", "used", confidence=0.8)

    # Set old created_at but recent retrieval
    conn = db.get_db()
    conn.execute(
        "UPDATE facts SET created_at = datetime('now', '-90 days'), "
        "last_retrieved_at = datetime('now')"
    )
    conn.commit()

    result = db.decay_stale_confidence(stale_days=60)
    assert result["decayed"] == 0


def test_decay_skips_new_facts(tmp_path):
    db = _make_db(tmp_path)
    db.add_fact("Fresh", "is", "new", confidence=0.8)
    # Don't backdate — fact was just created
    result = db.decay_stale_confidence(stale_days=60)
    assert result["decayed"] == 0

    conn = db.get_db()
    row = conn.execute("SELECT confidence FROM facts WHERE subject='Fresh'").fetchone()
    assert row["confidence"] == 0.8


def test_new_columns_exist_after_migration(tmp_path):
    db = _make_db(tmp_path)
    conn = db.get_db()
    row = conn.execute("SELECT retrieval_count, last_retrieved_at FROM facts LIMIT 0").fetchone()
    # No exception means columns exist
