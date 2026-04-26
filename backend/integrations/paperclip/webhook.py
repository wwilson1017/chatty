"""Chatty — Paperclip heartbeat webhook handler.

Receives heartbeat POSTs from Paperclip's built-in HTTP adapter and runs
the mapped Chatty agent via run_sync() (the non-streaming execution path
also used by Telegram).

Self-contained: does not import private helpers from agents/router.py.
"""

import importlib
import logging

from fastapi import Request
from fastapi.responses import JSONResponse

from agents import db as agent_db
from agents.engine import build_agent_config, get_context_manager
from core.providers import get_ai_provider
from core.agents.tool_registry import ToolRegistry
from core.agents.reminders.tools import (
    create_reminder_handler,
    list_reminders_handler,
    cancel_reminder_handler,
)
from core.agents.scheduled_actions.tools import (
    create_scheduled_action_handler,
    list_scheduled_actions_handler,
    update_scheduled_action_handler,
    delete_scheduled_action_handler,
)
from core.agents import ai_service

from .client import paperclip_run_ctx

logger = logging.getLogger(__name__)


# Integration module registry (same as agents/router.py + telegram/service.py)
_INTEGRATION_MODULES = {
    "crm_lite": ("integrations.crm_lite.tools", "CRM_LITE_TOOL_DEFS"),
    "odoo": ("integrations.odoo.tools", "ODOO_TOOL_DEFS"),
    "bamboohr": ("integrations.bamboohr.tools", "BAMBOOHR_TOOL_DEFS"),
    "quickbooks": ("integrations.quickbooks.tools", "QB_TOOL_DEFS"),
    "qb_csv": ("integrations.qb_csv.tools", "QB_CSV_TOOL_DEFS"),
    "paperclip": ("integrations.paperclip.tools", "PAPERCLIP_TOOL_DEFS"),
}


def _load_integration_tools() -> tuple[list[dict], dict]:
    """Load tool definitions and executors from all enabled integrations."""
    from integrations.registry import is_enabled

    tool_defs: list[dict] = []
    executors: dict = {}

    for name, (module_path, defs_attr) in _INTEGRATION_MODULES.items():
        if not is_enabled(name):
            continue
        try:
            if name == "crm_lite":
                from integrations.crm_lite.db import init_db, _connection
                if _connection is None:
                    init_db()
            if name == "qb_csv":
                from integrations.qb_csv.db import init_db as init_qb_csv, _connection as qb_csv_conn
                if qb_csv_conn is None:
                    init_qb_csv()

            mod = importlib.import_module(module_path)
            defs = getattr(mod, defs_attr, [])
            execs = getattr(mod, "TOOL_EXECUTORS", {})
            tool_defs.extend({**d, "integration": name} for d in defs)
            executors.update(execs)
        except Exception as e:
            logger.warning("Failed to load integration %s: %s", name, e)

    return tool_defs, executors


def _build_agent_handlers(agent_slug: str):
    reminder_handlers = {
        "create_reminder": lambda **kw: create_reminder_handler(agent_slug, **kw),
        "list_reminders": lambda **kw: list_reminders_handler(agent_slug, **kw),
        "cancel_reminder": lambda **kw: cancel_reminder_handler(agent_slug, **kw),
    }
    sa_handlers = {
        "create_scheduled_action": lambda **kw: create_scheduled_action_handler(agent_slug, **kw),
        "list_scheduled_actions": lambda **kw: list_scheduled_actions_handler(agent_slug, **kw),
        "update_scheduled_action": lambda **kw: update_scheduled_action_handler(agent_slug, **kw),
        "delete_scheduled_action": lambda **kw: delete_scheduled_action_handler(agent_slug, **kw),
    }
    return reminder_handlers, sa_handlers


async def handle_heartbeat(request: Request):
    """Process a heartbeat from Paperclip's HTTP adapter.

    Auth: shared secret header only (no Chatty JWT).
    Execution: run_sync() with Paperclip tool mode forced to "power".
    Response: synchronous JSON with result text.
    """
    from integrations.registry import get_credentials, get_tool_mode, is_enabled as _is_enabled

    try:
        payload = await request.json()
    except Exception:
        return JSONResponse({"status": "error", "error": "Invalid JSON"}, status_code=400)

    # 1. Validate shared secret
    creds = get_credentials("paperclip")
    expected_secret = creds.get("webhook_secret", "")
    if expected_secret:
        actual_secret = request.headers.get("X-Webhook-Secret", "")
        if actual_secret != expected_secret:
            return JSONResponse({"status": "error", "error": "Unauthorized"}, status_code=403)

    # 2. Map Paperclip agent → Chatty agent
    agent_id = payload.get("agentId", "")
    mapping = creds.get("agent_mapping", {})
    chatty_slug = mapping.get(agent_id)
    if not chatty_slug:
        logger.warning("Paperclip heartbeat: unmapped agentId=%s", agent_id)
        return JSONResponse(
            {"status": "error", "error": f"No Chatty agent mapped for Paperclip agent {agent_id}"},
            status_code=400,
        )

    # 3. Load agent
    agent = agent_db.get_agent_by_slug(chatty_slug)
    if not agent:
        return JSONResponse(
            {"status": "error", "error": f"Chatty agent '{chatty_slug}' not found"},
            status_code=404,
        )

    slug = agent["slug"]
    wake_reason = payload.get("wakeReason", "assigned")
    issue_id = payload.get("issueId", "")

    logger.info(
        "Paperclip heartbeat: agent=%s reason=%s issue=%s",
        slug, wake_reason, issue_id,
    )

    # 4. Set run context for Paperclip client (X-Paperclip-Run-Id header)
    ctx_token = paperclip_run_ctx.set({
        "run_id": payload.get("runId", ""),
        "agent_id": agent_id,
    })

    try:
        # 5. Build agent pipeline (mirrors telegram/service.py pattern)
        config = build_agent_config(agent)
        ctx_manager = get_context_manager(slug)

        provider = get_ai_provider(
            agent_provider=config.provider_override or None,
            agent_model=config.model_override or None,
        )
        if not provider:
            return JSONResponse(
                {"status": "error", "error": "No AI provider configured"},
                status_code=500,
            )

        google_connected = _is_enabled("google")
        integration_tool_defs, integration_executors = _load_integration_tools()

        # Force Paperclip writes to "power" — no approval UI in headless mode
        integration_tool_modes = {name: get_tool_mode(name) for name in _INTEGRATION_MODULES}
        integration_tool_modes["paperclip"] = "power"

        reminder_handlers, sa_handlers = _build_agent_handlers(slug)
        registry = ToolRegistry(
            context_dir=config.context_dir,
            google_connected=google_connected,
            integration_executors=integration_executors,
            agent_slug=slug,
            reminder_handlers=reminder_handlers,
            scheduled_action_handlers=sa_handlers,
        )

        # 6. Build task message
        context_parts = [f"[Paperclip Heartbeat] Reason: {wake_reason}."]
        if issue_id:
            context_parts.append(f"Issue ID: {issue_id}.")
        context_parts.append(
            "Check your Paperclip assignments and work on them. "
            "Use your Paperclip tools to list issues, claim tasks, update status, and post comments."
        )
        messages = [{"role": "user", "content": " ".join(context_parts)}]

        # 7. Run agent synchronously
        result_text = await ai_service.run_sync(
            config=config,
            provider=provider,
            registry=registry,
            ctx_manager=ctx_manager,
            messages=messages,
            integration_tool_defs=integration_tool_defs or None,
            integration_tool_modes=integration_tool_modes,
        )

        logger.info("Paperclip heartbeat complete: agent=%s len=%d", slug, len(result_text or ""))
        return {"status": "succeeded", "result": result_text or "No response generated."}

    except Exception as e:
        logger.error("Paperclip heartbeat failed: %s", e, exc_info=True)
        return JSONResponse(
            {"status": "error", "error": str(e)},
            status_code=500,
        )
    finally:
        paperclip_run_ctx.reset(ctx_token)
