"""
Chatty — computer task store (SQLite): tasks, gates and the step log.

A task is one `computer_task(...)` call: the helper loop (runner.py) drives the
computer for the agent, and the agent gets at most one report-back turn
(completion.py). Caps (steps, time, money) cover the whole follow-up chain,
keyed by `root_task_id`, which is always derived here, never taken from a tool.

finish_task() is the ONLY code path that makes a task terminal — the runner,
the orphan sweep, policy cancels and user/agent cancels all go through it, and
its whole read-modify-write runs under the write lock.
"""

import json
import logging
import os
import secrets
import sqlite3
import threading
import time
import uuid
from pathlib import Path

from core.storage import safe_init_sqlite
from integrations.claude_code.db import iso_z

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "computer"
DB_PATH = DATA_DIR / "tasks.db"
GCS_KEY = "computer/tasks.db"

ACTIVE_STATUSES = ("queued", "running")
TERMINAL_STATUSES = ("needs_approval", "outcome_unknown", "done", "failed", "cancelled")
GATE_KINDS = ("buy", "delete", "post", "send", "submit")
GATE_TTL_HOURS = 24

# Chain caps (per root task). Steps and time are hard; money is a budget on
# conservative reservations — see runner.reserve_for_call.
MAX_STEPS = 500
MAX_SECONDS = 2 * 3600
BUDGET_USD = 10.0

_connection: sqlite3.Connection | None = None
# Guards every use of the one shared connection — reads too (concurrent cursors on a
# shared sqlite3 connection fail). Re-entrant: finish_task takes it and is also called
# from inside the claim loop and the sweep.
_write_lock = threading.RLock()
_init_lock = threading.Lock()


def get_db() -> sqlite3.Connection:
    if _connection is None:
        with _init_lock:
            if _connection is None:
                init_db()
    assert _connection is not None
    return _connection


_SCHEMA = f"""
    CREATE TABLE IF NOT EXISTS tasks (
        id                    TEXT PRIMARY KEY,
        agent_slug            TEXT NOT NULL,
        conversation_id       TEXT,
        route                 TEXT,
        origin                TEXT NOT NULL CHECK(origin IN ('user','background','system')),
        action_id             TEXT,
        parent_task_id        TEXT,
        root_task_id          TEXT NOT NULL,
        approved_gate_id      TEXT,
        mode                  TEXT NOT NULL DEFAULT 'text' CHECK(mode IN ('text','screenshot')),
        helper_provider       TEXT NOT NULL,
        helper_model          TEXT NOT NULL,
        task                  TEXT NOT NULL,
        status                TEXT NOT NULL CHECK(status IN ('queued','running','needs_approval','outcome_unknown',
                                                           'done','failed','cancelled')),
        finish_reason         TEXT,
        takeover_state        TEXT,
        cancel_requested      INTEGER NOT NULL DEFAULT 0,
        phase                 TEXT NOT NULL DEFAULT '',
        pending_action_id     TEXT,
        gate_id               TEXT,
        steps                 INTEGER NOT NULL DEFAULT 0,
        input_tokens          INTEGER NOT NULL DEFAULT 0,
        output_tokens         INTEGER NOT NULL DEFAULT 0,
        cost_reserved_usd     REAL NOT NULL DEFAULT 0,
        cost_actual_usd       REAL NOT NULL DEFAULT 0,
        running_seconds       REAL NOT NULL DEFAULT 0,
        worker_id             TEXT,
        heartbeat_at          TEXT,
        started_at            TEXT,
        finished_at           TEXT,
        result_text           TEXT,
        error                 TEXT,
        completion_status     TEXT NOT NULL DEFAULT 'none'
                              CHECK(completion_status IN ('none','pending','running','done')),
        completion_claimed_at TEXT,
        completion_attempts   INTEGER NOT NULL DEFAULT 0,
        summary_text          TEXT,
        accounting_pending    INTEGER NOT NULL DEFAULT 0,
        created_at            TEXT NOT NULL DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_vc_tasks_status ON tasks(status);
    CREATE INDEX IF NOT EXISTS idx_vc_tasks_agent ON tasks(agent_slug, created_at);
    CREATE INDEX IF NOT EXISTS idx_vc_tasks_root ON tasks(root_task_id);
    CREATE INDEX IF NOT EXISTS idx_vc_tasks_completion ON tasks(completion_status);

    CREATE TABLE IF NOT EXISTS gates (
        id            TEXT PRIMARY KEY,
        task_id       TEXT NOT NULL,
        root_task_id  TEXT NOT NULL,
        agent_slug    TEXT NOT NULL,
        kind          TEXT NOT NULL CHECK(kind IN {GATE_KINDS!r}),
        rule          TEXT,
        action        TEXT,
        host          TEXT,
        path          TEXT,
        url           TEXT,
        frame_url     TEXT,
        role          TEXT,
        name          TEXT,
        form_action   TEXT,
        context_fp    TEXT,
        element_json  TEXT,
        total_json    TEXT,
        item          TEXT,
        store         TEXT,
        total_text    TEXT,
        reason        TEXT,
        screenshot    TEXT,
        status        TEXT NOT NULL DEFAULT 'pending'
                      CHECK(status IN ('pending','approved','denied','expired','dispatching','done',
                                       'outcome_unknown','cancelled')),
        action_id     TEXT,
        approval_ref  TEXT,
        decision      TEXT,
        decided_by    TEXT,
        decided_via   TEXT,
        decided_at    TEXT,
        expires_at    TEXT,
        created_at    TEXT NOT NULL DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_vc_gates_task ON gates(task_id);
    CREATE INDEX IF NOT EXISTS idx_vc_gates_status ON gates(status);

    CREATE TABLE IF NOT EXISTS steps (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id         TEXT NOT NULL,
        n               INTEGER NOT NULL,
        tool            TEXT NOT NULL,
        args_excerpt    TEXT,
        result_excerpt  TEXT,
        url             TEXT,
        screenshot      TEXT,
        verdict         TEXT,
        action_id       TEXT,
        cost_so_far_usd REAL,
        created_at      TEXT NOT NULL DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_vc_steps_task ON steps(task_id, n);
"""


def _setup_connection() -> None:
    global _connection
    _connection = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    _connection.row_factory = sqlite3.Row
    _connection.execute("PRAGMA journal_mode=WAL")
    _connection.execute("PRAGMA busy_timeout=5000")
    _connection.execute("PRAGMA synchronous=FULL")
    _connection.executescript(_SCHEMA)
    _connection.commit()
    logger.info("Computer tasks DB initialized at %s", DB_PATH)


def init_db() -> dict:
    return safe_init_sqlite(DB_PATH, GCS_KEY, init_fn=_setup_connection)


def close_db() -> None:
    global _connection
    if _connection:
        _connection.close()
        _connection = None


def write_lock() -> threading.RLock:
    return _write_lock


def query(sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    with _write_lock:
        return get_db().execute(sql, params).fetchall()


def execute(sql: str, params: tuple = ()) -> int:
    """One committed statement under the lock; returns the rowcount."""
    db = get_db()
    with _write_lock:
        n = db.execute(sql, params).rowcount
        db.commit()
    return n


_B32 = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def ulid() -> str:
    """A ULID (48-bit ms timestamp + 80 random bits, Crockford base32): the computer's
    action journal requires them and rejects ids older than 24 h."""
    n = (int(time.time() * 1000) << 80) | secrets.randbits(80)
    return "".join(_B32[(n >> (5 * i)) & 31] for i in range(25, -1, -1))


# ── tasks ────────────────────────────────────────────────────────────────────

def get_task(task_id: str) -> dict | None:
    rows = query("SELECT * FROM tasks WHERE id = ?", (task_id,))
    return dict(rows[0]) if rows else None


def insert_task(*, agent_slug: str, origin: str, task: str, helper_provider: str, helper_model: str,
                conversation_id: str | None = None, route: dict | None = None, action_id: str | None = None,
                parent: dict | None = None, approved_gate_id: str | None = None, mode: str = "text",
                commit: bool = True) -> str:
    """Queue a task. `parent` (a task row of the same agent) makes this a follow-up sharing its root."""
    task_id = uuid.uuid4().hex[:12]
    db = get_db()
    with _write_lock:
        db.execute(
            """INSERT INTO tasks (id, agent_slug, conversation_id, route, origin, action_id, parent_task_id,
                                  root_task_id, approved_gate_id, mode, helper_provider, helper_model, task, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'queued')""",
            (task_id, agent_slug, conversation_id, json.dumps(route) if route else None, origin, action_id,
             parent["id"] if parent else None, parent["root_task_id"] if parent else task_id,
             approved_gate_id, mode, helper_provider, helper_model, task),
        )
        if commit:
            db.commit()
    return task_id


def claim_next(worker_id: str) -> dict | None:
    """Conditional claim of the oldest queued task, user-origin tasks first."""
    db = get_db()
    with _write_lock:
        row = db.execute(
            "SELECT id FROM tasks WHERE status = 'queued' "
            "ORDER BY (origin = 'user') DESC, created_at, rowid LIMIT 1"
        ).fetchone()
        if not row:
            return None
        n = db.execute(
            "UPDATE tasks SET status = 'running', worker_id = ?, started_at = COALESCE(started_at, datetime('now')), "
            "heartbeat_at = datetime('now') WHERE id = ? AND status = 'queued'",
            (worker_id, row["id"]),
        ).rowcount
        db.commit()
        return get_task(row["id"]) if n == 1 else None


def requeue(task_id: str, worker_id: str) -> bool:
    """running → queued (the screen was busy); only for the worker that holds it."""
    return execute(
        "UPDATE tasks SET status = 'queued', worker_id = NULL, phase = '' "
        "WHERE id = ? AND status = 'running' AND worker_id = ?", (task_id, worker_id),
    ) == 1


def heartbeat(task_id: str, worker_id: str, running_seconds: float, phase: str,
              pending_action_id: str | None = None) -> bool:
    """The worker's liveness mark (every 30 s and at every step). False when the task is no
    longer this worker's running task — the loop must stop."""
    return execute(
        "UPDATE tasks SET heartbeat_at = datetime('now'), running_seconds = ?, phase = ?, pending_action_id = ? "
        "WHERE id = ? AND status = 'running' AND worker_id = ?",
        (running_seconds, phase, pending_action_id, task_id, worker_id),
    ) == 1


def chain_totals(root_task_id: str) -> dict:
    """Steps, counted seconds and money (reserved + actual) across the whole follow-up chain."""
    row = query(
        "SELECT COALESCE(SUM(steps), 0) AS steps, COALESCE(SUM(running_seconds), 0) AS seconds, "
        "COALESCE(SUM(cost_reserved_usd + cost_actual_usd), 0) AS cost FROM tasks WHERE root_task_id = ?",
        (root_task_id,),
    )[0]
    return {"steps": int(row["steps"]), "seconds": float(row["seconds"]), "cost": float(row["cost"])}


def reserve(task_id: str, root_task_id: str, usd: float) -> bool:
    """Check the chain's remaining budget and reserve `usd` in ONE transaction, so two tasks of
    a chain can never reserve the same money. False when it doesn't fit."""
    db = get_db()
    with _write_lock:
        spent = chain_totals(root_task_id)["cost"]
        if spent + usd > BUDGET_USD + 1e-9:
            return False
        db.execute("UPDATE tasks SET cost_reserved_usd = cost_reserved_usd + ? WHERE id = ?", (usd, task_id))
        db.commit()
    return True


def settle(task_id: str, reserved: float, actual: float, input_tokens: int, output_tokens: int) -> None:
    """Replace a call's reservation with what it actually cost. Never called when usage is unknown
    (crash, lost response): then the reservation stays charged."""
    execute(
        "UPDATE tasks SET cost_reserved_usd = MAX(0, cost_reserved_usd - ?), cost_actual_usd = cost_actual_usd + ?, "
        "input_tokens = input_tokens + ?, output_tokens = output_tokens + ? WHERE id = ?",
        (reserved, actual, input_tokens, output_tokens, task_id),
    )


def add_step(task_id: str, tool: str, args: dict | None, result: str, *, url: str | None = None,
             verdict: str | None = None, action_id: str | None = None, screenshot: str | None = None) -> int:
    """Append to the step log and bump the task's step count; returns the new count."""
    db = get_db()
    with _write_lock:
        db.execute("UPDATE tasks SET steps = steps + 1 WHERE id = ?", (task_id, ))
        row = db.execute("SELECT steps, root_task_id FROM tasks WHERE id = ?", (task_id,)).fetchone()
        n = row["steps"]
        cost = chain_totals(row["root_task_id"])["cost"]
        db.execute(
            """INSERT INTO steps (task_id, n, tool, args_excerpt, result_excerpt, url, screenshot, verdict, action_id,
                                  cost_so_far_usd) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (task_id, n, tool, json.dumps(args)[:300] if args is not None else None, (result or "")[:500],
             url, screenshot, verdict, action_id, cost),
        )
        db.commit()
    return n


def list_steps(task_id: str) -> list[dict]:
    return [dict(r) for r in query("SELECT * FROM steps WHERE task_id = ? ORDER BY n", (task_id,))]


_RESULT_FIELDS = ("result_text", "error", "cancel_requested", "gate_id", "takeover_state")


def finish_task(task_id: str, status: str, reason: str, *, notify: bool, commit: bool = True, **fields) -> bool:
    """Make a task terminal. False if it already was (first write wins).

    notify=True queues the completion turn (completion_status='pending') in the same UPDATE,
    except for system-origin tasks. accounting_pending=1 asks the sweep for the usage row
    (finish_task writes it too; the flag makes a crash in between harmless).
    """
    assert status in TERMINAL_STATUSES, status
    bad = set(fields) - set(_RESULT_FIELDS)
    if bad:
        raise ValueError(f"finish_task: unknown fields {bad}")
    db = get_db()
    with _write_lock:
        row = db.execute("SELECT origin FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if not row:
            return False
        notify = notify and row["origin"] != "system"
        sets = ["status = ?", "finish_reason = ?", "finished_at = datetime('now')", "phase = ''",
                "pending_action_id = NULL", "accounting_pending = 1"]
        params: list = [status, reason]
        if notify:
            sets.append("completion_status = 'pending'")
        for k, v in fields.items():
            sets.append(f"{k} = COALESCE(?, {k})")
            params.append(v)
        params.append(task_id)
        changed = db.execute(
            f"UPDATE tasks SET {', '.join(sets)} WHERE id = ? AND status IN ('queued','running')", params,
        ).rowcount == 1
        if commit:
            db.commit()
    if changed and commit:
        from .completion import record_usage, submit
        record_usage(task_id)
        if notify:
            submit(task_id)
    return changed


def task_view(task: dict, *, result_chars: int = 2000) -> dict:
    """Public shape of a task row (card + tools)."""
    out = {k: task[k] for k in (
        "id", "agent_slug", "origin", "mode", "helper_model", "status", "task", "finish_reason", "error",
        "takeover_state", "parent_task_id", "root_task_id", "approved_gate_id", "gate_id", "conversation_id",
        "steps", "input_tokens", "output_tokens",
    )}
    for k in ("created_at", "started_at", "finished_at"):
        out[k] = iso_z(task[k])
    out["cost_usd"] = round(task["cost_reserved_usd"] + task["cost_actual_usd"], 4)
    out["running_seconds"] = round(task["running_seconds"])
    out["result_text"] = (task["result_text"] or "")[:result_chars]
    out["result_truncated"] = len(task["result_text"] or "") > result_chars
    return out


# ── gates ────────────────────────────────────────────────────────────────────

def insert_gate(task: dict, *, kind: str, reason: str, rule: str = "", action: str | None = None,
                element: dict | None = None, url: str | None = None, item: str | None = None,
                store: str | None = None, total_text: str | None = None, screenshot: str | None = None,
                commit: bool = True) -> str:
    """Record what the helper was stopped before. `element` is the /browser/element description;
    its page/frame/form facts are copied into columns PR 4's approval binding reads."""
    assert kind in GATE_KINDS, kind
    gate_id = uuid.uuid4().hex[:12]
    el = element or {}
    page = el.get("page") or {}
    db = get_db()
    with _write_lock:
        db.execute(
            """INSERT INTO gates (id, task_id, root_task_id, agent_slug, kind, rule, action, host, path, url, frame_url,
                                  role, name, form_action, context_fp, element_json, total_json, item, store, total_text,
                                  reason, screenshot, status, expires_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', datetime('now', ?))""",
            (gate_id, task["id"], task["root_task_id"], task["agent_slug"], kind, rule, action,
             page.get("host"), page.get("path"), url, el.get("frame_url"), el.get("role"), el.get("name"),
             (el.get("form") or {}).get("action"), el.get("context_fp"),
             json.dumps(element) if element else None,
             json.dumps(el["total"]) if el.get("total") is not None else None,
             item, store, total_text, reason, screenshot, f"+{GATE_TTL_HOURS} hours"),
        )
        if commit:
            db.commit()
    return gate_id


def get_gate(gate_id: str) -> dict | None:
    rows = query("SELECT * FROM gates WHERE id = ?", (gate_id,))
    return dict(rows[0]) if rows else None


def gate_view(gate: dict) -> dict:
    out = {k: gate[k] for k in ("id", "task_id", "root_task_id", "agent_slug", "kind", "rule", "action", "host",
                                "path", "url", "frame_url", "role", "name", "form_action", "item", "store",
                                "total_text", "reason", "status", "decision", "decided_via")}
    out["total"] = json.loads(gate["total_json"]) if gate["total_json"] else None
    out["has_screenshot"] = bool(gate["screenshot"])
    for k in ("created_at", "expires_at", "decided_at"):
        out[k] = iso_z(gate[k])
    return out


def worker_id() -> str:
    """container + pid: the orphan sweep trusts heartbeats, not this, but it's in the row for forensics."""
    return f"{os.environ.get('RAILWAY_REPLICA_ID') or os.uname().nodename}:{os.getpid()}"
