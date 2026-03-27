"""Chatty -- Odoo Contacts/Partner tools.

6 tools for searching, viewing, creating, and updating contacts/partners,
plus fetching child contacts and recent transactions.
"""

import logging

from ..helpers import safe_get_client, flatten_m2o

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

CONTACTS_TOOL_DEFS = [
    # 1 - odoo_search_partners
    {
        "name": "odoo_search_partners",
        "description": (
            "Search Odoo contacts/partners by name, email, or company flag. "
            "Returns a list of matching partners with basic info."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Partial name to search (case-insensitive)",
                },
                "email": {
                    "type": "string",
                    "description": "Partial email to search (case-insensitive)",
                },
                "is_company": {
                    "type": "boolean",
                    "description": "Filter by company (true) or individual (false). Omit to return both.",
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
    # 2 - odoo_get_partner_details
    {
        "name": "odoo_get_partner_details",
        "description": (
            "Get full details for a single Odoo partner/contact by ID. "
            "Returns address, tags, ranks, and metadata."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "partner_id": {
                    "type": "integer",
                    "description": "The partner record ID",
                },
            },
            "required": ["partner_id"],
        },
        "kind": "integration",
    },
    # 3 - odoo_create_partner
    {
        "name": "odoo_create_partner",
        "description": (
            "Create a new contact or company in Odoo. "
            "Returns the created partner's details."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Contact or company name (required)",
                },
                "email": {
                    "type": "string",
                    "description": "Email address",
                },
                "phone": {
                    "type": "string",
                    "description": "Phone number",
                },
                "mobile": {
                    "type": "string",
                    "description": "Mobile phone number",
                },
                "is_company": {
                    "type": "boolean",
                    "description": "True to create a company, false for an individual contact (default false)",
                    "default": False,
                },
                "street": {
                    "type": "string",
                    "description": "Street address line 1",
                },
                "city": {
                    "type": "string",
                    "description": "City",
                },
                "state_id": {
                    "type": "integer",
                    "description": "State/province record ID (res.country.state)",
                },
                "zip": {
                    "type": "string",
                    "description": "ZIP / postal code",
                },
                "country_id": {
                    "type": "integer",
                    "description": "Country record ID (res.country)",
                },
                "website": {
                    "type": "string",
                    "description": "Website URL",
                },
                "parent_id": {
                    "type": "integer",
                    "description": "Parent company partner ID (makes this a child contact)",
                },
                "vat": {
                    "type": "string",
                    "description": "Tax ID / VAT number",
                },
                "comment": {
                    "type": "string",
                    "description": "Internal notes",
                },
            },
            "required": ["name"],
        },
        "kind": "integration",
    },
    # 4 - odoo_update_partner
    {
        "name": "odoo_update_partner",
        "description": (
            "Update fields on an existing Odoo partner/contact. "
            "Only provided fields are changed; others are left untouched."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "partner_id": {
                    "type": "integer",
                    "description": "The partner record ID to update",
                },
                "name": {
                    "type": "string",
                    "description": "New name",
                },
                "email": {
                    "type": "string",
                    "description": "New email address",
                },
                "phone": {
                    "type": "string",
                    "description": "New phone number",
                },
                "mobile": {
                    "type": "string",
                    "description": "New mobile number",
                },
                "street": {
                    "type": "string",
                    "description": "New street address",
                },
                "city": {
                    "type": "string",
                    "description": "New city",
                },
                "state_id": {
                    "type": "integer",
                    "description": "New state/province record ID",
                },
                "zip": {
                    "type": "string",
                    "description": "New ZIP / postal code",
                },
                "country_id": {
                    "type": "integer",
                    "description": "New country record ID",
                },
                "website": {
                    "type": "string",
                    "description": "New website URL",
                },
                "comment": {
                    "type": "string",
                    "description": "New internal notes",
                },
            },
            "required": ["partner_id"],
        },
        "kind": "integration",
    },
    # 5 - odoo_search_partner_contacts
    {
        "name": "odoo_search_partner_contacts",
        "description": (
            "Find child contacts belonging to a company partner. "
            "Returns contact name, email, phone, and job title."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "company_id": {
                    "type": "integer",
                    "description": "Partner ID of the parent company",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max contacts to return (default 50)",
                    "default": 50,
                },
            },
            "required": ["company_id"],
        },
        "kind": "integration",
    },
    # 6 - odoo_get_partner_transactions
    {
        "name": "odoo_get_partner_transactions",
        "description": (
            "Get recent transactions for a partner: sale orders, purchase orders, "
            "and invoices/bills. Useful for seeing a contact's activity history."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "partner_id": {
                    "type": "integer",
                    "description": "The partner record ID",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max records per transaction type (default 10)",
                    "default": 10,
                },
            },
            "required": ["partner_id"],
        },
        "kind": "integration",
    },
]

# ---------------------------------------------------------------------------
# Executor functions
# ---------------------------------------------------------------------------


def _odoo_search_partners(
    name: str = None, email: str = None, is_company: bool = None, limit: int = 20,
) -> dict:
    """Search contacts/partners by name, email, or company flag."""
    client, err = safe_get_client()
    if err:
        return err

    domain = []
    if name:
        domain.append(["name", "ilike", name])
    if email:
        domain.append(["email", "ilike", email])
    if is_company is not None:
        domain.append(["is_company", "=", is_company])

    fields = ["name", "email", "phone", "is_company", "company_type", "parent_id"]
    records = client.search_read("res.partner", domain, fields, limit=limit) or []

    partners = []
    for r in records:
        partners.append({
            "id": r["id"],
            "name": r.get("name", ""),
            "email": r.get("email", ""),
            "phone": r.get("phone", ""),
            "is_company": r.get("is_company", False),
            "parent": r["parent_id"][1] if r.get("parent_id") else None,
        })
    return {"partners": partners, "total": len(partners)}


def _odoo_get_partner_details(partner_id: int) -> dict:
    """Get full details for a single partner by ID."""
    client, err = safe_get_client()
    if err:
        return err

    fields = [
        "name", "email", "phone", "mobile",
        "street", "street2", "city", "state_id", "zip", "country_id",
        "website", "is_company", "company_type", "parent_id",
        "vat", "comment", "category_id",
        "create_date", "write_date",
        "customer_rank", "supplier_rank",
    ]
    records = client.read("res.partner", [partner_id], fields)
    if not records:
        return {"error": f"Partner with ID {partner_id} not found"}

    rec = records[0]

    # Flatten M2O fields
    partner = {
        "id": rec.get("id", partner_id),
        "name": rec.get("name", ""),
        "email": rec.get("email", ""),
        "phone": rec.get("phone", ""),
        "mobile": rec.get("mobile", ""),
        "street": rec.get("street", ""),
        "street2": rec.get("street2", ""),
        "city": rec.get("city", ""),
        "state": rec["state_id"][1] if isinstance(rec.get("state_id"), list) else None,
        "state_id": rec["state_id"][0] if isinstance(rec.get("state_id"), list) else None,
        "zip": rec.get("zip", ""),
        "country": rec["country_id"][1] if isinstance(rec.get("country_id"), list) else None,
        "country_id": rec["country_id"][0] if isinstance(rec.get("country_id"), list) else None,
        "website": rec.get("website", ""),
        "is_company": rec.get("is_company", False),
        "company_type": rec.get("company_type", ""),
        "parent_company": rec["parent_id"][1] if isinstance(rec.get("parent_id"), list) else None,
        "parent_id": rec["parent_id"][0] if isinstance(rec.get("parent_id"), list) else None,
        "vat": rec.get("vat", ""),
        "comment": rec.get("comment", ""),
        "tags": [
            tag[1] if isinstance(tag, list) else tag
            for tag in (rec.get("category_id") or [])
        ] if isinstance(rec.get("category_id"), list) else [],
        "create_date": rec.get("create_date", ""),
        "write_date": rec.get("write_date", ""),
        "customer_rank": rec.get("customer_rank", 0),
        "supplier_rank": rec.get("supplier_rank", 0),
    }
    return {"partner": partner}


def _odoo_create_partner(
    name: str,
    email: str = None,
    phone: str = None,
    mobile: str = None,
    is_company: bool = False,
    street: str = None,
    city: str = None,
    state_id: int = None,
    zip: str = None,
    country_id: int = None,
    website: str = None,
    parent_id: int = None,
    vat: str = None,
    comment: str = None,
) -> dict:
    """Create a new contact or company in Odoo."""
    client, err = safe_get_client()
    if err:
        return err

    vals: dict = {"name": name, "is_company": is_company}
    if email is not None:
        vals["email"] = email
    if phone is not None:
        vals["phone"] = phone
    if mobile is not None:
        vals["mobile"] = mobile
    if street is not None:
        vals["street"] = street
    if city is not None:
        vals["city"] = city
    if state_id is not None:
        vals["state_id"] = state_id
    if zip is not None:
        vals["zip"] = zip
    if country_id is not None:
        vals["country_id"] = country_id
    if website is not None:
        vals["website"] = website
    if parent_id is not None:
        vals["parent_id"] = parent_id
    if vat is not None:
        vals["vat"] = vat
    if comment is not None:
        vals["comment"] = comment

    try:
        partner_id = client.create("res.partner", vals)
    except Exception as e:
        return {"error": f"Odoo error creating partner: {e}"}

    if partner_id is None:
        return {"error": "Failed to create partner in Odoo"}

    # Read back the created partner
    return _odoo_get_partner_details(partner_id) | {"ok": True}


def _odoo_update_partner(
    partner_id: int,
    name: str = None,
    email: str = None,
    phone: str = None,
    mobile: str = None,
    street: str = None,
    city: str = None,
    state_id: int = None,
    zip: str = None,
    country_id: int = None,
    website: str = None,
    comment: str = None,
) -> dict:
    """Update fields on an existing partner."""
    client, err = safe_get_client()
    if err:
        return err

    vals: dict = {}
    if name is not None:
        vals["name"] = name
    if email is not None:
        vals["email"] = email
    if phone is not None:
        vals["phone"] = phone
    if mobile is not None:
        vals["mobile"] = mobile
    if street is not None:
        vals["street"] = street
    if city is not None:
        vals["city"] = city
    if state_id is not None:
        vals["state_id"] = state_id
    if zip is not None:
        vals["zip"] = zip
    if country_id is not None:
        vals["country_id"] = country_id
    if website is not None:
        vals["website"] = website
    if comment is not None:
        vals["comment"] = comment

    if not vals:
        return {"error": "Nothing to update -- provide at least one field to change"}

    try:
        client.write("res.partner", [partner_id], vals)
    except Exception as e:
        return {"error": f"Odoo error updating partner #{partner_id}: {e}"}

    return {"ok": True, "partner_id": partner_id, "updated": vals}


def _odoo_search_partner_contacts(company_id: int, limit: int = 50) -> dict:
    """Find child contacts belonging to a company partner."""
    client, err = safe_get_client()
    if err:
        return err

    fields = ["name", "email", "phone", "function"]
    records = client.search_read(
        "res.partner",
        [["parent_id", "=", company_id], ["is_company", "=", False]],
        fields,
        limit=limit,
    ) or []

    contacts = []
    for r in records:
        contacts.append({
            "id": r["id"],
            "name": r.get("name", ""),
            "email": r.get("email", ""),
            "phone": r.get("phone", ""),
            "job_title": r.get("function", ""),
        })
    return {"company_id": company_id, "contacts": contacts, "total": len(contacts)}


def _odoo_get_partner_transactions(partner_id: int, limit: int = 10) -> dict:
    """Get recent sales, purchases, and invoices for a partner."""
    client, err = safe_get_client()
    if err:
        return err

    # --- Sale orders ---
    sale_orders = client.search_read(
        "sale.order",
        [["partner_id", "=", partner_id]],
        ["name", "date_order", "state", "amount_total", "currency_id"],
        limit=limit,
        order="date_order desc",
    ) or []

    sales = []
    for so in sale_orders:
        sales.append({
            "id": so["id"],
            "name": so.get("name", ""),
            "date": so.get("date_order", ""),
            "state": so.get("state", ""),
            "amount_total": so.get("amount_total", 0),
            "currency": so["currency_id"][1] if isinstance(so.get("currency_id"), list) else "",
        })

    # --- Purchase orders ---
    purchase_orders = client.search_read(
        "purchase.order",
        [["partner_id", "=", partner_id]],
        ["name", "date_order", "state", "amount_total", "currency_id"],
        limit=limit,
        order="date_order desc",
    ) or []

    purchases = []
    for po in purchase_orders:
        purchases.append({
            "id": po["id"],
            "name": po.get("name", ""),
            "date": po.get("date_order", ""),
            "state": po.get("state", ""),
            "amount_total": po.get("amount_total", 0),
            "currency": po["currency_id"][1] if isinstance(po.get("currency_id"), list) else "",
        })

    # --- Invoices / bills (account.move) ---
    invoices_raw = client.search_read(
        "account.move",
        [["partner_id", "=", partner_id], ["move_type", "in", ["out_invoice", "out_refund", "in_invoice", "in_refund"]]],
        ["name", "invoice_date", "state", "move_type", "amount_total", "amount_residual", "currency_id"],
        limit=limit,
        order="invoice_date desc",
    ) or []

    invoices = []
    for inv in invoices_raw:
        invoices.append({
            "id": inv["id"],
            "name": inv.get("name", ""),
            "date": inv.get("invoice_date", ""),
            "state": inv.get("state", ""),
            "type": inv.get("move_type", ""),
            "amount_total": inv.get("amount_total", 0),
            "amount_due": inv.get("amount_residual", 0),
            "currency": inv["currency_id"][1] if isinstance(inv.get("currency_id"), list) else "",
        })

    return {
        "partner_id": partner_id,
        "sales": sales,
        "purchases": purchases,
        "invoices": invoices,
    }


# ---------------------------------------------------------------------------
# Executor map
# ---------------------------------------------------------------------------

CONTACTS_EXECUTORS = {
    "odoo_search_partners": lambda **kw: _odoo_search_partners(**kw),
    "odoo_get_partner_details": lambda **kw: _odoo_get_partner_details(**kw),
    "odoo_create_partner": lambda **kw: _odoo_create_partner(**kw),
    "odoo_update_partner": lambda **kw: _odoo_update_partner(**kw),
    "odoo_search_partner_contacts": lambda **kw: _odoo_search_partner_contacts(**kw),
    "odoo_get_partner_transactions": lambda **kw: _odoo_get_partner_transactions(**kw),
}
