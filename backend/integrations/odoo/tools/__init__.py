"""Chatty — Odoo tool aggregator.

Collects tool definitions and executors from all category modules.
Exports ODOO_TOOL_DEFS and TOOL_EXECUTORS for the integration loader.
"""

from .core_tools import CORE_TOOL_DEFS, CORE_EXECUTORS
from .crm_tools import CRM_TOOL_DEFS, CRM_EXECUTORS
from .helpdesk_tools import HELPDESK_TOOL_DEFS, HELPDESK_EXECUTORS
from .purchase_tools import PURCHASE_TOOL_DEFS, PURCHASE_EXECUTORS
from .contacts_tools import CONTACTS_TOOL_DEFS, CONTACTS_EXECUTORS
from .project_tools import PROJECT_TOOL_DEFS, PROJECT_EXECUTORS
from .accounting_tools import ACCOUNTING_TOOL_DEFS, ACCOUNTING_EXECUTORS
from .quality_tools import QUALITY_TOOL_DEFS, QUALITY_EXECUTORS
from .maintenance_tools import MAINTENANCE_TOOL_DEFS, MAINTENANCE_EXECUTORS

ODOO_TOOL_DEFS = (
    CORE_TOOL_DEFS
    + CRM_TOOL_DEFS
    + HELPDESK_TOOL_DEFS
    + PURCHASE_TOOL_DEFS
    + CONTACTS_TOOL_DEFS
    + PROJECT_TOOL_DEFS
    + ACCOUNTING_TOOL_DEFS
    + QUALITY_TOOL_DEFS
    + MAINTENANCE_TOOL_DEFS
)

TOOL_EXECUTORS = {
    **CORE_EXECUTORS,
    **CRM_EXECUTORS,
    **HELPDESK_EXECUTORS,
    **PURCHASE_EXECUTORS,
    **CONTACTS_EXECUTORS,
    **PROJECT_EXECUTORS,
    **ACCOUNTING_EXECUTORS,
    **QUALITY_EXECUTORS,
    **MAINTENANCE_EXECUTORS,
}
