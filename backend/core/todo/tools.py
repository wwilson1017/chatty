"""
Chatty — Todo (GTD) agent tools.

Definitions + executors for the global todo store. These are core tools
(kind "todo"): always loaded for every agent, dispatched by ToolRegistry
via module-level executors — the store is global, so no per-agent binding
is needed.
"""

import logging

from core.todo import service

logger = logging.getLogger(__name__)

_STATUS_DESC = (
    "GTD status: 'inbox' (captured, unprocessed), 'next_action' (ready to do), "
    "'waiting_for' (blocked on someone/something), 'delegated' (handed off, track follow-up), "
    "'someday_maybe' (not committed), 'done', 'dropped' (decided not to do)"
)

_UPDATE_FIELD_PROPS = {
    "title": {"type": "string", "description": "Todo title — a physical, visible next action"},
    "notes": {"type": "string", "description": "Free-form details: links, phone numbers, context"},
    "project": {
        "type": "string",
        "description": "Project name (created automatically if missing). Empty string clears the project.",
    },
    "context": {
        "type": "string",
        "description": "Where/how the task gets done, e.g. '@home', '@errands', '@computer', '@calls'",
    },
    "tags": {
        "type": "array",
        "items": {"type": "string"},
        "description": "Free-form labels (e.g. energy levels). Replaces the existing tag list.",
    },
    "status": {"type": "string", "enum": list(service.TODO_STATUSES), "description": _STATUS_DESC},
    "star": {"type": "boolean", "description": "Priority flag — keep starred items to a handful"},
    "due_date": {
        "type": "string",
        "description": "Real deadline as YYYY-MM-DD (not an aspiration). Empty string clears it.",
    },
}

TODO_TOOL_DEFS: list[dict] = [
    {
        "name": "todo_create",
        "description": (
            "Create a todo in the user's global GTD list. Defaults to the inbox; "
            "set status/project/context when the item is already clarified."
        ),
        "input_schema": {
            "type": "object",
            "properties": dict(_UPDATE_FIELD_PROPS),
            "required": ["title"],
        },
        "kind": "todo",
        "writes": True,
    },
    {
        "name": "todo_list",
        "description": (
            "List todos with filters. All filters are optional and combine with AND. "
            "Returns todos oldest-first (inbox processing order); done/dropped lists "
            "return newest-finished first."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": list(service.TODO_STATUSES), "description": _STATUS_DESC},
                "project": {"type": "string", "description": "Project name (or numeric id)"},
                "context": {"type": "string", "description": "Exact context match, e.g. '@home'"},
                "tag": {"type": "string", "description": "Todos carrying this tag"},
                "starred": {"type": "boolean", "description": "Only starred (true) or unstarred (false)"},
                "due_before": {"type": "string", "description": "due_date on or before this YYYY-MM-DD (overdue check: today's date)"},
                "due_after": {"type": "string", "description": "due_date on or after this YYYY-MM-DD"},
                "search": {"type": "string", "description": "Substring match on title and notes"},
                "limit": {"type": "integer", "description": "Max results (default 100, cap 500)"},
            },
            "required": [],
        },
        "kind": "todo",
        "writes": False,
    },
    {
        "name": "todo_get",
        "description": "Get one todo by id, including all fields and its project name.",
        "input_schema": {
            "type": "object",
            "properties": {"id": {"type": "integer", "description": "Todo id"}},
            "required": ["id"],
        },
        "kind": "todo",
        "writes": False,
    },
    {
        "name": "todo_update",
        "description": (
            "Update fields on one todo. Setting status 'done' timestamps completion; "
            "moving off 'done' clears it. Only provided fields change."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"id": {"type": "integer", "description": "Todo id"}, **_UPDATE_FIELD_PROPS},
            "required": ["id"],
        },
        "kind": "todo",
        "writes": True,
    },
    {
        "name": "todo_bulk_update",
        "description": (
            "Apply the same field changes to many todos at once (one transaction). "
            "Great for GTD processing: move several inbox items to next_action, "
            "assign a batch to a project, complete a list."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ids": {"type": "array", "items": {"type": "integer"}, "description": "Todo ids to update"},
                "fields": {
                    "type": "object",
                    "properties": _UPDATE_FIELD_PROPS,
                    "description": "Fields to set on every listed todo",
                },
            },
            "required": ["ids", "fields"],
        },
        "kind": "todo",
        "writes": True,
    },
    {
        "name": "todo_delete",
        "description": (
            "Permanently delete a todo. Prefer status 'dropped' to keep history; "
            "delete is for true mistakes/duplicates."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"id": {"type": "integer", "description": "Todo id"}},
            "required": ["id"],
        },
        "kind": "todo",
        "writes": True,
    },
    {
        "name": "todo_list_projects",
        "description": (
            "List projects with open-todo counts. GTD: every active project should "
            "have at least one next_action — flag ones that don't."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": list(service.PROJECT_STATUSES),
                    "description": "Filter: 'active', 'someday', 'completed', 'dropped'",
                },
            },
            "required": [],
        },
        "kind": "todo",
        "writes": False,
    },
    {
        "name": "todo_create_project",
        "description": "Create a project (an outcome needing more than one action). Names are unique (case-insensitive).",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Project name"},
                "notes": {"type": "string", "description": "Desired outcome, background, links"},
                "status": {
                    "type": "string",
                    "enum": list(service.PROJECT_STATUSES),
                    "description": "Default 'active'; use 'someday' for not-yet-committed projects",
                },
            },
            "required": ["name"],
        },
        "kind": "todo",
        "writes": True,
    },
    {
        "name": "todo_update_project",
        "description": "Rename a project, edit its notes, or change its status (active/someday/completed/dropped).",
        "input_schema": {
            "type": "object",
            "properties": {
                "id": {"type": "integer", "description": "Project id"},
                "name": {"type": "string", "description": "New name (unique, case-insensitive)"},
                "notes": {"type": "string", "description": "New notes"},
                "status": {"type": "string", "enum": list(service.PROJECT_STATUSES), "description": "New status"},
            },
            "required": ["id"],
        },
        "kind": "todo",
        "writes": True,
    },
    {
        "name": "todo_delete_project",
        "description": "Delete a project. Its todos survive and become project-less (they are NOT deleted).",
        "input_schema": {
            "type": "object",
            "properties": {"id": {"type": "integer", "description": "Project id"}},
            "required": ["id"],
        },
        "kind": "todo",
        "writes": True,
    },
    {
        "name": "todo_update_gtd_coaching",
        "description": (
            "Replace the GTD coaching text injected into EVERY agent's system prompt — "
            "this changes global instructions for all agents, so confirm intent with the "
            "user before calling. Full replace: send the complete new text. Empty string "
            "disables the coaching block. Returns the previous text so the change can be undone."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "The complete replacement coaching text (max 20,000 characters). Empty string disables coaching.",
                },
            },
            "required": ["text"],
        },
        "kind": "todo",
        "writes": True,
    },
]


# ── Executors ─────────────────────────────────────────────────────────────────

def _exec_create(**args) -> dict:
    args.pop("source", None)  # agents cannot spoof capture sources
    try:
        return {"todo": service.create_todo(args.pop("title", ""), source="agent", **args)}
    except (ValueError, TypeError) as e:
        return {"error": str(e)}


def _exec_list(**args) -> dict:
    try:
        todos = service.list_todos(**args)
        return {"todos": todos, "count": len(todos)}
    except (ValueError, TypeError) as e:
        return {"error": str(e)}


def _exec_get(**args) -> dict:
    todo = service.get_todo(int(args.get("id", 0)))
    return {"todo": todo} if todo else {"error": f"Todo not found: {args.get('id')}"}


def _exec_update(**args) -> dict:
    todo_id = args.pop("id", None)
    try:
        todo = service.update_todo(int(todo_id), args)
        return {"todo": todo} if todo else {"error": f"Todo not found: {todo_id}"}
    except (ValueError, TypeError) as e:
        return {"error": str(e)}


def _exec_bulk_update(**args) -> dict:
    try:
        return service.bulk_update(args.get("ids") or [], args.get("fields") or {})
    except (ValueError, TypeError) as e:
        return {"error": str(e)}


def _exec_delete(**args) -> dict:
    todo_id = args.get("id")
    if service.delete_todo(int(todo_id or 0)):
        return {"ok": True, "deleted": todo_id}
    return {"error": f"Todo not found: {todo_id}"}


def _exec_list_projects(**args) -> dict:
    try:
        projects = service.list_projects(status=args.get("status"))
        return {"projects": projects, "count": len(projects)}
    except (ValueError, TypeError) as e:
        return {"error": str(e)}


def _exec_create_project(**args) -> dict:
    try:
        return {
            "project": service.create_project(
                args.get("name", ""), notes=args.get("notes", ""), status=args.get("status", "active")
            )
        }
    except (ValueError, TypeError) as e:
        return {"error": str(e)}


def _exec_update_project(**args) -> dict:
    project_id = args.pop("id", None)
    try:
        project = service.update_project(int(project_id), args)
        return {"project": project} if project else {"error": f"Project not found: {project_id}"}
    except (ValueError, TypeError) as e:
        return {"error": str(e)}


def _exec_update_coaching(**args) -> dict:
    from core.admin_settings import load_admin_settings, set_admin_setting
    from core.todo.coaching import MAX_COACHING_CHARS

    text = args.get("text")
    if not isinstance(text, str):
        return {"error": "text must be a string"}
    if len(text) > MAX_COACHING_CHARS:
        return {"error": f"text too long (max {MAX_COACHING_CHARS} characters)"}
    previous = load_admin_settings().get("gtd_coaching_text", "")
    set_admin_setting("gtd_coaching_text", text.strip())
    return {"ok": True, "previous_text": previous, "coaching_disabled": not text.strip()}


def _exec_delete_project(**args) -> dict:
    project_id = args.get("id")
    if service.delete_project(int(project_id or 0)):
        return {"ok": True, "deleted": project_id, "note": "Its todos survive without a project"}
    return {"error": f"Project not found: {project_id}"}


TODO_TOOL_EXECUTORS: dict = {
    "todo_create": _exec_create,
    "todo_list": _exec_list,
    "todo_get": _exec_get,
    "todo_update": _exec_update,
    "todo_bulk_update": _exec_bulk_update,
    "todo_delete": _exec_delete,
    "todo_list_projects": _exec_list_projects,
    "todo_create_project": _exec_create_project,
    "todo_update_project": _exec_update_project,
    "todo_delete_project": _exec_delete_project,
    "todo_update_gtd_coaching": _exec_update_coaching,
}
