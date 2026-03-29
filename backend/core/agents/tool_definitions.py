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


# ── Web tools ─────────────────────────────────────────────────────────────────

WEB_TOOLS = [
    {
        "name": "web_search",
        "description": "Search the web for current information using DuckDuckGo. Returns titles, snippets, and URLs for top results.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query",
                },
                "num_results": {
                    "type": "integer",
                    "description": "Number of results to return (default 5, max 10)",
                },
            },
            "required": ["query"],
        },
        "kind": "web",
    },
    {
        "name": "web_fetch",
        "description": "Fetch a web page and extract its readable text content. Use after web_search to read a specific page.",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "URL to fetch",
                },
                "extract_links": {
                    "type": "boolean",
                    "description": "Also extract links from the page (default false)",
                },
            },
            "required": ["url"],
        },
        "kind": "web",
    },
]


# ── Real AI tools (management) ────────────────────────────────────────────────

REAL_TOOL_DEFS = [
    {
        "name": "create_real_tool",
        "description": "Create a new Python code tool. Write a markdown definition with # name, description, ## Parameters table, ## Code with ```python block containing a run(ctx, ...) function, and optional ## Writes (yes/no). The ctx object provides: ctx.http (GET/POST with SSRF protection), ctx.json, ctx.datetime, ctx.math, ctx.re, ctx.decimal.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Tool name (alphanumeric, hyphens, underscores)"},
                "definition": {"type": "string", "description": "Full markdown tool definition"},
            },
            "required": ["name", "definition"],
        },
        "kind": "real_tool",
    },
    {
        "name": "update_real_tool",
        "description": "Update an existing Python code tool with a new definition.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Tool name to update"},
                "definition": {"type": "string", "description": "Full updated markdown definition"},
            },
            "required": ["name", "definition"],
        },
        "kind": "real_tool",
    },
    {
        "name": "delete_real_tool",
        "description": "Delete a Python code tool.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Tool name to delete"},
            },
            "required": ["name"],
        },
        "kind": "real_tool",
    },
    {
        "name": "list_real_tools",
        "description": "List all Python code tools that have been created.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
        "kind": "real_tool",
    },
    {
        "name": "test_real_tool",
        "description": "Parse, validate, and execute a Python code tool definition without saving it. Use this to test before creating.",
        "input_schema": {
            "type": "object",
            "properties": {
                "definition": {"type": "string", "description": "Full markdown tool definition to test"},
                "test_args": {"type": "object", "description": "Test arguments to pass to the tool"},
            },
            "required": ["definition"],
        },
        "kind": "real_tool",
    },
]

# ── Report tools ──────────────────────────────────────────────────────────────

REPORT_TOOLS = [
    {
        "name": "generate_report",
        "description": "Generate a structured report with charts and tables. The report will be saved and viewable in the Reports tab.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Report title"},
                "subtitle": {"type": "string", "description": "Optional subtitle or date range"},
                "sections": {
                    "type": "array",
                    "description": "Report sections, each with a chart_type and data object",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "chart_type": {
                                "type": "string",
                                "enum": ["bar", "horizontal_bar", "stacked_bar", "grouped_bar",
                                         "line", "area", "pie", "donut", "table", "metric"],
                            },
                            "data": {
                                "type": "object",
                                "description": "Data object. For bar/line/area/pie/donut: {labels: [str], datasets: [{name: str, values: [number]}]}. For table: {headers: [str], rows: [[value]]}. For metric: {metrics: [{label: str, value: number, change?: str, unit?: str}]}.",
                                "properties": {
                                    "labels": {"type": "array", "items": {"type": "string"}, "description": "Category labels (bar/line/pie charts)"},
                                    "datasets": {
                                        "type": "array",
                                        "description": "Data series. Each: {name: str, values: [number]}",
                                        "items": {
                                            "type": "object",
                                            "properties": {
                                                "name": {"type": "string"},
                                                "values": {"type": "array", "items": {"type": "number"}},
                                            },
                                            "required": ["name", "values"],
                                        },
                                    },
                                    "headers": {"type": "array", "items": {"type": "string"}, "description": "Column headers (table only)"},
                                    "rows": {
                                        "type": "array",
                                        "description": "Table rows, each an array of values",
                                        "items": {"type": "array", "items": {}},
                                    },
                                    "metrics": {
                                        "type": "array",
                                        "description": "Metric cards: [{label, value, change?, unit?}]",
                                        "items": {
                                            "type": "object",
                                            "properties": {
                                                "label": {"type": "string"},
                                                "value": {"type": "number"},
                                                "change": {"type": "string"},
                                                "unit": {"type": "string"},
                                            },
                                            "required": ["label", "value"],
                                        },
                                    },
                                },
                            },
                        },
                        "required": ["title", "chart_type", "data"],
                    },
                },
            },
            "required": ["title", "sections"],
        },
        "kind": "report",
    },
]

# ── Reminder tools ────────────────────────────────────────────────────────────

REMINDER_TOOLS = [
    {
        "name": "create_reminder",
        "description": "Set a reminder for yourself to follow up on something. When the reminder fires, you will receive the message as context in a new conversation turn.",
        "input_schema": {
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "What to remind about"},
                "due_at": {"type": "string", "description": "When the reminder should fire (ISO 8601 datetime, e.g. '2026-03-27T14:00:00')"},
                "context": {"type": "string", "description": "Optional additional context for when the reminder fires"},
            },
            "required": ["message", "due_at"],
        },
        "kind": "reminder",
    },
    {
        "name": "list_reminders",
        "description": "List your active reminders.",
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "description": "Filter by status: 'pending', 'fired', 'cancelled' (default: 'pending')"},
            },
            "required": [],
        },
        "kind": "reminder",
    },
    {
        "name": "cancel_reminder",
        "description": "Cancel a pending reminder by its ID.",
        "input_schema": {
            "type": "object",
            "properties": {
                "reminder_id": {"type": "string", "description": "The reminder ID to cancel"},
            },
            "required": ["reminder_id"],
        },
        "kind": "reminder",
    },
]

# ── Scheduled action tools ────────────────────────────────────────────────────

SCHEDULED_ACTION_TOOLS = [
    {
        "name": "create_scheduled_action",
        "description": "Create a scheduled action that runs automatically on a cron schedule. The action will execute a prompt with your tools available.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Short name for this action"},
                "description": {"type": "string", "description": "What this action does"},
                "schedule_type": {"type": "string", "enum": ["cron", "interval", "once"], "description": "Schedule type"},
                "cron_expression": {"type": "string", "description": "Cron expression (for schedule_type='cron'), e.g. '0 9 * * 1-5' for weekdays at 9am"},
                "interval_minutes": {"type": "integer", "description": "Interval in minutes (for schedule_type='interval', min 5)"},
                "run_at": {"type": "string", "description": "ISO 8601 datetime (for schedule_type='once')"},
                "prompt": {"type": "string", "description": "The prompt to execute on each run"},
                "active_hours_start": {"type": "integer", "description": "Start hour for active window (0-23, default: 6)"},
                "active_hours_end": {"type": "integer", "description": "End hour for active window (0-23, default: 22)"},
            },
            "required": ["name", "prompt", "schedule_type"],
        },
        "kind": "scheduled_action",
    },
    {
        "name": "list_scheduled_actions",
        "description": "List your scheduled actions.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
        "kind": "scheduled_action",
    },
    {
        "name": "update_scheduled_action",
        "description": "Update a scheduled action's settings.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action_id": {"type": "string", "description": "The action ID to update"},
                "enabled": {"type": "boolean", "description": "Enable or disable the action"},
                "prompt": {"type": "string", "description": "Updated prompt"},
                "cron_expression": {"type": "string", "description": "Updated cron expression"},
                "interval_minutes": {"type": "integer", "description": "Updated interval"},
                "active_hours_start": {"type": "integer"},
                "active_hours_end": {"type": "integer"},
            },
            "required": ["action_id"],
        },
        "kind": "scheduled_action",
    },
    {
        "name": "delete_scheduled_action",
        "description": "Delete a scheduled action.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action_id": {"type": "string", "description": "The action ID to delete"},
            },
            "required": ["action_id"],
        },
        "kind": "scheduled_action",
    },
]


# ── System prompt additions ───────────────────────────────────────────────────

def get_report_instructions() -> str:
    """Instructions for the AI on how to use the generate_report tool."""
    return """## Reports
You can generate visual reports using the `generate_report` tool. Reports appear in the user's Reports tab with interactive charts.

Supported chart types: bar, horizontal_bar, stacked_bar, grouped_bar, line, area, pie, donut, table, metric.

Guidelines:
- Use `metric` for single KPI values (revenue, count, etc.)
- Use `bar` or `horizontal_bar` for comparisons across categories
- Use `line` or `area` for time series data
- Use `pie` or `donut` for proportions (keep to 7 or fewer slices)
- Use `table` for detailed data that doesn't suit a chart
- Use `stacked_bar` or `grouped_bar` for multi-series comparisons
- All numeric values in data must be numbers, not strings
- Include a clear title and optional subtitle (e.g. date range)
"""


def get_scheduling_instructions() -> str:
    """Instructions for the AI on how to use reminders and scheduled actions."""
    return """## Scheduling & Reminders
You can set reminders and create scheduled actions:

- **Reminders**: Use `create_reminder` to set a follow-up for yourself. When the reminder fires, you'll receive the context and can take action. Use ISO 8601 format for due_at.
- **Scheduled Actions**: Use `create_scheduled_action` to create recurring tasks. These run automatically on a cron schedule with your tools available. Use for periodic checks, reports, or maintenance tasks.

Guidelines:
- Always confirm with the user before creating scheduled actions
- Use descriptive names for scheduled actions
- Set reasonable active hours to avoid running during off-hours
- Prefer cron expressions for recurring tasks, 'once' for one-time future tasks
"""


def get_tool_definitions(
    gmail_enabled: bool = False,
    calendar_enabled: bool = False,
    web_enabled: bool = True,
    real_tools_enabled: bool = True,
    reports_enabled: bool = True,
    reminders_enabled: bool = True,
    scheduled_actions_enabled: bool = True,
    integration_tools: list[dict] | None = None,
    dynamic_real_tools: list[dict] | None = None,
) -> list[dict]:
    """Return the full list of tool definitions for the given feature flags."""
    tools = list(CONTEXT_TOOLS)
    if gmail_enabled:
        tools.extend(GMAIL_TOOLS)
    if calendar_enabled:
        tools.extend(CALENDAR_TOOLS)
    if web_enabled:
        tools.extend(WEB_TOOLS)
    if real_tools_enabled:
        tools.extend(REAL_TOOL_DEFS)
    if reports_enabled:
        tools.extend(REPORT_TOOLS)
    if reminders_enabled:
        tools.extend(REMINDER_TOOLS)
    if scheduled_actions_enabled:
        tools.extend(SCHEDULED_ACTION_TOOLS)
    if integration_tools:
        tools.extend(integration_tools)
    # Append agent-created real tools (loaded from filesystem)
    if dynamic_real_tools:
        tools.extend(dynamic_real_tools)
    return tools
