"""Chatty — Todoist agent tools.

17 tools covering tasks, projects, sections, comments, and labels.
Uses the official todoist-api-python SDK (async client).
"""

import logging
from datetime import date, datetime, timedelta, timezone

from .client import get_client_async

logger = logging.getLogger(__name__)

# Priority mapping: Todoist API uses inverted numbering
# p1 (urgent) in UI = priority 4 in API
# p4 (normal) in UI = priority 1 in API
_UI_TO_API_PRIORITY = {1: 4, 2: 3, 3: 2, 4: 1}
_API_TO_UI_PRIORITY = {4: 1, 3: 2, 2: 3, 1: 4}


def _to_str(val) -> str | None:
    """Convert date/datetime objects to ISO strings for JSON serialization."""
    if val is None:
        return None
    return val.isoformat() if hasattr(val, "isoformat") else str(val)


def _format_task(task) -> dict:
    """Convert a Task object to a clean dict for the agent."""
    due = None
    if task.due:
        due = {
            "date": _to_str(task.due.date),
            "string": task.due.string,
            "is_recurring": task.due.is_recurring,
        }
        if task.due.timezone:
            due["timezone"] = task.due.timezone

    result = {
        "id": task.id,
        "content": task.content,
        "description": task.description or "",
        "project_id": task.project_id,
        "section_id": task.section_id or None,
        "priority": _API_TO_UI_PRIORITY.get(task.priority, task.priority),
        "labels": task.labels or [],
        "due": due,
        "url": task.url,
        "created_at": _to_str(task.created_at),
    }
    if task.parent_id:
        result["parent_id"] = task.parent_id
    return result


def _format_project(project) -> dict:
    """Convert a Project object to a clean dict."""
    return {
        "id": project.id,
        "name": project.name,
        "color": project.color,
        "is_favorite": project.is_favorite,
        "is_shared": project.is_shared,
        "url": project.url,
    }


def _format_section(section) -> dict:
    """Convert a Section object to a clean dict."""
    return {
        "id": section.id,
        "name": section.name,
        "project_id": section.project_id,
        "order": section.order,
    }


def _format_comment(comment) -> dict:
    """Convert a Comment object to a clean dict."""
    return {
        "id": comment.id,
        "content": comment.content,
        "posted_at": _to_str(comment.posted_at),
        "task_id": getattr(comment, "task_id", None),
        "project_id": getattr(comment, "project_id", None),
    }


def _format_label(label) -> dict:
    """Convert a Label object to a clean dict."""
    return {
        "id": label.id,
        "name": label.name,
        "color": label.color,
        "order": label.order,
        "is_favorite": label.is_favorite,
    }


# ── Tool definitions ──────────────────────────────────────────────────────

TODOIST_TOOL_DEFS = [
    # ── Tasks ──────────────────────────────────────────────────────────
    {
        "name": "todoist_get_tasks",
        "description": (
            "List Todoist tasks. Supports Todoist's filter syntax "
            '(e.g. "today", "overdue", "#Work & p1", "due before: next week"). '
            "Can also filter by project_id, section_id, or label."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "filter": {
                    "type": "string",
                    "description": 'Todoist filter query (e.g. "today | overdue", "#ProjectName & p1")',
                },
                "project_id": {
                    "type": "string",
                    "description": "Filter by project ID",
                },
                "section_id": {
                    "type": "string",
                    "description": "Filter by section ID",
                },
                "label": {
                    "type": "string",
                    "description": "Filter by label name",
                },
            },
            "required": [],
        },
        "kind": "integration",
    },
    {
        "name": "todoist_get_task",
        "description": "Get a single Todoist task by its ID.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "The task ID"},
            },
            "required": ["task_id"],
        },
        "kind": "integration",
    },
    {
        "name": "todoist_create_task",
        "description": (
            "Create a new Todoist task. Priority uses p1 (urgent) through p4 (normal). "
            "Due dates accept natural language (e.g. 'tomorrow', 'every Monday')."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "Task title/content"},
                "description": {"type": "string", "description": "Detailed description"},
                "project_id": {"type": "string", "description": "Project to add the task to"},
                "section_id": {"type": "string", "description": "Section within the project"},
                "parent_id": {"type": "string", "description": "Parent task ID (to create a subtask)"},
                "priority": {
                    "type": "integer",
                    "description": "Priority: 1 (urgent/p1) to 4 (normal/p4)",
                    "enum": [1, 2, 3, 4],
                },
                "due_string": {
                    "type": "string",
                    "description": "Due date in natural language (e.g. 'tomorrow', 'every Friday', 'Jan 5')",
                },
                "due_date": {
                    "type": "string",
                    "description": "Due date as YYYY-MM-DD",
                },
                "labels": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Label names to apply",
                },
            },
            "required": ["content"],
        },
        "kind": "integration",
        "writes": True,
    },
    {
        "name": "todoist_quick_add",
        "description": (
            "Create a task using Todoist's natural language parser. "
            'Supports inline syntax like "Buy milk tomorrow #Shopping @errands p1". '
            "Project (#), label (@), priority (p1-p4), and due dates are parsed automatically."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "Natural language task text with inline project/label/date/priority",
                },
            },
            "required": ["text"],
        },
        "kind": "integration",
        "writes": True,
    },
    {
        "name": "todoist_update_task",
        "description": "Update an existing Todoist task. Only provide fields you want to change.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "The task ID to update"},
                "content": {"type": "string", "description": "New task title"},
                "description": {"type": "string", "description": "New description"},
                "priority": {
                    "type": "integer",
                    "description": "New priority: 1 (urgent/p1) to 4 (normal/p4)",
                    "enum": [1, 2, 3, 4],
                },
                "due_string": {
                    "type": "string",
                    "description": "New due date in natural language",
                },
                "due_date": {
                    "type": "string",
                    "description": "New due date as YYYY-MM-DD",
                },
                "labels": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Replace labels with this list",
                },
            },
            "required": ["task_id"],
        },
        "kind": "integration",
        "writes": True,
    },
    {
        "name": "todoist_complete_task",
        "description": "Mark a Todoist task as complete. For recurring tasks, advances to the next occurrence.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "The task ID to complete"},
            },
            "required": ["task_id"],
        },
        "kind": "integration",
        "writes": True,
    },
    {
        "name": "todoist_reopen_task",
        "description": "Reopen a previously completed Todoist task.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "The task ID to reopen"},
            },
            "required": ["task_id"],
        },
        "kind": "integration",
        "writes": True,
    },
    {
        "name": "todoist_move_task",
        "description": "Move a task to a different project or section.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "The task ID to move"},
                "project_id": {"type": "string", "description": "Destination project ID"},
                "section_id": {"type": "string", "description": "Destination section ID"},
            },
            "required": ["task_id"],
        },
        "kind": "integration",
        "writes": True,
    },
    {
        "name": "todoist_delete_task",
        "description": "Permanently delete a Todoist task.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "The task ID to delete"},
            },
            "required": ["task_id"],
        },
        "kind": "integration",
        "writes": True,
    },
    {
        "name": "todoist_get_completed_tasks",
        "description": "Get recently completed tasks. Defaults to last 7 days if no date range specified.",
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Max tasks to return (default 30, max 200)",
                },
                "since": {
                    "type": "string",
                    "description": "Start of date range, ISO 8601 (e.g. '2026-04-20T00:00:00Z'). Defaults to 7 days ago.",
                },
                "until": {
                    "type": "string",
                    "description": "End of date range, ISO 8601. Defaults to now.",
                },
            },
            "required": [],
        },
        "kind": "integration",
    },

    # ── Projects ──────────────────────────────────────────────────────
    {
        "name": "todoist_get_projects",
        "description": "List all Todoist projects.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
        "kind": "integration",
    },
    {
        "name": "todoist_create_project",
        "description": "Create a new Todoist project.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Project name"},
                "color": {"type": "string", "description": "Project color (e.g. 'berry_red', 'blue', 'green')"},
                "parent_id": {"type": "string", "description": "Parent project ID (to create a sub-project)"},
                "is_favorite": {"type": "boolean", "description": "Add to favorites"},
            },
            "required": ["name"],
        },
        "kind": "integration",
        "writes": True,
    },
    {
        "name": "todoist_update_project",
        "description": "Update a Todoist project. Only provide fields you want to change.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "The project ID to update"},
                "name": {"type": "string", "description": "New project name"},
                "color": {"type": "string", "description": "New project color"},
                "is_favorite": {"type": "boolean", "description": "Set favorite status"},
            },
            "required": ["project_id"],
        },
        "kind": "integration",
        "writes": True,
    },
    {
        "name": "todoist_get_sections",
        "description": "List sections within a Todoist project.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Project ID to list sections for"},
            },
            "required": ["project_id"],
        },
        "kind": "integration",
    },

    # ── Comments ──────────────────────────────────────────────────────
    {
        "name": "todoist_get_comments",
        "description": "Get comments on a Todoist task or project.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "Task ID to get comments for"},
                "project_id": {"type": "string", "description": "Project ID to get comments for"},
            },
            "required": [],
        },
        "kind": "integration",
    },
    {
        "name": "todoist_add_comment",
        "description": "Add a comment to a Todoist task or project.",
        "input_schema": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "Comment text"},
                "task_id": {"type": "string", "description": "Task ID to comment on"},
                "project_id": {"type": "string", "description": "Project ID to comment on"},
            },
            "required": ["content"],
        },
        "kind": "integration",
        "writes": True,
    },

    # ── Labels ────────────────────────────────────────────────────────
    {
        "name": "todoist_get_labels",
        "description": "List all personal Todoist labels.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
        "kind": "integration",
    },
]


# ── Tool handlers ─────────────────────────────────────────────────────────


async def _todoist_get_tasks(
    filter: str | None = None,
    project_id: str | None = None,
    section_id: str | None = None,
    label: str | None = None,
) -> dict:
    client = get_client_async()
    if not client:
        return {"error": "Todoist not configured"}
    try:
        kwargs = {}
        if filter:
            kwargs["filter"] = filter
        if project_id:
            kwargs["project_id"] = project_id
        if section_id:
            kwargs["section_id"] = section_id
        if label:
            kwargs["label"] = label

        async with client as api:
            if filter:
                tasks = []
                async for page in await api.filter_tasks(query=filter):
                    tasks.extend(page)
            else:
                tasks = []
                async for page in await api.get_tasks(**kwargs):
                    tasks.extend(page)

        return {"tasks": [_format_task(t) for t in tasks], "count": len(tasks)}
    except Exception as e:
        logger.error("todoist_get_tasks error: %s", e)
        return {"error": str(e)}


async def _todoist_get_task(task_id: str) -> dict:
    client = get_client_async()
    if not client:
        return {"error": "Todoist not configured"}
    try:
        async with client as api:
            task = await api.get_task(task_id)
        return _format_task(task)
    except Exception as e:
        logger.error("todoist_get_task error: %s", e)
        return {"error": str(e)}


async def _todoist_create_task(
    content: str,
    description: str | None = None,
    project_id: str | None = None,
    section_id: str | None = None,
    parent_id: str | None = None,
    priority: int | None = None,
    due_string: str | None = None,
    due_date: str | None = None,
    labels: list[str] | None = None,
) -> dict:
    client = get_client_async()
    if not client:
        return {"error": "Todoist not configured"}
    try:
        kwargs: dict = {"content": content}
        if description:
            kwargs["description"] = description
        if project_id:
            kwargs["project_id"] = project_id
        if section_id:
            kwargs["section_id"] = section_id
        if parent_id:
            kwargs["parent_id"] = parent_id
        if priority is not None:
            kwargs["priority"] = _UI_TO_API_PRIORITY.get(priority, priority)
        if due_string:
            kwargs["due_string"] = due_string
        if due_date:
            kwargs["due_date"] = date.fromisoformat(due_date)
        if labels:
            kwargs["labels"] = labels

        async with client as api:
            task = await api.add_task(**kwargs)
        return {"created": _format_task(task)}
    except Exception as e:
        logger.error("todoist_create_task error: %s", e)
        return {"error": str(e)}


async def _todoist_quick_add(text: str) -> dict:
    client = get_client_async()
    if not client:
        return {"error": "Todoist not configured"}
    try:
        async with client as api:
            task = await api.add_task_quick(text=text)
        return {"created": _format_task(task)}
    except Exception as e:
        logger.error("todoist_quick_add error: %s", e)
        return {"error": str(e)}


async def _todoist_update_task(
    task_id: str,
    content: str | None = None,
    description: str | None = None,
    priority: int | None = None,
    due_string: str | None = None,
    due_date: str | None = None,
    labels: list[str] | None = None,
) -> dict:
    client = get_client_async()
    if not client:
        return {"error": "Todoist not configured"}
    try:
        kwargs: dict = {}
        if content is not None:
            kwargs["content"] = content
        if description is not None:
            kwargs["description"] = description
        if priority is not None:
            kwargs["priority"] = _UI_TO_API_PRIORITY.get(priority, priority)
        if due_string is not None:
            kwargs["due_string"] = due_string
        if due_date is not None:
            kwargs["due_date"] = date.fromisoformat(due_date)
        if labels is not None:
            kwargs["labels"] = labels

        async with client as api:
            task = await api.update_task(task_id, **kwargs)
        return {"updated": _format_task(task)}
    except Exception as e:
        logger.error("todoist_update_task error: %s", e)
        return {"error": str(e)}


async def _todoist_complete_task(task_id: str) -> dict:
    client = get_client_async()
    if not client:
        return {"error": "Todoist not configured"}
    try:
        async with client as api:
            await api.complete_task(task_id)
        return {"completed": True, "task_id": task_id}
    except Exception as e:
        logger.error("todoist_complete_task error: %s", e)
        return {"error": str(e)}


async def _todoist_reopen_task(task_id: str) -> dict:
    client = get_client_async()
    if not client:
        return {"error": "Todoist not configured"}
    try:
        async with client as api:
            await api.uncomplete_task(task_id)
        return {"reopened": True, "task_id": task_id}
    except Exception as e:
        logger.error("todoist_reopen_task error: %s", e)
        return {"error": str(e)}


async def _todoist_move_task(
    task_id: str,
    project_id: str | None = None,
    section_id: str | None = None,
) -> dict:
    client = get_client_async()
    if not client:
        return {"error": "Todoist not configured"}
    try:
        kwargs: dict = {}
        if project_id:
            kwargs["project_id"] = project_id
        if section_id:
            kwargs["section_id"] = section_id
        if not kwargs:
            return {"error": "Provide project_id or section_id to move to"}

        async with client as api:
            await api.move_task(task_id, **kwargs)
        return {"moved": True, "task_id": task_id, **kwargs}
    except Exception as e:
        logger.error("todoist_move_task error: %s", e)
        return {"error": str(e)}


async def _todoist_delete_task(task_id: str) -> dict:
    client = get_client_async()
    if not client:
        return {"error": "Todoist not configured"}
    try:
        async with client as api:
            await api.delete_task(task_id)
        return {"deleted": True, "task_id": task_id}
    except Exception as e:
        logger.error("todoist_delete_task error: %s", e)
        return {"error": str(e)}


async def _todoist_get_completed_tasks(
    limit: int | None = None,
    since: str | None = None,
    until: str | None = None,
) -> dict:
    client = get_client_async()
    if not client:
        return {"error": "Todoist not configured"}
    try:
        since_dt = datetime.fromisoformat(since) if since else datetime.now(timezone.utc) - timedelta(days=7)
        until_dt = datetime.fromisoformat(until) if until else datetime.now(timezone.utc)
        max_tasks = min(limit or 30, 200)

        kwargs: dict = {"since": since_dt, "until": until_dt}
        if limit:
            kwargs["limit"] = max_tasks

        async with client as api:
            tasks = []
            async for page in await api.get_completed_tasks_by_completion_date(**kwargs):
                tasks.extend(page)
                if len(tasks) >= max_tasks:
                    break

        tasks = tasks[:max_tasks]
        return {
            "tasks": [
                {
                    "id": t.id,
                    "content": t.content,
                    "project_id": t.project_id,
                    "completed_at": _to_str(t.completed_at),
                }
                for t in tasks
            ],
            "count": len(tasks),
        }
    except Exception as e:
        logger.error("todoist_get_completed_tasks error: %s", e)
        return {"error": str(e)}


async def _todoist_get_projects() -> dict:
    client = get_client_async()
    if not client:
        return {"error": "Todoist not configured"}
    try:
        async with client as api:
            projects = []
            async for page in await api.get_projects():
                projects.extend(page)
        return {"projects": [_format_project(p) for p in projects], "count": len(projects)}
    except Exception as e:
        logger.error("todoist_get_projects error: %s", e)
        return {"error": str(e)}


async def _todoist_create_project(
    name: str,
    color: str | None = None,
    parent_id: str | None = None,
    is_favorite: bool | None = None,
) -> dict:
    client = get_client_async()
    if not client:
        return {"error": "Todoist not configured"}
    try:
        kwargs: dict = {"name": name}
        if color:
            kwargs["color"] = color
        if parent_id:
            kwargs["parent_id"] = parent_id
        if is_favorite is not None:
            kwargs["is_favorite"] = is_favorite

        async with client as api:
            project = await api.add_project(**kwargs)
        return {"created": _format_project(project)}
    except Exception as e:
        logger.error("todoist_create_project error: %s", e)
        return {"error": str(e)}


async def _todoist_update_project(
    project_id: str,
    name: str | None = None,
    color: str | None = None,
    is_favorite: bool | None = None,
) -> dict:
    client = get_client_async()
    if not client:
        return {"error": "Todoist not configured"}
    try:
        kwargs: dict = {}
        if name is not None:
            kwargs["name"] = name
        if color is not None:
            kwargs["color"] = color
        if is_favorite is not None:
            kwargs["is_favorite"] = is_favorite

        async with client as api:
            project = await api.update_project(project_id, **kwargs)
        return {"updated": _format_project(project)}
    except Exception as e:
        logger.error("todoist_update_project error: %s", e)
        return {"error": str(e)}


async def _todoist_get_sections(project_id: str) -> dict:
    client = get_client_async()
    if not client:
        return {"error": "Todoist not configured"}
    try:
        async with client as api:
            sections = []
            async for page in await api.get_sections(project_id=project_id):
                sections.extend(page)
        return {"sections": [_format_section(s) for s in sections], "count": len(sections)}
    except Exception as e:
        logger.error("todoist_get_sections error: %s", e)
        return {"error": str(e)}


async def _todoist_get_comments(
    task_id: str | None = None,
    project_id: str | None = None,
) -> dict:
    client = get_client_async()
    if not client:
        return {"error": "Todoist not configured"}
    try:
        if not task_id and not project_id:
            return {"error": "Provide task_id or project_id"}

        kwargs: dict = {}
        if task_id:
            kwargs["task_id"] = task_id
        if project_id:
            kwargs["project_id"] = project_id

        async with client as api:
            comments = []
            async for page in await api.get_comments(**kwargs):
                comments.extend(page)
        return {"comments": [_format_comment(c) for c in comments], "count": len(comments)}
    except Exception as e:
        logger.error("todoist_get_comments error: %s", e)
        return {"error": str(e)}


async def _todoist_add_comment(
    content: str,
    task_id: str | None = None,
    project_id: str | None = None,
) -> dict:
    client = get_client_async()
    if not client:
        return {"error": "Todoist not configured"}
    try:
        if not task_id and not project_id:
            return {"error": "Provide task_id or project_id"}

        kwargs: dict = {"content": content}
        if task_id:
            kwargs["task_id"] = task_id
        if project_id:
            kwargs["project_id"] = project_id

        async with client as api:
            comment = await api.add_comment(**kwargs)
        return {"created": _format_comment(comment)}
    except Exception as e:
        logger.error("todoist_add_comment error: %s", e)
        return {"error": str(e)}


async def _todoist_get_labels() -> dict:
    client = get_client_async()
    if not client:
        return {"error": "Todoist not configured"}
    try:
        async with client as api:
            labels = []
            async for page in await api.get_labels():
                labels.extend(page)
        return {"labels": [_format_label(lb) for lb in labels], "count": len(labels)}
    except Exception as e:
        logger.error("todoist_get_labels error: %s", e)
        return {"error": str(e)}


# ── Executor map ──────────────────────────────────────────────────────────

TOOL_EXECUTORS = {
    "todoist_get_tasks": _todoist_get_tasks,
    "todoist_get_task": _todoist_get_task,
    "todoist_create_task": _todoist_create_task,
    "todoist_quick_add": _todoist_quick_add,
    "todoist_update_task": _todoist_update_task,
    "todoist_complete_task": _todoist_complete_task,
    "todoist_reopen_task": _todoist_reopen_task,
    "todoist_move_task": _todoist_move_task,
    "todoist_delete_task": _todoist_delete_task,
    "todoist_get_completed_tasks": _todoist_get_completed_tasks,
    "todoist_get_projects": _todoist_get_projects,
    "todoist_create_project": _todoist_create_project,
    "todoist_update_project": _todoist_update_project,
    "todoist_get_sections": _todoist_get_sections,
    "todoist_get_comments": _todoist_get_comments,
    "todoist_add_comment": _todoist_add_comment,
    "todoist_get_labels": _todoist_get_labels,
}
