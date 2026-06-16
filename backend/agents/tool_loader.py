"""Chatty — Shared integration tool loading and agent handler construction.

Extracted from agents/router.py so both the chat flow and the scheduled
actions processor can build a full tool set with integration parity.
"""

import importlib
import logging
from datetime import datetime
from typing import NamedTuple
from zoneinfo import ZoneInfo

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


def format_current_time(tz_name: str = "America/Chicago") -> tuple[str, str]:
    """Return (date_str, time_str) for system prompt injection."""
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("America/Chicago")
    now = datetime.now(tz)
    return now.strftime("%A, %B %d, %Y"), now.strftime("%I:%M %p %Z")


INTEGRATION_MODULES = {
    "crm_lite": ("integrations.crm_lite.tools", "CRM_LITE_TOOL_DEFS"),
    "odoo": ("integrations.odoo.tools", "ODOO_TOOL_DEFS"),
    "bamboohr": ("integrations.bamboohr.tools", "BAMBOOHR_TOOL_DEFS"),
    "quickbooks": ("integrations.quickbooks.tools", "QB_TOOL_DEFS"),
    "qb_csv": ("integrations.qb_csv.tools", "QB_CSV_TOOL_DEFS"),
    "paperclip": ("integrations.paperclip.tools", "PAPERCLIP_TOOL_DEFS"),
    "todoist": ("integrations.todoist.tools", "TODOIST_TOOL_DEFS"),
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


def load_printed_cli_tools() -> tuple[list[dict], dict, dict]:
    """Load tool defs, executors, and per-CLI confirmation ceilings from every
    installed + enabled Printing Press CLI.

    Returns ``(tool_defs, executors, tool_modes)`` where ``tool_modes`` maps
    ``"pp:<slug>"`` → the CLI's tool mode (default ``"normal"``). Threading these
    modes everywhere is what keeps printed-CLI writes from defaulting to ``power``
    in ``_effective_mode`` (plan R4).
    """
    try:
        from integrations.printing_press import bridge, manifest as pp_manifest, store
    except Exception as e:
        logger.warning("Printing Press unavailable: %s", e)
        return [], {}, {}

    commands = []
    tool_modes: dict = {}
    try:
        installs = store.list_installed()
    except Exception as e:
        logger.warning("Failed to list printed CLIs: %s", e)
        return [], {}, {}

    for inst in installs:
        if not (inst.enabled and inst.build_status == store.BUILD_READY):
            continue
        manifest = store.get_manifest(inst.slug)
        if not manifest:
            continue
        try:
            commands.extend(pp_manifest.build_commands(inst.slug, manifest))
        except Exception as e:
            logger.warning("Failed to build tools for printed CLI %s: %s", inst.slug, e)
            continue
        # Per-CLI ceilings are needed even on the bridge path: the cli_call write
        # gate resolves to a slug and looks its mode up here.
        tool_modes[pp_manifest.integration_id(inst.slug)] = inst.tool_mode

    # Collapse to the bridge (cli_search/describe/call) above the token budget,
    # else emit flat per-command tools.
    tool_defs, executors = bridge.build_printed_surface(commands)
    return tool_defs, executors, tool_modes


class DynamicTools(NamedTuple):
    """Everything a ToolRegistry construction site needs from dynamic sources."""
    tool_defs: list[dict]           # integration defs + printed-CLI defs (kind-tagged)
    integration_executors: dict     # name → callable (kind="integration")
    printed_executors: dict         # name → callable (kind="printed_cli")
    printed_tool_modes: dict        # "pp:<slug>" → confirmation ceiling


def load_all_dynamic_tools() -> DynamicTools:
    """Single entry point for all dynamically-loaded tools — integrations *and*
    installed Printing Press CLIs.

    Every ToolRegistry construction site routes through here so the two sources
    stay in lockstep across chat, scheduled actions, heartbeat, Telegram,
    WhatsApp, Paperclip, and the CLI harness (plan R2).
    """
    integ_defs, integ_execs = load_integration_tools()
    pp_defs, pp_execs, pp_modes = load_printed_cli_tools()
    return DynamicTools(
        tool_defs=integ_defs + pp_defs,
        integration_executors=integ_execs,
        printed_executors=pp_execs,
        printed_tool_modes=pp_modes,
    )


def filter_no_confirm_writes(tool_defs: list[dict], modes: dict) -> list[dict]:
    """Drop write tools that must not auto-run in a no-confirm (background) context.

    Background turns (scheduled actions, heartbeat) have no approval UI. Existing
    integrations keep their behavior — only a ``read-only`` ceiling strips their
    writes. **Printed CLIs** (``integration`` id ``"pp:<slug>"``) are less-trusted
    external binaries, so their writes are blocked unless the CLI is explicitly set
    to ``power`` — that opt-in is the per-CLI auto-run allowlist (plan R4). This
    never strips context/memory tools.
    """
    def blocked(t: dict) -> bool:
        if not t.get("writes") or t.get("context_memory"):
            return False
        integ = t.get("integration", "")
        if not integ:
            return False
        if integ.startswith("pp:"):
            # Printed writes auto-run only with an explicit "power" opt-in; a missing
            # mode fails closed (block).
            return modes.get(integ, "normal") != "power"
        return modes.get(integ, "power") == "read-only"

    return [t for t in tool_defs if not blocked(t)]


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
