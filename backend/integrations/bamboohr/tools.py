"""Chatty — BambooHR agent tools."""

from .client import get_client

BAMBOOHR_TOOL_DEFS = [
    {
        "name": "bamboohr_get_directory",
        "description": "Get the BambooHR employee directory — names, titles, departments.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
        "kind": "integration",
    },
    {
        "name": "bamboohr_get_employee",
        "description": "Get details for a specific employee by their BambooHR ID.",
        "input_schema": {
            "type": "object",
            "properties": {
                "employee_id": {"type": "string", "description": "BambooHR employee ID"},
            },
            "required": ["employee_id"],
        },
        "kind": "integration",
    },
    {
        "name": "bamboohr_get_time_off",
        "description": "Get approved time-off requests for a date range.",
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


def bamboohr_get_directory() -> dict:
    client = get_client()
    if not client:
        return {"error": "BambooHR not configured or unavailable"}
    employees = client.get_employee_directory()
    return {"employees": employees, "count": len(employees)}


def bamboohr_get_employee(employee_id: str) -> dict:
    client = get_client()
    if not client:
        return {"error": "BambooHR not configured or unavailable"}
    return client.get_employee(employee_id)


def bamboohr_get_time_off(start_date: str, end_date: str) -> dict:
    client = get_client()
    if not client:
        return {"error": "BambooHR not configured or unavailable"}
    requests = client.get_time_off_requests(start_date, end_date)
    return {"requests": requests, "count": len(requests)}


TOOL_EXECUTORS = {
    "bamboohr_get_directory": lambda **kw: bamboohr_get_directory(),
    "bamboohr_get_employee": lambda **kw: bamboohr_get_employee(**kw),
    "bamboohr_get_time_off": lambda **kw: bamboohr_get_time_off(**kw),
}
