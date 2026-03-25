"""
Chatty — CRM Lite REST API for the frontend.

All endpoints require JWT auth and CRM to be enabled.

Contacts:
  GET    /api/crm/contacts              — paginated list
  GET    /api/crm/contacts/:id          — full detail
  POST   /api/crm/contacts              — create
  PUT    /api/crm/contacts/:id          — update
  DELETE /api/crm/contacts/:id          — delete

Deals:
  GET    /api/crm/deals                 — pipeline list
  GET    /api/crm/deals/:id             — detail
  POST   /api/crm/deals                 — create
  PUT    /api/crm/deals/:id             — update

Tasks:
  GET    /api/crm/tasks                 — filtered list
  POST   /api/crm/tasks                 — create
  PUT    /api/crm/tasks/:id             — update
  PUT    /api/crm/tasks/:id/complete    — mark done
  DELETE /api/crm/tasks/:id             — delete

Activity:
  GET    /api/crm/activity              — log
  POST   /api/crm/activity              — log new

Other:
  GET    /api/crm/dashboard             — summary stats
  POST   /api/crm/import                — CSV import (contacts)
"""

import csv
import io
import logging

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from pydantic import BaseModel

from core.auth import get_current_user
from integrations.registry import is_enabled
from . import client as crm
from .db import init_db, _connection

logger = logging.getLogger(__name__)
router = APIRouter()


# ── CRM-enabled guard ────────────────────────────────────────────────────────

def _require_crm(user=Depends(get_current_user)):
    """Dependency that ensures CRM is enabled and DB is initialized."""
    if not is_enabled("crm_lite"):
        raise HTTPException(status_code=403, detail="CRM is not enabled")
    global _connection
    if _connection is None:
        init_db()
    return user


# ── Request models ────────────────────────────────────────────────────────────

class ContactCreate(BaseModel):
    name: str
    email: str = ""
    phone: str = ""
    company: str = ""
    title: str = ""
    source: str = ""
    status: str = "active"
    tags: str = ""
    notes: str = ""


class ContactUpdate(BaseModel):
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    company: str | None = None
    title: str | None = None
    source: str | None = None
    status: str | None = None
    tags: str | None = None
    notes: str | None = None


class DealCreate(BaseModel):
    title: str
    contact_id: int | None = None
    stage: str = "lead"
    value: float = 0
    notes: str = ""
    expected_close_date: str = ""
    probability: int = 0
    currency: str = "USD"


class DealUpdate(BaseModel):
    title: str | None = None
    contact_id: int | None = None
    stage: str | None = None
    value: float | None = None
    notes: str | None = None
    expected_close_date: str | None = None
    probability: int | None = None
    currency: str | None = None


class TaskCreate(BaseModel):
    title: str
    description: str = ""
    due_date: str = ""
    contact_id: int | None = None
    deal_id: int | None = None
    priority: str = "medium"


class TaskUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    due_date: str | None = None
    contact_id: int | None = None
    deal_id: int | None = None
    priority: str | None = None
    completed: int | None = None


class ActivityCreate(BaseModel):
    activity: str
    note: str = ""
    contact_id: int | None = None
    deal_id: int | None = None


# ── Contacts ──────────────────────────────────────────────────────────────────

@router.get("/contacts")
async def list_contacts(
    q: str = "", status: str = "", limit: int = 50, offset: int = 0,
    user=Depends(_require_crm),
):
    if q:
        contacts = crm.search_contacts(q, status=status or None)
        return {"contacts": contacts, "total": len(contacts)}
    return crm.list_contacts(offset=offset, limit=limit, status=status or None)


@router.get("/contacts/{contact_id}")
async def get_contact(contact_id: int, user=Depends(_require_crm)):
    result = crm.get_contact_detail(contact_id)
    if not result:
        raise HTTPException(status_code=404, detail="Contact not found")
    return result


@router.post("/contacts")
async def create_contact(body: ContactCreate, user=Depends(_require_crm)):
    if not body.name.strip():
        raise HTTPException(status_code=400, detail="Name is required")
    return crm.create_contact(**body.model_dump())


@router.put("/contacts/{contact_id}")
async def update_contact(contact_id: int, body: ContactUpdate, user=Depends(_require_crm)):
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    result = crm.update_contact(contact_id, **updates)
    if not result:
        raise HTTPException(status_code=404, detail="Contact not found")
    return result


@router.delete("/contacts/{contact_id}")
async def delete_contact(contact_id: int, user=Depends(_require_crm)):
    if not crm.delete_contact(contact_id):
        raise HTTPException(status_code=404, detail="Contact not found")
    return {"deleted": True, "contact_id": contact_id}


# ── Deals ─────────────────────────────────────────────────────────────────────

@router.get("/deals")
async def list_deals(
    stage: str = "", contact_id: int | None = None,
    user=Depends(_require_crm),
):
    if stage or contact_id:
        deals = crm.list_deals(stage=stage or None, contact_id=contact_id)
        return {"deals": deals, "count": len(deals)}
    return crm.get_pipeline()


@router.get("/deals/{deal_id}")
async def get_deal(deal_id: int, user=Depends(_require_crm)):
    result = crm.get_deal_detail(deal_id)
    if not result:
        raise HTTPException(status_code=404, detail="Deal not found")
    return result


@router.post("/deals")
async def create_deal(body: DealCreate, user=Depends(_require_crm)):
    if not body.title.strip():
        raise HTTPException(status_code=400, detail="Title is required")
    return crm.create_deal(**body.model_dump())


@router.put("/deals/{deal_id}")
async def update_deal(deal_id: int, body: DealUpdate, user=Depends(_require_crm)):
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    result = crm.update_deal(deal_id, **updates)
    if not result:
        raise HTTPException(status_code=404, detail="Deal not found or invalid stage")
    return result


# ── Tasks ─────────────────────────────────────────────────────────────────────

@router.get("/tasks")
async def list_tasks(
    contact_id: int | None = None, deal_id: int | None = None,
    completed: bool | None = None, due_before: str = "",
    priority: str = "", limit: int = 50,
    user=Depends(_require_crm),
):
    tasks = crm.list_tasks(
        contact_id=contact_id, deal_id=deal_id,
        completed=completed, due_before=due_before or None,
        priority=priority or None, limit=limit,
    )
    return {"tasks": tasks, "count": len(tasks)}


@router.post("/tasks")
async def create_task(body: TaskCreate, user=Depends(_require_crm)):
    if not body.title.strip():
        raise HTTPException(status_code=400, detail="Title is required")
    return crm.create_task(**body.model_dump())


@router.put("/tasks/{task_id}")
async def update_task(task_id: int, body: TaskUpdate, user=Depends(_require_crm)):
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    result = crm.update_task(task_id, **updates)
    if not result:
        raise HTTPException(status_code=404, detail="Task not found")
    return result


@router.put("/tasks/{task_id}/complete")
async def complete_task(task_id: int, user=Depends(_require_crm)):
    result = crm.complete_task(task_id)
    if not result:
        raise HTTPException(status_code=404, detail="Task not found")
    return result


@router.delete("/tasks/{task_id}")
async def delete_task(task_id: int, user=Depends(_require_crm)):
    if not crm.delete_task(task_id):
        raise HTTPException(status_code=404, detail="Task not found")
    return {"deleted": True, "task_id": task_id}


# ── Activity ──────────────────────────────────────────────────────────────────

@router.get("/activity")
async def get_activity(
    contact_id: int | None = None, deal_id: int | None = None,
    limit: int = 20, user=Depends(_require_crm),
):
    activities = crm.get_activity_log(contact_id=contact_id, deal_id=deal_id, limit=limit)
    return {"activities": activities, "count": len(activities)}


@router.post("/activity")
async def log_activity(body: ActivityCreate, user=Depends(_require_crm)):
    if not body.activity.strip():
        raise HTTPException(status_code=400, detail="Activity type is required")
    return crm.log_activity(**body.model_dump())


# ── Dashboard ─────────────────────────────────────────────────────────────────

@router.get("/dashboard")
async def dashboard(user=Depends(_require_crm)):
    return crm.get_dashboard_stats()


# ── CSV Import ────────────────────────────────────────────────────────────────

@router.post("/import")
async def import_csv(file: UploadFile = File(...), user=Depends(_require_crm)):
    """Import contacts from a CSV file.

    Expected columns (case-insensitive, flexible matching):
    name (required), email, phone, company, title, source, tags, notes
    """
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="File must be a .csv")

    content = await file.read()
    try:
        text = content.decode("utf-8-sig")  # Handle BOM
    except UnicodeDecodeError:
        text = content.decode("latin-1")

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise HTTPException(status_code=400, detail="CSV has no headers")

    # Normalize headers to lowercase
    field_map = {f.strip().lower(): f for f in reader.fieldnames}

    # Map common column name variations
    COLUMN_ALIASES = {
        "name": ["name", "full_name", "full name", "contact_name", "contact name"],
        "email": ["email", "email_address", "email address", "e-mail"],
        "phone": ["phone", "phone_number", "phone number", "tel", "telephone"],
        "company": ["company", "company_name", "company name", "organization", "org"],
        "title": ["title", "job_title", "job title", "position", "role"],
        "source": ["source", "lead_source", "lead source", "origin"],
        "tags": ["tags", "labels", "categories"],
        "notes": ["notes", "note", "comments", "description"],
    }

    def _resolve(target: str) -> str | None:
        for alias in COLUMN_ALIASES.get(target, []):
            if alias in field_map:
                return field_map[alias]
        return None

    name_col = _resolve("name")
    if not name_col:
        raise HTTPException(status_code=400, detail="CSV must have a 'name' column")

    imported = 0
    skipped = 0
    errors = []

    for i, row in enumerate(reader, start=2):  # Row 2+ (after header)
        name = (row.get(name_col) or "").strip()
        if not name:
            skipped += 1
            continue
        try:
            crm.create_contact(
                name=name,
                email=(row.get(_resolve("email") or "", "") or "").strip(),
                phone=(row.get(_resolve("phone") or "", "") or "").strip(),
                company=(row.get(_resolve("company") or "", "") or "").strip(),
                title=(row.get(_resolve("title") or "", "") or "").strip(),
                source=(row.get(_resolve("source") or "", "") or "").strip(),
                tags=(row.get(_resolve("tags") or "", "") or "").strip(),
                notes=(row.get(_resolve("notes") or "", "") or "").strip(),
            )
            imported += 1
        except Exception as e:
            errors.append(f"Row {i}: {e}")
            if len(errors) > 50:
                break

    return {"imported": imported, "skipped": skipped, "errors": errors}
