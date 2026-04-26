"""Chatty — Paperclip agent tools.

MVP tool set: list issues, get issue details, checkout, update, comment.
Write tools marked with "writes": True for the approval flow.
"""

from .client import get_client

# ── Tool definitions ─────────────────────────────────────────────────────────

PAPERCLIP_TOOL_DEFS = [
    # ── Read tools ───────────────────────────────────────────────────────
    {
        "name": "paperclip_list_issues",
        "description": (
            "List issues (tasks) in the Paperclip company. "
            "Optionally filter by status or assigned agent. "
            "Statuses: backlog, todo, in_progress, in_review, done, blocked, cancelled."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "description": "Filter by status (e.g. 'todo', 'in_progress')",
                },
                "assignee_agent_id": {
                    "type": "string",
                    "description": "Filter by assigned Paperclip agent ID",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results (default 50)",
                },
            },
            "required": [],
        },
        "kind": "integration",
        "writes": False,
    },
    {
        "name": "paperclip_get_issue",
        "description": (
            "Get full details of a Paperclip issue including title, description, "
            "status, priority, assignee, documents, and recent comments."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "issue_id": {
                    "type": "string",
                    "description": "The Paperclip issue ID",
                },
            },
            "required": ["issue_id"],
        },
        "kind": "integration",
        "writes": False,
    },
    # ── Write tools ──────────────────────────────────────────────────────
    {
        "name": "paperclip_checkout_issue",
        "description": (
            "Atomically claim (checkout) a Paperclip issue for an agent. "
            "Returns 409 if already claimed by another agent. "
            "Requires the Paperclip agent ID performing the checkout."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "issue_id": {
                    "type": "string",
                    "description": "The issue ID to claim",
                },
                "agent_id": {
                    "type": "string",
                    "description": "The Paperclip agent ID claiming the issue",
                },
                "expected_statuses": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Allowed statuses for checkout (default: ['backlog', 'todo'])",
                },
            },
            "required": ["issue_id", "agent_id"],
        },
        "kind": "integration",
        "writes": True,
    },
    {
        "name": "paperclip_update_issue",
        "description": (
            "Update a Paperclip issue. Can change title, description, status, "
            "priority, or add an inline comment. "
            "Statuses: backlog, todo, in_progress, in_review, done, blocked, cancelled. "
            "Priorities: critical, high, medium, low."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "issue_id": {
                    "type": "string",
                    "description": "The issue ID to update",
                },
                "title": {"type": "string", "description": "New title"},
                "description": {"type": "string", "description": "New description"},
                "status": {"type": "string", "description": "New status"},
                "priority": {"type": "string", "description": "New priority"},
                "comment": {
                    "type": "string",
                    "description": "Inline comment to add with the update",
                },
            },
            "required": ["issue_id"],
        },
        "kind": "integration",
        "writes": True,
    },
    {
        "name": "paperclip_add_comment",
        "description": (
            "Post a comment on a Paperclip issue. "
            "Use @mentions to notify other agents."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "issue_id": {
                    "type": "string",
                    "description": "The issue ID to comment on",
                },
                "body": {
                    "type": "string",
                    "description": "The comment text",
                },
            },
            "required": ["issue_id", "body"],
        },
        "kind": "integration",
        "writes": True,
    },
]


# ── Executor functions ───────────────────────────────────────────────────────

def _paperclip_list_issues(
    status: str | None = None,
    assignee_agent_id: str | None = None,
    limit: int = 50,
) -> dict:
    client = get_client()
    if not client:
        return {"error": "Paperclip integration not configured"}
    return client.list_issues(status=status, assignee_agent_id=assignee_agent_id, limit=limit)


def _paperclip_get_issue(issue_id: str) -> dict:
    client = get_client()
    if not client:
        return {"error": "Paperclip integration not configured"}
    return client.get_issue(issue_id)


def _paperclip_checkout_issue(
    issue_id: str,
    agent_id: str,
    expected_statuses: list[str] | None = None,
) -> dict:
    client = get_client()
    if not client:
        return {"error": "Paperclip integration not configured"}
    return client.checkout_issue(issue_id, agent_id, expected_statuses)


def _paperclip_update_issue(issue_id: str, **updates) -> dict:
    client = get_client()
    if not client:
        return {"error": "Paperclip integration not configured"}
    body = {k: v for k, v in updates.items() if v is not None}
    return client.update_issue(issue_id, body)


def _paperclip_add_comment(issue_id: str, body: str) -> dict:
    client = get_client()
    if not client:
        return {"error": "Paperclip integration not configured"}
    return client.add_comment(issue_id, body)


# ── Executor map ─────────────────────────────────────────────────────────────

TOOL_EXECUTORS = {
    "paperclip_list_issues": lambda **kw: _paperclip_list_issues(**kw),
    "paperclip_get_issue": lambda **kw: _paperclip_get_issue(**kw),
    "paperclip_checkout_issue": lambda **kw: _paperclip_checkout_issue(**kw),
    "paperclip_update_issue": lambda **kw: _paperclip_update_issue(**kw),
    "paperclip_add_comment": lambda **kw: _paperclip_add_comment(**kw),
}
