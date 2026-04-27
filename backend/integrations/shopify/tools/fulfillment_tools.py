from integrations.shopify.client import get_client

FULFILLMENT_TOOL_DEFS = [
    {
        "name": "shopify_get_fulfillments",
        "description": "List fulfillments for a Shopify order.",
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
        "name": "shopify_get_fulfillment",
        "description": "Get a specific fulfillment for a Shopify order.",
        "input_schema": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string", "description": "The order ID"},
                "fulfillment_id": {"type": "string", "description": "The fulfillment ID"},
            },
            "required": ["order_id", "fulfillment_id"],
        },
        "kind": "integration",
        "writes": False,
    },
    {
        "name": "shopify_create_fulfillment_event",
        "description": "Create a fulfillment tracking event (e.g. in_transit, delivered).",
        "input_schema": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string", "description": "The order ID"},
                "fulfillment_id": {"type": "string", "description": "The fulfillment ID"},
                "status": {
                    "type": "string",
                    "enum": ["confirmed", "in_transit", "out_for_delivery", "attempted_delivery", "delivered", "failure",
                             "label_printed", "label_purchased", "ready_for_pickup", "picked_up", "carrier_picked_up", "delayed"],
                    "description": "Fulfillment event status",
                },
                "message": {"type": "string", "description": "Optional status message"},
            },
            "required": ["order_id", "fulfillment_id", "status"],
        },
        "kind": "integration",
        "writes": True,
    },
]


def shopify_get_fulfillments(**kwargs) -> dict | str:
    client = get_client()
    if not client:
        return "Shopify is not connected. Set it up in Settings → Integrations."
    result = client.get(f"/orders/{kwargs['order_id']}/fulfillments.json")
    if not result["ok"]:
        return f"Failed to fetch fulfillments: {result['data']}"
    return {"fulfillments": result["data"].get("fulfillments", [])}


def shopify_get_fulfillment(**kwargs) -> dict | str:
    client = get_client()
    if not client:
        return "Shopify is not connected. Set it up in Settings → Integrations."
    result = client.get(f"/orders/{kwargs['order_id']}/fulfillments/{kwargs['fulfillment_id']}.json")
    if not result["ok"]:
        return f"Failed to fetch fulfillment: {result['data']}"
    return result["data"].get("fulfillment", result["data"])


def shopify_create_fulfillment_event(**kwargs) -> dict | str:
    client = get_client()
    if not client:
        return "Shopify is not connected. Set it up in Settings → Integrations."
    event: dict = {"status": kwargs["status"]}
    if kwargs.get("message"):
        event["message"] = kwargs["message"]
    result = client.post(
        f"/orders/{kwargs['order_id']}/fulfillments/{kwargs['fulfillment_id']}/events.json",
        json_body={"event": event},
    )
    if not result["ok"]:
        return f"Failed to create fulfillment event: {result['data']}"
    return result["data"].get("fulfillment_event", result["data"])


FULFILLMENT_EXECUTORS = {
    "shopify_get_fulfillments": lambda **kw: shopify_get_fulfillments(**kw),
    "shopify_get_fulfillment": lambda **kw: shopify_get_fulfillment(**kw),
    "shopify_create_fulfillment_event": lambda **kw: shopify_create_fulfillment_event(**kw),
}
