from integrations.shopify.client import get_client

INVENTORY_TOOL_DEFS = [
    {
        "name": "shopify_get_locations",
        "description": "List all Shopify inventory locations.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
        "kind": "integration",
        "writes": False,
    },
    {
        "name": "shopify_adjust_inventory",
        "description": "Adjust inventory level of an item at a location. Use positive number to add stock, negative to remove.",
        "input_schema": {
            "type": "object",
            "properties": {
                "inventory_item_id": {"type": "integer", "description": "The inventory item ID (from product variant)"},
                "location_id": {"type": "integer", "description": "The location ID (from shopify_get_locations)"},
                "available_adjustment": {"type": "integer", "description": "Amount to adjust (positive to add, negative to remove)"},
            },
            "required": ["inventory_item_id", "location_id", "available_adjustment"],
        },
        "kind": "integration",
        "writes": True,
    },
]


def shopify_get_locations(**kwargs) -> dict | str:
    client = get_client()
    if not client:
        return "Shopify is not connected. Set it up in Settings → Integrations."
    result = client.get("/locations.json")
    if not result["ok"]:
        return f"Failed to fetch locations: {result['data']}"
    return {"locations": result["data"].get("locations", [])}


def shopify_adjust_inventory(**kwargs) -> dict | str:
    client = get_client()
    if not client:
        return "Shopify is not connected. Set it up in Settings → Integrations."
    result = client.post("/inventory_levels/adjust.json", json_body={
        "inventory_item_id": kwargs["inventory_item_id"],
        "location_id": kwargs["location_id"],
        "available_adjustment": kwargs["available_adjustment"],
    })
    if not result["ok"]:
        return f"Failed to adjust inventory: {result['data']}"
    return result["data"].get("inventory_level", result["data"])


INVENTORY_EXECUTORS = {
    "shopify_get_locations": lambda **kw: shopify_get_locations(**kw),
    "shopify_adjust_inventory": lambda **kw: shopify_adjust_inventory(**kw),
}
