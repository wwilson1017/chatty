"""
Chatty — Chat history SQLite connection with WAL mode and GCS backup/restore.

Thread safety: a single connection is shared across threads (check_same_thread=False).
WAL mode allows concurrent reads. All writes go through _write_lock so only one
thread writes at a time; busy_timeout handles any residual contention from WAL
checkpoints.

Each agent instantiates its own ChatHistoryDB with a separate db_path and
gcs_prefix, so databases are fully isolated.
"""

import logging
import sqlite3
import threading
from pathlib import Path

from core.storage import download_file, upload_file

logger = logging.getLogger(__name__)


class ChatHistoryDB:
    """Per-agent chat history database with SQLite WAL mode and GCS sync."""

    def __init__(self, data_dir: Path, gcs_prefix: str, db_filename: str = "chat.db"):
        self.data_dir = data_dir
        self.db_path = data_dir / db_filename
        self.gcs_key = gcs_prefix + db_filename
        self._connection: sqlite3.Connection | None = None
        self._write_lock = threading.Lock()

    def get_db(self) -> sqlite3.Connection:
        """Return the singleton SQLite connection."""
        if self._connection is None:
            raise RuntimeError("Chat history DB not initialized — call init_db() first")
        return self._connection

    def write_lock(self) -> threading.Lock:
        """Return the write lock for callers that need atomic read-then-write."""
        return self._write_lock

    def init_db(self) -> None:
        """Initialize the database: restore from GCS if available, create schema."""
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # Try to restore from GCS (no-op locally if CONFIG_BUCKET not set)
        if not self.db_path.exists():
            download_file(self.db_path, self.gcs_key)

        self._connection = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA foreign_keys=ON")
        self._connection.execute("PRAGMA busy_timeout=5000")

        self._create_schema(self._connection)
        logger.info("Chat history DB initialized at %s", self.db_path)

    def backup_to_gcs(self) -> None:
        """Checkpoint WAL then upload the DB file to GCS."""
        if self._connection is not None:
            try:
                self._connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except Exception as e:
                logger.warning("WAL checkpoint before backup failed: %s", e)
        upload_file(self.db_path, self.gcs_key)

    @staticmethod
    def _create_schema(conn: sqlite3.Connection) -> None:
        """Create tables if they don't exist."""
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL DEFAULT 'New conversation',
                title_edited_by_user INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_conv_updated ON conversations(updated_at DESC);

            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                role TEXT NOT NULL,
                content TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                seq INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_msg_conv ON messages(conversation_id, seq);
        """)
        conn.commit()
