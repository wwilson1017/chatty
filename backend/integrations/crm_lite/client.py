"""
Chatty — CRM Lite CRUD operations.
"""

import logging
from .db import _get_db, write_lock

logger = logging.getLogger(__name__)

DEAL_STAGES = ["lead", "qualified", "proposal", "negotiation", "won", "lost"]


# ── Contacts ──────────────────────────────────────────────────────────────────

def create_contact(name: str, email: str = "", phone: str = "", company: str = "", notes: str = "") -> dict:
    db = _get_db()
    with write_lock():
        cursor = db.execute(
            "INSERT INTO contacts (name, email, phone, company, notes) VALUES (?, ?, ?, ?, ?)",
            (name, email, phone, company, notes),
        )
        db.commit()
    return get_contact(cursor.lastrowid)


def get_contact(contact_id: int) -> dict | None:
    row = _get_db().execute("SELECT * FROM contacts WHERE id = ?", (contact_id,)).fetchone()
    return dict(row) if row else None


def search_contacts(query: str, limit: int = 20) -> list[dict]:
    like = f"%{query}%"
    rows = _get_db().execute(
        """SELECT * FROM contacts
           WHERE name LIKE ? OR email LIKE ? OR company LIKE ? OR notes LIKE ?
           ORDER BY updated_at DESC LIMIT ?""",
        (like, like, like, like, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def update_contact(contact_id: int, **fields) -> dict | None:
    allowed = {"name", "email", "phone", "company", "notes"}
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


# ── Deals ─────────────────────────────────────────────────────────────────────

def create_deal(title: str, contact_id: int | None = None, stage: str = "lead",
                value: float = 0, notes: str = "") -> dict:
    db = _get_db()
    with write_lock():
        cursor = db.execute(
            "INSERT INTO deals (title, contact_id, stage, value, notes) VALUES (?, ?, ?, ?, ?)",
            (title, contact_id, stage, value, notes),
        )
        db.commit()
    return get_deal(cursor.lastrowid)


def get_deal(deal_id: int) -> dict | None:
    row = _get_db().execute("SELECT * FROM deals WHERE id = ?", (deal_id,)).fetchone()
    return dict(row) if row else None


def get_pipeline(stage: str | None = None) -> list[dict]:
    if stage:
        rows = _get_db().execute(
            "SELECT * FROM deals WHERE stage = ? ORDER BY updated_at DESC", (stage,)
        ).fetchall()
    else:
        rows = _get_db().execute("SELECT * FROM deals ORDER BY updated_at DESC").fetchall()
    return [dict(r) for r in rows]


def update_deal_stage(deal_id: int, stage: str) -> dict | None:
    if stage not in DEAL_STAGES:
        return None
    with write_lock():
        _get_db().execute(
            "UPDATE deals SET stage = ?, updated_at = datetime('now') WHERE id = ?", (stage, deal_id)
        )
        _get_db().commit()
    return get_deal(deal_id)


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


def get_activity_log(contact_id: int | None = None, limit: int = 20) -> list[dict]:
    if contact_id:
        rows = _get_db().execute(
            "SELECT * FROM activity_log WHERE contact_id = ? ORDER BY created_at DESC LIMIT ?",
            (contact_id, limit),
        ).fetchall()
    else:
        rows = _get_db().execute(
            "SELECT * FROM activity_log ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]
