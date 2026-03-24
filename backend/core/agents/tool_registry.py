"""
Chatty — Tool registry and execution dispatcher.

Dispatches tool calls by kind: context, gmail, calendar, integration.
Each agent instance creates its own ToolRegistry with its own context_dir
and access token.
"""

import logging

from core.agents.tools.context_tools import (
    list_context_files,
    read_context_file,
    write_context_file,
    append_to_context_file,
    delete_context_file,
)
from core.agents.tools.gmail_tools import search_emails, get_email, get_email_thread
from core.agents.tools.calendar_tools import (
    list_calendar_events,
    get_calendar_event,
    search_calendar_events,
)

logger = logging.getLogger(__name__)


class ToolRegistry:
    """Per-agent tool executor. Routes tool calls to the correct handler."""

    def __init__(
        self,
        context_dir: str,
        google_access_token: str = "",
        integration_executors: dict | None = None,
    ):
        self.context_dir = context_dir
        self.google_access_token = google_access_token
        # Dict[tool_name -> callable] for integration tools (Odoo, QB, etc.)
        self.integration_executors: dict = integration_executors or {}

    async def execute_tool(self, tool_name: str, tool_args: dict, kind: str) -> dict:
        """Execute a tool by name and return its result."""
        try:
            if kind == "context":
                return self._execute_context(tool_name, tool_args)
            elif kind == "gmail":
                return self._execute_gmail(tool_name, tool_args)
            elif kind == "calendar":
                return self._execute_calendar(tool_name, tool_args)
            elif kind == "integration":
                return await self._execute_integration(tool_name, tool_args)
            else:
                return {"error": f"Unknown tool kind: {kind}"}
        except Exception as e:
            logger.error("Tool execution error [%s/%s]: %s", kind, tool_name, e)
            return {"error": f"Tool error: {str(e)}"}

    def _execute_context(self, tool_name: str, args: dict) -> dict:
        if tool_name == "list_context_files":
            return list_context_files(self.context_dir)
        elif tool_name == "read_context_file":
            return read_context_file(self.context_dir, args["filename"])
        elif tool_name == "write_context_file":
            return write_context_file(self.context_dir, args["filename"], args["content"])
        elif tool_name == "append_to_context_file":
            return append_to_context_file(self.context_dir, args["filename"], args["content"])
        elif tool_name == "delete_context_file":
            return delete_context_file(self.context_dir, args["filename"])
        return {"error": f"Unknown context tool: {tool_name}"}

    def _execute_gmail(self, tool_name: str, args: dict) -> dict:
        if not self.google_access_token:
            return {"error": "Google not connected — no access token available"}
        if tool_name == "search_emails":
            return search_emails(self.google_access_token, args["query"], args.get("max_results", 10))
        elif tool_name == "get_email":
            return get_email(self.google_access_token, args["message_id"])
        elif tool_name == "get_email_thread":
            return get_email_thread(self.google_access_token, args["thread_id"])
        return {"error": f"Unknown gmail tool: {tool_name}"}

    def _execute_calendar(self, tool_name: str, args: dict) -> dict:
        if not self.google_access_token:
            return {"error": "Google not connected — no access token available"}
        if tool_name == "list_calendar_events":
            return list_calendar_events(
                self.google_access_token,
                calendar_id=args.get("calendar_id", "primary"),
                max_results=args.get("max_results", 10),
                time_min=args.get("time_min", ""),
                time_max=args.get("time_max", ""),
            )
        elif tool_name == "get_calendar_event":
            return get_calendar_event(
                self.google_access_token,
                args["event_id"],
                calendar_id=args.get("calendar_id", "primary"),
            )
        elif tool_name == "search_calendar_events":
            return search_calendar_events(
                self.google_access_token,
                args["query"],
                max_results=args.get("max_results", 10),
                calendar_id=args.get("calendar_id", "primary"),
            )
        return {"error": f"Unknown calendar tool: {tool_name}"}

    async def _execute_integration(self, tool_name: str, args: dict) -> dict:
        executor = self.integration_executors.get(tool_name)
        if not executor:
            return {"error": f"Integration tool not available: {tool_name}"}
        if callable(executor):
            import asyncio
            if asyncio.iscoroutinefunction(executor):
                return await executor(**args)
            return executor(**args)
        return {"error": f"Invalid executor for tool: {tool_name}"}
