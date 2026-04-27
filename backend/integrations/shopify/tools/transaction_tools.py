from integrations.shopify.client import get_client

TRANSACTION_TOOL_DEFS = [
    {
        "name": "shopify_get_transactions",
        "description": "List transactions for a Shopify order.",
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
        "name": "shopify_get_transaction",
        "description": "Get a specific transaction for a Shopify order.",
        "input_schema": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string", "description": "The order ID"},
                "transaction_id": {"type": "string", "description": "The transaction ID"},
            },
            "required": ["order_id", "transaction_id"],
        },
        "kind": "integration",
        "writes": False,
    },
    {
        "name": "shopify_create_transaction",
        "description": "Create a transaction for a Shopify order (capture, void, or refund).",
        "input_schema": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string", "description": "The order ID"},
                "kind": {"type": "string", "enum": ["authorization", "sale", "capture", "void", "refund"], "description": "Transaction kind"},
                "amount": {"type": "string", "description": "Transaction amount"},
                "currency": {"type": "string", "description": "Currency code (e.g. USD)"},
                "parent_id": {"type": "string", "description": "Parent transaction ID (required for capture/void/refund)"},
            },
            "required": ["order_id", "kind"],
        },
        "kind": "integration",
        "writes": True,
    },
]


def shopify_get_transactions(**kwargs) -> dict | str:
    client = get_client()
    if not client:
        return "Shopify is not connected. Set it up in Settings → Integrations."
    result = client.get(f"/orders/{kwargs['order_id']}/transactions.json")
    if not result["ok"]:
        return f"Failed to fetch transactions: {result['data']}"
    return {"transactions": result["data"].get("transactions", [])}


def shopify_get_transaction(**kwargs) -> dict | str:
    client = get_client()
    if not client:
        return "Shopify is not connected. Set it up in Settings → Integrations."
    result = client.get(f"/orders/{kwargs['order_id']}/transactions/{kwargs['transaction_id']}.json")
    if not result["ok"]:
        return f"Failed to fetch transaction: {result['data']}"
    return result["data"].get("transaction", result["data"])


def shopify_create_transaction(**kwargs) -> dict | str:
    client = get_client()
    if not client:
        return "Shopify is not connected. Set it up in Settings → Integrations."
    txn: dict = {"kind": kwargs["kind"]}
    for key in ("amount", "currency", "parent_id"):
        if kwargs.get(key):
            txn[key] = kwargs[key]
    result = client.post(f"/orders/{kwargs['order_id']}/transactions.json", json_body={"transaction": txn})
    if not result["ok"]:
        return f"Failed to create transaction: {result['data']}"
    return result["data"].get("transaction", result["data"])


TRANSACTION_EXECUTORS = {
    "shopify_get_transactions": lambda **kw: shopify_get_transactions(**kw),
    "shopify_get_transaction": lambda **kw: shopify_get_transaction(**kw),
    "shopify_create_transaction": lambda **kw: shopify_create_transaction(**kw),
}
