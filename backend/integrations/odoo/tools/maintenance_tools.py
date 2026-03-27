"""Chatty — Odoo Maintenance tools."""

import logging

from ..helpers import safe_get_client, html_to_text

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

MAINTENANCE_TOOL_DEFS = [
    # --- Read tools ---
    # 1 - odoo_search_maintenance_requests
    {
        "name": "odoo_search_maintenance_requests",
        "description": (
            "Search maintenance requests with optional filters for equipment, "
            "type, stage, priority, technician, and date range."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "equipment_id": {
                    "type": "integer",
                    "description": "Filter by equipment ID.",
                },
                "request_type": {
                    "type": "string",
                    "enum": ["corrective", "preventive"],
                    "description": "Filter by maintenance type: 'corrective' or 'preventive'.",
                },
                "stage": {
                    "type": "string",
                    "description": "Filter by stage name (case-insensitive partial match).",
                },
                "priority": {
                    "type": "string",
                    "enum": ["0", "1", "2", "3"],
                    "description": "Filter by priority: 0=Normal, 1=Low, 2=High, 3=Very High.",
                },
                "user_id": {
                    "type": "integer",
                    "description": "Filter by technician (user) ID.",
                },
                "date_from": {
                    "type": "string",
                    "description": "Start date for request_date filter (YYYY-MM-DD).",
                },
                "date_to": {
                    "type": "string",
                    "description": "End date for request_date filter (YYYY-MM-DD).",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results (default 50).",
                    "default": 50,
                },
            },
            "required": [],
        },
        "kind": "integration",
    },
    # 2 - odoo_get_maintenance_request_details
    {
        "name": "odoo_get_maintenance_request_details",
        "description": (
            "Get full details for a single maintenance request including "
            "description, schedule, team, and category info."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "request_id": {
                    "type": "integer",
                    "description": "The ID of the maintenance request to retrieve.",
                },
            },
            "required": ["request_id"],
        },
        "kind": "integration",
    },
    # 3 - odoo_search_equipment
    {
        "name": "odoo_search_equipment",
        "description": (
            "Search the equipment catalog with optional filters for name, "
            "category, technician, and serial number."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Equipment name to search (case-insensitive partial match).",
                },
                "category_id": {
                    "type": "integer",
                    "description": "Filter by equipment category ID.",
                },
                "technician_user_id": {
                    "type": "integer",
                    "description": "Filter by responsible technician (user) ID.",
                },
                "serial_no": {
                    "type": "string",
                    "description": "Filter by serial number (exact match).",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results (default 50).",
                    "default": 50,
                },
            },
            "required": [],
        },
        "kind": "integration",
    },
    # 4 - odoo_get_equipment_details
    {
        "name": "odoo_get_equipment_details",
        "description": (
            "Get full details for a piece of equipment including its recent "
            "maintenance history (up to 10 most recent requests)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "equipment_id": {
                    "type": "integer",
                    "description": "The ID of the equipment to retrieve.",
                },
            },
            "required": ["equipment_id"],
        },
        "kind": "integration",
    },
    # --- Write tools ---
    # 5 - odoo_create_maintenance_request
    {
        "name": "odoo_create_maintenance_request",
        "description": (
            "Create a new maintenance request in Odoo. Requires a name and "
            "maintenance type (corrective or preventive)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Title/description of the maintenance request.",
                },
                "equipment_id": {
                    "type": "integer",
                    "description": "Equipment ID this request is for.",
                },
                "maintenance_type": {
                    "type": "string",
                    "enum": ["corrective", "preventive"],
                    "description": "Type of maintenance: 'corrective' or 'preventive'.",
                },
                "user_id": {
                    "type": "integer",
                    "description": "Technician (user) ID to assign.",
                },
                "schedule_date": {
                    "type": "string",
                    "description": "Scheduled date for the maintenance (YYYY-MM-DD HH:MM:SS or YYYY-MM-DD).",
                },
                "priority": {
                    "type": "string",
                    "enum": ["0", "1", "2", "3"],
                    "description": "Priority: 0=Normal, 1=Low, 2=High, 3=Very High.",
                },
                "description": {
                    "type": "string",
                    "description": "Detailed description or notes for the request.",
                },
                "maintenance_team_id": {
                    "type": "integer",
                    "description": "Maintenance team ID.",
                },
                "owner_user_id": {
                    "type": "integer",
                    "description": "Owner (user) ID who reported the issue.",
                },
            },
            "required": ["name", "maintenance_type"],
        },
        "kind": "integration",
    },
    # 6 - odoo_update_maintenance_request
    {
        "name": "odoo_update_maintenance_request",
        "description": (
            "Update fields on an existing maintenance request. Can change "
            "stage, technician, priority, schedule, duration, or description."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "request_id": {
                    "type": "integer",
                    "description": "The ID of the maintenance request to update.",
                },
                "stage_id": {
                    "type": "integer",
                    "description": "New stage ID to move the request to.",
                },
                "user_id": {
                    "type": "integer",
                    "description": "New technician (user) ID.",
                },
                "priority": {
                    "type": "string",
                    "enum": ["0", "1", "2", "3"],
                    "description": "New priority: 0=Normal, 1=Low, 2=High, 3=Very High.",
                },
                "schedule_date": {
                    "type": "string",
                    "description": "New scheduled date (YYYY-MM-DD HH:MM:SS or YYYY-MM-DD).",
                },
                "duration": {
                    "type": "number",
                    "description": "Duration in hours.",
                },
                "description": {
                    "type": "string",
                    "description": "Updated description or notes.",
                },
            },
            "required": ["request_id"],
        },
        "kind": "integration",
    },
]

# ---------------------------------------------------------------------------
# Executor functions
# ---------------------------------------------------------------------------


def odoo_search_maintenance_requests(
    equipment_id: int | None = None,
    request_type: str | None = None,
    stage: str | None = None,
    priority: str | None = None,
    user_id: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 50,
) -> dict:
    """Search maintenance requests with optional filters."""
    client, err = safe_get_client()
    if err:
        return err

    domain: list = []
    if equipment_id:
        domain.append(["equipment_id", "=", equipment_id])
    if request_type:
        domain.append(["maintenance_type", "=", request_type])
    if stage:
        domain.append(["stage_id.name", "ilike", stage])
    if priority:
        domain.append(["priority", "=", priority])
    if user_id:
        domain.append(["user_id", "=", user_id])
    if date_from:
        domain.append(["request_date", ">=", date_from])
    if date_to:
        domain.append(["request_date", "<=", date_to])

    fields = [
        "id", "name", "equipment_id", "request_date", "close_date",
        "stage_id", "maintenance_type", "priority", "user_id",
        "owner_user_id", "schedule_date", "duration", "create_date",
        "description",
    ]
    records = client.search_read(
        "maintenance.request", domain, fields, limit=limit,
    ) or []

    requests = []
    for r in records:
        requests.append({
            "id": r["id"],
            "name": r.get("name", ""),
            "equipment": r["equipment_id"][1] if r.get("equipment_id") else None,
            "equipment_id": r["equipment_id"][0] if r.get("equipment_id") else None,
            "request_date": r.get("request_date", ""),
            "close_date": r.get("close_date", ""),
            "stage": r["stage_id"][1] if r.get("stage_id") else None,
            "stage_id": r["stage_id"][0] if r.get("stage_id") else None,
            "maintenance_type": r.get("maintenance_type", ""),
            "priority": r.get("priority", "0"),
            "technician": r["user_id"][1] if r.get("user_id") else None,
            "technician_id": r["user_id"][0] if r.get("user_id") else None,
            "owner": r["owner_user_id"][1] if r.get("owner_user_id") else None,
            "schedule_date": r.get("schedule_date", ""),
            "duration": r.get("duration", 0),
            "created": r.get("create_date", ""),
            "description": html_to_text(r.get("description", "") or ""),
        })

    return {"requests": requests, "total": len(requests)}


def odoo_get_maintenance_request_details(request_id: int) -> dict:
    """Get full details for a single maintenance request."""
    client, err = safe_get_client()
    if err:
        return err

    fields = [
        "id", "name", "equipment_id", "request_date", "close_date",
        "stage_id", "maintenance_type", "priority", "user_id",
        "owner_user_id", "schedule_date", "duration", "create_date",
        "write_date", "description", "maintenance_team_id", "category_id",
    ]
    records = client.search_read(
        "maintenance.request", [["id", "=", request_id]], fields, limit=1,
    ) or []
    if not records:
        return {"error": f"Maintenance request #{request_id} not found"}

    r = records[0]
    return {
        "id": r["id"],
        "name": r.get("name", ""),
        "equipment": r["equipment_id"][1] if r.get("equipment_id") else None,
        "equipment_id": r["equipment_id"][0] if r.get("equipment_id") else None,
        "request_date": r.get("request_date", ""),
        "close_date": r.get("close_date", ""),
        "stage": r["stage_id"][1] if r.get("stage_id") else None,
        "stage_id": r["stage_id"][0] if r.get("stage_id") else None,
        "maintenance_type": r.get("maintenance_type", ""),
        "priority": r.get("priority", "0"),
        "technician": r["user_id"][1] if r.get("user_id") else None,
        "technician_id": r["user_id"][0] if r.get("user_id") else None,
        "owner": r["owner_user_id"][1] if r.get("owner_user_id") else None,
        "owner_id": r["owner_user_id"][0] if r.get("owner_user_id") else None,
        "schedule_date": r.get("schedule_date", ""),
        "duration": r.get("duration", 0),
        "created": r.get("create_date", ""),
        "updated": r.get("write_date", ""),
        "description": html_to_text(r.get("description", "") or ""),
        "maintenance_team": (
            r["maintenance_team_id"][1] if r.get("maintenance_team_id") else None
        ),
        "maintenance_team_id": (
            r["maintenance_team_id"][0] if r.get("maintenance_team_id") else None
        ),
        "category": r["category_id"][1] if r.get("category_id") else None,
        "category_id": r["category_id"][0] if r.get("category_id") else None,
    }


def odoo_search_equipment(
    name: str | None = None,
    category_id: int | None = None,
    technician_user_id: int | None = None,
    serial_no: str | None = None,
    limit: int = 50,
) -> dict:
    """Search the equipment catalog with optional filters."""
    client, err = safe_get_client()
    if err:
        return err

    domain: list = []
    if name:
        domain.append(["name", "ilike", name])
    if category_id:
        domain.append(["category_id", "=", category_id])
    if technician_user_id:
        domain.append(["technician_user_id", "=", technician_user_id])
    if serial_no:
        domain.append(["serial_no", "=", serial_no])

    fields = [
        "id", "name", "category_id", "technician_user_id", "owner_user_id",
        "serial_no", "model", "note", "location", "effective_date", "period",
        "maintenance_count", "color",
    ]
    records = client.search_read(
        "maintenance.equipment", domain, fields, limit=limit,
    ) or []

    equipment = []
    for r in records:
        equipment.append({
            "id": r["id"],
            "name": r.get("name", ""),
            "category": r["category_id"][1] if r.get("category_id") else None,
            "category_id": r["category_id"][0] if r.get("category_id") else None,
            "technician": (
                r["technician_user_id"][1] if r.get("technician_user_id") else None
            ),
            "technician_id": (
                r["technician_user_id"][0] if r.get("technician_user_id") else None
            ),
            "owner": r["owner_user_id"][1] if r.get("owner_user_id") else None,
            "owner_id": r["owner_user_id"][0] if r.get("owner_user_id") else None,
            "serial_no": r.get("serial_no", ""),
            "model": r.get("model", ""),
            "note": html_to_text(r.get("note", "") or ""),
            "location": r.get("location", ""),
            "effective_date": r.get("effective_date", ""),
            "period": r.get("period", 0),
            "maintenance_count": r.get("maintenance_count", 0),
            "color": r.get("color", 0),
        })

    return {"equipment": equipment, "total": len(equipment)}


def odoo_get_equipment_details(equipment_id: int) -> dict:
    """Get full details for a piece of equipment with recent maintenance history."""
    client, err = safe_get_client()
    if err:
        return err

    fields = [
        "id", "name", "category_id", "technician_user_id", "owner_user_id",
        "serial_no", "model", "note", "location", "effective_date", "period",
        "cost", "maintenance_count", "scrap_date", "warranty_date",
        "maintenance_team_id",
    ]
    records = client.search_read(
        "maintenance.equipment", [["id", "=", equipment_id]], fields, limit=1,
    ) or []
    if not records:
        return {"error": f"Equipment #{equipment_id} not found"}

    r = records[0]
    equip = {
        "id": r["id"],
        "name": r.get("name", ""),
        "category": r["category_id"][1] if r.get("category_id") else None,
        "category_id": r["category_id"][0] if r.get("category_id") else None,
        "technician": (
            r["technician_user_id"][1] if r.get("technician_user_id") else None
        ),
        "technician_id": (
            r["technician_user_id"][0] if r.get("technician_user_id") else None
        ),
        "owner": r["owner_user_id"][1] if r.get("owner_user_id") else None,
        "owner_id": r["owner_user_id"][0] if r.get("owner_user_id") else None,
        "serial_no": r.get("serial_no", ""),
        "model": r.get("model", ""),
        "note": html_to_text(r.get("note", "") or ""),
        "location": r.get("location", ""),
        "effective_date": r.get("effective_date", ""),
        "period": r.get("period", 0),
        "cost": r.get("cost", 0),
        "maintenance_count": r.get("maintenance_count", 0),
        "scrap_date": r.get("scrap_date", ""),
        "warranty_date": r.get("warranty_date", ""),
        "maintenance_team": (
            r["maintenance_team_id"][1] if r.get("maintenance_team_id") else None
        ),
        "maintenance_team_id": (
            r["maintenance_team_id"][0] if r.get("maintenance_team_id") else None
        ),
    }

    # Fetch recent maintenance requests for this equipment
    maint_fields = [
        "id", "name", "request_date", "close_date", "stage_id",
        "maintenance_type", "priority", "user_id", "create_date",
    ]
    maint_records = client.search_read(
        "maintenance.request",
        [["equipment_id", "=", equipment_id]],
        maint_fields,
        limit=10,
        order="create_date desc",
    ) or []

    recent_maintenance = []
    for m in maint_records:
        recent_maintenance.append({
            "id": m["id"],
            "name": m.get("name", ""),
            "request_date": m.get("request_date", ""),
            "close_date": m.get("close_date", ""),
            "stage": m["stage_id"][1] if m.get("stage_id") else None,
            "maintenance_type": m.get("maintenance_type", ""),
            "priority": m.get("priority", "0"),
            "technician": m["user_id"][1] if m.get("user_id") else None,
            "created": m.get("create_date", ""),
        })

    equip["recent_maintenance"] = recent_maintenance
    return equip


def odoo_create_maintenance_request(
    name: str,
    maintenance_type: str,
    equipment_id: int | None = None,
    user_id: int | None = None,
    schedule_date: str | None = None,
    priority: str | None = None,
    description: str | None = None,
    maintenance_team_id: int | None = None,
    owner_user_id: int | None = None,
) -> dict:
    """Create a new maintenance request."""
    client, err = safe_get_client()
    if err:
        return err

    vals: dict = {
        "name": name,
        "maintenance_type": maintenance_type,
    }
    if equipment_id:
        vals["equipment_id"] = equipment_id
    if user_id:
        vals["user_id"] = user_id
    if schedule_date:
        vals["schedule_date"] = schedule_date
    if priority is not None:
        vals["priority"] = priority
    if description:
        vals["description"] = description
    if maintenance_team_id:
        vals["maintenance_team_id"] = maintenance_team_id
    if owner_user_id:
        vals["owner_user_id"] = owner_user_id

    try:
        request_id = client.create("maintenance.request", vals)
    except Exception as e:
        return {"error": f"Odoo error creating maintenance request: {e}"}

    if request_id is None:
        return {"error": "Failed to create maintenance request in Odoo"}

    # Read back the created request for confirmation
    created = client.search_read(
        "maintenance.request",
        [["id", "=", request_id]],
        ["name", "stage_id", "equipment_id", "maintenance_type", "user_id"],
    )
    rec = created[0] if created else {}

    return {
        "ok": True,
        "id": request_id,
        "name": rec.get("name", name),
        "stage": rec["stage_id"][1] if rec.get("stage_id") else "New Request",
        "equipment": rec["equipment_id"][1] if rec.get("equipment_id") else None,
        "maintenance_type": rec.get("maintenance_type", maintenance_type),
        "technician": rec["user_id"][1] if rec.get("user_id") else None,
    }


def odoo_update_maintenance_request(
    request_id: int,
    stage_id: int | None = None,
    user_id: int | None = None,
    priority: str | None = None,
    schedule_date: str | None = None,
    duration: float | None = None,
    description: str | None = None,
) -> dict:
    """Update fields on an existing maintenance request."""
    client, err = safe_get_client()
    if err:
        return err

    vals: dict = {}
    if stage_id is not None:
        vals["stage_id"] = stage_id
    if user_id is not None:
        vals["user_id"] = user_id
    if priority is not None:
        vals["priority"] = priority
    if schedule_date is not None:
        vals["schedule_date"] = schedule_date
    if duration is not None:
        vals["duration"] = duration
    if description is not None:
        vals["description"] = description

    if not vals:
        return {"error": "Nothing to update -- provide at least one field"}

    try:
        client.write("maintenance.request", [request_id], vals)
    except Exception as e:
        return {"error": f"Odoo error updating maintenance request #{request_id}: {e}"}

    return {"ok": True, "request_id": request_id, "updated": vals}


# ---------------------------------------------------------------------------
# Executor map
# ---------------------------------------------------------------------------

MAINTENANCE_EXECUTORS = {
    "odoo_search_maintenance_requests": lambda **kw: odoo_search_maintenance_requests(**kw),
    "odoo_get_maintenance_request_details": lambda **kw: odoo_get_maintenance_request_details(**kw),
    "odoo_search_equipment": lambda **kw: odoo_search_equipment(**kw),
    "odoo_get_equipment_details": lambda **kw: odoo_get_equipment_details(**kw),
    "odoo_create_maintenance_request": lambda **kw: odoo_create_maintenance_request(**kw),
    "odoo_update_maintenance_request": lambda **kw: odoo_update_maintenance_request(**kw),
}
