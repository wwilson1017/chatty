"""Chatty — Odoo Project tools."""

import logging
from datetime import date as date_type

from ..helpers import safe_get_client, html_to_text

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

PROJECT_TOOL_DEFS = [
    # --- Read tools ---
    {
        "name": "odoo_search_projects",
        "description": "Search Odoo projects with optional filters by name, manager, or active status.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Filter by project name (case-insensitive partial match).",
                },
                "user_id": {
                    "type": "integer",
                    "description": "Filter by project manager (user) ID.",
                },
                "active": {
                    "type": "boolean",
                    "description": "Filter by active status (default true).",
                    "default": True,
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results (default 20).",
                    "default": 20,
                },
            },
            "required": [],
        },
        "kind": "integration",
    },
    {
        "name": "odoo_get_project_details",
        "description": "Get full details for a single Odoo project including task counts grouped by stage.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "integer",
                    "description": "The ID of the project to retrieve.",
                },
            },
            "required": ["project_id"],
        },
        "kind": "integration",
    },
    {
        "name": "odoo_search_tasks",
        "description": "Search project tasks with optional filters by project, stage, assignee, priority, deadline, or keyword.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "integer",
                    "description": "Filter by project ID.",
                },
                "stage": {
                    "type": "string",
                    "description": "Filter by stage name (case-insensitive partial match).",
                },
                "user_id": {
                    "type": "integer",
                    "description": "Filter by assignee (user) ID.",
                },
                "priority": {
                    "type": "string",
                    "enum": ["0", "1"],
                    "description": "Filter by priority: '0' = normal, '1' = urgent.",
                },
                "date_deadline_before": {
                    "type": "string",
                    "description": "Only tasks with deadline on or before this date (YYYY-MM-DD).",
                },
                "keyword": {
                    "type": "string",
                    "description": "Search keyword matched against task name.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results (default 50).",
                    "default": 50,
                },
            },
            "required": [],
        },
        "kind": "integration",
    },
    {
        "name": "odoo_get_task_details",
        "description": "Get full details for a single project task including subtask info, time tracking, and description.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "integer",
                    "description": "The ID of the task to retrieve.",
                },
            },
            "required": ["task_id"],
        },
        "kind": "integration",
    },
    # --- Write tools ---
    {
        "name": "odoo_create_task",
        "description": "Create a new task in an Odoo project.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Title of the task.",
                },
                "project_id": {
                    "type": "integer",
                    "description": "The project ID to create the task in.",
                },
                "user_ids": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "List of user IDs to assign as task members.",
                },
                "stage_id": {
                    "type": "integer",
                    "description": "Stage ID to place the task in.",
                },
                "priority": {
                    "type": "string",
                    "enum": ["0", "1"],
                    "description": "Priority: '0' = normal, '1' = urgent.",
                },
                "date_deadline": {
                    "type": "string",
                    "description": "Task deadline (YYYY-MM-DD).",
                },
                "description": {
                    "type": "string",
                    "description": "Task description or notes.",
                },
                "parent_id": {
                    "type": "integer",
                    "description": "Parent task ID (makes this a subtask).",
                },
                "planned_hours": {
                    "type": "number",
                    "description": "Planned hours for the task.",
                },
            },
            "required": ["name", "project_id"],
        },
        "kind": "integration",
    },
    {
        "name": "odoo_update_task",
        "description": "Update fields on an existing project task. Provide only the fields you want to change.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "integer",
                    "description": "The ID of the task to update.",
                },
                "name": {
                    "type": "string",
                    "description": "New task title.",
                },
                "stage_id": {
                    "type": "integer",
                    "description": "New stage ID.",
                },
                "user_ids": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "New list of assignee user IDs (replaces existing).",
                },
                "priority": {
                    "type": "string",
                    "enum": ["0", "1"],
                    "description": "Priority: '0' = normal, '1' = urgent.",
                },
                "date_deadline": {
                    "type": "string",
                    "description": "New deadline (YYYY-MM-DD).",
                },
                "description": {
                    "type": "string",
                    "description": "New description.",
                },
                "kanban_state": {
                    "type": "string",
                    "enum": ["normal", "done", "blocked"],
                    "description": "Kanban state: 'normal', 'done' (ready for next stage), or 'blocked'.",
                },
                "planned_hours": {
                    "type": "number",
                    "description": "Planned hours for the task.",
                },
            },
            "required": ["task_id"],
        },
        "kind": "integration",
    },
    {
        "name": "odoo_log_timesheet",
        "description": "Log time spent on a project task as a timesheet entry.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "integer",
                    "description": "The task ID to log time on.",
                },
                "hours": {
                    "type": "number",
                    "description": "Number of hours to log.",
                },
                "description": {
                    "type": "string",
                    "description": "Description of work performed.",
                    "default": "",
                },
                "date": {
                    "type": "string",
                    "description": "Date for the entry (YYYY-MM-DD). Defaults to today.",
                },
            },
            "required": ["task_id", "hours"],
        },
        "kind": "integration",
    },
]

# ---------------------------------------------------------------------------
# Executor functions
# ---------------------------------------------------------------------------


def odoo_search_projects(
    name: str | None = None,
    user_id: int | None = None,
    active: bool = True,
    limit: int = 20,
) -> dict:
    """Search Odoo projects with optional filters."""
    client, err = safe_get_client()
    if err:
        return err

    domain: list = [["active", "=", active]]
    if name:
        domain.append(["name", "ilike", name])
    if user_id:
        domain.append(["user_id", "=", user_id])

    fields = [
        "id", "name", "user_id", "partner_id", "task_count",
        "date_start", "date", "active", "stage_id",
    ]
    records = client.search_read("project.project", domain, fields, limit=limit) or []

    projects = []
    for r in records:
        projects.append({
            "id": r["id"],
            "name": r.get("name", ""),
            "manager": r["user_id"][1] if r.get("user_id") else None,
            "manager_id": r["user_id"][0] if r.get("user_id") else None,
            "customer": r["partner_id"][1] if r.get("partner_id") else None,
            "customer_id": r["partner_id"][0] if r.get("partner_id") else None,
            "task_count": r.get("task_count", 0),
            "date_start": r.get("date_start", ""),
            "date_end": r.get("date", ""),
            "active": r.get("active", True),
            "stage": r["stage_id"][1] if r.get("stage_id") else None,
            "stage_id": r["stage_id"][0] if r.get("stage_id") else None,
        })

    return {"projects": projects, "total": len(projects)}


def odoo_get_project_details(project_id: int) -> dict:
    """Get full details for a single project with task-by-stage breakdown."""
    client, err = safe_get_client()
    if err:
        return err

    fields = [
        "id", "name", "user_id", "partner_id", "task_count",
        "date_start", "date", "active", "description",
        "label_tasks", "allow_timesheets",
    ]
    records = client.search_read(
        "project.project", [["id", "=", project_id]], fields, limit=1
    ) or []
    if not records:
        return {"error": f"Project #{project_id} not found"}

    r = records[0]

    # Count tasks grouped by stage
    task_records = client.search_read(
        "project.task",
        [["project_id", "=", project_id]],
        ["stage_id"],
        limit=500,
    ) or []

    stages: dict[str, dict] = {}
    for t in task_records:
        stage_name = t["stage_id"][1] if t.get("stage_id") else "No Stage"
        stage_id = t["stage_id"][0] if t.get("stage_id") else 0
        key = str(stage_id)
        if key not in stages:
            stages[key] = {"stage": stage_name, "stage_id": stage_id, "count": 0}
        stages[key]["count"] += 1

    tasks_by_stage = sorted(stages.values(), key=lambda s: s["stage_id"])

    return {
        "id": r["id"],
        "name": r.get("name", ""),
        "manager": r["user_id"][1] if r.get("user_id") else None,
        "manager_id": r["user_id"][0] if r.get("user_id") else None,
        "customer": r["partner_id"][1] if r.get("partner_id") else None,
        "customer_id": r["partner_id"][0] if r.get("partner_id") else None,
        "task_count": r.get("task_count", 0),
        "date_start": r.get("date_start", ""),
        "date_end": r.get("date", ""),
        "active": r.get("active", True),
        "description": html_to_text(r.get("description", "") or ""),
        "label_tasks": r.get("label_tasks", "Tasks"),
        "allow_timesheets": r.get("allow_timesheets", False),
        "tasks_by_stage": tasks_by_stage,
    }


def odoo_search_tasks(
    project_id: int | None = None,
    stage: str | None = None,
    user_id: int | None = None,
    priority: str | None = None,
    date_deadline_before: str | None = None,
    keyword: str | None = None,
    limit: int = 50,
) -> dict:
    """Search project tasks with optional filters."""
    client, err = safe_get_client()
    if err:
        return err

    domain: list = []
    if project_id:
        domain.append(["project_id", "=", project_id])
    if stage:
        domain.append(["stage_id.name", "ilike", stage])
    if user_id:
        domain.append(["user_ids", "in", [user_id]])
    if priority:
        domain.append(["priority", "=", priority])
    if date_deadline_before:
        domain.append(["date_deadline", "<=", date_deadline_before])
    if keyword:
        domain.append(["name", "ilike", keyword])

    fields = [
        "id", "name", "project_id", "stage_id", "user_ids",
        "priority", "date_deadline", "date_last_stage_update",
        "kanban_state", "create_date",
    ]
    records = client.search_read("project.task", domain, fields, limit=limit) or []

    # Collect all user IDs from user_ids (Many2many) to batch-read names
    all_user_ids: set[int] = set()
    for r in records:
        if r.get("user_ids"):
            all_user_ids.update(r["user_ids"])

    user_names: dict[int, str] = {}
    if all_user_ids:
        users = client.read("res.users", list(all_user_ids), ["name"]) or []
        for u in users:
            user_names[u["id"]] = u.get("name", "")

    tasks = []
    for r in records:
        assignees = [
            {"id": uid, "name": user_names.get(uid, "")}
            for uid in (r.get("user_ids") or [])
        ]
        tasks.append({
            "id": r["id"],
            "name": r.get("name", ""),
            "project": r["project_id"][1] if r.get("project_id") else None,
            "project_id": r["project_id"][0] if r.get("project_id") else None,
            "stage": r["stage_id"][1] if r.get("stage_id") else None,
            "stage_id": r["stage_id"][0] if r.get("stage_id") else None,
            "assignees": assignees,
            "priority": r.get("priority", "0"),
            "deadline": r.get("date_deadline", ""),
            "last_stage_update": r.get("date_last_stage_update", ""),
            "kanban_state": r.get("kanban_state", "normal"),
            "created": r.get("create_date", ""),
        })

    return {"tasks": tasks, "total": len(tasks)}


def odoo_get_task_details(task_id: int) -> dict:
    """Get full details for a single project task."""
    client, err = safe_get_client()
    if err:
        return err

    fields = [
        "id", "name", "project_id", "stage_id", "user_ids",
        "priority", "date_deadline", "description", "tag_ids",
        "create_date", "write_date", "kanban_state",
        "parent_id", "child_ids", "effective_hours",
        "planned_hours", "remaining_hours", "subtask_count",
    ]
    records = client.search_read(
        "project.task", [["id", "=", task_id]], fields, limit=1
    ) or []
    if not records:
        return {"error": f"Task #{task_id} not found"}

    r = records[0]

    # Resolve user_ids (Many2many) to names
    assignees = []
    if r.get("user_ids"):
        users = client.read("res.users", r["user_ids"], ["name"]) or []
        assignees = [{"id": u["id"], "name": u.get("name", "")} for u in users]

    # Resolve tag_ids (Many2many) to names
    tags = []
    if r.get("tag_ids"):
        tag_records = client.read("project.tags", r["tag_ids"], ["name"]) or []
        tags = [{"id": t["id"], "name": t.get("name", "")} for t in tag_records]

    # Resolve child_ids to names
    subtasks = []
    if r.get("child_ids"):
        child_records = client.read(
            "project.task", r["child_ids"], ["name", "stage_id"]
        ) or []
        subtasks = [
            {
                "id": c["id"],
                "name": c.get("name", ""),
                "stage": c["stage_id"][1] if c.get("stage_id") else None,
            }
            for c in child_records
        ]

    return {
        "id": r["id"],
        "name": r.get("name", ""),
        "project": r["project_id"][1] if r.get("project_id") else None,
        "project_id": r["project_id"][0] if r.get("project_id") else None,
        "stage": r["stage_id"][1] if r.get("stage_id") else None,
        "stage_id": r["stage_id"][0] if r.get("stage_id") else None,
        "assignees": assignees,
        "priority": r.get("priority", "0"),
        "deadline": r.get("date_deadline", ""),
        "description": html_to_text(r.get("description", "") or ""),
        "tags": tags,
        "created": r.get("create_date", ""),
        "updated": r.get("write_date", ""),
        "kanban_state": r.get("kanban_state", "normal"),
        "parent": r["parent_id"][1] if r.get("parent_id") else None,
        "parent_id": r["parent_id"][0] if r.get("parent_id") else None,
        "subtasks": subtasks,
        "subtask_count": r.get("subtask_count", 0),
        "effective_hours": r.get("effective_hours", 0),
        "planned_hours": r.get("planned_hours", 0),
        "remaining_hours": r.get("remaining_hours", 0),
    }


def odoo_create_task(
    name: str,
    project_id: int,
    user_ids: list[int] | None = None,
    stage_id: int | None = None,
    priority: str | None = None,
    date_deadline: str | None = None,
    description: str | None = None,
    parent_id: int | None = None,
    planned_hours: float | None = None,
) -> dict:
    """Create a new task in an Odoo project."""
    client, err = safe_get_client()
    if err:
        return err

    vals: dict = {"name": name, "project_id": project_id}
    if user_ids is not None:
        vals["user_ids"] = [(6, 0, user_ids)]
    if stage_id is not None:
        vals["stage_id"] = stage_id
    if priority is not None:
        vals["priority"] = priority
    if date_deadline is not None:
        vals["date_deadline"] = date_deadline
    if description is not None:
        vals["description"] = description
    if parent_id is not None:
        vals["parent_id"] = parent_id
    if planned_hours is not None:
        vals["planned_hours"] = planned_hours

    try:
        task_id = client.create("project.task", vals)
    except Exception as e:
        return {"error": f"Odoo error creating task: {e}"}

    if task_id is None:
        return {"error": "Failed to create task in Odoo"}

    # Read back the created task for confirmation
    tasks = client.search_read(
        "project.task",
        [["id", "=", task_id]],
        ["name", "project_id", "stage_id", "user_ids", "date_deadline"],
    )
    task = tasks[0] if tasks else {}

    # Resolve assignee names
    assignees = []
    if task.get("user_ids"):
        users = client.read("res.users", task["user_ids"], ["name"]) or []
        assignees = [{"id": u["id"], "name": u.get("name", "")} for u in users]

    return {
        "ok": True,
        "id": task_id,
        "name": task.get("name", name),
        "project": task["project_id"][1] if task.get("project_id") else None,
        "stage": task["stage_id"][1] if task.get("stage_id") else "New",
        "assignees": assignees,
        "deadline": task.get("date_deadline", date_deadline or ""),
    }


def odoo_update_task(
    task_id: int,
    name: str | None = None,
    stage_id: int | None = None,
    user_ids: list[int] | None = None,
    priority: str | None = None,
    date_deadline: str | None = None,
    description: str | None = None,
    kanban_state: str | None = None,
    planned_hours: float | None = None,
) -> dict:
    """Update fields on an existing project task."""
    client, err = safe_get_client()
    if err:
        return err

    vals: dict = {}
    if name is not None:
        vals["name"] = name
    if stage_id is not None:
        vals["stage_id"] = stage_id
    if user_ids is not None:
        vals["user_ids"] = [(6, 0, user_ids)]
    if priority is not None:
        vals["priority"] = priority
    if date_deadline is not None:
        vals["date_deadline"] = date_deadline
    if description is not None:
        vals["description"] = description
    if kanban_state is not None:
        vals["kanban_state"] = kanban_state
    if planned_hours is not None:
        vals["planned_hours"] = planned_hours

    if not vals:
        return {"error": "Nothing to update -- provide at least one field"}

    try:
        client.write("project.task", [task_id], vals)
    except Exception as e:
        return {"error": f"Odoo error updating task #{task_id}: {e}"}

    return {"ok": True, "task_id": task_id, "updated": {
        k: v for k, v in vals.items() if k != "user_ids"
    } | ({"user_ids": user_ids} if user_ids is not None else {})}


def odoo_log_timesheet(
    task_id: int,
    hours: float,
    description: str = "",
    date: str | None = None,
) -> dict:
    """Log time spent on a project task as a timesheet entry."""
    client, err = safe_get_client()
    if err:
        return err

    # Look up the task to get its project_id
    tasks = client.search_read(
        "project.task", [["id", "=", task_id]], ["project_id"], limit=1
    ) or []
    if not tasks:
        return {"error": f"Task #{task_id} not found"}

    task = tasks[0]
    if not task.get("project_id"):
        return {"error": f"Task #{task_id} has no associated project"}

    project_id = task["project_id"][0]
    entry_date = date or date_type.today().isoformat()

    vals = {
        "task_id": task_id,
        "project_id": project_id,
        "name": description or "/",
        "unit_amount": hours,
        "date": entry_date,
    }

    try:
        entry_id = client.create("account.analytic.line", vals)
    except Exception as e:
        return {"error": f"Odoo error logging timesheet: {e}"}

    if entry_id is None:
        return {"error": "Failed to create timesheet entry"}

    return {
        "ok": True,
        "id": entry_id,
        "task_id": task_id,
        "project_id": project_id,
        "hours": hours,
        "description": description,
        "date": entry_date,
    }


# ---------------------------------------------------------------------------
# Executor map
# ---------------------------------------------------------------------------

PROJECT_EXECUTORS = {
    "odoo_search_projects": lambda **kw: odoo_search_projects(**kw),
    "odoo_get_project_details": lambda **kw: odoo_get_project_details(**kw),
    "odoo_search_tasks": lambda **kw: odoo_search_tasks(**kw),
    "odoo_get_task_details": lambda **kw: odoo_get_task_details(**kw),
    "odoo_create_task": lambda **kw: odoo_create_task(**kw),
    "odoo_update_task": lambda **kw: odoo_update_task(**kw),
    "odoo_log_timesheet": lambda **kw: odoo_log_timesheet(**kw),
}
