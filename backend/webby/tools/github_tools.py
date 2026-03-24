"""
Webby — GitHub tool definitions and handlers.

Phase 1: Stubs with correct signatures. Full implementation in Phase 2.
"""

from datetime import datetime

# ---------------------------------------------------------------------------
# Tool definitions (passed to the AI as available tools)
# ---------------------------------------------------------------------------

GITHUB_TOOL_DEFS = [
    {
        "name": "list_website_files",
        "description": "List files and directories in the website repository at a given path.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Directory path to list (default: root). E.g. 'src/pages' or ''.",
                },
            },
            "required": [],
        },
        "kind": "webby",
    },
    {
        "name": "read_website_file",
        "description": "Read the contents of a file in the website repository.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "File path relative to the repo root. E.g. 'index.html' or 'src/pages/about.tsx'.",
                },
                "ref": {
                    "type": "string",
                    "description": "Branch or commit to read from (default: default branch).",
                },
            },
            "required": ["path"],
        },
        "kind": "webby",
    },
    {
        "name": "edit_website_file",
        "description": (
            "Edit a file in the website repository. "
            "Creates a branch automatically (webby/{description}-{date}) and commits the change. "
            "Call create_website_pr after editing to open a pull request for review."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "File path relative to the repo root.",
                },
                "content": {
                    "type": "string",
                    "description": "Full new content of the file.",
                },
                "description": {
                    "type": "string",
                    "description": "Short description of the change (used in branch name and commit message). E.g. 'update-hero-text'.",
                },
                "branch": {
                    "type": "string",
                    "description": "Branch to commit to. If omitted, a new branch is created automatically.",
                },
            },
            "required": ["path", "content", "description"],
        },
        "kind": "webby",
    },
    {
        "name": "create_website_pr",
        "description": "Create a pull request so the user can review and approve the changes before they go live.",
        "input_schema": {
            "type": "object",
            "properties": {
                "branch": {
                    "type": "string",
                    "description": "The branch containing the changes.",
                },
                "title": {
                    "type": "string",
                    "description": "Short title for the pull request.",
                },
                "summary": {
                    "type": "string",
                    "description": "Plain-language summary of what changed and why.",
                },
            },
            "required": ["branch", "title", "summary"],
        },
        "kind": "webby",
    },
    {
        "name": "get_pending_changes",
        "description": "List any open pull requests (pending changes awaiting review).",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
        "kind": "webby",
    },
]


# ---------------------------------------------------------------------------
# Tool executors (Phase 1 stubs — implementation in Phase 2)
# ---------------------------------------------------------------------------

def _stub_result(tool_name: str) -> dict:
    return {
        "error": "not_implemented",
        "tool": tool_name,
        "message": (
            "GitHub integration is not fully implemented yet (Phase 2). "
            "To use Webby's website editing features, please check back in the next release."
        ),
    }


def list_website_files(path: str = "") -> dict:
    """List files at a path in the website repo. Phase 1 stub."""
    # TODO: Phase 2 — call github_client.list_contents() using stored PAT + repo
    return _stub_result("list_website_files")


def read_website_file(path: str, ref: str = "") -> dict:
    """Read a file from the website repo. Phase 1 stub."""
    # TODO: Phase 2 — call github_client.get_file()
    return _stub_result("read_website_file")


def edit_website_file(path: str, content: str, description: str, branch: str = "") -> dict:
    """Edit a file in the website repo (creates branch + commits). Phase 1 stub."""
    # TODO: Phase 2 — call github_client.create_branch() + create_or_update_file()
    # Auto-branch naming: f"webby/{description}-{datetime.now().strftime('%Y%m%d')}"
    return _stub_result("edit_website_file")


def create_website_pr(branch: str, title: str, summary: str) -> dict:
    """Open a pull request for the pending changes. Phase 1 stub."""
    # TODO: Phase 2 — call github_client.create_pull_request()
    return _stub_result("create_website_pr")


def get_pending_changes() -> dict:
    """List open pull requests (pending changes). Phase 1 stub."""
    # TODO: Phase 2 — call GitHub API to list open PRs created by Webby
    return _stub_result("get_pending_changes")


TOOL_EXECUTORS = {
    "list_website_files": list_website_files,
    "read_website_file": read_website_file,
    "edit_website_file": edit_website_file,
    "create_website_pr": create_website_pr,
    "get_pending_changes": get_pending_changes,
}
