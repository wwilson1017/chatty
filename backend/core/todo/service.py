"""
Chatty — Todo (GTD) service layer.

Pure CRUD/query functions over the global todo store. Used by the agent
tools, the REST router, the /capture endpoints, and the Telegram capture
intercept. Validation errors raise ValueError with a user-facing message.
"""

import json
import re

from core.todo import db as tododb
from core.todo.db import PROJECT_STATUSES, TODO_SOURCES, TODO_STATUSES

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MAX_TEXT_CHARS = 20_000

TODO_FIELDS = frozenset(
    {"title", "notes", "project", "project_id", "context", "tags", "status", "star", "due_date"}
)
PROJECT_FIELDS = frozenset({"name", "notes", "status"})

_SELECT_TODO = (
    "SELECT t.*, p.name AS project_name FROM todos t "
    "LEFT JOIN projects p ON t.project_id = p.id"
)


# ── Validation helpers ────────────────────────────────────────────────────────

def _validate_status(status: str) -> str:
    if status not in TODO_STATUSES:
        raise ValueError(f"Invalid status '{status}'. Valid: {', '.join(TODO_STATUSES)}")
    return status


def _validate_due(due_date) -> str | None:
    if due_date in (None, ""):
        return None
    due = str(due_date).strip()
    if not _DATE_RE.match(due):
        raise ValueError(f"due_date must be YYYY-MM-DD, got '{due_date}'")
    return due


def _validate_tags(tags) -> list[str]:
    if tags is None:
        return []
    if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
        raise ValueError("tags must be a list of strings")
    return [t.strip() for t in tags if t.strip()]


def _escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _todo_dict(row) -> dict:
    d = dict(row)
    try:
        d["tags"] = json.loads(d.get("tags") or "[]")
    except (ValueError, TypeError):
        d["tags"] = []
    d["star"] = bool(d.get("star"))
    return d


def _resolve_project_id(conn, name: str) -> int:
    """Return the id of the project named `name`, creating it (active) if missing.

    Caller must hold the write lock (may INSERT).
    """
    row = conn.execute("SELECT id FROM projects WHERE name = ?", (name,)).fetchone()
    if row:
        return row["id"]
    cur = conn.execute("INSERT INTO projects (name) VALUES (?)", (name,))
    return cur.lastrowid


def _check_project_id(conn, project_id) -> int | None:
    if project_id in (None, "", 0):
        return None
    pid = int(project_id)
    if not conn.execute("SELECT id FROM projects WHERE id = ?", (pid,)).fetchone():
        raise ValueError(f"Project id not found: {pid}")
    return pid


# ── Todos ─────────────────────────────────────────────────────────────────────

def create_todo(
    title: str,
    *,
    notes: str = "",
    project: str | None = None,
    project_id: int | None = None,
    context: str = "",
    tags: list[str] | None = None,
    status: str = "inbox",
    star=0,
    due_date: str | None = None,
    source: str = "agent",
) -> dict:
    title = (title or "").strip()
    if not title:
        raise ValueError("title is required")
    if len(title) > MAX_TEXT_CHARS:
        raise ValueError(f"title too long (max {MAX_TEXT_CHARS} characters)")
    _validate_status(status)
    if source not in TODO_SOURCES:
        raise ValueError(f"Invalid source '{source}'. Valid: {', '.join(TODO_SOURCES)}")
    due = _validate_due(due_date)
    tag_list = _validate_tags(tags)

    conn = tododb.get_db()
    with tododb.write_lock():
        try:
            if project_id is not None:
                pid = _check_project_id(conn, project_id)
            elif project and str(project).strip():
                pid = _resolve_project_id(conn, str(project).strip())
            else:
                pid = None
            cur = conn.execute(
                """INSERT INTO todos
                   (title, notes, project_id, context, tags, status, star, due_date, source,
                    completed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?,
                           CASE WHEN ? = 'done' THEN datetime('now') END)""",
                (
                    title,
                    str(notes or ""),
                    pid,
                    str(context or "").strip(),
                    json.dumps(tag_list),
                    status,
                    1 if star else 0,
                    due,
                    source,
                    status,
                ),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        new_id = cur.lastrowid
    return get_todo(new_id)


def get_todo(todo_id: int) -> dict | None:
    conn = tododb.get_db()
    row = conn.execute(_SELECT_TODO + " WHERE t.id = ?", (todo_id,)).fetchone()
    return _todo_dict(row) if row else None


def _apply_update(conn, todo_id: int, fields: dict) -> bool:
    """Apply a validated field update to one todo. Caller holds the write lock
    and commits. Returns False if the todo doesn't exist."""
    row = conn.execute("SELECT id, status FROM todos WHERE id = ?", (todo_id,)).fetchone()
    if not row:
        return False
    sets: list[str] = []
    params: list = []
    if "title" in fields:
        title = (fields["title"] or "").strip()
        if not title:
            raise ValueError("title cannot be empty")
        if len(title) > MAX_TEXT_CHARS:
            raise ValueError(f"title too long (max {MAX_TEXT_CHARS} characters)")
        sets.append("title = ?")
        params.append(title)
    if "notes" in fields:
        sets.append("notes = ?")
        params.append(str(fields["notes"] or ""))
    if "project_id" in fields:
        sets.append("project_id = ?")
        params.append(_check_project_id(conn, fields["project_id"]))
    elif "project" in fields:
        name = str(fields["project"] or "").strip()
        sets.append("project_id = ?")
        params.append(_resolve_project_id(conn, name) if name else None)
    if "context" in fields:
        sets.append("context = ?")
        params.append(str(fields["context"] or "").strip())
    if "tags" in fields:
        sets.append("tags = ?")
        params.append(json.dumps(_validate_tags(fields["tags"])))
    if "star" in fields:
        sets.append("star = ?")
        params.append(1 if fields["star"] else 0)
    if "due_date" in fields:
        sets.append("due_date = ?")
        params.append(_validate_due(fields["due_date"]))
    if "status" in fields:
        status = _validate_status(fields["status"])
        sets.append("status = ?")
        params.append(status)
        if status == "done":
            if row["status"] != "done":
                sets.append("completed_at = datetime('now')")
        else:
            sets.append("completed_at = NULL")
    sets.append("updated_at = datetime('now')")
    conn.execute(f"UPDATE todos SET {', '.join(sets)} WHERE id = ?", (*params, todo_id))
    return True


def _check_fields(fields: dict) -> None:
    if not fields:
        raise ValueError("No fields to update")
    unknown = set(fields) - TODO_FIELDS
    if unknown:
        raise ValueError(
            f"Unknown fields: {', '.join(sorted(unknown))}. Valid: {', '.join(sorted(TODO_FIELDS))}"
        )


def update_todo(todo_id: int, fields: dict) -> dict | None:
    """Update one todo. Returns the updated todo, or None if not found."""
    _check_fields(fields)
    conn = tododb.get_db()
    with tododb.write_lock():
        try:
            found = _apply_update(conn, todo_id, fields)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return get_todo(todo_id) if found else None


def bulk_update(ids: list[int], fields: dict) -> dict:
    """Apply the same field update to many todos in one transaction."""
    _check_fields(fields)
    if not ids:
        raise ValueError("ids is required")
    conn = tododb.get_db()
    updated: list[int] = []
    not_found: list[int] = []
    with tododb.write_lock():
        try:
            for todo_id in ids:
                if _apply_update(conn, int(todo_id), fields):
                    updated.append(int(todo_id))
                else:
                    not_found.append(int(todo_id))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return {"updated": updated, "not_found": not_found}


def delete_todo(todo_id: int) -> bool:
    conn = tododb.get_db()
    with tododb.write_lock():
        try:
            cur = conn.execute("DELETE FROM todos WHERE id = ?", (todo_id,))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return cur.rowcount > 0


def list_todos(
    status: str | None = None,
    project: str | int | None = None,
    context: str | None = None,
    tag: str | None = None,
    starred: bool | None = None,
    due_before: str | None = None,
    due_after: str | None = None,
    search: str | None = None,
    limit: int = 100,
) -> list[dict]:
    conn = tododb.get_db()
    where: list[str] = []
    params: list = []
    if status:
        _validate_status(status)
        where.append("t.status = ?")
        params.append(status)
    if project not in (None, ""):
        term = str(project).strip()
        if term.isdigit():
            pid = int(term)
        else:
            row = conn.execute("SELECT id FROM projects WHERE name = ?", (term,)).fetchone()
            if not row:
                return []
            pid = row["id"]
        where.append("t.project_id = ?")
        params.append(pid)
    if context:
        where.append("t.context = ? COLLATE NOCASE")
        params.append(context.strip())
    if tag:
        where.append("t.tags LIKE ? ESCAPE '\\'")
        params.append('%"' + _escape_like(tag) + '"%')
    if starred is not None:
        where.append("t.star = ?")
        params.append(1 if starred else 0)
    if due_before:
        where.append("t.due_date IS NOT NULL AND t.due_date <= ?")
        params.append(_validate_due(due_before))
    if due_after:
        where.append("t.due_date IS NOT NULL AND t.due_date >= ?")
        params.append(_validate_due(due_after))
    if search:
        esc = f"%{_escape_like(search)}%"
        where.append("(t.title LIKE ? ESCAPE '\\' OR t.notes LIKE ? ESCAPE '\\')")
        params.extend([esc, esc])
    sql = _SELECT_TODO
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY t.created_at ASC, t.id ASC LIMIT ?"
    params.append(max(1, min(int(limit or 100), 500)))
    return [_todo_dict(r) for r in conn.execute(sql, params).fetchall()]


# ── Projects ──────────────────────────────────────────────────────────────────

_SELECT_PROJECT = (
    "SELECT p.*, (SELECT COUNT(*) FROM todos t WHERE t.project_id = p.id "
    "AND t.status NOT IN ('done','dropped')) AS open_count FROM projects p"
)


def get_project(project_id: int) -> dict | None:
    conn = tododb.get_db()
    row = conn.execute(_SELECT_PROJECT + " WHERE p.id = ?", (project_id,)).fetchone()
    return dict(row) if row else None


def list_projects(status: str | None = None) -> list[dict]:
    conn = tododb.get_db()
    sql = _SELECT_PROJECT
    params: list = []
    if status:
        if status not in PROJECT_STATUSES:
            raise ValueError(
                f"Invalid project status '{status}'. Valid: {', '.join(PROJECT_STATUSES)}"
            )
        sql += " WHERE p.status = ?"
        params.append(status)
    sql += " ORDER BY p.name COLLATE NOCASE ASC"
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def create_project(name: str, notes: str = "", status: str = "active") -> dict:
    name = (name or "").strip()
    if not name:
        raise ValueError("name is required")
    if status not in PROJECT_STATUSES:
        raise ValueError(f"Invalid project status '{status}'. Valid: {', '.join(PROJECT_STATUSES)}")
    conn = tododb.get_db()
    with tododb.write_lock():
        try:
            if conn.execute("SELECT id FROM projects WHERE name = ?", (name,)).fetchone():
                raise ValueError(f'Project "{name}" already exists')
            cur = conn.execute(
                "INSERT INTO projects (name, notes, status) VALUES (?, ?, ?)",
                (name, str(notes or ""), status),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return get_project(cur.lastrowid)


def update_project(project_id: int, fields: dict) -> dict | None:
    if not fields:
        raise ValueError("No fields to update")
    unknown = set(fields) - PROJECT_FIELDS
    if unknown:
        raise ValueError(
            f"Unknown fields: {', '.join(sorted(unknown))}. Valid: {', '.join(sorted(PROJECT_FIELDS))}"
        )
    conn = tododb.get_db()
    with tododb.write_lock():
        try:
            if not conn.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone():
                return None
            sets: list[str] = []
            params: list = []
            if "name" in fields:
                name = (fields["name"] or "").strip()
                if not name:
                    raise ValueError("name cannot be empty")
                dup = conn.execute(
                    "SELECT id FROM projects WHERE name = ? AND id != ?", (name, project_id)
                ).fetchone()
                if dup:
                    raise ValueError(f'Project "{name}" already exists')
                sets.append("name = ?")
                params.append(name)
            if "notes" in fields:
                sets.append("notes = ?")
                params.append(str(fields["notes"] or ""))
            if "status" in fields:
                if fields["status"] not in PROJECT_STATUSES:
                    raise ValueError(
                        f"Invalid project status '{fields['status']}'. "
                        f"Valid: {', '.join(PROJECT_STATUSES)}"
                    )
                sets.append("status = ?")
                params.append(fields["status"])
            sets.append("updated_at = datetime('now')")
            conn.execute(
                f"UPDATE projects SET {', '.join(sets)} WHERE id = ?", (*params, project_id)
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return get_project(project_id)


def delete_project(project_id: int) -> bool:
    """Delete a project. Its todos survive with project_id set to NULL."""
    conn = tododb.get_db()
    with tododb.write_lock():
        try:
            cur = conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return cur.rowcount > 0


# ── Filters / capture ─────────────────────────────────────────────────────────

def get_filters() -> dict:
    """Distinct contexts, tag union, and per-status counts (all statuses, zeros included)."""
    conn = tododb.get_db()
    contexts = [
        r["context"]
        for r in conn.execute(
            "SELECT DISTINCT context FROM todos WHERE context != '' "
            "ORDER BY context COLLATE NOCASE"
        )
    ]
    tags: set[str] = set()
    for r in conn.execute("SELECT tags FROM todos WHERE tags != '[]'"):
        try:
            tags.update(t for t in json.loads(r["tags"]) if isinstance(t, str))
        except (ValueError, TypeError):
            pass
    counts = {s: 0 for s in TODO_STATUSES}
    for r in conn.execute("SELECT status, COUNT(*) AS n FROM todos GROUP BY status"):
        if r["status"] in counts:
            counts[r["status"]] = r["n"]
    return {"contexts": contexts, "tags": sorted(tags, key=str.lower), "status_counts": counts}


def capture(text: str, source: str = "capture_web") -> dict:
    """Deterministic quick capture: full trimmed text becomes an inbox todo's title."""
    text = (text or "").strip()
    if not text:
        raise ValueError("Nothing to capture")
    if len(text) > MAX_TEXT_CHARS:
        raise ValueError(f"Capture text too long (max {MAX_TEXT_CHARS} characters)")
    return create_todo(text, status="inbox", source=source)
