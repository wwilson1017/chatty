"""
Chatty — Tool definitions (schema only).

Defines the tool schemas sent to the AI provider. Actual execution
is handled by ToolRegistry. No Odoo, DIMM, or voice tools here.
"""

# ── Context tools ─────────────────────────────────────────────────────────────

CONTEXT_TOOLS = [
    {
        "name": "list_context_files",
        "description": "List all knowledge/context files you have saved. Use this to see what you already know.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
        "kind": "context",
    },
    {
        "name": "read_context_file",
        "description": "Read the full contents of a specific context/knowledge file.",
        "input_schema": {
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": "The .md filename to read (e.g. 'profile.md')",
                },
            },
            "required": ["filename"],
        },
        "kind": "context",
    },
    {
        "name": "write_context_file",
        "description": "Write or overwrite a knowledge file. Use this to save important information about the user.",
        "input_schema": {
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": "The .md filename to write (e.g. 'profile.md')",
                },
                "content": {
                    "type": "string",
                    "description": "The full markdown content to write",
                },
            },
            "required": ["filename", "content"],
        },
        "kind": "context",
    },
    {
        "name": "append_to_context_file",
        "description": "Append content to an existing knowledge file without overwriting it.",
        "input_schema": {
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": "The .md filename to append to",
                },
                "content": {
                    "type": "string",
                    "description": "The markdown content to append",
                },
            },
            "required": ["filename", "content"],
        },
        "kind": "context",
    },
    {
        "name": "delete_context_file",
        "description": "Delete a knowledge file that is no longer needed.",
        "input_schema": {
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": "The .md filename to delete",
                },
            },
            "required": ["filename"],
        },
        "kind": "context",
    },
]

# ── Gmail tools ───────────────────────────────────────────────────────────────

GMAIL_TOOLS = [
    {
        "name": "search_emails",
        "description": "Search Gmail messages using a query. Supports Gmail search operators (from:, to:, subject:, after:, before:, etc.).",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Gmail search query (e.g. 'from:boss@company.com subject:report')",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of results to return (default: 10)",
                    "default": 10,
                },
            },
            "required": ["query"],
        },
        "kind": "gmail",
    },
    {
        "name": "get_email",
        "description": "Get the full content of a specific email by its message ID.",
        "input_schema": {
            "type": "object",
            "properties": {
                "message_id": {
                    "type": "string",
                    "description": "The Gmail message ID",
                },
            },
            "required": ["message_id"],
        },
        "kind": "gmail",
    },
    {
        "name": "get_email_thread",
        "description": "Get all messages in a Gmail thread by thread ID.",
        "input_schema": {
            "type": "object",
            "properties": {
                "thread_id": {
                    "type": "string",
                    "description": "The Gmail thread ID",
                },
            },
            "required": ["thread_id"],
        },
        "kind": "gmail",
    },
]

# ── Calendar tools ─────────────────────────────────────────────────────────────

CALENDAR_TOOLS = [
    {
        "name": "list_calendar_events",
        "description": "List upcoming Google Calendar events.",
        "input_schema": {
            "type": "object",
            "properties": {
                "calendar_id": {
                    "type": "string",
                    "description": "Calendar ID (default: 'primary')",
                    "default": "primary",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of events to return (default: 10)",
                    "default": 10,
                },
                "time_min": {
                    "type": "string",
                    "description": "Start time in RFC 3339 format (e.g. '2024-01-01T00:00:00Z')",
                },
                "time_max": {
                    "type": "string",
                    "description": "End time in RFC 3339 format",
                },
            },
            "required": [],
        },
        "kind": "calendar",
    },
    {
        "name": "get_calendar_event",
        "description": "Get a specific calendar event by ID.",
        "input_schema": {
            "type": "object",
            "properties": {
                "event_id": {
                    "type": "string",
                    "description": "The Google Calendar event ID",
                },
                "calendar_id": {
                    "type": "string",
                    "description": "Calendar ID (default: 'primary')",
                    "default": "primary",
                },
            },
            "required": ["event_id"],
        },
        "kind": "calendar",
    },
    {
        "name": "search_calendar_events",
        "description": "Search Google Calendar events by text query.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Text to search for in event titles, descriptions, and locations",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of results (default: 10)",
                    "default": 10,
                },
                "calendar_id": {
                    "type": "string",
                    "description": "Calendar ID (default: 'primary')",
                    "default": "primary",
                },
            },
            "required": ["query"],
        },
        "kind": "calendar",
    },
]


def get_tool_definitions(
    gmail_enabled: bool = False,
    calendar_enabled: bool = False,
    integration_tools: list[dict] | None = None,
) -> list[dict]:
    """Return the full list of tool definitions for the given feature flags."""
    tools = list(CONTEXT_TOOLS)
    if gmail_enabled:
        tools.extend(GMAIL_TOOLS)
    if calendar_enabled:
        tools.extend(CALENDAR_TOOLS)
    if integration_tools:
        tools.extend(integration_tools)
    return tools
