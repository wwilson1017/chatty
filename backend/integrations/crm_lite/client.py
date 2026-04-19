"""
Chatty — CRM Lite CRUD operations.

Contacts, deals, tasks, activities, and analytics for small businesses.
"""

import logging
from .db import _get_db, write_lock

logger = logging.getLogger(__name__)

DEAL_STAGES = ["lead", "qualified", "proposal", "negotiation", "won", "lost"]
CONTACT_STATUSES = ["active", "inactive", "archived"]
TASK_PRIORITIES = ["low", "medium", "high"]


# ── Contacts ──────────────────────────────────────────────────────────────────

def create_contact(
    name: str, email: str = "", phone: str = "", company: str = "",
    title: str = "", source: str = "", status: str = "active",
    tags: str = "", notes: str = "",
) -> dict:
    db = _get_db()
    with write_lock():
        cursor = db.execute(
            """INSERT INTO contacts (name, email, phone, company, title, source, status, tags, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (name, email, phone, company, title, source, status, tags, notes),
        )
        db.commit()
    return get_contact(cursor.lastrowid)


def get_contact(contact_id: int) -> dict | None:
    row = _get_db().execute("SELECT * FROM contacts WHERE id = ?", (contact_id,)).fetchone()
    return dict(row) if row else None


def search_contacts(query: str, status: str | None = None, tags: str | None = None, limit: int = 20) -> list[dict]:
    like = f"%{query}%"
    conditions = ["(name LIKE ? OR email LIKE ? OR company LIKE ? OR notes LIKE ?)"]
    params: list = [like, like, like, like]
    if status:
        conditions.append("status = ?")
        params.append(status)
    if tags:
        conditions.append("tags LIKE ?")
        params.append(f"%{tags}%")
    params.append(limit)
    where = " AND ".join(conditions)
    rows = _get_db().execute(
        f"SELECT * FROM contacts WHERE {where} ORDER BY updated_at DESC LIMIT ?",
        params,
    ).fetchall()
    return [dict(r) for r in rows]


def list_contacts(offset: int = 0, limit: int = 50, status: str | None = None, sort: str = "updated_at") -> dict:
    allowed_sorts = {"updated_at", "created_at", "name", "company"}
    sort_col = sort if sort in allowed_sorts else "updated_at"

    conditions = []
    params: list = []
    if status:
        conditions.append("status = ?")
        params.append(status)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    total = _get_db().execute(f"SELECT COUNT(*) FROM contacts {where}", params).fetchone()[0]

    params.extend([limit, offset])
    rows = _get_db().execute(
        f"SELECT * FROM contacts {where} ORDER BY {sort_col} DESC LIMIT ? OFFSET ?",
        params,
    ).fetchall()
    return {"contacts": [dict(r) for r in rows], "total": total, "limit": limit, "offset": offset}


def update_contact(contact_id: int, **fields) -> dict | None:
    allowed = {"name", "email", "phone", "company", "title", "source", "status", "tags", "notes"}
    filtered = {k: v for k, v in fields.items() if k in allowed}
    if not filtered:
        return get_contact(contact_id)
    set_clause = ", ".join(f"{k} = ?" for k in filtered)
    values = list(filtered.values()) + [contact_id]
    with write_lock():
        _get_db().execute(
            f"UPDATE contacts SET {set_clause}, updated_at = datetime('now') WHERE id = ?", values
        )
        _get_db().commit()
    return get_contact(contact_id)


def delete_contact(contact_id: int) -> bool:
    db = _get_db()
    existing = get_contact(contact_id)
    if not existing:
        return False
    with write_lock():
        db.execute("DELETE FROM activity_log WHERE contact_id = ?", (contact_id,))
        db.execute("DELETE FROM tasks WHERE contact_id = ?", (contact_id,))
        db.execute("DELETE FROM contacts WHERE id = ?", (contact_id,))
        db.commit()
    return True


def get_contact_detail(contact_id: int) -> dict | None:
    """Full contact profile with associated deals, tasks, and recent activity."""
    contact = get_contact(contact_id)
    if not contact:
        return None
    db = _get_db()
    deals = [dict(r) for r in db.execute(
        "SELECT * FROM deals WHERE contact_id = ? ORDER BY updated_at DESC", (contact_id,)
    ).fetchall()]
    tasks = [dict(r) for r in db.execute(
        "SELECT * FROM tasks WHERE contact_id = ? ORDER BY completed ASC, due_date ASC LIMIT 20", (contact_id,)
    ).fetchall()]
    activity = [dict(r) for r in db.execute(
        "SELECT * FROM activity_log WHERE contact_id = ? ORDER BY created_at DESC LIMIT 20", (contact_id,)
    ).fetchall()]
    return {**contact, "deals": deals, "tasks": tasks, "activity": activity}


# ── Deals ─────────────────────────────────────────────────────────────────────

def create_deal(
    title: str, contact_id: int | None = None, stage: str = "lead",
    value: float = 0, notes: str = "", expected_close_date: str = "",
    probability: int = 0, currency: str = "USD",
) -> dict:
    db = _get_db()
    with write_lock():
        cursor = db.execute(
            """INSERT INTO deals (title, contact_id, stage, value, notes, expected_close_date, probability, currency)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (title, contact_id, stage, value, notes, expected_close_date, probability, currency),
        )
        db.commit()
    return get_deal(cursor.lastrowid)


def get_deal(deal_id: int) -> dict | None:
    row = _get_db().execute(
        """SELECT d.*, c.name AS contact_name
           FROM deals d LEFT JOIN contacts c ON d.contact_id = c.id
           WHERE d.id = ?""",
        (deal_id,),
    ).fetchone()
    return dict(row) if row else None


def get_deal_detail(deal_id: int) -> dict | None:
    """Full deal with contact info and activity."""
    deal = get_deal(deal_id)
    if not deal:
        return None
    db = _get_db()
    activity = [dict(r) for r in db.execute(
        "SELECT * FROM activity_log WHERE deal_id = ? ORDER BY created_at DESC LIMIT 20", (deal_id,)
    ).fetchall()]
    return {**deal, "activity": activity}


def get_pipeline(stage: str | None = None) -> dict:
    db = _get_db()
    if stage:
        rows = db.execute(
            """SELECT d.*, c.name AS contact_name
               FROM deals d LEFT JOIN contacts c ON d.contact_id = c.id
               WHERE d.stage = ? ORDER BY d.updated_at DESC""",
            (stage,),
        ).fetchall()
    else:
        rows = db.execute(
            """SELECT d.*, c.name AS contact_name
               FROM deals d LEFT JOIN contacts c ON d.contact_id = c.id
               ORDER BY d.updated_at DESC""",
        ).fetchall()

    deals = [dict(r) for r in rows]

    # Value summaries per stage
    summary_rows = db.execute(
        """SELECT stage, COUNT(*) as count, COALESCE(SUM(value), 0) as total_value
           FROM deals WHERE stage NOT IN ('won', 'lost')
           GROUP BY stage"""
    ).fetchall()
    stage_summary = [dict(r) for r in summary_rows]
    total_pipeline = sum(s["total_value"] for s in stage_summary)

    return {"deals": deals, "stage_summary": stage_summary, "total_pipeline_value": total_pipeline}


def list_deals(stage: str | None = None, contact_id: int | None = None, limit: int = 50) -> list[dict]:
    conditions = []
    params: list = []
    if stage:
        conditions.append("d.stage = ?")
        params.append(stage)
    if contact_id:
        conditions.append("d.contact_id = ?")
        params.append(contact_id)
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    params.append(limit)
    rows = _get_db().execute(
        f"""SELECT d.*, c.name AS contact_name
            FROM deals d LEFT JOIN contacts c ON d.contact_id = c.id
            {where} ORDER BY d.updated_at DESC LIMIT ?""",
        params,
    ).fetchall()
    return [dict(r) for r in rows]


def update_deal(deal_id: int, **fields) -> dict | None:
    allowed = {"title", "stage", "value", "notes", "expected_close_date", "probability", "currency", "contact_id"}
    filtered = {k: v for k, v in fields.items() if k in allowed}
    if "stage" in filtered and filtered["stage"] not in DEAL_STAGES:
        return None
    if not filtered:
        return get_deal(deal_id)
    set_clause = ", ".join(f"{k} = ?" for k in filtered)
    values = list(filtered.values()) + [deal_id]
    with write_lock():
        _get_db().execute(
            f"UPDATE deals SET {set_clause}, updated_at = datetime('now') WHERE id = ?", values
        )
        _get_db().commit()
    return get_deal(deal_id)


def update_deal_stage(deal_id: int, stage: str) -> dict | None:
    if stage not in DEAL_STAGES:
        return None
    with write_lock():
        _get_db().execute(
            "UPDATE deals SET stage = ?, updated_at = datetime('now') WHERE id = ?", (stage, deal_id)
        )
        _get_db().commit()
    return get_deal(deal_id)


# ── Tasks ─────────────────────────────────────────────────────────────────────

def create_task(
    title: str, description: str = "", due_date: str = "",
    contact_id: int | None = None, deal_id: int | None = None,
    priority: str = "medium",
) -> dict:
    db = _get_db()
    with write_lock():
        cursor = db.execute(
            """INSERT INTO tasks (title, description, due_date, contact_id, deal_id, priority)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (title, description, due_date, contact_id, deal_id, priority),
        )
        db.commit()
    return get_task(cursor.lastrowid)


def get_task(task_id: int) -> dict | None:
    row = _get_db().execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    return dict(row) if row else None


def list_tasks(
    contact_id: int | None = None, deal_id: int | None = None,
    completed: bool | None = None, due_before: str | None = None,
    priority: str | None = None, limit: int = 50,
) -> list[dict]:
    conditions = []
    params: list = []
    if contact_id is not None:
        conditions.append("t.contact_id = ?")
        params.append(contact_id)
    if deal_id is not None:
        conditions.append("t.deal_id = ?")
        params.append(deal_id)
    if completed is not None:
        conditions.append("t.completed = ?")
        params.append(1 if completed else 0)
    if due_before:
        conditions.append("t.due_date != '' AND t.due_date <= ?")
        params.append(due_before)
    if priority:
        conditions.append("t.priority = ?")
        params.append(priority)
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    params.append(limit)
    rows = _get_db().execute(
        f"""SELECT t.*, c.name AS contact_name, d.title AS deal_title
            FROM tasks t
            LEFT JOIN contacts c ON t.contact_id = c.id
            LEFT JOIN deals d ON t.deal_id = d.id
            {where} ORDER BY t.completed ASC, t.due_date ASC LIMIT ?""",
        params,
    ).fetchall()
    return [dict(r) for r in rows]


def complete_task(task_id: int) -> dict | None:
    existing = get_task(task_id)
    if not existing:
        return None
    with write_lock():
        _get_db().execute(
            "UPDATE tasks SET completed = 1, updated_at = datetime('now') WHERE id = ?", (task_id,)
        )
        _get_db().commit()
    return get_task(task_id)


def update_task(task_id: int, **fields) -> dict | None:
    allowed = {"title", "description", "due_date", "contact_id", "deal_id", "priority", "completed"}
    filtered = {k: v for k, v in fields.items() if k in allowed}
    if not filtered:
        return get_task(task_id)
    set_clause = ", ".join(f"{k} = ?" for k in filtered)
    values = list(filtered.values()) + [task_id]
    with write_lock():
        _get_db().execute(
            f"UPDATE tasks SET {set_clause}, updated_at = datetime('now') WHERE id = ?", values
        )
        _get_db().commit()
    return get_task(task_id)


def delete_task(task_id: int) -> bool:
    existing = get_task(task_id)
    if not existing:
        return False
    with write_lock():
        _get_db().execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        _get_db().commit()
    return True


# ── Activity log ──────────────────────────────────────────────────────────────

def log_activity(activity: str, note: str = "", contact_id: int | None = None,
                 deal_id: int | None = None) -> dict:
    db = _get_db()
    with write_lock():
        cursor = db.execute(
            "INSERT INTO activity_log (activity, note, contact_id, deal_id) VALUES (?, ?, ?, ?)",
            (activity, note, contact_id, deal_id),
        )
        db.commit()
    row = db.execute("SELECT * FROM activity_log WHERE id = ?", (cursor.lastrowid,)).fetchone()
    return dict(row) if row else {}


def get_activity_log(contact_id: int | None = None, deal_id: int | None = None, limit: int = 20) -> list[dict]:
    conditions = []
    params: list = []
    if contact_id is not None:
        conditions.append("a.contact_id = ?")
        params.append(contact_id)
    if deal_id is not None:
        conditions.append("a.deal_id = ?")
        params.append(deal_id)
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    params.append(limit)
    rows = _get_db().execute(
        f"""SELECT a.*, c.name AS contact_name, d.title AS deal_title
            FROM activity_log a
            LEFT JOIN contacts c ON a.contact_id = c.id
            LEFT JOIN deals d ON a.deal_id = d.id
            {where} ORDER BY a.created_at DESC LIMIT ?""",
        params,
    ).fetchall()
    return [dict(r) for r in rows]


def update_activity(activity_id: int, activity: str | None = None, note: str | None = None) -> dict:
    db = _get_db()
    fields = []
    params: list = []
    if activity is not None:
        fields.append("activity = ?")
        params.append(activity)
    if note is not None:
        fields.append("note = ?")
        params.append(note)
    if not fields:
        row = db.execute("SELECT * FROM activity_log WHERE id = ?", (activity_id,)).fetchone()
        return dict(row) if row else {}
    params.append(activity_id)
    with write_lock():
        db.execute(f"UPDATE activity_log SET {', '.join(fields)} WHERE id = ?", params)
        db.commit()
    row = db.execute("SELECT * FROM activity_log WHERE id = ?", (activity_id,)).fetchone()
    return dict(row) if row else {}


def delete_activity(activity_id: int) -> bool:
    db = _get_db()
    with write_lock():
        cursor = db.execute("DELETE FROM activity_log WHERE id = ?", (activity_id,))
        db.commit()
    return cursor.rowcount > 0


# ── Analytics ─────────────────────────────────────────────────────────────────

def get_dashboard_stats() -> dict:
    db = _get_db()

    total_contacts = db.execute("SELECT COUNT(*) FROM contacts").fetchone()[0]
    contacts_by_status = {}
    for row in db.execute("SELECT status, COUNT(*) as count FROM contacts GROUP BY status").fetchall():
        contacts_by_status[row["status"]] = row["count"]

    pipeline_rows = db.execute(
        """SELECT stage, COUNT(*) as count, COALESCE(SUM(value), 0) as total_value
           FROM deals GROUP BY stage"""
    ).fetchall()
    pipeline_by_stage = [dict(r) for r in pipeline_rows]
    total_pipeline_value = sum(
        r["total_value"] for r in pipeline_rows if r["stage"] not in ("won", "lost")
    )

    overdue_tasks = db.execute(
        "SELECT COUNT(*) FROM tasks WHERE completed = 0 AND due_date != '' AND due_date < datetime('now')"
    ).fetchone()[0]

    pending_tasks = db.execute(
        "SELECT COUNT(*) FROM tasks WHERE completed = 0"
    ).fetchone()[0]

    recent_activity = get_activity_log(limit=10)

    # Top open deals by value
    top_deals = [dict(r) for r in db.execute(
        """SELECT d.*, c.name AS contact_name
           FROM deals d LEFT JOIN contacts c ON d.contact_id = c.id
           WHERE d.stage NOT IN ('won', 'lost')
           ORDER BY d.value DESC LIMIT 5"""
    ).fetchall()]

    return {
        "total_contacts": total_contacts,
        "contacts_by_status": contacts_by_status,
        "pipeline_by_stage": pipeline_by_stage,
        "total_pipeline_value": total_pipeline_value,
        "overdue_tasks": overdue_tasks,
        "pending_tasks": pending_tasks,
        "recent_activity": recent_activity,
        "top_deals": top_deals,
    }
