"""
Chatty — Tool registry and execution dispatcher.

Dispatches tool calls by kind: context, gmail, calendar, web, real_tool,
report, reminder, scheduled_action, integration.
Each agent instance creates its own ToolRegistry with its own context_dir
and access token.
"""

import logging
from pathlib import Path

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
from core.agents.tools.web_tools import web_search, web_fetch
from core.agents.tools.real_tools import (
    create_real_tool,
    update_real_tool,
    delete_real_tool,
    list_real_tools,
    test_real_tool,
    execute_real_tool,
    parse_real_tool_definition,
    ToolContext,
)
from core.agents.tools.report_tools import generate_report

logger = logging.getLogger(__name__)


class ToolRegistry:
    """Per-agent tool executor. Routes tool calls to the correct handler."""

    def __init__(
        self,
        context_dir: str,
        google_access_token: str = "",
        integration_executors: dict | None = None,
        agent_slug: str = "",
        reminder_handlers: dict | None = None,
        scheduled_action_handlers: dict | None = None,
    ):
        self.context_dir = context_dir
        self.google_access_token = google_access_token
        self.integration_executors: dict = integration_executors or {}
        self.agent_slug = agent_slug

        # Derived paths
        agent_data_dir = str(Path(context_dir).parent)
        self.real_tools_dir = str(Path(agent_data_dir) / "real_tools")
        self.reports_dir = str(Path(agent_data_dir) / "reports")

        # Injected handlers for reminders and scheduled actions
        self.reminder_handlers: dict = reminder_handlers or {}
        self.scheduled_action_handlers: dict = scheduled_action_handlers or {}

        # Cache for loaded real tool code (name -> code string)
        self._real_tool_code: dict[str, str] = {}

    async def execute_tool(self, tool_name: str, tool_args: dict, kind: str) -> dict:
        """Execute a tool by name and return its result."""
        try:
            if kind == "context":
                return self._execute_context(tool_name, tool_args)
            elif kind == "gmail":
                return self._execute_gmail(tool_name, tool_args)
            elif kind == "calendar":
                return self._execute_calendar(tool_name, tool_args)
            elif kind == "web":
                return self._execute_web(tool_name, tool_args)
            elif kind == "real_tool":
                return self._execute_real_tool(tool_name, tool_args)
            elif kind == "report":
                return self._execute_report(tool_name, tool_args)
            elif kind == "reminder":
                return self._execute_reminder(tool_name, tool_args)
            elif kind == "scheduled_action":
                return self._execute_scheduled_action(tool_name, tool_args)
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

    def _execute_web(self, tool_name: str, args: dict) -> dict:
        if tool_name == "web_search":
            return web_search(args["query"], args.get("num_results", 5))
        elif tool_name == "web_fetch":
            return web_fetch(args["url"], args.get("extract_links", False))
        return {"error": f"Unknown web tool: {tool_name}"}

    def _execute_real_tool(self, tool_name: str, args: dict) -> dict:
        # Management tools
        if tool_name == "create_real_tool":
            return create_real_tool(self.real_tools_dir, args["name"], args["definition"])
        elif tool_name == "update_real_tool":
            return update_real_tool(self.real_tools_dir, args["name"], args["definition"])
        elif tool_name == "delete_real_tool":
            return delete_real_tool(self.real_tools_dir, args["name"])
        elif tool_name == "list_real_tools":
            return list_real_tools(self.real_tools_dir)
        elif tool_name == "test_real_tool":
            return test_real_tool(args["definition"], args.get("test_args"))

        # Agent-created tool execution — name matches a loaded .realtool.md
        tool_file = Path(self.real_tools_dir) / f"{tool_name}.realtool.md"
        if tool_file.exists():
            try:
                parsed = parse_real_tool_definition(tool_file.read_text(encoding="utf-8"))
                ctx = ToolContext()
                # Apply defaults for missing args
                effective_args = dict(args)
                for p in parsed["parameters"]:
                    if p["name"] not in effective_args and p.get("default"):
                        effective_args[p["name"]] = p["default"]
                return execute_real_tool(parsed["code"], ctx, effective_args)
            except Exception as e:
                return {"error": f"Real tool execution failed: {e}"}

        return {"error": f"Unknown real_tool: {tool_name}"}

    def _execute_report(self, tool_name: str, args: dict) -> dict:
        if tool_name == "generate_report":
            return generate_report(
                self.reports_dir,
                args["title"],
                args["sections"],
                subtitle=args.get("subtitle", ""),
            )
        return {"error": f"Unknown report tool: {tool_name}"}

    def _execute_reminder(self, tool_name: str, args: dict) -> dict:
        handler = self.reminder_handlers.get(tool_name)
        if handler:
            return handler(**args)
        return {"error": f"Reminder tool not available: {tool_name}"}

    def _execute_scheduled_action(self, tool_name: str, args: dict) -> dict:
        handler = self.scheduled_action_handlers.get(tool_name)
        if handler:
            return handler(**args)
        return {"error": f"Scheduled action tool not available: {tool_name}"}

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
