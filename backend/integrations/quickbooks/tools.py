"""Chatty — QuickBooks Online agent tools.

Full suite of read + write tools for QBO entities.
Write tools are marked with "writes": True so the approval flow
intercepts them in normal mode.
"""

from .client import get_client

# ── Helpers ──────────────────────────────────────────────────────────────────

_ALLOWED_CREATE_TYPES = {
    "Customer", "Vendor", "Item", "Bill", "VendorCredit", "Purchase", "CreditMemo",
}
_ALLOWED_UPDATE_TYPES = {"Customer", "Vendor", "Item"}
_ALLOWED_GET_TYPES = {
    "Customer", "Vendor", "Item", "Invoice", "Estimate", "Payment",
    "Bill", "Purchase", "CreditMemo", "Account",
}


def _build_line_items(line_items: list[dict]) -> list[dict]:
    """Convert simplified line items into QBO Line array format.

    Accepts: [{description, amount, quantity?, item_id?, rate?}, ...]
    Returns: QBO SalesItemLineDetail lines.
    """
    lines = []
    for item in line_items:
        amount = item.get("amount", 0)
        qty = item.get("quantity", 1)
        rate = item.get("rate", amount / qty if qty else amount)
        detail: dict = {"Qty": qty, "UnitPrice": rate}
        if item.get("item_id"):
            detail["ItemRef"] = {"value": str(item["item_id"])}
        line: dict = {
            "DetailType": "SalesItemLineDetail",
            "Amount": amount,
            "SalesItemLineDetail": detail,
        }
        if item.get("description"):
            line["Description"] = item["description"]
        lines.append(line)
    return lines


def _build_payment_lines(invoice_ids: list[str], total_amount: float) -> list[dict]:
    """Build QBO Payment Line array linking to invoices."""
    if not invoice_ids:
        return []
    lines = []
    for inv_id in invoice_ids:
        lines.append({
            "Amount": total_amount / len(invoice_ids),
            "LinkedTxn": [{"TxnId": str(inv_id), "TxnType": "Invoice"}],
        })
    return lines


# ── Tool definitions ─────────────────────────────────────────────────────────

QB_TOOL_DEFS = [
    # ── Read tools ───────────────────────────────────────────────────────
    {
        "name": "qbo_query",
        "description": "Query QuickBooks records using SQL-style syntax. E.g. SELECT * FROM Invoice WHERE TotalAmt > 1000",
        "input_schema": {
            "type": "object",
            "properties": {
                "sql": {"type": "string", "description": "QBO SQL query"},
            },
            "required": ["sql"],
        },
        "kind": "integration",
    },
    {
        "name": "qbo_profit_and_loss",
        "description": "Get Profit & Loss report for a date range.",
        "input_schema": {
            "type": "object",
            "properties": {
                "start_date": {"type": "string", "description": "Start date YYYY-MM-DD"},
                "end_date": {"type": "string", "description": "End date YYYY-MM-DD"},
            },
            "required": ["start_date", "end_date"],
        },
        "kind": "integration",
    },
    {
        "name": "qbo_get_balance_sheet",
        "description": "Get Balance Sheet report for a date range.",
        "input_schema": {
            "type": "object",
            "properties": {
                "start_date": {"type": "string", "description": "Start date YYYY-MM-DD"},
                "end_date": {"type": "string", "description": "End date YYYY-MM-DD"},
            },
            "required": ["start_date", "end_date"],
        },
        "kind": "integration",
    },
    {
        "name": "qbo_get_entity",
        "description": "Get a single QuickBooks entity by type and ID. Returns full details including all fields.",
        "input_schema": {
            "type": "object",
            "properties": {
                "entity_type": {
                    "type": "string",
                    "description": "Entity type",
                    "enum": sorted(_ALLOWED_GET_TYPES),
                },
                "entity_id": {"type": "string", "description": "The entity ID"},
            },
            "required": ["entity_type", "entity_id"],
        },
        "kind": "integration",
    },

    # ── Invoice tools ────────────────────────────────────────────────────
    {
        "name": "qbo_create_invoice",
        "description": "Create a new invoice in QuickBooks. Requires customer ID and at least one line item.",
        "input_schema": {
            "type": "object",
            "properties": {
                "customer_id": {"type": "string", "description": "QBO Customer Id (query customers first to find the ID)"},
                "line_items": {
                    "type": "array",
                    "description": "Invoice line items",
                    "items": {
                        "type": "object",
                        "properties": {
                            "description": {"type": "string", "description": "Line item description"},
                            "amount": {"type": "number", "description": "Total line amount"},
                            "quantity": {"type": "number", "description": "Quantity (default 1)"},
                            "rate": {"type": "number", "description": "Unit price (defaults to amount/quantity)"},
                            "item_id": {"type": "string", "description": "QBO Item Id (product/service)"},
                        },
                        "required": ["amount"],
                    },
                },
                "due_date": {"type": "string", "description": "Due date YYYY-MM-DD"},
                "txn_date": {"type": "string", "description": "Invoice date YYYY-MM-DD (defaults to today)"},
                "doc_number": {"type": "string", "description": "Custom invoice number"},
                "customer_memo": {"type": "string", "description": "Memo visible to customer"},
                "private_note": {"type": "string", "description": "Internal note (not visible to customer)"},
            },
            "required": ["customer_id", "line_items"],
        },
        "kind": "integration",
        "writes": True,
    },
    {
        "name": "qbo_update_invoice",
        "description": "Update an existing invoice. Fetches current data and SyncToken automatically. Provide only fields to change.",
        "input_schema": {
            "type": "object",
            "properties": {
                "invoice_id": {"type": "string", "description": "QBO Invoice Id"},
                "line_items": {
                    "type": "array",
                    "description": "Replaces all line items if provided",
                    "items": {
                        "type": "object",
                        "properties": {
                            "description": {"type": "string"},
                            "amount": {"type": "number"},
                            "quantity": {"type": "number"},
                            "rate": {"type": "number"},
                            "item_id": {"type": "string"},
                        },
                        "required": ["amount"],
                    },
                },
                "due_date": {"type": "string", "description": "New due date YYYY-MM-DD"},
                "customer_memo": {"type": "string", "description": "Updated memo for customer"},
                "private_note": {"type": "string", "description": "Updated internal note"},
                "doc_number": {"type": "string", "description": "Updated invoice number"},
            },
            "required": ["invoice_id"],
        },
        "kind": "integration",
        "writes": True,
    },
    {
        "name": "qbo_send_invoice",
        "description": "Email an invoice to the customer. The customer's email must be on file in QuickBooks unless you provide an override.",
        "input_schema": {
            "type": "object",
            "properties": {
                "invoice_id": {"type": "string", "description": "QBO Invoice Id"},
                "email_to": {"type": "string", "description": "Override recipient email address (optional)"},
            },
            "required": ["invoice_id"],
        },
        "kind": "integration",
        "writes": True,
    },
    {
        "name": "qbo_void_invoice",
        "description": "Void an invoice in QuickBooks. Sets the balance to zero without deleting the record.",
        "input_schema": {
            "type": "object",
            "properties": {
                "invoice_id": {"type": "string", "description": "QBO Invoice Id"},
            },
            "required": ["invoice_id"],
        },
        "kind": "integration",
        "writes": True,
    },

    # ── Payment tools ────────────────────────────────────────────────────
    {
        "name": "qbo_record_payment",
        "description": "Record a payment received from a customer, optionally linked to specific invoices.",
        "input_schema": {
            "type": "object",
            "properties": {
                "customer_id": {"type": "string", "description": "QBO Customer Id"},
                "total_amount": {"type": "number", "description": "Payment amount"},
                "payment_date": {"type": "string", "description": "Payment date YYYY-MM-DD (defaults to today)"},
                "invoice_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Invoice Ids to apply this payment to",
                },
                "payment_method": {"type": "string", "description": "E.g. 'Check', 'Credit Card', 'Cash'"},
                "reference_number": {"type": "string", "description": "Check number or payment reference"},
                "private_note": {"type": "string", "description": "Internal note"},
            },
            "required": ["customer_id", "total_amount"],
        },
        "kind": "integration",
        "writes": True,
    },

    # ── Estimate tools ───────────────────────────────────────────────────
    {
        "name": "qbo_create_estimate",
        "description": "Create a new estimate/quote for a customer in QuickBooks.",
        "input_schema": {
            "type": "object",
            "properties": {
                "customer_id": {"type": "string", "description": "QBO Customer Id"},
                "line_items": {
                    "type": "array",
                    "description": "Estimate line items",
                    "items": {
                        "type": "object",
                        "properties": {
                            "description": {"type": "string"},
                            "amount": {"type": "number"},
                            "quantity": {"type": "number"},
                            "rate": {"type": "number"},
                            "item_id": {"type": "string"},
                        },
                        "required": ["amount"],
                    },
                },
                "expiration_date": {"type": "string", "description": "Estimate expiration date YYYY-MM-DD"},
                "txn_date": {"type": "string", "description": "Estimate date YYYY-MM-DD"},
                "customer_memo": {"type": "string", "description": "Memo visible to customer"},
                "private_note": {"type": "string", "description": "Internal note"},
            },
            "required": ["customer_id", "line_items"],
        },
        "kind": "integration",
        "writes": True,
    },
    {
        "name": "qbo_send_estimate",
        "description": "Email an estimate/quote to the customer.",
        "input_schema": {
            "type": "object",
            "properties": {
                "estimate_id": {"type": "string", "description": "QBO Estimate Id"},
                "email_to": {"type": "string", "description": "Override recipient email address (optional)"},
            },
            "required": ["estimate_id"],
        },
        "kind": "integration",
        "writes": True,
    },

    # ── Generic entity tools ─────────────────────────────────────────────
    {
        "name": "qbo_create_entity",
        "description": "Create a Customer, Vendor, Item (product/service), Bill, Expense, or Credit Memo in QuickBooks. Pass the entity type and fields as a JSON object following the QBO API schema.",
        "input_schema": {
            "type": "object",
            "properties": {
                "entity_type": {
                    "type": "string",
                    "description": "Entity type to create",
                    "enum": sorted(_ALLOWED_CREATE_TYPES),
                },
                "data": {
                    "type": "object",
                    "description": "Entity fields per QBO API. E.g. for Customer: {\"DisplayName\": \"Acme Corp\", \"PrimaryEmailAddr\": {\"Address\": \"acme@example.com\"}}",
                },
            },
            "required": ["entity_type", "data"],
        },
        "kind": "integration",
        "writes": True,
    },
    {
        "name": "qbo_update_entity",
        "description": "Update an existing Customer, Vendor, or Item in QuickBooks. Automatically fetches the current record to get the SyncToken. Provide only the fields to change.",
        "input_schema": {
            "type": "object",
            "properties": {
                "entity_type": {
                    "type": "string",
                    "description": "Entity type to update",
                    "enum": sorted(_ALLOWED_UPDATE_TYPES),
                },
                "entity_id": {"type": "string", "description": "The entity ID to update"},
                "data": {
                    "type": "object",
                    "description": "Fields to update (merged with current record)",
                },
            },
            "required": ["entity_type", "entity_id", "data"],
        },
        "kind": "integration",
        "writes": True,
    },
]


# ── Executor functions ───────────────────────────────────────────────────────

def qbo_query(sql: str) -> dict:
    client = get_client()
    if not client:
        return {"error": "QuickBooks not configured or unavailable"}
    results = client.query(sql)
    return {"results": results, "count": len(results)}


def qbo_profit_and_loss(start_date: str, end_date: str) -> dict:
    client = get_client()
    if not client:
        return {"error": "QuickBooks not configured or unavailable"}
    return client.get_profit_and_loss(start_date, end_date)


def qbo_get_balance_sheet(start_date: str, end_date: str) -> dict:
    client = get_client()
    if not client:
        return {"error": "QuickBooks not configured or unavailable"}
    return client.get_balance_sheet(start_date, end_date)


def qbo_get_entity(entity_type: str, entity_id: str) -> dict:
    if entity_type not in _ALLOWED_GET_TYPES:
        return {"error": f"Entity type '{entity_type}' not supported. Allowed: {sorted(_ALLOWED_GET_TYPES)}"}
    client = get_client()
    if not client:
        return {"error": "QuickBooks not configured or unavailable"}
    result = client.get_entity(entity_type, entity_id)
    if "error" in result:
        return result
    return {"ok": True, "entity_type": entity_type, "entity": result}


# ── Invoice executors ────────────────────────────────────────────────────────

def qbo_create_invoice(
    customer_id: str,
    line_items: list[dict],
    due_date: str = "",
    txn_date: str = "",
    doc_number: str = "",
    customer_memo: str = "",
    private_note: str = "",
) -> dict:
    client = get_client()
    if not client:
        return {"error": "QuickBooks not configured or unavailable"}
    if not line_items:
        return {"error": "At least one line item is required"}

    payload: dict = {
        "CustomerRef": {"value": str(customer_id)},
        "Line": _build_line_items(line_items),
    }
    if due_date:
        payload["DueDate"] = due_date
    if txn_date:
        payload["TxnDate"] = txn_date
    if doc_number:
        payload["DocNumber"] = doc_number
    if customer_memo:
        payload["CustomerMemo"] = {"value": customer_memo}
    if private_note:
        payload["PrivateNote"] = private_note

    result = client.create_entity("Invoice", payload)
    if "error" in result:
        return result
    return {
        "ok": True,
        "id": result.get("Id"),
        "doc_number": result.get("DocNumber"),
        "total": result.get("TotalAmt"),
        "balance": result.get("Balance"),
        "status": result.get("EmailStatus"),
    }


def qbo_update_invoice(
    invoice_id: str,
    line_items: list[dict] | None = None,
    due_date: str = "",
    customer_memo: str = "",
    private_note: str = "",
    doc_number: str = "",
) -> dict:
    client = get_client()
    if not client:
        return {"error": "QuickBooks not configured or unavailable"}

    fetched = client._fetch_sync_token("Invoice", invoice_id)
    if not fetched:
        return {"error": f"Invoice {invoice_id} not found"}
    current, _ = fetched

    if line_items is not None:
        current["Line"] = _build_line_items(line_items)
    if due_date:
        current["DueDate"] = due_date
    if customer_memo:
        current["CustomerMemo"] = {"value": customer_memo}
    if private_note:
        current["PrivateNote"] = private_note
    if doc_number:
        current["DocNumber"] = doc_number

    result = client.update_entity("Invoice", current)
    if "error" in result:
        return result
    return {
        "ok": True,
        "id": result.get("Id"),
        "doc_number": result.get("DocNumber"),
        "total": result.get("TotalAmt"),
        "balance": result.get("Balance"),
    }


def qbo_send_invoice(invoice_id: str, email_to: str = "") -> dict:
    client = get_client()
    if not client:
        return {"error": "QuickBooks not configured or unavailable"}
    result = client.send_entity("Invoice", invoice_id, email_to or None)
    if "error" in result:
        return result
    return {
        "ok": True,
        "id": result.get("Id"),
        "email_status": result.get("EmailStatus"),
        "delivered_to": result.get("BillEmail", {}).get("Address", ""),
    }


def qbo_void_invoice(invoice_id: str) -> dict:
    client = get_client()
    if not client:
        return {"error": "QuickBooks not configured or unavailable"}

    fetched = client._fetch_sync_token("Invoice", invoice_id)
    if not fetched:
        return {"error": f"Invoice {invoice_id} not found"}
    _, sync_token = fetched

    result = client.void_entity("Invoice", invoice_id, sync_token)
    if "error" in result:
        return result
    return {
        "ok": True,
        "id": result.get("Id"),
        "doc_number": result.get("DocNumber"),
        "balance": result.get("Balance"),
        "voided": True,
    }


# ── Payment executor ─────────────────────────────────────────────────────────

def qbo_record_payment(
    customer_id: str,
    total_amount: float,
    payment_date: str = "",
    invoice_ids: list[str] | None = None,
    payment_method: str = "",
    reference_number: str = "",
    private_note: str = "",
) -> dict:
    client = get_client()
    if not client:
        return {"error": "QuickBooks not configured or unavailable"}

    payload: dict = {
        "CustomerRef": {"value": str(customer_id)},
        "TotalAmt": total_amount,
    }
    if payment_date:
        payload["TxnDate"] = payment_date
    if invoice_ids:
        payload["Line"] = _build_payment_lines(invoice_ids, total_amount)
    if payment_method:
        payload["PaymentMethodRef"] = {"value": payment_method}
    if reference_number:
        payload["PaymentRefNum"] = reference_number
    if private_note:
        payload["PrivateNote"] = private_note

    result = client.create_entity("Payment", payload)
    if "error" in result:
        return result
    return {
        "ok": True,
        "id": result.get("Id"),
        "amount": result.get("TotalAmt"),
        "date": result.get("TxnDate"),
        "unapplied": result.get("UnappliedAmt"),
    }


# ── Estimate executors ───────────────────────────────────────────────────────

def qbo_create_estimate(
    customer_id: str,
    line_items: list[dict],
    expiration_date: str = "",
    txn_date: str = "",
    customer_memo: str = "",
    private_note: str = "",
) -> dict:
    client = get_client()
    if not client:
        return {"error": "QuickBooks not configured or unavailable"}
    if not line_items:
        return {"error": "At least one line item is required"}

    payload: dict = {
        "CustomerRef": {"value": str(customer_id)},
        "Line": _build_line_items(line_items),
    }
    if expiration_date:
        payload["ExpirationDate"] = expiration_date
    if txn_date:
        payload["TxnDate"] = txn_date
    if customer_memo:
        payload["CustomerMemo"] = {"value": customer_memo}
    if private_note:
        payload["PrivateNote"] = private_note

    result = client.create_entity("Estimate", payload)
    if "error" in result:
        return result
    return {
        "ok": True,
        "id": result.get("Id"),
        "doc_number": result.get("DocNumber"),
        "total": result.get("TotalAmt"),
        "status": result.get("TxnStatus"),
    }


def qbo_send_estimate(estimate_id: str, email_to: str = "") -> dict:
    client = get_client()
    if not client:
        return {"error": "QuickBooks not configured or unavailable"}
    result = client.send_entity("Estimate", estimate_id, email_to or None)
    if "error" in result:
        return result
    return {
        "ok": True,
        "id": result.get("Id"),
        "email_status": result.get("EmailStatus"),
        "delivered_to": result.get("BillEmail", {}).get("Address", ""),
    }


# ── Generic entity executors ─────────────────────────────────────────────────

def qbo_create_entity(entity_type: str, data: dict) -> dict:
    if entity_type not in _ALLOWED_CREATE_TYPES:
        return {"error": f"Entity type '{entity_type}' not supported for creation. Allowed: {sorted(_ALLOWED_CREATE_TYPES)}"}
    client = get_client()
    if not client:
        return {"error": "QuickBooks not configured or unavailable"}
    if not data:
        return {"error": "data is required"}

    result = client.create_entity(entity_type, data)
    if "error" in result:
        return result
    return {
        "ok": True,
        "entity_type": entity_type,
        "id": result.get("Id"),
        "display_name": result.get("DisplayName", result.get("Name", "")),
        "sync_token": result.get("SyncToken"),
    }


def qbo_update_entity(entity_type: str, entity_id: str, data: dict) -> dict:
    if entity_type not in _ALLOWED_UPDATE_TYPES:
        return {"error": f"Entity type '{entity_type}' not supported for update. Allowed: {sorted(_ALLOWED_UPDATE_TYPES)}"}
    client = get_client()
    if not client:
        return {"error": "QuickBooks not configured or unavailable"}
    if not data:
        return {"error": "data is required — provide at least one field to update"}

    fetched = client._fetch_sync_token(entity_type, entity_id)
    if not fetched:
        return {"error": f"{entity_type} {entity_id} not found"}
    current, _ = fetched

    # Merge updates on top of current entity
    current.update(data)

    result = client.update_entity(entity_type, current)
    if "error" in result:
        return result
    return {
        "ok": True,
        "entity_type": entity_type,
        "id": result.get("Id"),
        "display_name": result.get("DisplayName", result.get("Name", "")),
        "sync_token": result.get("SyncToken"),
    }


# ── Executor map ─────────────────────────────────────────────────────────────

TOOL_EXECUTORS = {
    # Read tools
    "qbo_query": lambda **kw: qbo_query(**kw),
    "qbo_profit_and_loss": lambda **kw: qbo_profit_and_loss(**kw),
    "qbo_get_balance_sheet": lambda **kw: qbo_get_balance_sheet(**kw),
    "qbo_get_entity": lambda **kw: qbo_get_entity(**kw),
    # Invoice tools
    "qbo_create_invoice": lambda **kw: qbo_create_invoice(**kw),
    "qbo_update_invoice": lambda **kw: qbo_update_invoice(**kw),
    "qbo_send_invoice": lambda **kw: qbo_send_invoice(**kw),
    "qbo_void_invoice": lambda **kw: qbo_void_invoice(**kw),
    # Payment tools
    "qbo_record_payment": lambda **kw: qbo_record_payment(**kw),
    # Estimate tools
    "qbo_create_estimate": lambda **kw: qbo_create_estimate(**kw),
    "qbo_send_estimate": lambda **kw: qbo_send_estimate(**kw),
    # Generic entity tools
    "qbo_create_entity": lambda **kw: qbo_create_entity(**kw),
    "qbo_update_entity": lambda **kw: qbo_update_entity(**kw),
}
