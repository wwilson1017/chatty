"""
Chatty — Tool registry and execution dispatcher.

Dispatches tool calls by kind: context, memory, shared_context, gmail,
calendar, web, real_tool, report, reminder, scheduled_action, integration.
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
from integrations.google.tools import (
    # Gmail
    create_draft,
    download_email_attachment,
    get_email,
    get_email_thread,
    batch_mark_emails_as_read,
    mark_email_as_read,
    reply_to_email,
    reply_to_email_with_attachment,
    search_emails,
    send_email,
    send_email_with_attachment,
    # Calendar
    create_calendar_event,
    delete_calendar_event,
    find_free_slot,
    get_calendar_event,
    list_calendar_events,
    search_calendar_events,
    update_calendar_event,
    # Drive
    copy_drive_file,
    create_drive_file,
    create_drive_folder,
    get_drive_file_info,
    list_drive_folder,
    move_drive_file,
    read_drive_file_content,
    rename_drive_file,
    search_drive_files,
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
        gcs_prefix: str = "",
        google_connected: bool = False,
        gmail_account_id: str = "",
        calendar_account_id: str = "",
        drive_account_id: str = "",
        integration_executors: dict | None = None,
        agent_slug: str = "",
        agent_name: str = "",
        reminder_handlers: dict | None = None,
        scheduled_action_handlers: dict | None = None,
    ):
        self.context_dir = context_dir
        self.gcs_prefix = gcs_prefix
        self.google_connected = google_connected
        self.gmail_account_id = gmail_account_id
        self.calendar_account_id = calendar_account_id
        self.drive_account_id = drive_account_id
        self.integration_executors: dict = integration_executors or {}
        self.agent_slug = agent_slug
        self.agent_name = agent_name

        # Derived paths
        agent_data_dir = str(Path(context_dir).parent)
        self.agent_data_dir = agent_data_dir
        self.real_tools_dir = str(Path(agent_data_dir) / "real_tools")
        self.reports_dir = str(Path(agent_data_dir) / "reports")
        self.file_cache_dir = str(Path(agent_data_dir) / "file_cache")

        # Shared context data dir
        self.shared_data_dir = str(Path(agent_data_dir).parent.parent / "shared")

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
            elif kind == "memory":
                return self._execute_memory(tool_name, tool_args)
            elif kind == "shared_context":
                return self._execute_shared_context(tool_name, tool_args)
            elif kind == "gmail":
                return self._execute_gmail(tool_name, tool_args)
            elif kind == "calendar":
                return self._execute_calendar(tool_name, tool_args)
            elif kind == "drive":
                return self._execute_drive(tool_name, tool_args)
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
            elif kind == "setup":
                return self._execute_setup(tool_name, tool_args)
            elif kind == "import":
                return self._execute_import(tool_name, tool_args)
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

    def _execute_memory(self, tool_name: str, args: dict) -> dict:
        from core.agents.tools.memory_tools import (
            append_daily_note, read_daily_note, list_daily_notes,
            read_memory, update_memory, consolidate_memory,
        )
        from core.agents.memory.search_tools import (
            search_memory, add_fact, query_facts, invalidate_fact,
        )

        # Memory tools use context_dir (not agent_data_dir) because
        # ContextManager expects the context directory as data_dir.
        # Daily notes live at context_dir/daily/, MEMORY.md at context_dir/.
        ctx_dir = self.context_dir
        prefix = self.gcs_prefix

        if tool_name == "append_daily_note":
            return append_daily_note(ctx_dir, prefix, args["content"],
                                     date=args.get("date"), memory_type=args.get("memory_type"))
        elif tool_name == "read_daily_note":
            return read_daily_note(ctx_dir, prefix, args["date"])
        elif tool_name == "list_daily_notes":
            return list_daily_notes(ctx_dir, prefix, limit=args.get("limit", 30))
        elif tool_name == "read_memory":
            return read_memory(ctx_dir, prefix)
        elif tool_name == "update_memory":
            return update_memory(ctx_dir, prefix, args["content"])
        elif tool_name == "search_memory":
            return search_memory(
                ctx_dir, prefix, args["query"],
                source_type=args.get("source_type"),
                memory_type=args.get("memory_type"),
                date_from=args.get("date_from"),
                date_to=args.get("date_to"),
                limit=args.get("limit", 20),
            )
        elif tool_name == "add_fact":
            return add_fact(
                ctx_dir, prefix,
                subject=args["subject"], predicate=args["predicate"], object=args["object"],
                memory_type=args.get("memory_type"), confidence=args.get("confidence", 1.0),
            )
        elif tool_name == "query_facts":
            return query_facts(
                ctx_dir, prefix,
                subject=args.get("subject"), predicate=args.get("predicate"),
                as_of=args.get("as_of"), memory_type=args.get("memory_type"),
                include_expired=args.get("include_expired", False),
                limit=args.get("limit", 50),
            )
        elif tool_name == "invalidate_fact":
            return invalidate_fact(
                ctx_dir, prefix,
                fact_id=args["fact_id"], valid_to=args.get("valid_to"),
            )
        elif tool_name == "consolidate_memory":
            from core.providers.credentials import CredentialStore
            store = CredentialStore()
            _, anthropic_profile = store.get_active_profile(provider_override="anthropic")
            api_key = (anthropic_profile or {}).get("key", "")
            return consolidate_memory(
                ctx_dir, prefix, api_key,
                days=args.get("days", 7),
            )
        return {"error": f"Unknown memory tool: {tool_name}"}

    def _execute_shared_context(self, tool_name: str, args: dict) -> dict:
        from core.agents.shared_context.tools import (
            list_shared_context, read_shared_context, write_shared_context,
        )

        if tool_name == "list_shared_context":
            return list_shared_context(self.shared_data_dir, category=args.get("category", ""))
        elif tool_name == "read_shared_context":
            return read_shared_context(self.shared_data_dir,
                                       filename=args.get("filename", ""),
                                       entry_id=args.get("entry_id", ""))
        elif tool_name == "write_shared_context":
            return write_shared_context(
                self.shared_data_dir, self.gcs_prefix, self.agent_name,
                title=args["title"], content=args["content"],
                category=args.get("category", ""),
            )
        return {"error": f"Unknown shared_context tool: {tool_name}"}

    def _execute_gmail(self, tool_name: str, args: dict) -> dict:
        aid = self.gmail_account_id
        if not aid:
            return {"error": "No Gmail account assigned. Assign one at Settings → Integrations → Google.",
                    "needs_reconnect": True}
        if tool_name == "search_emails":
            return search_emails(aid, query=args["query"], max_results=args.get("max_results", 10))
        elif tool_name == "get_email":
            return get_email(aid, message_id=args["message_id"])
        elif tool_name == "get_email_thread":
            return get_email_thread(aid, thread_id=args["thread_id"])
        elif tool_name == "send_email":
            return send_email(
                aid, to=args["to"], subject=args["subject"], body=args["body"],
                cc=args.get("cc", ""), bcc=args.get("bcc", ""),
            )
        elif tool_name == "reply_to_email":
            return reply_to_email(
                aid, message_id=args["message_id"], body=args["body"],
                reply_all=args.get("reply_all", False),
            )
        elif tool_name == "create_draft":
            return create_draft(
                aid, to=args["to"], subject=args["subject"], body=args["body"],
                cc=args.get("cc", ""), bcc=args.get("bcc", ""),
            )
        elif tool_name == "mark_email_as_read":
            return mark_email_as_read(aid, message_id=args["message_id"])
        elif tool_name == "batch_mark_emails_as_read":
            return batch_mark_emails_as_read(aid, message_ids=args["message_ids"])
        elif tool_name == "download_email_attachment":
            return download_email_attachment(
                aid, message_id=args["message_id"], filename=args["filename"],
                cache_dir=self.file_cache_dir,
            )
        elif tool_name == "send_email_with_attachment":
            return send_email_with_attachment(
                aid, to=args["to"], subject=args["subject"], body=args["body"],
                attachment_filename=args.get("attachment_filename", ""),
                attachment_base64=args.get("attachment_base64", ""),
                attachment_mime_type=args.get("attachment_mime_type", "application/pdf"),
                cc=args.get("cc", ""), bcc=args.get("bcc", ""),
                file_ref=args.get("file_ref", ""),
                cache_dir=self.file_cache_dir,
            )
        elif tool_name == "reply_to_email_with_attachment":
            return reply_to_email_with_attachment(
                aid, message_id=args["message_id"], body=args["body"],
                attachment_filename=args.get("attachment_filename", ""),
                attachment_base64=args.get("attachment_base64", ""),
                attachment_mime_type=args.get("attachment_mime_type", "application/pdf"),
                reply_all=args.get("reply_all", False),
                file_ref=args.get("file_ref", ""),
                cache_dir=self.file_cache_dir,
            )
        return {"error": f"Unknown gmail tool: {tool_name}"}

    def _execute_calendar(self, tool_name: str, args: dict) -> dict:
        aid = self.calendar_account_id
        if not aid:
            return {"error": "No Calendar account assigned. Assign one at Settings → Integrations → Google.",
                    "needs_reconnect": True}
        if tool_name == "list_calendar_events":
            return list_calendar_events(
                aid, calendar_id=args.get("calendar_id", "primary"),
                max_results=args.get("max_results", 10),
                time_min=args.get("time_min", ""),
                time_max=args.get("time_max", ""),
            )
        elif tool_name == "get_calendar_event":
            return get_calendar_event(
                aid, event_id=args["event_id"],
                calendar_id=args.get("calendar_id", "primary"),
            )
        elif tool_name == "search_calendar_events":
            return search_calendar_events(
                aid, query=args["query"],
                time_min=args.get("time_min", ""),
                time_max=args.get("time_max", ""),
                max_results=args.get("max_results", 20),
                calendar_id=args.get("calendar_id", "primary"),
            )
        elif tool_name == "find_free_slot":
            return find_free_slot(
                aid, duration_minutes=args["duration_minutes"],
                between_start=args["between_start"],
                between_end=args["between_end"],
                calendar_ids=args.get("calendar_ids"),
            )
        elif tool_name == "create_calendar_event":
            return create_calendar_event(
                aid, summary=args["summary"], start=args["start"], end=args["end"],
                description=args.get("description", ""), location=args.get("location", ""),
                attendees=args.get("attendees"),
                calendar_id=args.get("calendar_id", "primary"),
            )
        elif tool_name == "update_calendar_event":
            return update_calendar_event(
                aid, event_id=args["event_id"],
                calendar_id=args.get("calendar_id", "primary"),
                summary=args.get("summary"), start=args.get("start"), end=args.get("end"),
                description=args.get("description"), location=args.get("location"),
                attendees=args.get("attendees"),
            )
        elif tool_name == "delete_calendar_event":
            return delete_calendar_event(
                aid, event_id=args["event_id"],
                calendar_id=args.get("calendar_id", "primary"),
            )
        return {"error": f"Unknown calendar tool: {tool_name}"}

    def _execute_drive(self, tool_name: str, args: dict) -> dict:
        aid = self.drive_account_id
        if not aid:
            return {"error": "No Drive account assigned. Assign one at Settings → Integrations → Google.",
                    "needs_reconnect": True}
        if tool_name == "search_drive_files":
            return search_drive_files(
                aid, query=args["query"],
                max_results=args.get("max_results", 20),
            )
        elif tool_name == "list_drive_folder":
            return list_drive_folder(
                aid, folder_id=args.get("folder_id", "root"),
                max_results=args.get("max_results", 50),
            )
        elif tool_name == "get_drive_file_info":
            return get_drive_file_info(aid, file_id=args["file_id"])
        elif tool_name == "read_drive_file_content":
            return read_drive_file_content(
                aid, file_id=args["file_id"],
                max_chars=args.get("max_chars", 50000),
            )
        elif tool_name == "create_drive_folder":
            return create_drive_folder(
                aid, name=args["name"],
                parent_folder_id=args.get("parent_folder_id", "root"),
            )
        elif tool_name == "create_drive_file":
            return create_drive_file(
                aid, name=args["name"],
                content=args.get("content", ""),
                file_type=args.get("file_type", "document"),
                folder_id=args.get("folder_id", "root"),
            )
        elif tool_name == "move_drive_file":
            return move_drive_file(
                aid, file_id=args["file_id"],
                new_parent_id=args["new_parent_id"],
            )
        elif tool_name == "rename_drive_file":
            return rename_drive_file(
                aid, file_id=args["file_id"],
                new_name=args["new_name"],
            )
        elif tool_name == "copy_drive_file":
            return copy_drive_file(
                aid, file_id=args["file_id"],
                new_name=args.get("new_name"),
                folder_id=args.get("folder_id"),
            )
        return {"error": f"Unknown drive tool: {tool_name}"}

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

    def _execute_setup(self, tool_name: str, args: dict) -> dict:
        """Execute integration setup tools using this agent's context."""
        if tool_name == "setup_telegram_bot":
            return self._setup_telegram(args["bot_token"])
        elif tool_name == "check_telegram_registration":
            return self._check_telegram_registration()
        elif tool_name == "setup_odoo":
            return self._setup_odoo(args["url"], args["database"], args["username"], args["api_key"])
        elif tool_name == "setup_bamboohr":
            return self._setup_bamboohr(args["subdomain"], args["api_key"])
        elif tool_name == "enable_crm":
            return self._enable_crm()
        elif tool_name == "check_integrations":
            return self._check_integrations()
        return {"error": f"Unknown setup tool: {tool_name}"}

    def _execute_import(self, tool_name: str, args: dict) -> dict:
        from agents.import_service import sessions
        from agents.import_service.tools import execute_import_tool
        from core.agents.context_manager import ContextManager

        session = getattr(self, "_import_session", None)
        ctx_manager = ContextManager(Path(self.context_dir), gcs_prefix=self.gcs_prefix)
        return execute_import_tool(tool_name, args, session, ctx_manager)

    def _mark_setup_complete(self, integration_name: str) -> None:
        """Auto-update _pending-setup.md to check off a completed integration."""
        from integrations.pending_setup import mark_integration_complete
        mark_integration_complete(self.context_dir, integration_name)

    def _setup_telegram(self, bot_token: str) -> dict:
        from agents.db import get_agent_by_slug
        agent = get_agent_by_slug(self.agent_slug)
        if not agent:
            return {"error": "Agent not found"}
        from integrations.telegram.lifecycle import validate_and_save_token
        try:
            result = validate_and_save_token(agent["id"], bot_token)
            self._mark_setup_complete("Telegram Bot")
            return result
        except ValueError as e:
            return {"error": str(e)}

    def _check_telegram_registration(self) -> dict:
        from agents.db import get_agent_by_slug
        from integrations.telegram.state import get_registration_window, is_registration_open
        agent = get_agent_by_slug(self.agent_slug)
        if not agent:
            return {"error": "Agent not found"}
        window = get_registration_window(agent["id"])
        if not window:
            return {"registered": False, "window_open": False, "message": "No registration window. Set up the bot first."}
        return {
            "registered": bool(window.get("registered_user_id")),
            "window_open": is_registration_open(agent["id"]),
            "expires_at": window.get("expires_at", ""),
            "registered_user_id": window.get("registered_user_id"),
        }

    def _setup_odoo(self, url: str, database: str, username: str, api_key: str) -> dict:
        from integrations.odoo.onboarding import setup
        result = setup(url=url, database=database, username=username, api_key=api_key)
        if result.get("ok"):
            self._mark_setup_complete("Odoo ERP")
        return result

    def _setup_bamboohr(self, subdomain: str, api_key: str) -> dict:
        from integrations.bamboohr.onboarding import setup
        result = setup(subdomain=subdomain, api_key=api_key)
        if result.get("ok"):
            self._mark_setup_complete("BambooHR")
        return result

    def _enable_crm(self) -> dict:
        from integrations.crm_lite.onboarding import setup
        result = setup()
        if result.get("ok"):
            self._mark_setup_complete("CRM")
        return result

    def _check_integrations(self) -> dict:
        from integrations.registry import list_integrations
        from agents.db import get_agent_by_slug
        agent = get_agent_by_slug(self.agent_slug)
        results = []
        for i in list_integrations():
            entry = {"id": i["id"], "name": i["name"], "configured": i["configured"], "enabled": i["enabled"]}
            if i["id"] == "telegram" and agent:
                entry["configured"] = bool(agent.get("telegram_bot_token"))
                entry["enabled"] = bool(agent.get("telegram_enabled"))
            elif i["id"] == "whatsapp" and agent:
                entry["configured"] = bool(agent.get("whatsapp_session_id"))
                entry["enabled"] = bool(agent.get("whatsapp_session_id"))
            results.append(entry)
        return {"integrations": results}

    _CACHE_AWARE_TOOLS = {
        "download_odoo_pdf", "create_odoo_attachment",
    }

    async def _execute_integration(self, tool_name: str, args: dict) -> dict:
        executor = self.integration_executors.get(tool_name)
        if not executor:
            return {"error": f"Integration tool not available: {tool_name}"}
        if callable(executor):
            if tool_name in self._CACHE_AWARE_TOOLS:
                args = {**args, "cache_dir": self.file_cache_dir}
            import asyncio
            if asyncio.iscoroutinefunction(executor):
                return await executor(**args)
            return executor(**args)
        return {"error": f"Invalid executor for tool: {tool_name}"}
