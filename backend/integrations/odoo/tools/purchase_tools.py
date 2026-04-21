"""Chatty -- Odoo Purchase Order tools."""

import logging

from ..helpers import safe_get_client

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

PURCHASE_TOOL_DEFS = [
    # 1 - odoo_search_purchase_orders
    {
        "name": "odoo_search_purchase_orders",
        "description": (
            "Search purchase orders by PO number, vendor name, or state. "
            "Returns a list of matching POs with key details."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "po_number": {
                    "type": "string",
                    "description": "PO number to search for (partial match)",
                },
                "vendor": {
                    "type": "string",
                    "description": "Vendor name to filter by (partial match)",
                },
                "state": {
                    "type": "string",
                    "description": (
                        "PO state filter (e.g. draft, sent, purchase, done, cancel)"
                    ),
                },
                "limit": {
                    "type": "integer",
                    "description": "Max records to return (default 20)",
                    "default": 20,
                },
            },
            "required": [],
        },
        "kind": "integration",
    },
    # 2 - odoo_get_purchase_order_details
    {
        "name": "odoo_get_purchase_order_details",
        "description": (
            "Get full details of a single purchase order including all line items."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "po_id": {
                    "type": "integer",
                    "description": "Purchase order record ID",
                },
            },
            "required": ["po_id"],
        },
        "kind": "integration",
    },
    # 3 - odoo_create_purchase_order
    {
        "name": "odoo_create_purchase_order",
        "description": (
            "Create a new draft purchase order with line items. "
            "Returns the created PO details."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "partner_id": {
                    "type": "integer",
                    "description": "Vendor (res.partner) ID",
                },
                "lines": {
                    "type": "array",
                    "description": "Order lines to add",
                    "items": {
                        "type": "object",
                        "properties": {
                            "product_id": {
                                "type": "integer",
                                "description": "Product ID",
                            },
                            "product_qty": {
                                "type": "number",
                                "description": "Quantity to order",
                            },
                            "price_unit": {
                                "type": "number",
                                "description": "Unit price (optional, uses product default if omitted)",
                            },
                            "name": {
                                "type": "string",
                                "description": "Line description (optional, uses product name if omitted)",
                            },
                        },
                        "required": ["product_id", "product_qty"],
                    },
                },
            },
            "required": ["partner_id", "lines"],
        },
        "kind": "integration",
        "writes": True,
    },
    # 4 - odoo_confirm_purchase_order
    {
        "name": "odoo_confirm_purchase_order",
        "description": (
            "Confirm a draft purchase order, changing its state from draft to purchase."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "po_id": {
                    "type": "integer",
                    "description": "Purchase order record ID to confirm",
                },
            },
            "required": ["po_id"],
        },
        "kind": "integration",
        "writes": True,
    },
    # 5 - odoo_approve_purchase_order
    {
        "name": "odoo_approve_purchase_order",
        "description": "Approve a confirmed purchase order.",
        "input_schema": {
            "type": "object",
            "properties": {
                "po_id": {
                    "type": "integer",
                    "description": "Purchase order record ID to approve",
                },
            },
            "required": ["po_id"],
        },
        "kind": "integration",
        "writes": True,
    },
    # 6 - odoo_update_purchase_order
    {
        "name": "odoo_update_purchase_order",
        "description": (
            "Update fields on a draft purchase order. "
            "Only draft POs can be updated."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "po_id": {
                    "type": "integer",
                    "description": "Purchase order record ID to update",
                },
                "date_planned": {
                    "type": "string",
                    "description": "New planned receipt date (YYYY-MM-DD or YYYY-MM-DD HH:MM:SS)",
                },
                "notes": {
                    "type": "string",
                    "description": "Internal notes to set on the PO",
                },
            },
            "required": ["po_id"],
        },
        "kind": "integration",
        "writes": True,
    },
    # 7 - odoo_post_purchase_message
    {
        "name": "odoo_post_purchase_message",
        "description": (
            "Post a chatter message on a purchase order. "
            "Use for internal notes or vendor-visible comments."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "po_id": {
                    "type": "integer",
                    "description": "Purchase order record ID",
                },
                "message": {
                    "type": "string",
                    "description": "Message body (plain text or HTML)",
                },
                "partner_ids": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "Partner IDs to notify (omit for internal note)",
                },
            },
            "required": ["po_id", "message"],
        },
        "kind": "integration",
        "writes": True,
    },
]

# ---------------------------------------------------------------------------
# Executor functions
# ---------------------------------------------------------------------------


def _odoo_search_purchase_orders(
    po_number: str = None, vendor: str = None, state: str = None, limit: int = 20,
) -> dict:
    """Search purchase orders by PO number, vendor, or state."""
    client, err = safe_get_client()
    if err:
        return err

    domain = []
    if po_number:
        domain.append(["name", "ilike", po_number])
    if vendor:
        domain.append(["partner_id.name", "ilike", vendor])
    if state:
        domain.append(["state", "=", state])

    fields = ["name", "partner_id", "date_order", "amount_total", "state", "date_planned"]
    records = client.search_read("purchase.order", domain, fields, limit=limit) or []

    orders = []
    for r in records:
        orders.append({
            "id": r.get("id"),
            "po_number": r.get("name", ""),
            "vendor": r["partner_id"][1] if isinstance(r.get("partner_id"), list) else None,
            "order_date": r.get("date_order", ""),
            "planned_date": r.get("date_planned", ""),
            "total": r.get("amount_total", 0),
            "state": r.get("state", ""),
        })
    return {"orders": orders, "total": len(orders)}


def _odoo_get_purchase_order_details(po_id: int) -> dict:
    """Get full details of a single purchase order with line items."""
    client, err = safe_get_client()
    if err:
        return err

    pos = client.search_read(
        "purchase.order",
        [("id", "=", po_id)],
        [
            "name", "partner_id", "date_order", "date_planned",
            "amount_total", "amount_untaxed", "state", "notes",
            "currency_id", "order_line",
        ],
    )
    if not pos:
        return {"error": f"Purchase order #{po_id} not found"}
    po = pos[0]

    # Batch-fetch order lines
    line_ids = po.get("order_line", [])
    lines = []
    if line_ids:
        raw_lines = client.search_read(
            "purchase.order.line",
            [("id", "in", line_ids)],
            [
                "product_id", "name", "product_qty", "product_uom",
                "price_unit", "price_subtotal", "qty_received", "qty_invoiced",
            ],
        )
        for ln in (raw_lines or []):
            lines.append({
                "id": ln.get("id"),
                "product": ln["product_id"][1] if isinstance(ln.get("product_id"), list) else None,
                "product_id": ln["product_id"][0] if isinstance(ln.get("product_id"), list) else ln.get("product_id"),
                "description": ln.get("name", ""),
                "qty": ln.get("product_qty", 0),
                "uom": ln["product_uom"][1] if isinstance(ln.get("product_uom"), list) else "",
                "price_unit": ln.get("price_unit", 0),
                "subtotal": ln.get("price_subtotal", 0),
                "qty_received": ln.get("qty_received", 0),
                "qty_invoiced": ln.get("qty_invoiced", 0),
            })

    return {
        "id": po.get("id"),
        "po_number": po.get("name", ""),
        "vendor": po["partner_id"][1] if isinstance(po.get("partner_id"), list) else None,
        "vendor_id": po["partner_id"][0] if isinstance(po.get("partner_id"), list) else None,
        "order_date": po.get("date_order", ""),
        "planned_date": po.get("date_planned", ""),
        "amount_untaxed": po.get("amount_untaxed", 0),
        "amount_total": po.get("amount_total", 0),
        "state": po.get("state", ""),
        "notes": po.get("notes", ""),
        "currency": po["currency_id"][1] if isinstance(po.get("currency_id"), list) else "",
        "lines": lines,
    }


def _odoo_create_purchase_order(partner_id: int, lines: list[dict]) -> dict:
    """Create a new draft purchase order with line items."""
    client, err = safe_get_client()
    if err:
        return err

    if not lines:
        return {"error": "At least one order line is required"}

    # Create the PO header
    try:
        po_id = client.create("purchase.order", {"partner_id": partner_id})
    except Exception as e:
        return {"error": f"Odoo error creating purchase order: {e}"}

    if po_id is None:
        return {"error": "Failed to create purchase order in Odoo"}

    # Create each order line
    for line in lines:
        line_vals = {
            "order_id": po_id,
            "product_id": line["product_id"],
            "product_qty": line["product_qty"],
        }
        if "price_unit" in line and line["price_unit"] is not None:
            line_vals["price_unit"] = line["price_unit"]
        if "name" in line and line["name"]:
            line_vals["name"] = line["name"]
        try:
            client.create("purchase.order.line", line_vals)
        except Exception as e:
            logger.error("Failed to create PO line on PO #%d: %s", po_id, e)
            return {"error": f"PO #{po_id} created but failed adding line: {e}"}

    # Read back the created PO
    pos = client.search_read(
        "purchase.order",
        [("id", "=", po_id)],
        ["name", "partner_id", "state", "amount_total", "date_planned"],
    )
    po = pos[0] if pos else {}
    return {
        "ok": True,
        "id": po_id,
        "po_number": po.get("name", ""),
        "vendor": po["partner_id"][1] if isinstance(po.get("partner_id"), list) else "",
        "state": po.get("state", "draft"),
        "amount_total": po.get("amount_total", 0),
        "planned_date": po.get("date_planned", ""),
    }


def _odoo_confirm_purchase_order(po_id: int) -> dict:
    """Confirm a draft purchase order (draft -> purchase)."""
    client, err = safe_get_client()
    if err:
        return err

    # Check current state
    pos = client.search_read(
        "purchase.order",
        [("id", "=", po_id)],
        ["name", "state"],
    )
    if not pos:
        return {"error": f"Purchase order #{po_id} not found"}
    po = pos[0]
    if po["state"] != "draft":
        return {
            "error": (
                f"PO '{po['name']}' is in state '{po['state']}' -- "
                "only draft POs can be confirmed"
            ),
        }

    try:
        client.execute("purchase.order", "button_confirm", [po_id])
    except Exception as e:
        return {"error": f"Odoo error confirming PO '{po['name']}': {e}"}

    return {"ok": True, "po_number": po["name"], "state": "purchase"}


def _odoo_approve_purchase_order(po_id: int) -> dict:
    """Approve a confirmed purchase order."""
    client, err = safe_get_client()
    if err:
        return err

    pos = client.search_read(
        "purchase.order",
        [("id", "=", po_id)],
        ["name", "state"],
    )
    if not pos:
        return {"error": f"Purchase order #{po_id} not found"}
    po = pos[0]

    try:
        client.execute("purchase.order", "button_approve", [po_id])
    except Exception as e:
        return {"error": f"Odoo error approving PO '{po['name']}': {e}"}

    return {"ok": True, "po_number": po["name"], "state": "approved"}


def _odoo_update_purchase_order(
    po_id: int, date_planned: str = None, notes: str = None,
) -> dict:
    """Update fields on a draft purchase order."""
    client, err = safe_get_client()
    if err:
        return err

    # Verify PO exists and is in draft
    pos = client.search_read(
        "purchase.order",
        [("id", "=", po_id)],
        ["name", "state"],
    )
    if not pos:
        return {"error": f"Purchase order #{po_id} not found"}
    po = pos[0]
    if po["state"] != "draft":
        return {
            "error": (
                f"PO '{po['name']}' is in state '{po['state']}' -- "
                "only draft POs can be updated"
            ),
        }

    vals: dict = {}
    if date_planned is not None:
        vals["date_planned"] = date_planned
    if notes is not None:
        vals["notes"] = notes
    if not vals:
        return {"error": "Nothing to update -- provide date_planned or notes"}

    try:
        client.write("purchase.order", [po_id], vals)
    except Exception as e:
        return {"error": f"Odoo error updating PO '{po['name']}': {e}"}

    return {"ok": True, "po_number": po["name"], "updated": vals}


def _odoo_post_purchase_message(
    po_id: int, message: str, partner_ids: list[int] = None,
) -> dict:
    """Post a chatter message on a purchase order."""
    client, err = safe_get_client()
    if err:
        return err

    if not message:
        return {"error": "Message body is required"}

    # Verify PO exists
    pos = client.search_read(
        "purchase.order",
        [("id", "=", po_id)],
        ["name"],
    )
    if not pos:
        return {"error": f"Purchase order #{po_id} not found"}
    po = pos[0]

    subtype = "mail.mt_comment" if partner_ids else "mail.mt_note"
    kwargs: dict = {
        "body": message,
        "message_type": "comment",
        "subtype_xmlid": subtype,
    }
    if partner_ids:
        kwargs["partner_ids"] = partner_ids

    try:
        result = client.execute("purchase.order", "message_post", [po_id], **kwargs)
    except Exception as e:
        return {"error": f"Odoo error posting message on PO '{po['name']}': {e}"}

    return {"ok": True, "po_number": po["name"], "message_id": result}


# ---------------------------------------------------------------------------
# Executor map
# ---------------------------------------------------------------------------

PURCHASE_EXECUTORS = {
    "odoo_search_purchase_orders": lambda **kw: _odoo_search_purchase_orders(**kw),
    "odoo_get_purchase_order_details": lambda **kw: _odoo_get_purchase_order_details(**kw),
    "odoo_create_purchase_order": lambda **kw: _odoo_create_purchase_order(**kw),
    "odoo_confirm_purchase_order": lambda **kw: _odoo_confirm_purchase_order(**kw),
    "odoo_approve_purchase_order": lambda **kw: _odoo_approve_purchase_order(**kw),
    "odoo_update_purchase_order": lambda **kw: _odoo_update_purchase_order(**kw),
    "odoo_post_purchase_message": lambda **kw: _odoo_post_purchase_message(**kw),
}
