"""
Chatty — Claude Code connector job store (SQLite).

Jobs that agents delegate to the user's own Claude Code / Codex, picked up by
the external `chatty-connector` over /api/connector. Plus a small key-value
`connector_state` table (last_seen, version, runners, capabilities,
pair_generation).

finish_job() is the ONLY code path that makes a job terminal — /result, lost
and stale jobs, disconnect, re-pair, claim-time policy cancels and user
cancels all go through it, so the completion notify matrix lives in one place.
"""

import json
import logging
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from core.storage import safe_init_sqlite

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "claude_code"
DB_PATH = DATA_DIR / "jobs.db"
GCS_KEY = "claude_code/jobs.db"

TERMINAL_STATUSES = ("done", "failed", "cancelled", "expired")
LEVELS = ("look", "sandbox", "full")  # job `mode` values, least to most power
APPROVAL_TTL_HOURS = 24
ONLINE_WINDOW_S = 90  # the connector polls every 5 s (with backoff)

_connection: sqlite3.Connection | None = None
# Guards every use of the one shared connection — reads too: concurrent cursors
# on a shared sqlite3 connection fail ("bad parameter or other API misuse").
# Re-entrant: finish_job takes it itself and is also called from inside the
# /poll claim loop and the disconnect / re-pair transitions.
_write_lock = threading.RLock()
_init_lock = threading.Lock()


def get_db() -> sqlite3.Connection:
    """Return the connection, lazily initializing if needed."""
    if _connection is None:
        with _init_lock:
            if _connection is None:
                init_db()
    assert _connection is not None
    return _connection


_JOBS_COLUMNS = """(
            id                    TEXT PRIMARY KEY,
            agent_slug            TEXT NOT NULL DEFAULT '',
            conversation_id       TEXT,
            route                 TEXT,
            origin                TEXT NOT NULL CHECK(origin IN ('user','background','system')),
            runner                TEXT NOT NULL,
            mode                  TEXT NOT NULL CHECK(mode IN ('look','sandbox','full')),
            task                  TEXT NOT NULL,
            prompt                TEXT NOT NULL,
            parent_job_id         TEXT,
            root_job_id           TEXT NOT NULL,
            session_id            TEXT,
            pair_generation       INTEGER,
            status                TEXT NOT NULL CHECK(status IN ('pending_approval','queued','running',
                                                               'done','failed','cancelled','expired')),
            cancel_requested      INTEGER NOT NULL DEFAULT 0,
            finish_reason         TEXT,
            completion_status     TEXT NOT NULL DEFAULT 'none'
                                  CHECK(completion_status IN ('none','pending','running','done')),
            completion_claimed_at TEXT,
            completion_attempts   INTEGER NOT NULL DEFAULT 0,
            summary_text          TEXT,
            created_at            TEXT NOT NULL DEFAULT (datetime('now')),
            claimed_at            TEXT,
            last_reported_at      TEXT,
            finished_at           TEXT,
            result_text           TEXT,
            error                 TEXT,
            usage_json            TEXT,
            approval_expires_at   TEXT,
            approval_ref          TEXT,
            decision              TEXT,
            decided_by            TEXT,
            decided_via           TEXT,
            decided_at            TEXT,
            approved_prompt_sha256 TEXT
        )"""


def _migrate_safe_mode(conn: sqlite3.Connection) -> None:
    """PR 1 DBs: mode CHECK was ('safe','full'). SQLite can't ALTER a CHECK, so
    rebuild the table, mapping safe → sandbox."""
    row = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='jobs'").fetchone()
    if not row or "'safe'" not in row[0]:
        return
    # simplification: one-shot rebuild migration
    cols = [r[1] for r in conn.execute("PRAGMA table_info(jobs)")]
    select = ", ".join("CASE mode WHEN 'safe' THEN 'sandbox' ELSE mode END" if c == "mode" else c for c in cols)
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(f"CREATE TABLE jobs_v2 {_JOBS_COLUMNS}")
        conn.execute(f"INSERT INTO jobs_v2 ({', '.join(cols)}) SELECT {select} FROM jobs ORDER BY rowid")
        conn.execute("DROP TABLE jobs")
        conn.execute("ALTER TABLE jobs_v2 RENAME TO jobs")
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    logger.info("Claude Code jobs: migrated mode 'safe' → 'sandbox'")


def _setup_connection() -> None:
    """Open connection, set PRAGMAs, create schema."""
    global _connection
    _connection = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    _connection.row_factory = sqlite3.Row
    _connection.execute("PRAGMA journal_mode=WAL")
    _connection.execute("PRAGMA busy_timeout=5000")
    _connection.execute("PRAGMA synchronous=FULL")

    _migrate_safe_mode(_connection)
    _connection.executescript(f"""
        CREATE TABLE IF NOT EXISTS jobs {_JOBS_COLUMNS};
        CREATE INDEX IF NOT EXISTS idx_cc_jobs_status ON jobs(status);
        CREATE INDEX IF NOT EXISTS idx_cc_jobs_agent ON jobs(agent_slug, created_at);
        CREATE INDEX IF NOT EXISTS idx_cc_jobs_root ON jobs(root_job_id);
        CREATE INDEX IF NOT EXISTS idx_cc_jobs_completion ON jobs(completion_status);

        CREATE TABLE IF NOT EXISTS connector_state (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
    """)
    _connection.commit()
    logger.info("Claude Code jobs DB initialized at %s", DB_PATH)


def init_db() -> dict:
    """Initialize with integrity check + GCS download-on-missing."""
    return safe_init_sqlite(DB_PATH, GCS_KEY, init_fn=_setup_connection)


def close_db() -> None:
    """Close the jobs DB connection (for backup/restore)."""
    global _connection
    if _connection:
        _connection.close()
        _connection = None


def write_lock() -> threading.RLock:
    return _write_lock


def query(sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    with _write_lock:
        return get_db().execute(sql, params).fetchall()


# ── connector_state ──────────────────────────────────────────────────────────

def get_state(key: str, default=None):
    rows = query("SELECT value FROM connector_state WHERE key = ?", (key,))
    return json.loads(rows[0]["value"]) if rows else default


def set_state(key: str, value, *, commit: bool = True) -> None:
    db = get_db()
    with _write_lock:
        db.execute(
            "INSERT OR REPLACE INTO connector_state (key, value) VALUES (?, ?)",
            (key, json.dumps(value)),
        )
        if commit:
            db.commit()


def generation() -> int:
    return int(get_state("pair_generation", 0))


def is_online() -> bool:
    return time.time() - float(get_state("last_seen", 0)) < ONLINE_WINDOW_S


# ── policy (creds file `claude_code.json`) ───────────────────────────────────

def creds() -> dict:
    from integrations.registry import get_credentials
    return get_credentials("claude_code")


def policy_error(agent_slug: str) -> str | None:
    """Why this agent may not run Claude Code jobs right now, or None."""
    c = creds()
    if not (c.get("enabled") and c.get("token_hash")):
        return "Claude Code is not connected or is disabled."
    if agent_slug in (c.get("disabled_agents") or []):
        return "Claude Code is turned off for this agent."
    return None


def level_rank(level: str | None) -> int:
    """Position in LEVELS; -1 for anything unknown (an unreported ceiling allows nothing)."""
    return LEVELS.index(level) if level in LEVELS else -1


def access_level() -> str:
    """The owner's choice on the card (creds `access_level`, default sandbox)."""
    return creds().get("access_level") or "sandbox"


def ceiling() -> str | None:
    """The highest level the connector's machine allows, from its last poll (None: not reported)."""
    return get_state("ceiling")


def default_level() -> str:
    """sandbox, or lower if the access level or a reported ceiling is lower."""
    ranks = [level_rank("sandbox"), level_rank(access_level())]
    if ceiling():
        ranks.append(level_rank(ceiling()))
    return LEVELS[max(0, min(ranks))]


def level_error(level: str, origin: str) -> str | None:
    """Why a job at `level` from `origin` may not be queued right now, or None."""
    if level not in LEVELS:
        return f"level must be one of {', '.join(LEVELS)}"
    if level_rank(level) > level_rank(access_level()):
        return f"The owner has set Claude Code access to '{access_level()}'; '{level}' is above it."
    top = ceiling()
    # Unreported ceiling (fresh pair, or a 0.1.x connector): sandbox and below may queue; claim rechecks.
    if level_rank(level) > level_rank(top or "sandbox"):
        host = creds().get("host") or "the connector's machine"
        return (f"{host} allows up to '{top or 'sandbox'}'. The owner can raise it by running "
                f"`chatty-connector setup` there.")
    if level == "full" and origin != "user":  # background, proactive and completion turns cap at sandbox
        return "Full access is only for jobs the user asked for in chat — background work stays at sandbox."
    return None


# ── jobs ─────────────────────────────────────────────────────────────────────

def get_job(job_id: str) -> dict | None:
    rows = query("SELECT * FROM jobs WHERE id = ?", (job_id,))
    return dict(rows[0]) if rows else None


def insert_job(*, agent_slug: str, origin: str, runner: str, mode: str, task: str, prompt: str,
               conversation_id: str | None = None, route: dict | None = None,
               parent: dict | None = None, status: str = "queued", commit: bool = True) -> str:
    job_id = uuid.uuid4().hex[:12]
    db = get_db()
    with _write_lock:
        db.execute(
            """INSERT INTO jobs (id, agent_slug, conversation_id, route, origin, runner, mode,
                                 task, prompt, parent_job_id, root_job_id, status, approval_expires_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                       CASE WHEN ? = 'pending_approval' THEN datetime('now', ?) END)""",
            (job_id, agent_slug, conversation_id, json.dumps(route) if route else None,
             origin, runner, mode, task, prompt,
             parent["id"] if parent else None,
             parent["root_job_id"] if parent else job_id, status, status, f"+{APPROVAL_TTL_HOURS} hours"),
        )
        if commit:
            db.commit()
    return job_id


_RESULT_FIELDS = ("result_text", "session_id", "usage_json", "error", "cancel_requested")


def finish_job(job_id: str, status: str, reason: str, *, notify: bool,
               running_generation: int | None = None, commit: bool = True, **fields) -> bool:
    """Make a job terminal. Returns False if it was already terminal (first write wins).

    notify=True queues the completion turn (completion_status='pending') in the
    same UPDATE, except for system-origin jobs (no agent to tell). running_generation restricts the transition to a job that is
    `running` under that pairing (the /result path). Extra fields: any of
    _RESULT_FIELDS (session_id is kept when not given).
    """
    assert status in TERMINAL_STATUSES
    bad = set(fields) - set(_RESULT_FIELDS)
    if bad:
        raise ValueError(f"finish_job: unknown fields {bad}")
    sets = ["status = ?", "finish_reason = ?", "finished_at = datetime('now')"]
    params: list = [status, reason]
    db = get_db()
    row = db.execute("SELECT origin FROM jobs WHERE id = ?", (job_id,)).fetchone()
    notify = notify and not (row and row["origin"] == "system")
    if notify:
        sets.append("completion_status = 'pending'")
    for k, v in fields.items():
        sets.append(f"{k} = COALESCE(?, {k})")
        params.append(v)
    where = "id = ? AND status IN ('pending_approval','queued','running')"
    params.append(job_id)
    if running_generation is not None:
        where += " AND status = 'running' AND pair_generation = ?"
        params.append(running_generation)

    with _write_lock:
        changed = db.execute(f"UPDATE jobs SET {', '.join(sets)} WHERE {where}", params).rowcount == 1
        if commit:
            db.commit()
    if changed and notify and commit:
        from .completion import submit
        submit(job_id)
    return changed


def iso_z(v) -> str | None:
    """API timestamp: ISO-8601 UTC with 'Z'. Accepts SQLite datetime('now') text
    (naive UTC), an aware isoformat string, or epoch seconds."""
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        dt = datetime.fromtimestamp(v, timezone.utc)
    else:
        dt = datetime.fromisoformat(str(v).replace(" ", "T"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def job_view(job: dict, *, result_chars: int = 2000) -> dict:
    """Public shape of a job row (card + tools)."""
    out = {k: job[k] for k in (
        "id", "agent_slug", "origin", "runner", "mode", "status", "task", "finish_reason",
        "error", "session_id", "parent_job_id", "root_job_id", "conversation_id",
    )}
    for k in ("created_at", "claimed_at", "finished_at"):
        out[k] = iso_z(job[k])
    out["result_text"] = (job["result_text"] or "")[:result_chars]
    out["result_truncated"] = len(job["result_text"] or "") > result_chars
    out["workdir_key"] = job["root_job_id"]
    out["usage"] = json.loads(job["usage_json"]) if job["usage_json"] else None
    return out
