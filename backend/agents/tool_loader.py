"""Chatty — Shared integration tool loading and agent handler construction.

Extracted from agents/router.py so both the chat flow and the scheduled
actions processor can build a full tool set with integration parity.
"""

import importlib
import logging

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

logger = logging.getLogger(__name__)

INTEGRATION_MODULES = {
    "crm_lite": ("integrations.crm_lite.tools", "CRM_LITE_TOOL_DEFS"),
    "odoo": ("integrations.odoo.tools", "ODOO_TOOL_DEFS"),
    "bamboohr": ("integrations.bamboohr.tools", "BAMBOOHR_TOOL_DEFS"),
    "quickbooks": ("integrations.quickbooks.tools", "QB_TOOL_DEFS"),
    "qb_csv": ("integrations.qb_csv.tools", "QB_CSV_TOOL_DEFS"),
    "paperclip": ("integrations.paperclip.tools", "PAPERCLIP_TOOL_DEFS"),
}


def load_integration_tools() -> tuple[list[dict], dict]:
    """Load tool definitions and executors from all enabled integrations."""
    from integrations.registry import is_enabled

    tool_defs: list[dict] = []
    executors: dict = {}

    for name, (module_path, defs_attr) in INTEGRATION_MODULES.items():
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


def build_agent_handlers(agent_slug: str) -> tuple[dict, dict]:
    """Build reminder and scheduled action handler dicts for an agent."""
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
