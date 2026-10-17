"""Action journal: at-most-once execution for /actions and /browser/act.

Every action carries a ULID `action_id`. The id is reserved atomically with the payload's
sha256 before anything runs, then moves reserved -> executing -> done | failed. A repeat with the
same payload gets the stored outcome; the same id with a different payload is a conflict. Rows
still in flight when the process died become `unknown` and are never re-run.
"""
import hashlib
import json
import sqlite3
import threading
import time

ULID_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
MAX_ID_AGE_S = 24 * 3600
PRUNE_AFTER_S = 7 * 24 * 3600


def ulid_time_ms(action_id) -> int | None:
    """Creation time encoded in a ULID, or None if the string isn't one."""
    if not isinstance(action_id, str) or len(action_id) != 26:
        return None
    s = action_id.upper()
    if s[0] > "7" or any(c not in ULID_ALPHABET for c in s):
        return None
    t = 0
    for c in s[:10]:
        t = t * 32 + ULID_ALPHABET.index(c)
    return t


def payload_hash(payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


class Journal:
    def __init__(self, path: str):
        self._lock = threading.Lock()
        self._db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute(
            """CREATE TABLE IF NOT EXISTS actions (
                 id TEXT PRIMARY KEY,
                 payload_sha256 TEXT NOT NULL,
                 status TEXT NOT NULL,
                 http_status INTEGER,
                 response TEXT,
                 created_at REAL NOT NULL,
                 updated_at REAL NOT NULL)"""
        )
        now = time.time()
        self._db.execute(
            "UPDATE actions SET status='unknown', updated_at=? WHERE status IN ('reserved','executing')",
            (now,),
        )
        self._db.execute("DELETE FROM actions WHERE created_at < ?", (now - PRUNE_AFTER_S,))

    def validate_id(self, action_id) -> str | None:
        """Error code for an unusable id, or None."""
        t = ulid_time_ms(action_id)
        if t is None:
            return "action_id_invalid"
        if t < (time.time() - MAX_ID_AGE_S) * 1000:
            return "action_id_expired"
        return None

    def reserve(self, action_id: str, sha: str) -> tuple[str, dict | None]:
        """Returns ("reserved", None) when this caller owns the id, ("replay", row) for a
        same-payload repeat, ("conflict", row) when the payload differs."""
        with self._lock:
            now = time.time()
            cur = self._db.execute(
                "INSERT OR IGNORE INTO actions (id, payload_sha256, status, created_at, updated_at)"
                " VALUES (?, ?, 'reserved', ?, ?)",
                (action_id, sha, now, now),
            )
            if cur.rowcount == 1:
                return "reserved", None
            row = self.get(action_id)
            return ("replay" if row["payload_sha256"] == sha else "conflict"), row

    def set_status(self, action_id: str, status: str, http_status: int | None = None, response: dict | None = None):
        with self._lock:
            self._db.execute(
                "UPDATE actions SET status=?, http_status=?, response=?, updated_at=? WHERE id=?",
                (status, http_status, json.dumps(response) if response is not None else None, time.time(), action_id),
            )

    def get(self, action_id: str) -> dict | None:
        row = self._db.execute("SELECT * FROM actions WHERE id=?", (action_id,)).fetchone()
        if row is None:
            return None
        d = dict(row)
        d["response"] = json.loads(d["response"]) if d["response"] else None
        return d
