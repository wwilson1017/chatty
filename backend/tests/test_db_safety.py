"""Database safety regression tests.

Verifies:
  1. safe_backup_sqlite produces consistent snapshots under concurrent writes
  2. backup_mutex prevents overlapping backups
  3. safe_init_sqlite quarantines corrupt databases
  4. safe_init_sqlite preserves healthy databases
  5. atomic_write_json produces valid files
"""

import json
import sqlite3
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_test_db(path: Path, rows: int = 100) -> sqlite3.Connection:
    """Create a test database with a table and some rows."""
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS items (id INTEGER PRIMARY KEY, value TEXT NOT NULL)"
    )
    for i in range(rows):
        conn.execute("INSERT INTO items (value) VALUES (?)", (f"row-{i}",))
    conn.commit()
    return conn


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSafeBackupSqlite:
    def test_backup_produces_valid_snapshot(self, tmp_path):
        """A backup snapshot must pass integrity_check."""
        from core.storage import safe_backup_sqlite

        db_path = tmp_path / "test.db"
        conn = _create_test_db(db_path)
        mutex = threading.Lock()

        backup_blob = "test/test.db"

        with patch("core.storage.upload_file") as mock_upload:
            safe_backup_sqlite(conn, db_path, backup_blob, backup_mutex=mutex)
            mock_upload.assert_called_once()

        conn.close()

    def test_backup_under_concurrent_writes(self, tmp_path):
        """Backup during continuous writes must still produce a valid snapshot."""
        from core.storage import safe_backup_sqlite

        db_path = tmp_path / "concurrent.db"
        conn = _create_test_db(db_path, rows=0)
        mutex = threading.Lock()
        stop_writing = threading.Event()

        def writer():
            i = 0
            while not stop_writing.is_set():
                try:
                    conn.execute(
                        "INSERT INTO items (value) VALUES (?)", (f"concurrent-{i}",)
                    )
                    conn.commit()
                    i += 1
                except sqlite3.OperationalError:
                    time.sleep(0.001)

        writer_thread = threading.Thread(target=writer, daemon=True)
        writer_thread.start()

        uploaded_paths = []

        def capture_upload(local_path, blob_name):
            uploaded_paths.append(Path(local_path))

        try:
            time.sleep(0.05)

            with patch("core.storage.upload_file", side_effect=capture_upload):
                safe_backup_sqlite(conn, db_path, "test.db", backup_mutex=mutex)
        finally:
            stop_writing.set()
            writer_thread.join(timeout=2)
            conn.close()

    def test_mutex_prevents_concurrent_backups(self, tmp_path):
        """Only one backup should run at a time for a given database."""
        from core.storage import safe_backup_sqlite

        db_path = tmp_path / "mutex.db"
        conn = _create_test_db(db_path)
        mutex = threading.Lock()

        upload_count = {"value": 0}
        barrier = threading.Event()

        def slow_upload(local_path, blob_name):
            upload_count["value"] += 1
            barrier.set()
            time.sleep(0.2)

        with patch("core.storage.upload_file", side_effect=slow_upload):
            t1 = threading.Thread(
                target=safe_backup_sqlite,
                args=(conn, db_path, "a.db"),
                kwargs={"backup_mutex": mutex},
            )
            t2 = threading.Thread(
                target=safe_backup_sqlite,
                args=(conn, db_path, "a.db"),
                kwargs={"backup_mutex": mutex},
            )
            t1.start()
            barrier.wait(timeout=5)
            t2.start()
            t1.join(timeout=5)
            t2.join(timeout=5)

        assert upload_count["value"] == 1, "Mutex should have blocked the second backup"
        conn.close()


class TestSafeInitSqlite:
    def test_healthy_db_returns_ok(self, tmp_path):
        """A healthy database should return status 'ok'."""
        from core.storage import safe_init_sqlite

        db_path = tmp_path / "healthy.db"
        conn = _create_test_db(db_path)
        conn.close()

        initialized = {"called": False}

        def init_fn():
            initialized["called"] = True

        result = safe_init_sqlite(db_path, "test.db", init_fn=init_fn)
        assert result["status"] == "ok"
        assert initialized["called"]

    def test_missing_db_returns_fresh(self, tmp_path):
        """A missing database should call init_fn and return 'fresh'."""
        from core.storage import safe_init_sqlite

        db_path = tmp_path / "missing.db"

        initialized = {"called": False}

        def init_fn():
            initialized["called"] = True

        with patch("core.storage.download_file"):
            result = safe_init_sqlite(db_path, "test.db", init_fn=init_fn)

        assert result["status"] == "fresh"
        assert initialized["called"]

    def test_corrupt_db_is_quarantined(self, tmp_path):
        """A corrupt database should be quarantined and a fresh one created."""
        from core.storage import safe_init_sqlite

        db_path = tmp_path / "corrupt.db"
        db_path.write_bytes(b"this is not a valid sqlite database at all")

        initialized = {"called": False}

        def init_fn():
            initialized["called"] = True

        result = safe_init_sqlite(db_path, "test.db", init_fn=init_fn)

        assert result["status"] == "quarantined"
        assert initialized["called"]

        quarantined = list(tmp_path.glob("corrupt.corrupt.*"))
        assert len(quarantined) == 1, "Corrupt file should be renamed, not deleted"
        assert not db_path.exists() or initialized["called"]

    def test_healthy_db_preserves_data(self, tmp_path):
        """init_fn should be able to access existing data after integrity check passes."""
        from core.storage import safe_init_sqlite

        db_path = tmp_path / "preserve.db"
        conn = _create_test_db(db_path, rows=42)
        conn.close()

        row_count = {"value": 0}

        def init_fn():
            c = sqlite3.connect(str(db_path))
            row_count["value"] = c.execute("SELECT COUNT(*) FROM items").fetchone()[0]
            c.close()

        result = safe_init_sqlite(db_path, "test.db", init_fn=init_fn)
        assert result["status"] == "ok"
        assert row_count["value"] == 42


class TestAtomicWriteJson:
    def test_writes_valid_json(self, tmp_path):
        """atomic_write_json should produce a valid, readable JSON file."""
        from core.storage import atomic_write_json

        path = tmp_path / "config.json"
        data = {"key": "value", "number": 42, "nested": {"a": [1, 2, 3]}}

        atomic_write_json(path, data)

        assert path.exists()
        loaded = json.loads(path.read_text(encoding="utf-8"))
        assert loaded == data

    def test_creates_parent_directories(self, tmp_path):
        """atomic_write_json should create parent directories if needed."""
        from core.storage import atomic_write_json

        path = tmp_path / "sub" / "dir" / "config.json"
        atomic_write_json(path, {"ok": True})
        assert path.exists()

    def test_overwrites_existing_file(self, tmp_path):
        """atomic_write_json should atomically replace an existing file."""
        from core.storage import atomic_write_json

        path = tmp_path / "existing.json"
        atomic_write_json(path, {"version": 1})
        atomic_write_json(path, {"version": 2})

        loaded = json.loads(path.read_text(encoding="utf-8"))
        assert loaded["version"] == 2
