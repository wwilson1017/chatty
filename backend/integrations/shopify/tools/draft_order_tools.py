from integrations.shopify.client import get_client

DRAFT_ORDER_TOOL_DEFS = [
    {
        "name": "shopify_create_draft_order",
        "description": "Create a Shopify draft order (quote/estimate). Can be sent to the customer or converted to a real order.",
        "input_schema": {
            "type": "object",
            "properties": {
                "line_items": {
                    "type": "array",
                    "description": "Array of line items",
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
                "note": {"type": "string", "description": "Draft order note"},
                "tags": {"type": "string", "description": "Comma-separated tags"},
            },
            "required": ["line_items"],
        },
        "kind": "integration",
        "writes": True,
    },
]


def shopify_create_draft_order(**kwargs) -> dict | str:
    client = get_client()
    if not client:
        return "Shopify is not connected. Set it up in Settings → Integrations."
    draft: dict = {"line_items": kwargs["line_items"]}
    if kwargs.get("customer_id"):
        draft["customer"] = {"id": kwargs["customer_id"]}
    for key in ("note", "tags"):
        if kwargs.get(key):
            draft[key] = kwargs[key]
    result = client.post("/draft_orders.json", json_body={"draft_order": draft})
    if not result["ok"]:
        return f"Failed to create draft order: {result['data']}"
    return result["data"].get("draft_order", result["data"])


DRAFT_ORDER_EXECUTORS = {
    "shopify_create_draft_order": lambda **kw: shopify_create_draft_order(**kw),
}
