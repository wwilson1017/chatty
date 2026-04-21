"""Chatty — Odoo Accounting tools."""

import logging
from datetime import date

from ..helpers import safe_get_client

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

ACCOUNTING_TOOL_DEFS = [
    # --- Read tools ---
    {
        "name": "odoo_search_invoices",
        "description": (
            "Search invoices, bills, and credit notes. "
            "Filter by number, partner, type, amount, state, or date range."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "number": {
                    "type": "string",
                    "description": "Invoice/bill number (partial match).",
                },
                "partner": {
                    "type": "string",
                    "description": "Partner (customer/vendor) name to filter by (partial match).",
                },
                "move_type": {
                    "type": "string",
                    "enum": ["out_invoice", "in_invoice", "out_refund", "in_refund"],
                    "description": (
                        "Invoice type: out_invoice (customer invoice), in_invoice (vendor bill), "
                        "out_refund (customer credit note), in_refund (vendor credit note)."
                    ),
                },
                "amount_min": {
                    "type": "number",
                    "description": "Minimum total amount.",
                },
                "amount_max": {
                    "type": "number",
                    "description": "Maximum total amount.",
                },
                "state": {
                    "type": "string",
                    "enum": ["draft", "posted", "cancel"],
                    "description": "Invoice state: draft, posted, or cancel.",
                },
                "date_from": {
                    "type": "string",
                    "description": "Start date for invoice date filter (YYYY-MM-DD).",
                },
                "date_to": {
                    "type": "string",
                    "description": "End date for invoice date filter (YYYY-MM-DD).",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results (default 20).",
                    "default": 20,
                },
            },
            "required": [],
        },
        "kind": "integration",
    },
    {
        "name": "odoo_search_bills",
        "description": (
            "Search vendor bills and vendor credit notes. "
            "Filter by number, vendor name, amount, state, or date range."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "number": {
                    "type": "string",
                    "description": "Bill number (partial match).",
                },
                "vendor": {
                    "type": "string",
                    "description": "Vendor name to filter by (partial match).",
                },
                "amount_min": {
                    "type": "number",
                    "description": "Minimum total amount.",
                },
                "amount_max": {
                    "type": "number",
                    "description": "Maximum total amount.",
                },
                "state": {
                    "type": "string",
                    "enum": ["draft", "posted", "cancel"],
                    "description": "Bill state: draft, posted, or cancel.",
                },
                "date_from": {
                    "type": "string",
                    "description": "Start date for bill date filter (YYYY-MM-DD).",
                },
                "date_to": {
                    "type": "string",
                    "description": "End date for bill date filter (YYYY-MM-DD).",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results (default 20).",
                    "default": 20,
                },
            },
            "required": [],
        },
        "kind": "integration",
    },
    {
        "name": "odoo_get_invoice_details",
        "description": (
            "Get full details for a single invoice or bill, including line items, "
            "taxes, and payment status."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "invoice_id": {
                    "type": "integer",
                    "description": "The ID of the invoice/bill to retrieve.",
                },
            },
            "required": ["invoice_id"],
        },
        "kind": "integration",
    },
    {
        "name": "odoo_search_payments",
        "description": (
            "Search payments (customer receipts and vendor payments). "
            "Filter by partner, type, state, or date range."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "partner": {
                    "type": "string",
                    "description": "Partner name to filter by (partial match).",
                },
                "payment_type": {
                    "type": "string",
                    "enum": ["inbound", "outbound"],
                    "description": "Payment type: inbound (received) or outbound (sent).",
                },
                "state": {
                    "type": "string",
                    "enum": ["draft", "posted", "cancel"],
                    "description": "Payment state: draft, posted, or cancel.",
                },
                "date_from": {
                    "type": "string",
                    "description": "Start date for payment date filter (YYYY-MM-DD).",
                },
                "date_to": {
                    "type": "string",
                    "description": "End date for payment date filter (YYYY-MM-DD).",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results (default 20).",
                    "default": 20,
                },
            },
            "required": [],
        },
        "kind": "integration",
    },
    {
        "name": "odoo_get_aged_receivables",
        "description": (
            "Get accounts receivable aging report. Shows outstanding customer invoices "
            "grouped by aging bucket (current, 1-30, 31-60, 61-90, 90+ days) "
            "with per-partner breakdown."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
        "kind": "integration",
    },
    {
        "name": "odoo_get_aged_payables",
        "description": (
            "Get accounts payable aging report. Shows outstanding vendor bills "
            "grouped by aging bucket (current, 1-30, 31-60, 61-90, 90+ days) "
            "with per-vendor breakdown."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
        "kind": "integration",
    },
    # --- Write tools ---
    {
        "name": "odoo_create_invoice",
        "description": (
            "Create a draft customer invoice with one or more line items. "
            "The invoice is created in draft state and must be confirmed separately."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "partner_id": {
                    "type": "integer",
                    "description": "Customer (partner) ID for the invoice.",
                },
                "lines": {
                    "type": "array",
                    "description": "Invoice line items.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "product_id": {
                                "type": "integer",
                                "description": "Optional product ID for the line.",
                            },
                            "name": {
                                "type": "string",
                                "description": "Line description/label.",
                            },
                            "quantity": {
                                "type": "number",
                                "description": "Quantity (default 1).",
                                "default": 1,
                            },
                            "price_unit": {
                                "type": "number",
                                "description": "Unit price.",
                            },
                        },
                        "required": ["name", "price_unit"],
                    },
                },
                "invoice_date": {
                    "type": "string",
                    "description": "Invoice date (YYYY-MM-DD). Defaults to today.",
                },
                "ref": {
                    "type": "string",
                    "description": "Payment reference or external reference number.",
                },
            },
            "required": ["partner_id", "lines"],
        },
        "kind": "integration",
        "writes": True,
    },
    {
        "name": "odoo_register_payment",
        "description": (
            "Register a payment against an existing invoice or bill. "
            "The invoice must be in 'posted' state. If no amount is given, "
            "pays the full remaining balance."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "invoice_id": {
                    "type": "integer",
                    "description": "The ID of the invoice/bill to pay.",
                },
                "amount": {
                    "type": "number",
                    "description": (
                        "Payment amount. Defaults to the full remaining balance if omitted."
                    ),
                },
                "date": {
                    "type": "string",
                    "description": "Payment date (YYYY-MM-DD). Defaults to today.",
                },
            },
            "required": ["invoice_id"],
        },
        "kind": "integration",
        "writes": True,
    },
]

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_INVOICE_FIELDS = [
    "name", "partner_id", "invoice_date", "invoice_date_due",
    "amount_total", "amount_residual", "state", "move_type", "payment_state",
]


def _format_invoice(r: dict) -> dict:
    """Normalise an account.move record into a clean dict."""
    return {
        "id": r["id"],
        "number": r.get("name", ""),
        "partner": r["partner_id"][1] if r.get("partner_id") else None,
        "partner_id": r["partner_id"][0] if r.get("partner_id") else None,
        "date": r.get("invoice_date", ""),
        "due_date": r.get("invoice_date_due", ""),
        "total": r.get("amount_total", 0),
        "balance_due": r.get("amount_residual", 0),
        "state": r.get("state", ""),
        "type": r.get("move_type", ""),
        "payment_state": r.get("payment_state", ""),
    }


def _compute_aging_buckets(records: list[dict]) -> dict:
    """Group invoice records into aging buckets based on due date."""
    today = date.today()
    buckets: dict[str, list] = {
        "current": [],
        "1_30": [],
        "31_60": [],
        "61_90": [],
        "over_90": [],
    }
    for r in records:
        due = r.get("invoice_date_due")
        if not due:
            buckets["current"].append(r)
            continue
        try:
            due_date = date.fromisoformat(due) if isinstance(due, str) else due
        except (ValueError, TypeError):
            buckets["current"].append(r)
            continue
        days_overdue = (today - due_date).days
        if days_overdue <= 0:
            buckets["current"].append(r)
        elif days_overdue <= 30:
            buckets["1_30"].append(r)
        elif days_overdue <= 60:
            buckets["31_60"].append(r)
        elif days_overdue <= 90:
            buckets["61_90"].append(r)
        else:
            buckets["over_90"].append(r)
    return buckets


def _aging_report(records: list[dict]) -> dict:
    """Build an aging report with bucket totals and per-partner breakdown."""
    buckets = _compute_aging_buckets(records)

    summary = {}
    partner_totals: dict[str, float] = {}

    for bucket_name, items in buckets.items():
        bucket_total = sum(r.get("amount_residual", 0) for r in items)
        summary[bucket_name] = {
            "count": len(items),
            "total": round(bucket_total, 2),
        }
        for r in items:
            p_name = r["partner_id"][1] if r.get("partner_id") else "Unknown"
            partner_totals[p_name] = partner_totals.get(p_name, 0) + r.get("amount_residual", 0)

    grand_total = sum(b["total"] for b in summary.values())
    partners = [
        {"partner": name, "balance_due": round(amt, 2)}
        for name, amt in sorted(partner_totals.items(), key=lambda x: -x[1])
    ]

    return {
        "buckets": summary,
        "grand_total": round(grand_total, 2),
        "partners": partners,
        "invoice_count": len(records),
    }


# ---------------------------------------------------------------------------
# Executor functions
# ---------------------------------------------------------------------------


def odoo_search_invoices(
    number: str | None = None,
    partner: str | None = None,
    move_type: str | None = None,
    amount_min: float | None = None,
    amount_max: float | None = None,
    state: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 20,
) -> dict:
    """Search invoices, bills, and credit notes."""
    client, err = safe_get_client()
    if err:
        return err

    domain: list = [
        ["move_type", "in", ["out_invoice", "out_refund", "in_invoice", "in_refund"]],
    ]
    if number:
        domain.append(["name", "ilike", number])
    if partner:
        domain.append(["partner_id.name", "ilike", partner])
    if move_type:
        domain.append(["move_type", "=", move_type])
    if amount_min is not None:
        domain.append(["amount_total", ">=", amount_min])
    if amount_max is not None:
        domain.append(["amount_total", "<=", amount_max])
    if state:
        domain.append(["state", "=", state])
    if date_from:
        domain.append(["invoice_date", ">=", date_from])
    if date_to:
        domain.append(["invoice_date", "<=", date_to])

    records = client.search_read("account.move", domain, _INVOICE_FIELDS, limit=limit) or []
    invoices = [_format_invoice(r) for r in records]
    return {"invoices": invoices, "total": len(invoices)}


def odoo_search_bills(
    number: str | None = None,
    vendor: str | None = None,
    amount_min: float | None = None,
    amount_max: float | None = None,
    state: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 20,
) -> dict:
    """Search vendor bills and vendor credit notes."""
    client, err = safe_get_client()
    if err:
        return err

    domain: list = [
        ["move_type", "in", ["in_invoice", "in_refund"]],
    ]
    if number:
        domain.append(["name", "ilike", number])
    if vendor:
        domain.append(["partner_id.name", "ilike", vendor])
    if amount_min is not None:
        domain.append(["amount_total", ">=", amount_min])
    if amount_max is not None:
        domain.append(["amount_total", "<=", amount_max])
    if state:
        domain.append(["state", "=", state])
    if date_from:
        domain.append(["invoice_date", ">=", date_from])
    if date_to:
        domain.append(["invoice_date", "<=", date_to])

    records = client.search_read("account.move", domain, _INVOICE_FIELDS, limit=limit) or []
    bills = [_format_invoice(r) for r in records]
    return {"bills": bills, "total": len(bills)}


def odoo_get_invoice_details(invoice_id: int) -> dict:
    """Get full details for a single invoice or bill with line items."""
    client, err = safe_get_client()
    if err:
        return err

    fields = [
        "name", "partner_id", "invoice_date", "invoice_date_due",
        "amount_total", "amount_residual", "amount_untaxed", "amount_tax",
        "state", "move_type", "payment_state", "currency_id",
        "ref", "narration", "invoice_line_ids",
    ]
    records = client.search_read(
        "account.move", [["id", "=", invoice_id]], fields, limit=1,
    ) or []
    if not records:
        return {"error": f"Invoice #{invoice_id} not found"}

    inv = records[0]

    # Fetch line items
    line_ids = inv.get("invoice_line_ids", [])
    lines = []
    if line_ids:
        line_fields = [
            "product_id", "name", "quantity", "price_unit",
            "price_subtotal", "tax_ids", "account_id",
        ]
        line_domain = [
            ["move_id", "=", invoice_id],
            ["exclude_from_invoice_tab", "=", False],
        ]
        line_records = client.search_read(
            "account.move.line", line_domain, line_fields, limit=200,
        ) or []
        for lr in line_records:
            lines.append({
                "id": lr["id"],
                "product": lr["product_id"][1] if lr.get("product_id") else None,
                "product_id": lr["product_id"][0] if lr.get("product_id") else None,
                "description": lr.get("name", ""),
                "quantity": lr.get("quantity", 0),
                "unit_price": lr.get("price_unit", 0),
                "subtotal": lr.get("price_subtotal", 0),
                "account": lr["account_id"][1] if lr.get("account_id") else None,
            })

    return {
        "id": inv["id"],
        "number": inv.get("name", ""),
        "partner": inv["partner_id"][1] if inv.get("partner_id") else None,
        "partner_id": inv["partner_id"][0] if inv.get("partner_id") else None,
        "date": inv.get("invoice_date", ""),
        "due_date": inv.get("invoice_date_due", ""),
        "amount_untaxed": inv.get("amount_untaxed", 0),
        "amount_tax": inv.get("amount_tax", 0),
        "amount_total": inv.get("amount_total", 0),
        "balance_due": inv.get("amount_residual", 0),
        "state": inv.get("state", ""),
        "type": inv.get("move_type", ""),
        "payment_state": inv.get("payment_state", ""),
        "currency": inv["currency_id"][1] if inv.get("currency_id") else None,
        "reference": inv.get("ref", ""),
        "notes": inv.get("narration", ""),
        "lines": lines,
    }


def odoo_search_payments(
    partner: str | None = None,
    payment_type: str | None = None,
    state: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 20,
) -> dict:
    """Search payments (customer receipts and vendor payments)."""
    client, err = safe_get_client()
    if err:
        return err

    domain: list = []
    if partner:
        domain.append(["partner_id.name", "ilike", partner])
    if payment_type:
        domain.append(["payment_type", "=", payment_type])
    if state:
        domain.append(["state", "=", state])
    if date_from:
        domain.append(["date", ">=", date_from])
    if date_to:
        domain.append(["date", "<=", date_to])

    fields = [
        "name", "partner_id", "amount", "payment_type", "date",
        "state", "payment_method_line_id", "ref", "currency_id",
    ]
    records = client.search_read("account.payment", domain, fields, limit=limit) or []

    payments = []
    for r in records:
        payments.append({
            "id": r["id"],
            "name": r.get("name", ""),
            "partner": r["partner_id"][1] if r.get("partner_id") else None,
            "partner_id": r["partner_id"][0] if r.get("partner_id") else None,
            "amount": r.get("amount", 0),
            "payment_type": r.get("payment_type", ""),
            "date": r.get("date", ""),
            "state": r.get("state", ""),
            "payment_method": (
                r["payment_method_line_id"][1]
                if r.get("payment_method_line_id") else None
            ),
            "reference": r.get("ref", ""),
            "currency": r["currency_id"][1] if r.get("currency_id") else None,
        })

    return {"payments": payments, "total": len(payments)}


def odoo_get_aged_receivables() -> dict:
    """Get accounts receivable aging report."""
    client, err = safe_get_client()
    if err:
        return err

    domain = [
        ["move_type", "=", "out_invoice"],
        ["state", "=", "posted"],
        ["payment_state", "in", ["not_paid", "partial"]],
    ]
    fields = ["name", "partner_id", "invoice_date_due", "amount_residual"]
    records = client.search_read("account.move", domain, fields, limit=500) or []

    report = _aging_report(records)
    report["report_type"] = "receivables"
    return report


def odoo_get_aged_payables() -> dict:
    """Get accounts payable aging report."""
    client, err = safe_get_client()
    if err:
        return err

    domain = [
        ["move_type", "=", "in_invoice"],
        ["state", "=", "posted"],
        ["payment_state", "in", ["not_paid", "partial"]],
    ]
    fields = ["name", "partner_id", "invoice_date_due", "amount_residual"]
    records = client.search_read("account.move", domain, fields, limit=500) or []

    report = _aging_report(records)
    report["report_type"] = "payables"
    return report


def odoo_create_invoice(
    partner_id: int,
    lines: list[dict],
    invoice_date: str | None = None,
    ref: str | None = None,
) -> dict:
    """Create a draft customer invoice."""
    client, err = safe_get_client()
    if err:
        return err

    # Build invoice line commands: [(0, 0, vals), ...]
    invoice_lines = []
    for line in lines:
        line_vals: dict = {
            "name": line["name"],
            "quantity": line.get("quantity", 1),
            "price_unit": line["price_unit"],
        }
        if line.get("product_id"):
            line_vals["product_id"] = line["product_id"]
        invoice_lines.append((0, 0, line_vals))

    vals: dict = {
        "move_type": "out_invoice",
        "partner_id": partner_id,
        "invoice_line_ids": invoice_lines,
    }
    if invoice_date:
        vals["invoice_date"] = invoice_date
    if ref:
        vals["ref"] = ref

    try:
        invoice_id = client.create("account.move", vals)
    except Exception as e:
        return {"error": f"Odoo error creating invoice: {e}"}

    if not invoice_id:
        return {"error": "Failed to create invoice in Odoo"}

    # Read back the created invoice for confirmation
    created = client.search_read(
        "account.move",
        [["id", "=", invoice_id]],
        ["name", "partner_id", "amount_total", "state", "invoice_date"],
        limit=1,
    )
    inv = created[0] if created else {}

    return {
        "ok": True,
        "id": invoice_id,
        "number": inv.get("name", ""),
        "partner": inv["partner_id"][1] if inv.get("partner_id") else None,
        "amount_total": inv.get("amount_total", 0),
        "state": inv.get("state", "draft"),
        "date": inv.get("invoice_date", ""),
    }


def odoo_register_payment(
    invoice_id: int,
    amount: float | None = None,
    date: str | None = None,
) -> dict:
    """Register a payment against an invoice or bill."""
    client, err = safe_get_client()
    if err:
        return err

    # Verify invoice exists and is posted
    invoices = client.search_read(
        "account.move",
        [["id", "=", invoice_id]],
        ["name", "partner_id", "move_type", "state", "amount_residual", "currency_id"],
        limit=1,
    ) or []
    if not invoices:
        return {"error": f"Invoice #{invoice_id} not found"}

    inv = invoices[0]
    if inv.get("state") != "posted":
        return {"error": f"Invoice #{invoice_id} is in '{inv.get('state')}' state — must be posted to register payment"}

    partner_id = inv["partner_id"][0] if inv.get("partner_id") else None
    if not partner_id:
        return {"error": f"Invoice #{invoice_id} has no partner — cannot create payment"}

    # Determine payment type based on move type
    move_type = inv.get("move_type", "")
    if move_type in ("out_invoice", "out_refund"):
        payment_type = "inbound"
        partner_type = "customer"
    else:
        payment_type = "outbound"
        partner_type = "supplier"

    pay_amount = amount if amount is not None else inv.get("amount_residual", 0)

    payment_vals: dict = {
        "partner_id": partner_id,
        "payment_type": payment_type,
        "partner_type": partner_type,
        "amount": pay_amount,
    }
    if date:
        payment_vals["date"] = date
    if inv.get("currency_id"):
        payment_vals["currency_id"] = inv["currency_id"][0]

    try:
        payment_id = client.create("account.payment", payment_vals)
    except Exception as e:
        return {"error": f"Odoo error creating payment: {e}"}

    if not payment_id:
        return {"error": "Failed to create payment in Odoo"}

    # Post the payment
    try:
        client.execute("account.payment", "action_post", [payment_id])
    except Exception as e:
        return {"error": f"Payment created (ID {payment_id}) but failed to post: {e}"}

    # Read back for confirmation
    payments = client.search_read(
        "account.payment",
        [["id", "=", payment_id]],
        ["name", "amount", "date", "state", "payment_type"],
        limit=1,
    )
    pay = payments[0] if payments else {}

    return {
        "ok": True,
        "payment_id": payment_id,
        "name": pay.get("name", ""),
        "invoice_id": invoice_id,
        "invoice_number": inv.get("name", ""),
        "amount": pay.get("amount", pay_amount),
        "date": pay.get("date", ""),
        "state": pay.get("state", ""),
        "payment_type": pay.get("payment_type", payment_type),
    }


# ---------------------------------------------------------------------------
# Executor map
# ---------------------------------------------------------------------------

ACCOUNTING_EXECUTORS = {
    "odoo_search_invoices": lambda **kw: odoo_search_invoices(**kw),
    "odoo_search_bills": lambda **kw: odoo_search_bills(**kw),
    "odoo_get_invoice_details": lambda **kw: odoo_get_invoice_details(**kw),
    "odoo_search_payments": lambda **kw: odoo_search_payments(**kw),
    "odoo_get_aged_receivables": lambda **kw: odoo_get_aged_receivables(**kw),
    "odoo_get_aged_payables": lambda **kw: odoo_get_aged_payables(**kw),
    "odoo_create_invoice": lambda **kw: odoo_create_invoice(**kw),
    "odoo_register_payment": lambda **kw: odoo_register_payment(**kw),
}
