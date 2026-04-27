from integrations.shopify.client import get_client

ORDER_TOOL_DEFS = [
    {
        "name": "shopify_get_orders",
        "description": "List Shopify orders with optional filters. Returns orders with pagination support.",
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["open", "closed", "cancelled", "any"], "description": "Order status filter (default: open)"},
                "financial_status": {"type": "string", "enum": ["authorized", "pending", "paid", "partially_paid", "refunded", "voided", "partially_refunded", "any"], "description": "Financial status filter"},
                "fulfillment_status": {"type": "string", "enum": ["shipped", "partial", "unshipped", "any", "unfulfilled"], "description": "Fulfillment status filter"},
                "created_at_min": {"type": "string", "description": "Minimum creation date (ISO 8601)"},
                "created_at_max": {"type": "string", "description": "Maximum creation date (ISO 8601)"},
                "limit": {"type": "integer", "description": "Max results per page (default 50, max 250)"},
                "page_info": {"type": "string", "description": "Cursor for next page (from previous response's next_page_info)"},
            },
            "required": [],
        },
        "kind": "integration",
        "writes": False,
    },
    {
        "name": "shopify_get_order",
        "description": "Get a single Shopify order by ID with full details.",
        "input_schema": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string", "description": "The order ID"},
            },
            "required": ["order_id"],
        },
        "kind": "integration",
        "writes": False,
    },
    {
        "name": "shopify_create_order",
        "description": "Create a new Shopify order.",
        "input_schema": {
            "type": "object",
            "properties": {
                "line_items": {
                    "type": "array",
                    "description": "Array of line items. Each needs variant_id or (title + price)",
                    "items": {
                        "type": "object",
                        "properties": {
                            "variant_id": {"type": "integer", "description": "Product variant ID"},
                            "product_id": {"type": "integer", "description": "Product ID"},
                            "title": {"type": "string", "description": "Line item title (if no variant_id)"},
                            "quantity": {"type": "integer", "description": "Quantity (default 1)"},
                            "price": {"type": "string", "description": "Price per item (if no variant_id)"},
                        },
                    },
                },
                "customer_id": {"type": "integer", "description": "Existing customer ID"},
                "email": {"type": "string", "description": "Customer email"},
                "financial_status": {"type": "string", "enum": ["pending", "authorized", "partially_paid", "paid"], "description": "Financial status"},
                "tags": {"type": "string", "description": "Comma-separated tags"},
                "note": {"type": "string", "description": "Order note"},
                "send_receipt": {"type": "boolean", "description": "Send order confirmation email"},
                "send_fulfillment_receipt": {"type": "boolean", "description": "Send fulfillment email"},
            },
            "required": ["line_items"],
        },
        "kind": "integration",
        "writes": True,
    },
    {
        "name": "shopify_update_order",
        "description": "Update an existing Shopify order (note, tags, email, phone).",
        "input_schema": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string", "description": "The order ID to update"},
                "note": {"type": "string", "description": "Order note"},
                "tags": {"type": "string", "description": "Comma-separated tags"},
                "email": {"type": "string", "description": "Customer email"},
                "phone": {"type": "string", "description": "Customer phone"},
            },
            "required": ["order_id"],
        },
        "kind": "integration",
        "writes": True,
    },
    {
        "name": "shopify_cancel_order",
        "description": "Cancel a Shopify order.",
        "input_schema": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string", "description": "The order ID to cancel"},
                "reason": {"type": "string", "enum": ["customer", "fraud", "inventory", "declined", "other"], "description": "Cancellation reason"},
                "restock": {"type": "boolean", "description": "Whether to restock items (default true)"},
                "email": {"type": "boolean", "description": "Send cancellation email to customer"},
            },
            "required": ["order_id"],
        },
        "kind": "integration",
        "writes": True,
    },
    {
        "name": "shopify_close_order",
        "description": "Close (archive) a Shopify order.",
        "input_schema": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string", "description": "The order ID to close"},
            },
            "required": ["order_id"],
        },
        "kind": "integration",
        "writes": True,
    },
]


def shopify_get_orders(**kwargs) -> dict | str:
    client = get_client()
    if not client:
        return "Shopify is not connected. Set it up in Settings → Integrations."
    params = {}
    if kwargs.get("page_info"):
        params["page_info"] = kwargs["page_info"]
    else:
        for key in ("status", "financial_status", "fulfillment_status", "created_at_min", "created_at_max"):
            if kwargs.get(key):
                params[key] = kwargs[key]
    params["limit"] = min(kwargs.get("limit", 50), 250)
    result = client.get("/orders.json", params=params)
    if not result["ok"]:
        return f"Failed to fetch orders: {result['data']}"
    orders = result["data"].get("orders", [])
    return {"orders": orders, "count": len(orders), "next_page_info": result["next_page_info"]}


def shopify_get_order(**kwargs) -> dict | str:
    client = get_client()
    if not client:
        return "Shopify is not connected. Set it up in Settings → Integrations."
    result = client.get(f"/orders/{kwargs['order_id']}.json")
    if not result["ok"]:
        return f"Failed to fetch order: {result['data']}"
    return result["data"].get("order", result["data"])


def shopify_create_order(**kwargs) -> dict | str:
    client = get_client()
    if not client:
        return "Shopify is not connected. Set it up in Settings → Integrations."
    order: dict = {"line_items": kwargs["line_items"]}
    if kwargs.get("customer_id"):
        order["customer"] = {"id": kwargs["customer_id"]}
    for key in ("email", "financial_status", "tags", "note"):
        if kwargs.get(key):
            order[key] = kwargs[key]
    if kwargs.get("send_receipt") is not None:
        order["send_receipt"] = kwargs["send_receipt"]
    if kwargs.get("send_fulfillment_receipt") is not None:
        order["send_fulfillment_receipt"] = kwargs["send_fulfillment_receipt"]
    result = client.post("/orders.json", json_body={"order": order})
    if not result["ok"]:
        return f"Failed to create order: {result['data']}"
    return result["data"].get("order", result["data"])


def shopify_update_order(**kwargs) -> dict | str:
    client = get_client()
    if not client:
        return "Shopify is not connected. Set it up in Settings → Integrations."
    order: dict = {}
    for key in ("note", "tags", "email", "phone"):
        if kwargs.get(key) is not None:
            order[key] = kwargs[key]
    result = client.put(f"/orders/{kwargs['order_id']}.json", json_body={"order": order})
    if not result["ok"]:
        return f"Failed to update order: {result['data']}"
    return result["data"].get("order", result["data"])


def shopify_cancel_order(**kwargs) -> dict | str:
    client = get_client()
    if not client:
        return "Shopify is not connected. Set it up in Settings → Integrations."
    body: dict = {}
    if kwargs.get("reason"):
        body["reason"] = kwargs["reason"]
    if kwargs.get("restock") is not None:
        body["restock"] = kwargs["restock"]
    if kwargs.get("email") is not None:
        body["email"] = kwargs["email"]
    result = client.post(f"/orders/{kwargs['order_id']}/cancel.json", json_body=body)
    if not result["ok"]:
        return f"Failed to cancel order: {result['data']}"
    return result["data"].get("order", result["data"])


def shopify_close_order(**kwargs) -> dict | str:
    client = get_client()
    if not client:
        return "Shopify is not connected. Set it up in Settings → Integrations."
    result = client.post(f"/orders/{kwargs['order_id']}/close.json", json_body={})
    if not result["ok"]:
        return f"Failed to close order: {result['data']}"
    return result["data"].get("order", result["data"])


ORDER_EXECUTORS = {
    "shopify_get_orders": lambda **kw: shopify_get_orders(**kw),
    "shopify_get_order": lambda **kw: shopify_get_order(**kw),
    "shopify_create_order": lambda **kw: shopify_create_order(**kw),
    "shopify_update_order": lambda **kw: shopify_update_order(**kw),
    "shopify_cancel_order": lambda **kw: shopify_cancel_order(**kw),
    "shopify_close_order": lambda **kw: shopify_close_order(**kw),
}
