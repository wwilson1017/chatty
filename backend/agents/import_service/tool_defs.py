"""Tool definitions for Import Mode."""

IMPORT_TOOLS = [
    {
        "name": "scan_directory",
        "description": "Scan a local directory for markdown files. Use when the user gives a folder path. Returns a list of found .md files with sizes. Restricted to the user's home directory.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Directory path to scan, e.g. '~/Downloads/agent-files/' or '~/Documents/openclaw-export/'",
                },
            },
            "required": ["path"],
        },
        "kind": "import",
        "writes": False,
    },
    {
        "name": "ingest_pasted_text",
        "description": "Process markdown text that the user pasted directly into the chat. Call this when the user pastes knowledge content rather than pointing to a file.",
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "The markdown text the user pasted",
                },
            },
            "required": ["text"],
        },
        "kind": "import",
        "writes": False,
    },
    {
        "name": "list_import_files",
        "description": "List all files available in the current import source (after scan_directory or ingest_pasted_text has been called).",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
        "kind": "import",
        "writes": False,
    },
    {
        "name": "read_import_file",
        "description": "Read the content of a specific file from the import source. Secrets are automatically redacted.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "File path from list_import_files (e.g. 'SOUL.md', 'memory/2026-04-15.md')",
                },
            },
            "required": ["path"],
        },
        "kind": "import",
        "writes": False,
    },
    {
        "name": "skip_import_file",
        "description": "Mark a file as skipped so it won't be imported.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "File path to skip",
                },
                "reason": {
                    "type": "string",
                    "description": "Brief reason for skipping",
                },
            },
            "required": ["path"],
        },
        "kind": "import",
        "writes": False,
    },
    {
        "name": "read_existing_context",
        "description": "Read one of the new agent's existing Chatty context files. Useful during re-import to compare what's already there versus what's being imported.",
        "input_schema": {
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": "Chatty context filename (e.g. 'soul.md', 'MEMORY.md')",
                },
            },
            "required": ["filename"],
        },
        "kind": "import",
        "writes": False,
    },
    {
        "name": "write_import_context",
        "description": "Write a knowledge file to the new agent's context directory. Use Chatty's style: first-person, concise, no filler. Valid targets: soul.md, identity.md, user.md, profile.md, goals.md, preferences.md, environment.md, MEMORY.md, or daily/{date}.md for daily logs.",
        "input_schema": {
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": "Target filename (e.g. 'soul.md', 'MEMORY.md', 'daily/2026-04-22.md')",
                },
                "content": {
                    "type": "string",
                    "description": "The markdown content to write",
                },
            },
            "required": ["filename", "content"],
        },
        "kind": "import",
        "writes": True,
    },
    {
        "name": "extract_zip",
        "description": "Extract a zip file of markdown files uploaded by the user. Call this when a .zip file is attached to the chat. Provide the filename of the attachment.",
        "input_schema": {
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": "The filename of the uploaded zip attachment",
                },
            },
            "required": ["filename"],
        },
        "kind": "import",
        "writes": False,
    },
    {
        "name": "import_openclaw_agent",
        "description": "Import knowledge from a specific OpenClaw agent. Use when the user picks an OpenClaw agent to import from. The agent must have been discovered via the OpenClaw auto-detection in the opening message.",
        "input_schema": {
            "type": "object",
            "properties": {
                "agent_id": {
                    "type": "string",
                    "description": "The OpenClaw agent ID (e.g. 'default', 'research-bot')",
                },
            },
            "required": ["agent_id"],
        },
        "kind": "import",
        "writes": False,
    },
    {
        "name": "finalize_import",
        "description": "Complete the import process. Call this after all files have been written. Creates a fresh conversation with a primed opener greeting and marks the agent as ready.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
        "kind": "import",
        "writes": True,
    },
]
