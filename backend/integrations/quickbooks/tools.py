"""Chatty — QuickBooks Online agent tools."""

from .client import get_client

QB_TOOL_DEFS = [
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
]


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


TOOL_EXECUTORS = {
    "qbo_query": lambda **kw: qbo_query(**kw),
    "qbo_profit_and_loss": lambda **kw: qbo_profit_and_loss(**kw),
}
