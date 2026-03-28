"""Chatty — BambooHR agent tools.

Curated high-value tools (employee name resolution, formatted output) plus
a generic tool for full BambooHR API coverage.
"""

from datetime import date

from .client import get_client

BAMBOOHR_TOOL_DEFS = [
    {
        "name": "bamboohr_get_directory",
        "description": "Get the BambooHR employee directory — names, titles, departments. Optionally filter by department.",
        "input_schema": {
            "type": "object",
            "properties": {
                "department": {"type": "string", "description": "Filter by department name (case-insensitive partial match)"},
            },
            "required": [],
        },
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
        "name": "bamboohr_get_employee_details",
        "description": "Get a full employee profile by name. Resolves name to ID automatically.",
        "input_schema": {
            "type": "object",
            "properties": {
                "employee_name": {"type": "string", "description": "Employee name (first, last, or full)"},
                "fields": {"type": "string", "description": "Comma-separated field names to return. Defaults to a broad set of common fields."},
            },
            "required": ["employee_name"],
        },
        "kind": "integration",
    },
    {
        "name": "bamboohr_whos_out",
        "description": "Check who is out of office today or in a date range.",
        "input_schema": {
            "type": "object",
            "properties": {
                "start_date": {"type": "string", "description": "Start date YYYY-MM-DD (defaults to today)"},
                "end_date": {"type": "string", "description": "End date YYYY-MM-DD"},
            },
            "required": [],
        },
        "kind": "integration",
    },
    {
        "name": "bamboohr_get_time_off_requests",
        "description": "List time-off requests for a date range, optionally filtered by employee name or status.",
        "input_schema": {
            "type": "object",
            "properties": {
                "start_date": {"type": "string", "description": "Start date YYYY-MM-DD"},
                "end_date": {"type": "string", "description": "End date YYYY-MM-DD"},
                "employee_name": {"type": "string", "description": "Filter by employee name"},
                "status": {"type": "string", "description": "Filter by status (approved, denied, cancelled, requested)"},
            },
            "required": ["start_date", "end_date"],
        },
        "kind": "integration",
    },
    {
        "name": "bamboohr_get_time_off_balance",
        "description": "Check an employee's PTO/time-off balance by name.",
        "input_schema": {
            "type": "object",
            "properties": {
                "employee_name": {"type": "string", "description": "Employee name"},
                "end_date": {"type": "string", "description": "Balance as of this date (YYYY-MM-DD, defaults to today)"},
            },
            "required": ["employee_name"],
        },
        "kind": "integration",
    },
    {
        "name": "bamboohr_api_request",
        "description": "Execute any BambooHR API request. Use for endpoints not covered by other tools. Common paths: /api/v1/employees/directory, /api/v1/time_off/whos_out, /api/v1/employees/{id}.",
        "input_schema": {
            "type": "object",
            "properties": {
                "method": {"type": "string", "description": "HTTP method (GET, POST, PUT, DELETE)", "enum": ["GET", "POST", "PUT", "DELETE"]},
                "path": {"type": "string", "description": "API path (e.g. /api/v1/time_off/whos_out)"},
                "params": {"type": "object", "description": "Query parameters"},
                "body": {"type": "object", "description": "JSON request body (for POST/PUT)"},
                "path_params": {"type": "object", "description": "Path parameter substitutions for {placeholders}"},
            },
            "required": ["method", "path"],
        },
        "kind": "integration",
    },
    # Keep legacy tool name for backwards compatibility
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


# ── Employee name resolution ─────────────────────────────────────────────


def _resolve_employee(employee_name: str) -> tuple[dict | None, dict | None]:
    """Resolve an employee name to a directory entry.

    Uses the BambooHR directory API (no external dependencies).

    Returns (employee_dict, None) on unique match,
    or (None, error_dict) if ambiguous or not found.
    """
    client = get_client()
    if not client:
        return None, {"error": "BambooHR not configured or unavailable"}

    employees = client.get_employee_directory()
    if not employees:
        return None, {"error": "Could not fetch employee directory"}

    name_lower = employee_name.strip().lower()

    # Exact match on displayName
    exact = [e for e in employees if (e.get("displayName", "") or "").lower() == name_lower]
    if len(exact) == 1:
        return exact[0], None

    # Fuzzy: all query words appear in the display name
    fuzzy = [
        e for e in employees
        if all(word in (e.get("displayName", "") or "").lower() for word in name_lower.split())
    ]
    if len(fuzzy) == 1:
        return fuzzy[0], None
    if len(fuzzy) > 1:
        names = [
            f"{e.get('displayName', '')} (ID {e.get('id', '')}, {e.get('department', '')})"
            for e in fuzzy
        ]
        return None, {
            "error": f"Multiple employees match '{employee_name}'. Please be more specific.",
            "matches": names,
        }

    return None, {"error": f"Could not find employee matching '{employee_name}'"}


# ── Tool handlers ─────────────────────────────────────────────────────────


def bamboohr_get_directory(department: str | None = None) -> dict:
    client = get_client()
    if not client:
        return {"error": "BambooHR not configured or unavailable"}
    employees = client.get_employee_directory()

    if department:
        dept_lower = department.lower()
        employees = [
            e for e in employees
            if dept_lower in (e.get("department", "") or "").lower()
        ]

    condensed = []
    for e in employees:
        condensed.append({
            "id": e.get("id", ""),
            "displayName": e.get("displayName", ""),
            "firstName": e.get("firstName", ""),
            "lastName": e.get("lastName", ""),
            "jobTitle": e.get("jobTitle", ""),
            "department": e.get("department", ""),
            "location": e.get("location", ""),
            "workEmail": e.get("workEmail", ""),
        })

    return {"employees": condensed, "count": len(condensed)}


def bamboohr_get_employee(employee_id: str) -> dict:
    client = get_client()
    if not client:
        return {"error": "BambooHR not configured or unavailable"}
    return client.get_employee(employee_id)


def bamboohr_get_employee_details(
    employee_name: str, fields: str | None = None,
) -> dict:
    emp, err = _resolve_employee(employee_name)
    if err:
        return err

    client = get_client()
    if not client:
        return {"error": "BambooHR not configured or unavailable"}

    params: dict = {}
    if fields:
        params["fields"] = fields
    else:
        params["fields"] = (
            "firstName,lastName,preferredName,displayName,jobTitle,department,"
            "division,location,workEmail,workPhone,mobilePhone,hireDate,"
            "status,employmentHistoryStatus,supervisor,dateOfBirth,"
            "address1,city,state,zip"
        )

    emp_id = emp.get("id", "")
    path = f"/api/v1/employees/{emp_id}"
    result = client.api_request("GET", path, params=params)
    if not result["ok"]:
        return {"error": f"BambooHR API error: {result['status_code']}", "detail": result["data"]}

    return {
        "employee": emp.get("displayName", ""),
        "employee_id": emp_id,
        "details": result["data"],
    }


def bamboohr_whos_out(
    start_date: str | None = None, end_date: str | None = None,
) -> dict:
    client = get_client()
    if not client:
        return {"error": "BambooHR not configured or unavailable"}

    params: dict = {}
    if start_date:
        params["start"] = start_date
    if end_date:
        params["end"] = end_date

    result = client.api_request("GET", "/api/v1/time_off/whos_out", params=params)
    if not result["ok"]:
        return {"error": f"BambooHR API error: {result['status_code']}", "detail": result["data"]}

    data = result["data"]
    if not isinstance(data, list):
        return {"entries": [], "message": "No one is out for this period"}

    entries = []
    for item in data:
        entries.append({
            "type": item.get("type", ""),
            "name": item.get("name", ""),
            "start": item.get("start", ""),
            "end": item.get("end", ""),
        })

    return {"entries": entries, "count": len(entries)}


def bamboohr_get_time_off_requests(
    start_date: str,
    end_date: str,
    employee_name: str | None = None,
    status: str | None = None,
) -> dict:
    client = get_client()
    if not client:
        return {"error": "BambooHR not configured or unavailable"}

    params: dict = {"start": start_date, "end": end_date}
    if status:
        params["status"] = status

    if employee_name:
        emp, err = _resolve_employee(employee_name)
        if err:
            return err
        params["employeeId"] = emp.get("id", "")

    result = client.api_request("GET", "/api/v1/time_off/requests", params=params)
    if not result["ok"]:
        return {"error": f"BambooHR API error: {result['status_code']}", "detail": result["data"]}

    data = result["data"]
    if not isinstance(data, list):
        data = []

    requests = []
    for req in data:
        requests.append({
            "id": req.get("id", ""),
            "employee_name": req.get("name", ""),
            "status": req.get("status", {}).get("status", "") if isinstance(req.get("status"), dict) else req.get("status", ""),
            "type": req.get("type", {}).get("name", "") if isinstance(req.get("type"), dict) else req.get("type", ""),
            "start": req.get("start", ""),
            "end": req.get("end", ""),
            "notes": req.get("notes", {}).get("employee", "") if isinstance(req.get("notes"), dict) else "",
            "amount": req.get("amount", {}).get("amount", "") if isinstance(req.get("amount"), dict) else req.get("amount", ""),
        })

    return {"requests": requests, "count": len(requests)}


def bamboohr_get_time_off_balance(
    employee_name: str, end_date: str | None = None,
) -> dict:
    emp, err = _resolve_employee(employee_name)
    if err:
        return err

    client = get_client()
    if not client:
        return {"error": "BambooHR not configured or unavailable"}

    end = end_date or date.today().isoformat()
    emp_id = emp.get("id", "")
    path = f"/api/v1/employees/{emp_id}/time_off/calculator"
    result = client.api_request("GET", path, params={"end": end})
    if not result["ok"]:
        return {"error": f"BambooHR API error: {result['status_code']}", "detail": result["data"]}

    return {
        "employee": emp.get("displayName", ""),
        "employee_id": emp_id,
        "as_of": end,
        "balances": result["data"],
    }


def bamboohr_get_time_off(start_date: str, end_date: str) -> dict:
    """Legacy wrapper — delegates to the richer get_time_off_requests."""
    return bamboohr_get_time_off_requests(start_date, end_date)


def bamboohr_api_request(
    method: str,
    path: str,
    params: dict | None = None,
    body: dict | None = None,
    path_params: dict | None = None,
) -> dict:
    client = get_client()
    if not client:
        return {"error": "BambooHR not configured or unavailable"}

    if path_params:
        for key, value in path_params.items():
            path = path.replace(f"{{{key}}}", str(value))

    if "{" in path:
        return {"error": f"Unresolved path parameters in '{path}'. Provide path_params for all {{placeholders}}."}

    return client.api_request(method, path, params=params, body=body)


TOOL_EXECUTORS = {
    "bamboohr_get_directory": lambda **kw: bamboohr_get_directory(**kw),
    "bamboohr_get_employee": lambda **kw: bamboohr_get_employee(**kw),
    "bamboohr_get_employee_details": lambda **kw: bamboohr_get_employee_details(**kw),
    "bamboohr_whos_out": lambda **kw: bamboohr_whos_out(**kw),
    "bamboohr_get_time_off_requests": lambda **kw: bamboohr_get_time_off_requests(**kw),
    "bamboohr_get_time_off_balance": lambda **kw: bamboohr_get_time_off_balance(**kw),
    "bamboohr_api_request": lambda **kw: bamboohr_api_request(**kw),
    "bamboohr_get_time_off": lambda **kw: bamboohr_get_time_off(**kw),
}
