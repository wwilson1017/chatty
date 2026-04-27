from integrations.shopify.client import get_client

CUSTOMER_TOOL_DEFS = [
    {
        "name": "shopify_get_customers",
        "description": "List Shopify customers with optional search. Returns customers with pagination support.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query (name, email, etc.)"},
                "limit": {"type": "integer", "description": "Max results per page (default 50, max 250)"},
                "page_info": {"type": "string", "description": "Cursor for next page"},
            },
            "required": [],
        },
        "kind": "integration",
        "writes": False,
    },
    {
        "name": "shopify_get_customer",
        "description": "Get a single Shopify customer by ID.",
        "input_schema": {
            "type": "object",
            "properties": {
                "customer_id": {"type": "string", "description": "The customer ID"},
            },
            "required": ["customer_id"],
        },
        "kind": "integration",
        "writes": False,
    },
    {
        "name": "shopify_create_customer",
        "description": "Create a new Shopify customer.",
        "input_schema": {
            "type": "object",
            "properties": {
                "first_name": {"type": "string", "description": "First name"},
                "last_name": {"type": "string", "description": "Last name"},
                "email": {"type": "string", "description": "Email address"},
                "phone": {"type": "string", "description": "Phone number"},
                "tags": {"type": "string", "description": "Comma-separated tags"},
                "note": {"type": "string", "description": "Note about the customer"},
                "accepts_marketing": {"type": "boolean", "description": "Accepts email marketing"},
            },
            "required": [],
        },
        "kind": "integration",
        "writes": True,
    },
    {
        "name": "shopify_update_customer",
        "description": "Update an existing Shopify customer.",
        "input_schema": {
            "type": "object",
            "properties": {
                "customer_id": {"type": "string", "description": "The customer ID to update"},
                "first_name": {"type": "string", "description": "First name"},
                "last_name": {"type": "string", "description": "Last name"},
                "email": {"type": "string", "description": "Email address"},
                "phone": {"type": "string", "description": "Phone number"},
                "tags": {"type": "string", "description": "Comma-separated tags"},
                "note": {"type": "string", "description": "Note about the customer"},
            },
            "required": ["customer_id"],
        },
        "kind": "integration",
        "writes": True,
    },
    {
        "name": "shopify_get_customer_orders",
        "description": "List orders for a specific Shopify customer.",
        "input_schema": {
            "type": "object",
            "properties": {
                "customer_id": {"type": "string", "description": "The customer ID"},
                "status": {"type": "string", "enum": ["open", "closed", "cancelled", "any"], "description": "Order status filter"},
                "limit": {"type": "integer", "description": "Max results (default 50)"},
            },
            "required": ["customer_id"],
        },
        "kind": "integration",
        "writes": False,
    },
]


def shopify_get_customers(**kwargs) -> dict | str:
    client = get_client()
    if not client:
        return "Shopify is not connected. Set it up in Settings → Integrations."
    params = {}
    if kwargs.get("page_info"):
        params["page_info"] = kwargs["page_info"]
    else:
        if kwargs.get("query"):
            params["query"] = kwargs["query"]
    params["limit"] = min(kwargs.get("limit", 50), 250)
    result = client.get("/customers.json", params=params)
    if not result["ok"]:
        return f"Failed to fetch customers: {result['data']}"
    customers = result["data"].get("customers", [])
    return {"customers": customers, "count": len(customers), "next_page_info": result["next_page_info"]}


def shopify_get_customer(**kwargs) -> dict | str:
    client = get_client()
    if not client:
        return "Shopify is not connected. Set it up in Settings → Integrations."
    result = client.get(f"/customers/{kwargs['customer_id']}.json")
    if not result["ok"]:
        return f"Failed to fetch customer: {result['data']}"
    return result["data"].get("customer", result["data"])


def shopify_create_customer(**kwargs) -> dict | str:
    client = get_client()
    if not client:
        return "Shopify is not connected. Set it up in Settings → Integrations."
    customer: dict = {}
    for key in ("first_name", "last_name", "email", "phone", "tags", "note"):
        if kwargs.get(key):
            customer[key] = kwargs[key]
    if kwargs.get("accepts_marketing") is not None:
        customer["email_marketing_consent"] = {
            "state": "subscribed" if kwargs["accepts_marketing"] else "unsubscribed",
            "opt_in_level": "single_opt_in",
        }
    result = client.post("/customers.json", json_body={"customer": customer})
    if not result["ok"]:
        return f"Failed to create customer: {result['data']}"
    return result["data"].get("customer", result["data"])


def shopify_update_customer(**kwargs) -> dict | str:
    client = get_client()
    if not client:
        return "Shopify is not connected. Set it up in Settings → Integrations."
    customer: dict = {}
    for key in ("first_name", "last_name", "email", "phone", "tags", "note"):
        if kwargs.get(key) is not None:
            customer[key] = kwargs[key]
    result = client.put(f"/customers/{kwargs['customer_id']}.json", json_body={"customer": customer})
    if not result["ok"]:
        return f"Failed to update customer: {result['data']}"
    return result["data"].get("customer", result["data"])


def shopify_get_customer_orders(**kwargs) -> dict | str:
    client = get_client()
    if not client:
        return "Shopify is not connected. Set it up in Settings → Integrations."
    params: dict = {}
    if kwargs.get("status"):
        params["status"] = kwargs["status"]
    params["limit"] = min(kwargs.get("limit", 50), 250)
    result = client.get(f"/customers/{kwargs['customer_id']}/orders.json", params=params)
    if not result["ok"]:
        return f"Failed to fetch customer orders: {result['data']}"
    orders = result["data"].get("orders", [])
    return {"orders": orders, "count": len(orders)}


CUSTOMER_EXECUTORS = {
    "shopify_get_customers": lambda **kw: shopify_get_customers(**kw),
    "shopify_get_customer": lambda **kw: shopify_get_customer(**kw),
    "shopify_create_customer": lambda **kw: shopify_create_customer(**kw),
    "shopify_update_customer": lambda **kw: shopify_update_customer(**kw),
    "shopify_get_customer_orders": lambda **kw: shopify_get_customer_orders(**kw),
}
