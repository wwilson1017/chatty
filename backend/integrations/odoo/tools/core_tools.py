"""
Chatty -- Odoo core agent tools.

14 tools covering generic CRUD, sales, manufacturing, inventory, HR, products,
and messaging.  Each executor calls safe_get_client() internally so the agent
engine never has to manage Odoo connections.
"""

import logging

from ..helpers import safe_get_client, flatten_m2o
from ..constants import ALLOWED_MODELS, ALLOWED_METHODS, ALLOWED_ACTION_METHODS

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

CORE_TOOL_DEFS = [
    # 1 - odoo_search
    {
        "name": "odoo_search",
        "description": (
            "Search Odoo records with domain filtering. "
            "Use this to find customers, products, invoices, POs, etc."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "model": {
                    "type": "string",
                    "description": "Odoo model (e.g. res.partner, product.product, account.move)",
                },
                "domain": {
                    "type": "array",
                    "description": "Odoo domain filter (list of [field, op, value] tuples)",
                    "items": {"type": "array", "items": {}},
                    "default": [],
                },
                "fields": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Fields to return",
                    "default": [],
                },
                "limit": {
                    "type": "integer",
                    "description": "Max records (default 20)",
                    "default": 20,
                },
            },
            "required": ["model"],
        },
        "kind": "integration",
    },
    # 2 - odoo_read
    {
        "name": "odoo_read",
        "description": "Read specific Odoo records by ID.",
        "input_schema": {
            "type": "object",
            "properties": {
                "model": {
                    "type": "string",
                    "description": "Odoo model",
                },
                "ids": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "Record IDs to read",
                },
                "fields": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Fields to return",
                    "default": [],
                },
            },
            "required": ["model", "ids"],
        },
        "kind": "integration",
    },
    # 3 - odoo_query
    {
        "name": "odoo_query",
        "description": (
            "Generic search_read on any allowed Odoo model. "
            "Returns records with Many2one fields flattened to display names."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "model": {
                    "type": "string",
                    "description": "Odoo model to query",
                },
                "domain": {
                    "type": "array",
                    "description": "Odoo domain filter",
                    "items": {"type": "array", "items": {}},
                    "default": [],
                },
                "fields": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Fields to return",
                    "default": [],
                },
                "limit": {
                    "type": "integer",
                    "description": "Max records (1-500, default 100)",
                    "default": 100,
                },
            },
            "required": ["model"],
        },
        "kind": "integration",
    },
    # 4 - odoo_search_orders
    {
        "name": "odoo_search_orders",
        "description": (
            "Search sale orders by date range and state. "
            "Returns orders with their line items batch-fetched."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "date_from": {
                    "type": "string",
                    "description": "Start date (YYYY-MM-DD)",
                },
                "date_to": {
                    "type": "string",
                    "description": "End date (YYYY-MM-DD)",
                },
                "state": {
                    "type": "string",
                    "description": "Order state filter (default 'sale', or 'all' for sale+done)",
                    "default": "sale",
                },
            },
            "required": ["date_from", "date_to"],
        },
        "kind": "integration",
    },
    # 5 - odoo_get_manufacturing_orders
    {
        "name": "odoo_get_manufacturing_orders",
        "description": (
            "Get manufacturing orders filtered by date and/or state. "
            "Defaults to confirmed, progress, and ready states."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "date_from": {
                    "type": "string",
                    "description": "Earliest start date (YYYY-MM-DD), optional",
                },
                "state": {
                    "type": "string",
                    "description": (
                        "MO state filter (e.g. draft, confirmed, progress, ready, done, cancel). "
                        "Omit for default: confirmed + progress + ready."
                    ),
                },
            },
            "required": [],
        },
        "kind": "integration",
    },
    # 6 - odoo_get_stock_levels
    {
        "name": "odoo_get_stock_levels",
        "description": (
            "Get current inventory stock levels from internal locations. "
            "Aggregates quantities by product with product codes."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "product_ids": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "Optional list of product IDs to filter by",
                },
            },
            "required": [],
        },
        "kind": "integration",
    },
    # 7 - odoo_get_employees
    {
        "name": "odoo_get_employees",
        "description": "Get employee list, optionally filtered by department name.",
        "input_schema": {
            "type": "object",
            "properties": {
                "department": {
                    "type": "string",
                    "description": "Department name to filter by (case-insensitive partial match)",
                },
            },
            "required": [],
        },
        "kind": "integration",
    },
    # 8 - odoo_get_products
    {
        "name": "odoo_get_products",
        "description": "Get product catalog, optionally filtered by category name.",
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": "Product category name to filter by (case-insensitive partial match)",
                },
            },
            "required": [],
        },
        "kind": "integration",
    },
    # 9 - odoo_create_manufacturing_order
    {
        "name": "odoo_create_manufacturing_order",
        "description": "Create a new manufacturing order in Odoo. Returns the created MO details.",
        "input_schema": {
            "type": "object",
            "properties": {
                "product_id": {
                    "type": "integer",
                    "description": "Product ID to manufacture",
                },
                "qty": {
                    "type": "number",
                    "description": "Quantity to produce",
                },
                "date_start": {
                    "type": "string",
                    "description": "Planned start date (YYYY-MM-DD HH:MM:SS), optional",
                },
                "bom_id": {
                    "type": "integer",
                    "description": "Bill of Materials ID, optional (Odoo auto-selects if omitted)",
                },
                "origin": {
                    "type": "string",
                    "description": "Source document reference, optional",
                },
            },
            "required": ["product_id", "qty"],
        },
        "kind": "integration",
    },
    # 10 - odoo_update_manufacturing_order
    {
        "name": "odoo_update_manufacturing_order",
        "description": (
            "Update a manufacturing order by its name (e.g. MO/00042). "
            "Cannot update done or cancelled MOs."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "mo_name": {
                    "type": "string",
                    "description": "Manufacturing order name (e.g. MO/00042)",
                },
                "qty": {
                    "type": "number",
                    "description": "New quantity to produce",
                },
                "date_start": {
                    "type": "string",
                    "description": "New planned start date (YYYY-MM-DD HH:MM:SS)",
                },
            },
            "required": ["mo_name"],
        },
        "kind": "integration",
    },
    # 11 - odoo_confirm_manufacturing_order
    {
        "name": "odoo_confirm_manufacturing_order",
        "description": "Confirm a draft manufacturing order, changing its state from draft to confirmed.",
        "input_schema": {
            "type": "object",
            "properties": {
                "mo_name": {
                    "type": "string",
                    "description": "Manufacturing order name (e.g. MO/00042)",
                },
            },
            "required": ["mo_name"],
        },
        "kind": "integration",
    },
    # 12 - odoo_update_record
    {
        "name": "odoo_update_record",
        "description": (
            "Update field values on any whitelisted Odoo record. "
            "For manufacturing orders, prefer the dedicated MO update tools."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "model": {
                    "type": "string",
                    "description": "Odoo model (must be in allowed list)",
                },
                "record_id": {
                    "type": "integer",
                    "description": "Record ID to update",
                },
                "field_values": {
                    "type": "object",
                    "description": "Dict of field names to new values",
                },
            },
            "required": ["model", "record_id", "field_values"],
        },
        "kind": "integration",
    },
    # 13 - odoo_execute_action
    {
        "name": "odoo_execute_action",
        "description": (
            "Execute a button/action method on an Odoo record "
            "(e.g. action_confirm, action_done, action_cancel)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "model": {
                    "type": "string",
                    "description": "Odoo model (must be in allowed list)",
                },
                "record_id": {
                    "type": "integer",
                    "description": "Record ID to act on",
                },
                "action": {
                    "type": "string",
                    "description": (
                        "Action method to call (e.g. action_confirm, action_done, "
                        "action_cancel, button_confirm, action_approve)"
                    ),
                },
            },
            "required": ["model", "record_id", "action"],
        },
        "kind": "integration",
    },
    # 14 - odoo_post_message
    {
        "name": "odoo_post_message",
        "description": (
            "Post a chatter message or internal note on any Odoo record."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "model": {
                    "type": "string",
                    "description": "Odoo model (must be in allowed list)",
                },
                "record_id": {
                    "type": "integer",
                    "description": "Record ID to post the message on",
                },
                "body": {
                    "type": "string",
                    "description": "Message body (plain text or HTML)",
                },
                "partner_ids": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "Partner IDs to notify, optional",
                },
                "subtype_xmlid": {
                    "type": "string",
                    "description": "Message subtype (default mail.mt_note for internal note, use mail.mt_comment for notification)",
                    "default": "mail.mt_note",
                },
            },
            "required": ["model", "record_id", "body"],
        },
        "kind": "integration",
    },
]

# ---------------------------------------------------------------------------
# Executor functions
# ---------------------------------------------------------------------------


def _odoo_search(model: str, domain=None, fields=None, limit: int = 20) -> dict:
    """Search Odoo records with domain filtering."""
    if model not in ALLOWED_MODELS:
        return {"error": f"Model not allowed: {model}. Allowed: {', '.join(sorted(ALLOWED_MODELS))}"}
    client, err = safe_get_client()
    if err:
        return err
    records = client.search_read(model, domain or [], fields or [], limit=limit)
    return {"records": records, "count": len(records)}


def _odoo_read(model: str, ids: list[int], fields=None) -> dict:
    """Read specific Odoo records by ID."""
    if model not in ALLOWED_MODELS:
        return {"error": f"Model not allowed: {model}"}
    client, err = safe_get_client()
    if err:
        return err
    records = client.read(model, ids, fields or [])
    return {"records": records}


def _odoo_query(model: str, domain=None, fields=None, limit: int = 100) -> dict:
    """Generic search_read with M2O flattening."""
    if model not in ALLOWED_MODELS:
        return {"error": f"Model '{model}' is not allowed. Allowed: {', '.join(sorted(ALLOWED_MODELS))}"}
    client, err = safe_get_client()
    if err:
        return err
    domain = domain or []
    fields = fields or []
    limit = max(1, min(500, limit))
    records = client.search_read(model=model, domain=domain, fields=fields, limit=limit)
    if records is None:
        return {"error": f"Failed to query model '{model}'. It may not exist or you lack access."}
    cleaned = [flatten_m2o(rec) for rec in records]
    return {"model": model, "records": cleaned, "total": len(cleaned)}


def _odoo_search_orders(date_from: str, date_to: str, state: str = "sale") -> dict:
    """Search sale orders by date range with order lines batch-fetched."""
    client, err = safe_get_client()
    if err:
        return err
    states = [state] if state != "all" else ["sale", "done"]
    orders = client.search_read(
        model="sale.order",
        domain=[
            ("state", "in", states),
            ("commitment_date", ">=", f"{date_from} 00:00:00"),
            ("commitment_date", "<=", f"{date_to} 23:59:59"),
        ],
        fields=["name", "partner_id", "commitment_date", "state", "order_line"],
    )
    if orders is None:
        return {"orders": [], "total": 0, "error": "Failed to fetch orders from Odoo"}

    # Batch-fetch all order lines
    all_line_ids = []
    for so in orders:
        all_line_ids.extend(so.get("order_line", []))

    lines_by_order: dict[int, list] = {}
    if all_line_ids:
        lines = client.search_read(
            model="sale.order.line",
            domain=[("id", "in", all_line_ids)],
            fields=["order_id", "product_id", "product_uom_qty", "name"],
        )
        if lines:
            for line in lines:
                oid = line["order_id"][0] if isinstance(line["order_id"], list) else line["order_id"]
                lines_by_order.setdefault(oid, []).append({
                    "product": line["product_id"][1] if isinstance(line["product_id"], list) else str(line["product_id"]),
                    "product_id": line["product_id"][0] if isinstance(line["product_id"], list) else line["product_id"],
                    "qty": line.get("product_uom_qty", 0),
                    "description": line.get("name", ""),
                })

    result = []
    for so in orders:
        result.append({
            "name": so["name"],
            "partner": so["partner_id"][1] if isinstance(so["partner_id"], list) else str(so["partner_id"]),
            "commitment_date": so.get("commitment_date", ""),
            "state": so["state"],
            "lines": lines_by_order.get(so["id"], []),
        })
    return {"orders": result, "total": len(result)}


def _odoo_get_manufacturing_orders(date_from: str = None, state: str = None) -> dict:
    """Get manufacturing orders filtered by date and/or state."""
    client, err = safe_get_client()
    if err:
        return err
    domain = []
    if state:
        domain.append(("state", "=", state))
    else:
        domain.append(("state", "in", ["confirmed", "progress", "ready"]))
    if date_from:
        domain.append(("date_start", ">=", f"{date_from} 00:00:00"))

    mos = client.search_read(
        model="mrp.production",
        domain=domain,
        fields=["name", "product_id", "product_qty", "product_uom_id", "state", "date_start", "date_finished"],
    )
    if mos is None:
        return {"orders": [], "error": "Failed to fetch manufacturing orders from Odoo"}

    result = []
    for mo in mos:
        uom = ""
        if isinstance(mo.get("product_uom_id"), list) and len(mo["product_uom_id"]) > 1:
            uom = mo["product_uom_id"][1]
        result.append({
            "name": mo["name"],
            "product": mo["product_id"][1] if isinstance(mo["product_id"], list) else str(mo["product_id"]),
            "qty": mo.get("product_qty", 0),
            "uom": uom,
            "state": mo["state"],
            "date_start": mo.get("date_start", ""),
            "date_finished": mo.get("date_finished", ""),
        })
    return {"orders": result, "total": len(result)}


def _odoo_get_stock_levels(product_ids: list[int] = None) -> dict:
    """Get inventory stock levels from internal locations."""
    client, err = safe_get_client()
    if err:
        return err
    domain = [("location_id.usage", "=", "internal")]
    if product_ids:
        domain.append(("product_id", "in", product_ids))

    quants = client.search_read(
        model="stock.quant",
        domain=domain,
        fields=["product_id", "quantity"],
    )
    if quants is None:
        return {"stock": [], "error": "Failed to fetch stock from Odoo"}

    # Fetch product codes for all referenced products
    pids = list({q["product_id"][0] for q in quants if isinstance(q.get("product_id"), list)})
    code_map: dict[int, dict] = {}
    if pids:
        products = client.search_read(
            model="product.product",
            domain=[("id", "in", pids)],
            fields=["id", "default_code", "name"],
        )
        if products:
            code_map = {
                p["id"]: {"code": (p.get("default_code") or "").strip(), "name": p.get("name", "")}
                for p in products
            }

    # Aggregate quantities by product
    aggregated: dict[int, dict] = {}
    for q in quants:
        pid = q["product_id"][0] if isinstance(q.get("product_id"), list) else None
        if not pid:
            continue
        if pid not in aggregated:
            info = code_map.get(pid, {"code": "", "name": ""})
            aggregated[pid] = {"product_id": pid, "code": info["code"], "name": info["name"], "qty": 0}
        aggregated[pid]["qty"] += q.get("quantity") or 0

    stock = sorted(aggregated.values(), key=lambda x: x["code"])
    return {"stock": stock, "total": len(stock)}


def _odoo_get_employees(department: str = None) -> dict:
    """Get employees, optionally filtered by department."""
    client, err = safe_get_client()
    if err:
        return err
    domain = [("active", "=", True)]
    if department:
        domain.append(("department_id.name", "ilike", department))

    employees = client.search_read(
        model="hr.employee",
        domain=domain,
        fields=["name", "job_title", "department_id", "work_email"],
    )
    if employees is None:
        return {"employees": [], "error": "Failed to fetch employees from Odoo"}

    result = []
    for emp in employees:
        result.append({
            "name": emp["name"],
            "job_title": emp.get("job_title", ""),
            "department": emp["department_id"][1] if isinstance(emp.get("department_id"), list) else "",
            "email": emp.get("work_email", ""),
        })
    return {"employees": result, "total": len(result)}


def _odoo_get_products(category: str = None) -> dict:
    """Get product catalog, optionally filtered by category."""
    client, err = safe_get_client()
    if err:
        return err
    domain = [("active", "=", True), ("sale_ok", "=", True)]
    if category:
        domain.append(("categ_id.name", "ilike", category))

    products = client.search_read(
        model="product.product",
        domain=domain,
        fields=["name", "default_code", "categ_id", "list_price", "qty_available"],
    )
    if products is None:
        return {"products": [], "error": "Failed to fetch products from Odoo"}

    result = []
    for p in products:
        result.append({
            "name": p["name"],
            "code": (p.get("default_code") or "").strip(),
            "category": p["categ_id"][1] if isinstance(p.get("categ_id"), list) else "",
            "price": p.get("list_price", 0),
            "qty_available": p.get("qty_available", 0),
        })
    return {"products": result, "total": len(result)}


def _odoo_create_manufacturing_order(
    product_id: int, qty: float, date_start: str = None, bom_id: int = None, origin: str = None,
) -> dict:
    """Create a new manufacturing order."""
    client, err = safe_get_client()
    if err:
        return err
    vals: dict = {"product_id": product_id, "product_qty": qty}
    if date_start:
        vals["date_start"] = date_start
    if bom_id is not None:
        vals["bom_id"] = bom_id
    if origin:
        vals["origin"] = origin

    try:
        mo_id = client.create("mrp.production", vals)
    except Exception as e:
        return {"error": f"Odoo error creating MO: {e}"}

    if mo_id is None:
        return {"error": "Failed to create manufacturing order in Odoo"}

    # Read back created MO
    mos = client.search_read(
        model="mrp.production",
        domain=[("id", "=", mo_id)],
        fields=["name", "product_id", "product_qty", "state", "date_start"],
    )
    mo = mos[0] if mos else {}
    return {
        "ok": True,
        "id": mo_id,
        "name": mo.get("name", ""),
        "product": mo["product_id"][1] if isinstance(mo.get("product_id"), list) else "",
        "qty": mo.get("product_qty", qty),
        "state": mo.get("state", "draft"),
        "date_start": mo.get("date_start", ""),
    }


def _odoo_update_manufacturing_order(mo_name: str, qty: float = None, date_start: str = None) -> dict:
    """Update a manufacturing order by name."""
    client, err = safe_get_client()
    if err:
        return err
    mos = client.search_read(
        model="mrp.production",
        domain=[("name", "=", mo_name)],
        fields=["id", "name", "state"],
    )
    if not mos:
        return {"error": f"Manufacturing order '{mo_name}' not found"}
    mo = mos[0]
    if mo["state"] in ("done", "cancel"):
        return {"error": f"Cannot update MO '{mo_name}' -- it is already {mo['state']}"}

    vals: dict = {}
    if qty is not None:
        vals["product_qty"] = qty
    if date_start is not None:
        vals["date_start"] = date_start
    if not vals:
        return {"error": "Nothing to update -- provide qty or date_start"}

    try:
        client.write("mrp.production", [mo["id"]], vals)
    except Exception as e:
        return {"error": f"Odoo error updating MO '{mo_name}': {e}"}
    return {"ok": True, "name": mo_name, "updated": vals}


def _odoo_confirm_manufacturing_order(mo_name: str) -> dict:
    """Confirm a draft manufacturing order."""
    client, err = safe_get_client()
    if err:
        return err
    mos = client.search_read(
        model="mrp.production",
        domain=[("name", "=", mo_name)],
        fields=["id", "name", "state"],
    )
    if not mos:
        return {"error": f"Manufacturing order '{mo_name}' not found"}
    mo = mos[0]
    if mo["state"] != "draft":
        return {"error": f"MO '{mo_name}' is already '{mo['state']}' -- only draft MOs can be confirmed"}

    try:
        result = client.execute("mrp.production", "action_confirm", [mo["id"]])
    except Exception as e:
        return {"error": f"Odoo error confirming MO '{mo_name}': {e}"}
    if result is None:
        return {"error": f"Failed to confirm MO '{mo_name}'"}
    return {"ok": True, "name": mo_name, "state": "confirmed"}


def _odoo_update_record(model: str, record_id: int, field_values: dict) -> dict:
    """Generic field update on a whitelisted model."""
    if model not in ALLOWED_MODELS:
        return {"error": f"Model '{model}' is not allowed"}
    if not field_values:
        return {"error": "No field values provided"}
    client, err = safe_get_client()
    if err:
        return err
    try:
        result = client.execute(model, "write", [record_id], field_values)
    except Exception as e:
        return {"error": f"Odoo error updating {model} #{record_id}: {e}"}
    if not result:
        return {"error": f"Failed to update {model} #{record_id}"}
    return {"ok": True, "model": model, "id": record_id, "updated": field_values}


def _odoo_execute_action(model: str, record_id: int, action: str) -> dict:
    """Execute a button/action method on an Odoo record."""
    if model not in ALLOWED_MODELS:
        return {"error": f"Model '{model}' is not allowed"}
    if action not in ALLOWED_ACTION_METHODS:
        return {
            "error": (
                f"Action '{action}' is not allowed. "
                f"Allowed: {', '.join(sorted(ALLOWED_ACTION_METHODS))}. "
                "Use odoo_update_record for field updates, odoo_post_message for messages."
            ),
        }
    client, err = safe_get_client()
    if err:
        return err
    try:
        result = client.execute(model, action, [record_id])
    except Exception as e:
        return {"error": f"Odoo error executing {action} on {model} #{record_id}: {e}"}
    return {"ok": True, "model": model, "id": record_id, "action": action, "result": str(result)}


def _odoo_post_message(
    model: str, record_id: int, body: str, partner_ids: list[int] = None, subtype_xmlid: str = "mail.mt_note",
) -> dict:
    """Post a chatter message or internal note on an Odoo record."""
    if model not in ALLOWED_MODELS:
        return {"error": f"Model '{model}' is not allowed"}
    if not body:
        return {"error": "Message body is required"}
    client, err = safe_get_client()
    if err:
        return err
    kwargs: dict = {"body": body, "message_type": "comment", "subtype_xmlid": subtype_xmlid}
    if partner_ids:
        kwargs["partner_ids"] = partner_ids
    try:
        result = client.execute(model, "message_post", [record_id], **kwargs)
    except Exception as e:
        return {"error": f"Odoo error posting message on {model} #{record_id}: {e}"}
    return {"ok": True, "model": model, "id": record_id, "message_id": result}


# ---------------------------------------------------------------------------
# Executor map
# ---------------------------------------------------------------------------

CORE_EXECUTORS = {
    "odoo_search": lambda **kw: _odoo_search(**kw),
    "odoo_read": lambda **kw: _odoo_read(**kw),
    "odoo_query": lambda **kw: _odoo_query(**kw),
    "odoo_search_orders": lambda **kw: _odoo_search_orders(**kw),
    "odoo_get_manufacturing_orders": lambda **kw: _odoo_get_manufacturing_orders(**kw),
    "odoo_get_stock_levels": lambda **kw: _odoo_get_stock_levels(**kw),
    "odoo_get_employees": lambda **kw: _odoo_get_employees(**kw),
    "odoo_get_products": lambda **kw: _odoo_get_products(**kw),
    "odoo_create_manufacturing_order": lambda **kw: _odoo_create_manufacturing_order(**kw),
    "odoo_update_manufacturing_order": lambda **kw: _odoo_update_manufacturing_order(**kw),
    "odoo_confirm_manufacturing_order": lambda **kw: _odoo_confirm_manufacturing_order(**kw),
    "odoo_update_record": lambda **kw: _odoo_update_record(**kw),
    "odoo_execute_action": lambda **kw: _odoo_execute_action(**kw),
    "odoo_post_message": lambda **kw: _odoo_post_message(**kw),
}
