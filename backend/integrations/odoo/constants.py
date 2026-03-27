"""Shared constants for Odoo tool safety enforcement.

ALLOWED_MODELS controls which Odoo models any tool may access.
ALLOWED_METHODS controls which Odoo execute methods the generic write tools may call.
"""

# Only these Odoo models may be accessed by agent tools.
ALLOWED_MODELS = {
    # Sales & Purchase
    "sale.order", "sale.order.line", "purchase.order", "purchase.order.line",
    # Manufacturing
    "mrp.production", "mrp.bom", "mrp.bom.line", "mrp.workcenter", "mrp.workorder",
    # PLM (Engineering Change Orders)
    "mrp.eco",
    # Inventory
    "stock.quant", "stock.move", "stock.picking", "stock.warehouse", "stock.location",
    "stock.lot",
    # Products
    "product.product", "product.template", "product.category", "product.supplierinfo",
    "uom.uom",
    # HR
    "hr.employee", "hr.department",
    # Contacts & Accounting
    "res.partner", "account.move", "account.move.line",
    "account.payment", "account.payment.term",
    # CRM
    "crm.lead", "crm.team", "crm.stage",
    # Calendar
    "calendar.event",
    # Project
    "project.project", "project.task", "project.task.type",
    "account.analytic.line",
    # Helpdesk
    "helpdesk.ticket", "helpdesk.stage", "helpdesk.team",
    # Maintenance
    "maintenance.request", "maintenance.equipment", "maintenance.equipment.category",
    "maintenance.stage", "maintenance.team",
    # Quality
    "quality.check", "quality.alert", "quality.point",
    "quality.check.wizard", "quality.reason",
    "quality.tag", "quality.team",
    # Messaging / Utilities
    "res.users", "mail.activity", "mail.message", "ir.model",
}

# Only these Odoo execute methods may be called by generic write tools.
# Notably excludes "unlink" (delete) for safety.
ALLOWED_METHODS = {
    "write", "create",
    "button_confirm", "action_confirm", "action_done",
    "action_draft", "action_cancel", "button_draft",
    "action_approve", "button_approve",
    "message_post",
}

# Subset for execute_odoo_action — button/action methods only.
# write, create, and message_post require structured arguments and have dedicated tools.
ALLOWED_ACTION_METHODS = ALLOWED_METHODS - {"write", "create", "message_post"}

# Quality check actions — separate because they use different method names.
QUALITY_ACTION_METHODS = {"do_pass", "do_fail"}
