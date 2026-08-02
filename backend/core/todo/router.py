"""
Chatty — Todo (GTD) REST API for the frontend.

All endpoints require JWT auth (the todo system is a core feature — no
enabled guard). Single-item endpoints return the entity; list endpoints
return envelopes ({"todos": [...]}, {"projects": [...]}).

  GET    /api/todo/todos            — filtered list
  POST   /api/todo/todos            — create (source forced to "ui")
  GET    /api/todo/todos/:id        — detail
  PUT    /api/todo/todos/:id        — partial update (only provided fields)
  DELETE /api/todo/todos/:id        — delete
  POST   /api/todo/todos/bulk       — same fields applied to many ids
  GET    /api/todo/projects         — list with open counts
  POST   /api/todo/projects         — create
  PUT    /api/todo/projects/:id     — partial update
  DELETE /api/todo/projects/:id     — delete (todos orphan, not deleted)
  GET    /api/todo/filters          — contexts, tags, per-status counts
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from core.auth import get_current_user
from core.todo import service

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Request models ────────────────────────────────────────────────────────────

class TodoCreate(BaseModel):
    title: str
    notes: str = ""
    project: str | None = None
    project_id: int | None = None
    context: str = ""
    tags: list[str] = []
    status: str = "inbox"
    star: bool = False
    due_date: str | None = None


class TodoUpdate(BaseModel):
    title: str | None = None
    notes: str | None = None
    project: str | None = None
    project_id: int | None = None
    context: str | None = None
    tags: list[str] | None = None
    status: str | None = None
    star: bool | None = None
    due_date: str | None = None


class TodoBulkUpdate(BaseModel):
    ids: list[int]
    fields: dict


class ProjectCreate(BaseModel):
    name: str
    notes: str = ""
    status: str = "active"


class ProjectUpdate(BaseModel):
    name: str | None = None
    notes: str | None = None
    status: str | None = None


# ── Todos ─────────────────────────────────────────────────────────────────────

@router.get("/todos")
async def list_todos(
    status: str | None = None,
    project: str | None = None,
    context: str | None = None,
    tag: str | None = None,
    starred: bool | None = None,
    due_before: str | None = None,
    due_after: str | None = None,
    search: str | None = None,
    limit: int = Query(default=200, ge=1, le=500),
    user=Depends(get_current_user),
):
    try:
        todos = service.list_todos(
            status=status, project=project, context=context, tag=tag, starred=starred,
            due_before=due_before, due_after=due_after, search=search, limit=limit,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"todos": todos}


@router.post("/todos")
async def create_todo(body: TodoCreate, user=Depends(get_current_user)):
    try:
        return service.create_todo(
            body.title,
            notes=body.notes,
            project=body.project,
            project_id=body.project_id,
            context=body.context,
            tags=body.tags,
            status=body.status,
            star=body.star,
            due_date=body.due_date,
            source="ui",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/todos/{todo_id}")
async def get_todo(todo_id: int, user=Depends(get_current_user)):
    todo = service.get_todo(todo_id)
    if not todo:
        raise HTTPException(status_code=404, detail="Todo not found")
    return todo


@router.put("/todos/{todo_id}")
async def update_todo(todo_id: int, body: TodoUpdate, user=Depends(get_current_user)):
    # exclude_unset: only fields the client actually sent are updated, so
    # explicit nulls/empties clear values without clobbering the rest.
    fields = body.model_dump(exclude_unset=True)
    try:
        todo = service.update_todo(todo_id, fields)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not todo:
        raise HTTPException(status_code=404, detail="Todo not found")
    return todo


@router.delete("/todos/{todo_id}")
async def delete_todo(todo_id: int, user=Depends(get_current_user)):
    if not service.delete_todo(todo_id):
        raise HTTPException(status_code=404, detail="Todo not found")
    return {"ok": True}


@router.post("/todos/bulk")
async def bulk_update(body: TodoBulkUpdate, user=Depends(get_current_user)):
    try:
        return service.bulk_update(body.ids, body.fields)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── Projects ──────────────────────────────────────────────────────────────────

@router.get("/projects")
async def list_projects(status: str | None = None, user=Depends(get_current_user)):
    try:
        return {"projects": service.list_projects(status=status)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/projects")
async def create_project(body: ProjectCreate, user=Depends(get_current_user)):
    try:
        return service.create_project(body.name, notes=body.notes, status=body.status)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/projects/{project_id}")
async def update_project(project_id: int, body: ProjectUpdate, user=Depends(get_current_user)):
    fields = body.model_dump(exclude_unset=True)
    try:
        project = service.update_project(project_id, fields)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.delete("/projects/{project_id}")
async def delete_project(project_id: int, user=Depends(get_current_user)):
    if not service.delete_project(project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    return {"ok": True}


# ── Filters ───────────────────────────────────────────────────────────────────

@router.get("/filters")
async def get_filters(user=Depends(get_current_user)):
    return service.get_filters()
