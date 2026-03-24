"""
Chatty — Odoo agent tools.

Provides search/read access to Odoo records for AI agents.
"""

import logging
from .client import get_client

logger = logging.getLogger(__name__)

ODOO_TOOL_DEFS = [
    {
        "name": "odoo_search",
        "description": "Search Odoo records. Use this to find customers, products, invoices, POs, etc.",
        "input_schema": {
            "type": "object",
            "properties": {
                "model": {"type": "string", "description": "Odoo model (e.g. res.partner, product.product, account.move)"},
                "domain": {"type": "array", "description": "Odoo domain filter (list of [field, op, value] tuples)", "default": []},
                "fields": {"type": "array", "items": {"type": "string"}, "description": "Fields to return", "default": []},
                "limit": {"type": "integer", "description": "Max records (default: 20)", "default": 20},
            },
            "required": ["model"],
        },
        "kind": "integration",
    },
    {
        "name": "odoo_read",
        "description": "Read specific Odoo records by ID.",
        "input_schema": {
            "type": "object",
            "properties": {
                "model": {"type": "string", "description": "Odoo model"},
                "ids": {"type": "array", "items": {"type": "integer"}, "description": "Record IDs"},
                "fields": {"type": "array", "items": {"type": "string"}, "description": "Fields to return", "default": []},
            },
            "required": ["model", "ids"],
        },
        "kind": "integration",
    },
]

ALLOWED_MODELS = {
    "res.partner", "product.product", "product.template",
    "sale.order", "purchase.order", "account.move",
    "stock.picking", "mrp.production", "project.project",
    "project.task", "hr.employee",
}


def odoo_search(model: str, domain=None, fields=None, limit: int = 20) -> dict:
    if model not in ALLOWED_MODELS:
        return {"error": f"Model not allowed: {model}. Allowed: {', '.join(sorted(ALLOWED_MODELS))}"}
    client = get_client()
    if not client:
        return {"error": "Odoo not configured or unavailable"}
    records = client.search_read(model, domain or [], fields or [], limit=limit)
    return {"records": records, "count": len(records)}


def odoo_read(model: str, ids: list[int], fields=None) -> dict:
    if model not in ALLOWED_MODELS:
        return {"error": f"Model not allowed: {model}"}
    client = get_client()
    if not client:
        return {"error": "Odoo not configured or unavailable"}
    records = client.read(model, ids, fields or [])
    return {"records": records}


TOOL_EXECUTORS = {
    "odoo_search": lambda **kw: odoo_search(**kw),
    "odoo_read": lambda **kw: odoo_read(**kw),
}
