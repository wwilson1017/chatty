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
        "writes": False,
        "context_memory": True,
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
        "writes": False,
        "context_memory": True,
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
        "writes": True,
        "context_memory": True,
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
        "writes": True,
        "context_memory": True,
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
        "writes": True,
        "context_memory": True,
    },
]

# ── Memory tools (daily notes, MEMORY.md, FTS5 search, facts) ────────────────

MEMORY_TOOLS = [
    {
        "name": "append_daily_note",
        "description": "Append a timestamped entry to today's daily note. Use this to record significant events, decisions, and information as they happen during conversation.",
        "input_schema": {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "The content to append (will be timestamped automatically)",
                },
                "memory_type": {
                    "type": "string",
                    "description": "Optional type tag: decision, preference, problem, milestone, insight, person, task, idea, reference, someday-maybe",
                },
            },
            "required": ["content"],
        },
        "kind": "memory",
        "writes": True,
        "context_memory": True,
    },
    {
        "name": "read_daily_note",
        "description": "Read the full contents of a daily note for a specific date.",
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "description": "Date in YYYY-MM-DD format",
                },
            },
            "required": ["date"],
        },
        "kind": "memory",
        "writes": False,
        "context_memory": True,
    },
    {
        "name": "list_daily_notes",
        "description": "List recent daily notes with headlines, newest first.",
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Max notes to return (default 30)",
                },
            },
            "required": [],
        },
        "kind": "memory",
        "writes": False,
        "context_memory": True,
    },
    {
        "name": "read_memory",
        "description": "Read the current MEMORY.md — your living snapshot of key facts.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
        "kind": "memory",
        "writes": False,
        "context_memory": True,
    },
    {
        "name": "update_memory",
        "description": "Overwrite MEMORY.md with new content. Always read_memory first, then write back the full merged snapshot.",
        "input_schema": {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "The full new MEMORY.md content (replaces entire file)",
                },
            },
            "required": ["content"],
        },
        "kind": "memory",
        "writes": True,
        "context_memory": True,
    },
    {
        "name": "search_memory",
        "description": "Full-text search across all your knowledge: daily notes, MEMORY.md, topic files, and facts. Use this to find information you've recorded.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query (natural language or keywords)",
                },
                "source_type": {
                    "type": "string",
                    "description": "Optional filter: 'daily', 'memory', 'topic', or 'fact'",
                },
                "memory_type": {
                    "type": "string",
                    "description": "Optional filter by memory type (decision, person, etc.)",
                },
                "date_from": {
                    "type": "string",
                    "description": "Optional start date (YYYY-MM-DD)",
                },
                "date_to": {
                    "type": "string",
                    "description": "Optional end date (YYYY-MM-DD)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results (default 20, max 100)",
                },
            },
            "required": ["query"],
        },
        "kind": "memory",
        "writes": False,
        "context_memory": True,
    },
    {
        "name": "add_fact",
        "description": "Record a temporal fact (entity-relationship triple) in your knowledge base. Facts have validity windows and can be queried later.",
        "input_schema": {
            "type": "object",
            "properties": {
                "subject": {"type": "string", "description": "The entity (e.g. 'John Smith')"},
                "predicate": {"type": "string", "description": "The relationship (e.g. 'works at')"},
                "object": {"type": "string", "description": "The value (e.g. 'Acme Corp')"},
                "memory_type": {"type": "string", "description": "Optional type: person, decision, etc."},
                "confidence": {"type": "number", "description": "Confidence 0.0-1.0 (default 1.0)"},
            },
            "required": ["subject", "predicate", "object"],
        },
        "kind": "memory",
        "writes": True,
        "context_memory": True,
    },
    {
        "name": "query_facts",
        "description": "Query temporal facts by subject, predicate, or point-in-time.",
        "input_schema": {
            "type": "object",
            "properties": {
                "subject": {"type": "string", "description": "Filter by subject (partial match)"},
                "predicate": {"type": "string", "description": "Filter by predicate (partial match)"},
                "as_of": {"type": "string", "description": "Point-in-time view (YYYY-MM-DD)"},
                "memory_type": {"type": "string", "description": "Filter by memory type"},
                "include_expired": {"type": "boolean", "description": "Include expired facts (default false)"},
                "limit": {"type": "integer", "description": "Max results (default 50)"},
            },
            "required": [],
        },
        "kind": "memory",
        "writes": False,
        "context_memory": True,
    },
    {
        "name": "invalidate_fact",
        "description": "Mark a fact as no longer valid by setting its valid_to date.",
        "input_schema": {
            "type": "object",
            "properties": {
                "fact_id": {"type": "integer", "description": "The fact ID to invalidate"},
                "valid_to": {"type": "string", "description": "End date (default: today)"},
            },
            "required": ["fact_id"],
        },
        "kind": "memory",
        "writes": True,
        "context_memory": True,
    },
    {
        "name": "consolidate_memory",
        "description": (
            "Regenerate MEMORY.md by synthesizing the last N days of daily notes with the "
            "current MEMORY.md. Uses Claude Sonnet to produce a tight bulleted snapshot with "
            "four sections: Key People, Active Projects, Decisions, Lessons Learned. Runs "
            "automatically weekly; call this on demand if the user asks you to refresh your "
            "memory now."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "description": "Number of recent days to synthesize (default 7, max 90).",
                },
            },
        },
        "kind": "memory",
        "writes": True,
        "context_memory": True,
    },
]

# ── Shared context tools ─────────────────────────────────────────────────────

SHARED_CONTEXT_TOOLS = [
    {
        "name": "list_shared_context",
        "description": "List shared knowledge files and entries visible to all agents.",
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {"type": "string", "description": "Optional category filter"},
            },
            "required": [],
        },
        "kind": "shared_context",
        "writes": False,
        "context_memory": True,
    },
    {
        "name": "read_shared_context",
        "description": "Read a shared file by name or a shared entry by ID.",
        "input_schema": {
            "type": "object",
            "properties": {
                "filename": {"type": "string", "description": "Shared file name (e.g. 'policies.md')"},
                "entry_id": {"type": "string", "description": "Shared entry UUID"},
            },
            "required": [],
        },
        "kind": "shared_context",
        "writes": False,
        "context_memory": True,
    },
    {
        "name": "write_shared_context",
        "description": "Publish a knowledge entry visible to all agents. Use for cross-agent information sharing.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Entry title"},
                "content": {"type": "string", "description": "Entry content (markdown)"},
                "category": {"type": "string", "description": "Optional category tag"},
            },
            "required": ["title", "content"],
        },
        "kind": "shared_context",
        "writes": True,
        "context_memory": True,
    },
]

# ── Gmail tools ───────────────────────────────────────────────────────────────

GMAIL_READ_TOOLS = [
    {
        "name": "search_emails",
        "description": "Search Gmail messages using a query. Supports Gmail search operators (from:, to:, subject:, after:, before:, is:unread, newer_than:7d, has:attachment, etc.).",
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
        "writes": False,
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
        "writes": False,
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
        "writes": False,
    },
]

GMAIL_WRITE_TOOLS = [
    {
        "name": "send_email",
        "description": "Send a new email. The user must approve this action before it goes out.",
        "input_schema": {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Recipient email address(es), comma-separated"},
                "subject": {"type": "string", "description": "Email subject line"},
                "body": {"type": "string", "description": "Plain-text email body"},
                "cc": {"type": "string", "description": "CC recipient(s), comma-separated", "default": ""},
                "bcc": {"type": "string", "description": "BCC recipient(s), comma-separated", "default": ""},
            },
            "required": ["to", "subject", "body"],
        },
        "kind": "gmail",
        "writes": True,
    },
    {
        "name": "reply_to_email",
        "description": "Reply to an existing email, preserving thread headers. The user must approve before sending.",
        "input_schema": {
            "type": "object",
            "properties": {
                "message_id": {"type": "string", "description": "The message ID to reply to"},
                "body": {"type": "string", "description": "Plain-text reply body"},
                "reply_all": {"type": "boolean", "description": "Include all original recipients in CC", "default": False},
            },
            "required": ["message_id", "body"],
        },
        "kind": "gmail",
        "writes": True,
    },
    {
        "name": "create_draft",
        "description": "Save a draft in Gmail without sending. Useful when the user wants to review before the email goes out.",
        "input_schema": {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Recipient email address(es)"},
                "subject": {"type": "string", "description": "Email subject"},
                "body": {"type": "string", "description": "Plain-text body"},
                "cc": {"type": "string", "default": ""},
                "bcc": {"type": "string", "default": ""},
            },
            "required": ["to", "subject", "body"],
        },
        "kind": "gmail",
        "writes": True,
    },
    {
        "name": "mark_email_as_read",
        "description": "Mark a specific email as read in Gmail. Usually not needed since get_email auto-marks emails as read, but useful for queuing held emails without reading them.",
        "input_schema": {
            "type": "object",
            "properties": {
                "message_id": {"type": "string", "description": "Gmail message ID to mark as read"},
            },
            "required": ["message_id"],
        },
        "kind": "gmail",
        "writes": True,
    },
    {
        "name": "batch_mark_emails_as_read",
        "description": "Mark multiple emails as read in Gmail in a single operation. More efficient than calling mark_email_as_read repeatedly. Use after search_emails to bulk-clear unread messages.",
        "input_schema": {
            "type": "object",
            "properties": {
                "message_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of Gmail message IDs to mark as read (max 50)",
                },
            },
            "required": ["message_ids"],
        },
        "kind": "gmail",
        "writes": True,
    },
    {
        "name": "send_email_with_attachment",
        "description": "Send a new email with a file attachment. Pass the file_ref from download_odoo_pdf or download_email_attachment.",
        "input_schema": {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Recipient email address"},
                "subject": {"type": "string", "description": "Email subject line"},
                "body": {"type": "string", "description": "Plain text email body"},
                "file_ref": {"type": "string", "description": "File reference from download_odoo_pdf or download_email_attachment (preferred)"},
                "attachment_base64": {"type": "string", "description": "Base64-encoded file content (fallback — prefer file_ref)"},
                "attachment_filename": {"type": "string", "description": "Filename for the attachment (e.g. 'PO00123.pdf'). Optional when using file_ref — defaults to the cached filename."},
                "attachment_mime_type": {"type": "string", "description": "MIME type (default: application/pdf)"},
                "cc": {"type": "string", "description": "CC recipients (comma-separated, optional)"},
                "bcc": {"type": "string", "description": "BCC recipients (comma-separated, optional)"},
            },
            "required": ["to", "subject", "body"],
        },
        "kind": "gmail",
        "writes": True,
    },
    {
        "name": "reply_to_email_with_attachment",
        "description": "Reply to an existing email thread with a file attachment, preserving Gmail threading. Use the message_id from search_emails or get_email. Pass the file_ref from a download tool to attach the original file.",
        "input_schema": {
            "type": "object",
            "properties": {
                "message_id": {"type": "string", "description": "Gmail message ID to reply to"},
                "body": {"type": "string", "description": "Plain text reply body"},
                "file_ref": {"type": "string", "description": "File reference from download_odoo_pdf or download_email_attachment (preferred)"},
                "attachment_base64": {"type": "string", "description": "Base64-encoded file content (fallback — prefer file_ref)"},
                "attachment_filename": {"type": "string", "description": "Filename for the attachment. Optional when using file_ref — defaults to the cached filename."},
                "attachment_mime_type": {"type": "string", "description": "MIME type (default: application/pdf)"},
                "reply_all": {"type": "boolean", "description": "Include all original recipients in CC", "default": False},
            },
            "required": ["message_id", "body"],
        },
        "kind": "gmail",
        "writes": True,
    },
]

GMAIL_ATTACHMENT_READ_TOOLS = [
    {
        "name": "download_email_attachment",
        "description": "Download an attachment from an email by message ID and filename. Supports PDFs, Word docs (.docx), spreadsheets (.xlsx/.xls), CSV, text files, and images. Returns extracted text and a file_ref for forwarding the original via send/reply tools. Images are also shown for visual analysis.",
        "input_schema": {
            "type": "object",
            "properties": {
                "message_id": {"type": "string", "description": "Gmail message ID (from search_emails or get_email)"},
                "filename": {"type": "string", "description": "Exact filename of the attachment to download"},
            },
            "required": ["message_id", "filename"],
        },
        "kind": "gmail",
        "writes": False,
    },
]


# ── Calendar tools ─────────────────────────────────────────────────────────────

CALENDAR_READ_TOOLS = [
    {
        "name": "list_calendar_events",
        "description": "List upcoming Google Calendar events. Defaults to events from now forward if time_min is not provided.",
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
                    "description": "Start time in RFC 3339 format (e.g. '2026-04-16T00:00:00-05:00')",
                },
                "time_max": {
                    "type": "string",
                    "description": "End time in RFC 3339 format",
                },
            },
            "required": [],
        },
        "kind": "calendar",
        "writes": False,
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
        "writes": False,
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
                "time_min": {
                    "type": "string",
                    "description": "Start time in RFC 3339 format (optional)",
                },
                "time_max": {
                    "type": "string",
                    "description": "End time in RFC 3339 format (optional)",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of results (default: 20)",
                    "default": 20,
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
        "writes": False,
    },
    {
        "name": "find_free_slot",
        "description": "Find the earliest free window of a given duration within a time range. Uses the calendar free/busy query.",
        "input_schema": {
            "type": "object",
            "properties": {
                "duration_minutes": {
                    "type": "integer",
                    "description": "Meeting duration in minutes",
                },
                "between_start": {
                    "type": "string",
                    "description": "Earliest start time to consider (RFC 3339)",
                },
                "between_end": {
                    "type": "string",
                    "description": "Latest end time to consider (RFC 3339)",
                },
                "calendar_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Calendar IDs to check for busy time (default: ['primary'])",
                },
            },
            "required": ["duration_minutes", "between_start", "between_end"],
        },
        "kind": "calendar",
        "writes": False,
    },
]

CALENDAR_WRITE_TOOLS = [
    {
        "name": "create_calendar_event",
        "description": "Create a new calendar event. The user must approve this action before it is written.",
        "input_schema": {
            "type": "object",
            "properties": {
                "summary": {"type": "string", "description": "Event title"},
                "start": {"type": "string", "description": "Start time (RFC 3339, e.g. '2026-04-20T14:00:00-05:00')"},
                "end": {"type": "string", "description": "End time (RFC 3339)"},
                "description": {"type": "string", "description": "Event description", "default": ""},
                "location": {"type": "string", "description": "Physical or virtual location", "default": ""},
                "attendees": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Attendee email addresses",
                },
                "calendar_id": {"type": "string", "default": "primary"},
            },
            "required": ["summary", "start", "end"],
        },
        "kind": "calendar",
        "writes": True,
    },
    {
        "name": "update_calendar_event",
        "description": "Patch-update an existing event. Only the fields you pass are modified. The user must approve before changes are saved.",
        "input_schema": {
            "type": "object",
            "properties": {
                "event_id": {"type": "string"},
                "calendar_id": {"type": "string", "default": "primary"},
                "summary": {"type": "string"},
                "start": {"type": "string", "description": "RFC 3339 start"},
                "end": {"type": "string", "description": "RFC 3339 end"},
                "description": {"type": "string"},
                "location": {"type": "string"},
                "attendees": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["event_id"],
        },
        "kind": "calendar",
        "writes": True,
    },
    {
        "name": "delete_calendar_event",
        "description": "Delete a calendar event. The user must approve this action.",
        "input_schema": {
            "type": "object",
            "properties": {
                "event_id": {"type": "string"},
                "calendar_id": {"type": "string", "default": "primary"},
            },
            "required": ["event_id"],
        },
        "kind": "calendar",
        "writes": True,
    },
]

# ── Drive tools ────────────────────────────────────────────────────────────────

DRIVE_READ_TOOLS = [
    {
        "name": "search_drive_files",
        "description": "Search files in the user's Google Drive using Drive query syntax. Examples: \"name contains 'budget'\", \"mimeType = 'application/vnd.google-apps.spreadsheet'\", \"modifiedTime > '2026-01-01'\", \"'FOLDER_ID' in parents\". Combine conditions with 'and'/'or'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Google Drive search query (Drive API q parameter syntax)"},
                "max_results": {"type": "integer", "description": "Max files to return (default 20)"},
            },
            "required": ["query"],
        },
        "kind": "drive",
        "writes": False,
    },
    {
        "name": "list_drive_folder",
        "description": "List contents of a Google Drive folder. Defaults to the root (My Drive). Use a folder ID from search results to browse into subfolders.",
        "input_schema": {
            "type": "object",
            "properties": {
                "folder_id": {"type": "string", "description": "Drive folder ID (default: 'root' = My Drive top level)"},
                "max_results": {"type": "integer", "description": "Max items to return (default 50)"},
            },
            "required": [],
        },
        "kind": "drive",
        "writes": False,
    },
    {
        "name": "get_drive_file_info",
        "description": "Get detailed metadata for a specific Google Drive file or folder: name, type, size, owner, sharing status, last modified, and a web link.",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_id": {"type": "string", "description": "Google Drive file ID"},
            },
            "required": ["file_id"],
        },
        "kind": "drive",
        "writes": False,
    },
    {
        "name": "read_drive_file_content",
        "description": "Read the text content of a Google Drive file. Google Docs are exported as plain text, Sheets as CSV (first sheet only), Slides as plain text. Plain text files are read directly. Binary files (PDF, images) cannot be read — use get_drive_file_info instead.",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_id": {"type": "string", "description": "Google Drive file ID"},
                "max_chars": {"type": "integer", "description": "Max characters to return (default 50000)"},
            },
            "required": ["file_id"],
        },
        "kind": "drive",
        "writes": False,
    },
]

DRIVE_WRITE_TOOLS = [
    {
        "name": "create_drive_folder",
        "description": "Create a new folder in Google Drive.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Folder name"},
                "parent_folder_id": {"type": "string", "description": "Parent folder ID (default: 'root' = My Drive)"},
            },
            "required": ["name"],
        },
        "kind": "drive",
        "writes": True,
    },
    {
        "name": "create_drive_file",
        "description": "Create a new file in Google Drive with text content. Set file_type to 'document' for a Google Doc or 'text' for a plain text file.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "File name"},
                "content": {"type": "string", "description": "Text content for the file"},
                "file_type": {"type": "string", "enum": ["document", "text"], "description": "File type: 'document' (Google Doc) or 'text' (plain text). Default: 'document'"},
                "folder_id": {"type": "string", "description": "Parent folder ID (default: 'root' = My Drive)"},
            },
            "required": ["name"],
        },
        "kind": "drive",
        "writes": True,
    },
    {
        "name": "move_drive_file",
        "description": "Move a file or folder to a different parent folder in Google Drive.",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_id": {"type": "string", "description": "ID of the file to move"},
                "new_parent_id": {"type": "string", "description": "ID of the destination folder"},
            },
            "required": ["file_id", "new_parent_id"],
        },
        "kind": "drive",
        "writes": True,
    },
    {
        "name": "rename_drive_file",
        "description": "Rename a file or folder in Google Drive.",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_id": {"type": "string", "description": "ID of the file to rename"},
                "new_name": {"type": "string", "description": "New name for the file"},
            },
            "required": ["file_id", "new_name"],
        },
        "kind": "drive",
        "writes": True,
    },
    {
        "name": "copy_drive_file",
        "description": "Copy a file in Google Drive, optionally with a new name and/or into a different folder.",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_id": {"type": "string", "description": "ID of the file to copy"},
                "new_name": {"type": "string", "description": "Name for the copy (default: 'Copy of {original}')"},
                "folder_id": {"type": "string", "description": "Folder for the copy (default: same as original)"},
            },
            "required": ["file_id"],
        },
        "kind": "drive",
        "writes": True,
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
        "writes": False,
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
        "writes": False,
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
        "writes": True,
        "context_memory": True,
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
        "writes": True,
        "context_memory": True,
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
        "writes": True,
        "context_memory": True,
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
        "writes": False,
        "context_memory": True,
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
        "writes": False,
        "context_memory": True,
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
        "writes": True,
        "context_memory": True,
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
        "writes": True,
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
        "writes": False,
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
        "writes": True,
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
                "active_hours_start": {"type": "integer", "description": "Start hour for active window (0-23, default: 6). Actions only run during this window."},
                "active_hours_end": {"type": "integer", "description": "End hour for active window (0-23, default: 20). Actions only run during this window."},
                "always_on": {"type": "boolean", "description": "Set true for 24/7 operation, bypassing active hours. Default: false"},
            },
            "required": ["name", "prompt", "schedule_type"],
        },
        "kind": "scheduled_action",
        "writes": True,
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
        "writes": False,
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
                "active_hours_start": {"type": "integer", "description": "Start hour for active window (0-23)"},
                "active_hours_end": {"type": "integer", "description": "End hour for active window (0-23)"},
                "always_on": {"type": "boolean", "description": "Set true for 24/7 operation, bypassing active hours"},
            },
            "required": ["action_id"],
        },
        "kind": "scheduled_action",
        "writes": True,
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
        "writes": True,
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

### Reminders
Use `create_reminder` to set a follow-up for yourself. When the reminder fires, you'll receive the context and can take action. Use ISO 8601 format for due_at.

### Heartbeat (your main recurring loop)
You have a **background heartbeat** — your primary mechanism for recurring work. It runs periodically (check `list_scheduled_actions` for your interval) and checks your `HEARTBEAT.md` file. Each item is evaluated and you can take action using your tools.

To add a recurring task, use `write_context_file` to edit your HEARTBEAT.md checklist. Add items with time conditions (e.g., "Every weekday at 9 AM: send morning brief"). The heartbeat will pick it up automatically on its next pulse. Do NOT create a separate scheduled action for something the heartbeat can handle.

Good checklist items are specific and actionable: "Check if user has unread emails from important contacts", "Look for overdue invoices", "Check today's calendar for double-bookings". Vague items like "check things" waste a cycle.

If a user asks you to proactively monitor something, add it to HEARTBEAT.md. If they ask you to stop monitoring, remove the item. Use `list_scheduled_actions` to check your heartbeat status and interval.

### Scheduled Actions
Use `create_scheduled_action` only when you need a task with its own independent schedule that doesn't fit the heartbeat pattern (e.g., a one-time future task with `schedule_type="once"`). Always confirm with the user before creating one.

### Active Hours
- Scheduled actions have an **active hours window** — they only run during this window.
- Default is 6 AM to 8 PM. To change, set `active_hours_start` and `active_hours_end` (integers 0-23).
- For 24/7 operation, set `always_on=true` — this bypasses active hours entirely.
- Your heartbeat runs 24/7 by default (`always_on`). Time-gating belongs in your HEARTBEAT.md checklist items (e.g., "Only on weekdays before 10 AM: ..."), not on the heartbeat's active hours.

### Guidelines
- Always confirm with the user before creating scheduled actions
- Use descriptive names for scheduled actions
- Prefer adding items to HEARTBEAT.md (via `write_context_file`) over creating new scheduled actions
- For one-time future tasks, use `schedule_type="once"` with `run_at`
"""


def get_qb_csv_instructions() -> str:
    """Instructions for the AI on how to use QuickBooks CSV analysis tools."""
    return """## QuickBooks CSV Analysis

You have access to imported QuickBooks financial data. Use the qb_csv_* tools to answer questions about the user's finances.

### Auto-Import Protocol
When you see `[QuickBooks CSV detected: ...]` in an uploaded file:
1. Call `qb_csv_import_csv` with the CSV content and filename to persist it
2. Report what was imported (entity type, row count)
3. If multiple QBO files are uploaded, import each one
4. After importing, call `qb_csv_financial_summary` and use `generate_report` to create a visual financial overview

### Query Guidelines
- Use `qb_csv_financial_summary` for overview questions ("how's my business?", "show me my financials")
- Use `qb_csv_search_transactions` for filtered lookups ("show me invoices over $5k", "expenses last month")
- Use `qb_csv_query` with raw SQL for complex analysis (JOINs, GROUP BY, aggregations, date ranges)
- Use `qb_csv_find_duplicates` and `qb_csv_find_issues` when asked about data cleanup or quality
- Use `generate_report` to create visual charts from financial data

### Available Tables (for qb_csv_query SQL)
- accounts (name, type, detail_type, balance)
- customers (display_name, email, phone, balance)
- vendors (display_name, email, phone, balance)
- products (name, sku, type, price, cost, quantity_on_hand)
- transactions (txn_type, txn_number, txn_date, due_date, entity_name, category, amount, balance, status)
  - txn_type values: invoice, bill, expense, payment, journal_entry
- journal_lines (journal_date, account, debit, credit, description)
- imports (filename, entity_type, row_count, imported_at)
"""


# ── Integration setup tools ──────────────────────────────────────────────────

SETUP_TOOLS = [
    {
        "name": "setup_telegram_bot",
        "description": "Set up a Telegram bot for this agent. Call after the user gives you their bot token from @BotFather. Validates the token, registers the webhook, and opens a 10-minute registration window.",
        "input_schema": {
            "type": "object",
            "properties": {
                "bot_token": {"type": "string", "description": "The Telegram bot token from @BotFather (e.g. 123456789:ABCdef...)"},
            },
            "required": ["bot_token"],
        },
        "kind": "setup",
        "writes": True,
    },
    {
        "name": "check_telegram_registration",
        "description": "Check if a Telegram user has linked their account to this agent's bot by messaging it.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
        "kind": "setup",
        "writes": False,
    },
    {
        "name": "setup_odoo",
        "description": "Connect Odoo ERP. Validates the credentials via XML-RPC and saves them.",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Odoo server URL (e.g. https://mycompany.odoo.com)"},
                "database": {"type": "string", "description": "Odoo database name"},
                "username": {"type": "string", "description": "Odoo username or email"},
                "api_key": {"type": "string", "description": "Odoo API key"},
            },
            "required": ["url", "database", "username", "api_key"],
        },
        "kind": "setup",
        "writes": True,
    },
    {
        "name": "setup_bamboohr",
        "description": "Connect BambooHR. Validates the credentials and saves them.",
        "input_schema": {
            "type": "object",
            "properties": {
                "subdomain": {"type": "string", "description": "BambooHR subdomain (the 'company' in company.bamboohr.com)"},
                "api_key": {"type": "string", "description": "BambooHR API key"},
            },
            "required": ["subdomain", "api_key"],
        },
        "kind": "setup",
        "writes": True,
    },
    {
        "name": "enable_crm",
        "description": "Enable the built-in CRM for contacts, deals, tasks, and pipeline tracking. No credentials needed.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
        "kind": "setup",
        "writes": True,
    },
    {
        "name": "check_integrations",
        "description": "Check which integrations are currently configured and enabled.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
        "kind": "setup",
        "writes": False,
    },
]


# ── Helper maps for tool mode ────────────────────────────────────────────────

def build_writes_map(tool_defs: list[dict]) -> dict[str, bool]:
    """Map tool name → whether it performs write operations."""
    return {t["name"]: t.get("writes", False) for t in tool_defs}


def build_context_memory_map(tool_defs: list[dict]) -> dict[str, bool]:
    """Map tool name → whether it's a context/memory tool (always allowed)."""
    return {t["name"]: t.get("context_memory", False) for t in tool_defs}


def get_tool_definitions(
    gmail_enabled: bool = False,
    calendar_enabled: bool = False,
    gmail_read_enabled: bool | None = None,
    gmail_send_enabled: bool = False,
    calendar_read_enabled: bool | None = None,
    calendar_write_enabled: bool = False,
    drive_read_enabled: bool = False,
    drive_write_enabled: bool = False,
    web_enabled: bool = True,
    real_tools_enabled: bool = True,
    reports_enabled: bool = True,
    reminders_enabled: bool = True,
    scheduled_actions_enabled: bool = True,
    memory_enabled: bool = True,
    shared_context_enabled: bool = True,
    integration_tools: list[dict] | None = None,
    dynamic_real_tools: list[dict] | None = None,
    import_mode: bool = False,
) -> list[dict]:
    """Return the full list of tool definitions for the given feature flags.

    Granular Google flags take precedence when set. `gmail_enabled` /
    `calendar_enabled` serve as shortcuts that enable read access (they do
    not imply write access). The agents/router.py caller computes the
    granular flags by intersecting global scope grants (from google.json)
    with the agent's per-capability toggles.
    """
    if import_mode:
        from agents.import_service.tool_defs import IMPORT_TOOLS
        read_only_context = [t for t in CONTEXT_TOOLS if not t.get("writes", False)]
        return read_only_context + list(IMPORT_TOOLS)

    tools = list(CONTEXT_TOOLS)
    if memory_enabled:
        tools.extend(MEMORY_TOOLS)
    if shared_context_enabled:
        tools.extend(SHARED_CONTEXT_TOOLS)

    # Gmail — fall through to legacy flag if granular not specified
    if gmail_read_enabled is None:
        gmail_read_enabled = gmail_enabled
    if gmail_read_enabled:
        tools.extend(GMAIL_READ_TOOLS)
        tools.extend(GMAIL_ATTACHMENT_READ_TOOLS)
    if gmail_send_enabled:
        tools.extend(GMAIL_WRITE_TOOLS)

    # Calendar
    if calendar_read_enabled is None:
        calendar_read_enabled = calendar_enabled
    if calendar_read_enabled:
        tools.extend(CALENDAR_READ_TOOLS)
    if calendar_write_enabled:
        tools.extend(CALENDAR_WRITE_TOOLS)

    # Drive
    if drive_read_enabled:
        tools.extend(DRIVE_READ_TOOLS)
    if drive_write_enabled:
        tools.extend(DRIVE_WRITE_TOOLS)

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
    tools.extend(SETUP_TOOLS)
    # Append agent-created real tools (loaded from filesystem)
    if dynamic_real_tools:
        tools.extend(dynamic_real_tools)
    return tools
