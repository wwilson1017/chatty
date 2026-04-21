"""Chatty -- Odoo Quality tools.

7 tools covering quality check search/details, quality alert search/details,
pass/fail actions, and alert creation.  Each executor calls safe_get_client()
internally so the agent engine never has to manage Odoo connections.
"""

import logging

from ..helpers import safe_get_client, flatten_m2o, html_to_text

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

QUALITY_TOOL_DEFS = [
    # 1 - odoo_search_quality_checks
    {
        "name": "odoo_search_quality_checks",
        "description": (
            "Search quality checks with optional filters for product, state, "
            "quality point, and team."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "product_id": {
                    "type": "integer",
                    "description": "Product ID to filter by",
                },
                "quality_state": {
                    "type": "string",
                    "description": "Quality state filter: 'none', 'pass', or 'fail'",
                },
                "point_id": {
                    "type": "integer",
                    "description": "Quality point ID to filter by",
                },
                "team_id": {
                    "type": "integer",
                    "description": "Quality team ID to filter by",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max checks to return (default 50)",
                    "default": 50,
                },
            },
            "required": [],
        },
        "kind": "integration",
    },
    # 2 - odoo_get_quality_check_details
    {
        "name": "odoo_get_quality_check_details",
        "description": (
            "Get full details of a single quality check including measurement "
            "data, tolerances, and linked records."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "check_id": {
                    "type": "integer",
                    "description": "Quality check ID",
                },
            },
            "required": ["check_id"],
        },
        "kind": "integration",
    },
    # 3 - odoo_search_quality_alerts
    {
        "name": "odoo_search_quality_alerts",
        "description": (
            "Search quality alerts with optional filters for product, stage, "
            "team, priority, and date range."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "product_id": {
                    "type": "integer",
                    "description": "Product ID to filter by",
                },
                "stage": {
                    "type": "string",
                    "description": "Stage name to filter by (case-insensitive partial match)",
                },
                "team_id": {
                    "type": "integer",
                    "description": "Quality team ID to filter by",
                },
                "priority": {
                    "type": "string",
                    "description": "Priority filter ('0'=Normal, '1'=Low, '2'=High, '3'=Very High)",
                },
                "date_from": {
                    "type": "string",
                    "description": "Earliest create date (YYYY-MM-DD)",
                },
                "date_to": {
                    "type": "string",
                    "description": "Latest create date (YYYY-MM-DD)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max alerts to return (default 50)",
                    "default": 50,
                },
            },
            "required": [],
        },
        "kind": "integration",
    },
    # 4 - odoo_get_quality_alert_details
    {
        "name": "odoo_get_quality_alert_details",
        "description": (
            "Get full details of a single quality alert including description, "
            "corrective/preventive actions, and root cause."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "alert_id": {
                    "type": "integer",
                    "description": "Quality alert ID",
                },
            },
            "required": ["alert_id"],
        },
        "kind": "integration",
    },
    # 5 - odoo_pass_quality_check
    {
        "name": "odoo_pass_quality_check",
        "description": (
            "Pass a quality check. The check must be in 'none' state "
            "(not already passed or failed)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "check_id": {
                    "type": "integer",
                    "description": "Quality check ID to pass",
                },
            },
            "required": ["check_id"],
        },
        "kind": "integration",
        "writes": True,
    },
    # 6 - odoo_fail_quality_check
    {
        "name": "odoo_fail_quality_check",
        "description": (
            "Fail a quality check. The check must be in 'none' state "
            "(not already passed or failed)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "check_id": {
                    "type": "integer",
                    "description": "Quality check ID to fail",
                },
            },
            "required": ["check_id"],
        },
        "kind": "integration",
        "writes": True,
    },
    # 7 - odoo_create_quality_alert
    {
        "name": "odoo_create_quality_alert",
        "description": (
            "Create a new quality alert. Returns the created alert details."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Alert title / name",
                },
                "product_id": {
                    "type": "integer",
                    "description": "Product ID (product.product)",
                },
                "product_tmpl_id": {
                    "type": "integer",
                    "description": "Product template ID (product.template)",
                },
                "lot_id": {
                    "type": "integer",
                    "description": "Lot / serial number ID",
                },
                "team_id": {
                    "type": "integer",
                    "description": "Quality team ID",
                },
                "user_id": {
                    "type": "integer",
                    "description": "Responsible user ID",
                },
                "priority": {
                    "type": "string",
                    "description": "Priority: '0'=Normal, '1'=Low, '2'=High, '3'=Very High",
                },
                "description": {
                    "type": "string",
                    "description": "Alert description (plain text or HTML)",
                },
                "reason_id": {
                    "type": "integer",
                    "description": "Root cause / reason ID (quality.reason)",
                },
            },
            "required": ["name"],
        },
        "kind": "integration",
        "writes": True,
    },
]

# ---------------------------------------------------------------------------
# Executor functions
# ---------------------------------------------------------------------------


def _odoo_search_quality_checks(
    product_id: int = None,
    quality_state: str = None,
    point_id: int = None,
    team_id: int = None,
    limit: int = 50,
) -> dict:
    """Search quality checks with optional filters."""
    client, err = safe_get_client()
    if err:
        return err

    domain = []
    if product_id:
        domain.append(["product_id", "=", product_id])
    if quality_state:
        domain.append(["quality_state", "=", quality_state])
    if point_id:
        domain.append(["point_id", "=", point_id])
    if team_id:
        domain.append(["team_id", "=", team_id])

    fields = [
        "name", "product_id", "point_id", "quality_state", "team_id",
        "lot_id", "create_date", "write_date", "picking_id", "production_id",
    ]
    records = client.search_read("quality.check", domain, fields, limit=limit) or []

    checks = []
    for r in records:
        row = flatten_m2o(r)
        checks.append({
            "id": row.get("id"),
            "name": row.get("name", ""),
            "product": row.get("product_id", ""),
            "product_id": row.get("product_id_id"),
            "point": row.get("point_id", ""),
            "point_id": row.get("point_id_id"),
            "quality_state": row.get("quality_state", ""),
            "team": row.get("team_id", ""),
            "team_id": row.get("team_id_id"),
            "lot": row.get("lot_id", ""),
            "lot_id": row.get("lot_id_id"),
            "created": row.get("create_date", ""),
            "updated": row.get("write_date", ""),
            "picking": row.get("picking_id", ""),
            "picking_id": row.get("picking_id_id"),
            "production": row.get("production_id", ""),
            "production_id": row.get("production_id_id"),
        })
    return {"checks": checks, "total": len(checks)}


def _odoo_get_quality_check_details(check_id: int) -> dict:
    """Get full details of a single quality check."""
    client, err = safe_get_client()
    if err:
        return err

    fields = [
        "name", "product_id", "point_id", "quality_state", "team_id",
        "lot_id", "measure", "measure_success", "tolerance_min",
        "tolerance_max", "norm_unit", "note", "create_date", "write_date",
        "picking_id", "production_id", "test_type_id",
    ]
    records = client.search_read(
        "quality.check", [["id", "=", check_id]], fields, limit=1,
    ) or []
    if not records:
        return {"error": f"Quality check #{check_id} not found"}

    r = records[0]
    row = flatten_m2o(r)
    return {
        "id": row.get("id"),
        "name": row.get("name", ""),
        "product": row.get("product_id", ""),
        "product_id": row.get("product_id_id"),
        "point": row.get("point_id", ""),
        "point_id": row.get("point_id_id"),
        "quality_state": row.get("quality_state", ""),
        "team": row.get("team_id", ""),
        "team_id": row.get("team_id_id"),
        "lot": row.get("lot_id", ""),
        "lot_id": row.get("lot_id_id"),
        "measure": row.get("measure"),
        "measure_success": row.get("measure_success"),
        "tolerance_min": row.get("tolerance_min"),
        "tolerance_max": row.get("tolerance_max"),
        "norm_unit": row.get("norm_unit", ""),
        "note": html_to_text(row.get("note", "") or ""),
        "created": row.get("create_date", ""),
        "updated": row.get("write_date", ""),
        "picking": row.get("picking_id", ""),
        "picking_id": row.get("picking_id_id"),
        "production": row.get("production_id", ""),
        "production_id": row.get("production_id_id"),
        "test_type": row.get("test_type_id", ""),
        "test_type_id": row.get("test_type_id_id"),
    }


def _odoo_search_quality_alerts(
    product_id: int = None,
    stage: str = None,
    team_id: int = None,
    priority: str = None,
    date_from: str = None,
    date_to: str = None,
    limit: int = 50,
) -> dict:
    """Search quality alerts with optional filters."""
    client, err = safe_get_client()
    if err:
        return err

    domain = []
    if product_id:
        domain.append(["product_id", "=", product_id])
    if stage:
        domain.append(["stage_id.name", "ilike", stage])
    if team_id:
        domain.append(["team_id", "=", team_id])
    if priority:
        domain.append(["priority", "=", priority])
    if date_from:
        domain.append(["create_date", ">=", f"{date_from} 00:00:00"])
    if date_to:
        domain.append(["create_date", "<=", f"{date_to} 23:59:59"])

    fields = [
        "name", "product_id", "product_tmpl_id", "lot_id", "team_id",
        "stage_id", "user_id", "priority", "partner_id", "create_date",
        "description",
    ]
    records = client.search_read("quality.alert", domain, fields, limit=limit) or []

    alerts = []
    for r in records:
        row = flatten_m2o(r)
        alerts.append({
            "id": row.get("id"),
            "name": row.get("name", ""),
            "product": row.get("product_id", ""),
            "product_id": row.get("product_id_id"),
            "product_template": row.get("product_tmpl_id", ""),
            "product_tmpl_id": row.get("product_tmpl_id_id"),
            "lot": row.get("lot_id", ""),
            "lot_id": row.get("lot_id_id"),
            "team": row.get("team_id", ""),
            "team_id": row.get("team_id_id"),
            "stage": row.get("stage_id", ""),
            "stage_id": row.get("stage_id_id"),
            "assigned_to": row.get("user_id", ""),
            "assigned_to_id": row.get("user_id_id"),
            "priority": row.get("priority", "0"),
            "partner": row.get("partner_id", ""),
            "partner_id": row.get("partner_id_id"),
            "created": row.get("create_date", ""),
            "description_preview": html_to_text(
                row.get("description", "") or ""
            )[:200],
        })
    return {"alerts": alerts, "total": len(alerts)}


def _odoo_get_quality_alert_details(alert_id: int) -> dict:
    """Get full details of a single quality alert."""
    client, err = safe_get_client()
    if err:
        return err

    fields = [
        "name", "product_id", "product_tmpl_id", "lot_id", "team_id",
        "stage_id", "user_id", "priority", "partner_id", "create_date",
        "write_date", "description", "reason_id", "action_corrective",
        "action_preventive",
    ]
    records = client.search_read(
        "quality.alert", [["id", "=", alert_id]], fields, limit=1,
    ) or []
    if not records:
        return {"error": f"Quality alert #{alert_id} not found"}

    r = records[0]
    row = flatten_m2o(r)
    return {
        "id": row.get("id"),
        "name": row.get("name", ""),
        "product": row.get("product_id", ""),
        "product_id": row.get("product_id_id"),
        "product_template": row.get("product_tmpl_id", ""),
        "product_tmpl_id": row.get("product_tmpl_id_id"),
        "lot": row.get("lot_id", ""),
        "lot_id": row.get("lot_id_id"),
        "team": row.get("team_id", ""),
        "team_id": row.get("team_id_id"),
        "stage": row.get("stage_id", ""),
        "stage_id": row.get("stage_id_id"),
        "assigned_to": row.get("user_id", ""),
        "assigned_to_id": row.get("user_id_id"),
        "priority": row.get("priority", "0"),
        "partner": row.get("partner_id", ""),
        "partner_id": row.get("partner_id_id"),
        "created": row.get("create_date", ""),
        "updated": row.get("write_date", ""),
        "description": html_to_text(row.get("description", "") or ""),
        "reason": row.get("reason_id", ""),
        "reason_id": row.get("reason_id_id"),
        "action_corrective": html_to_text(
            row.get("action_corrective", "") or ""
        ),
        "action_preventive": html_to_text(
            row.get("action_preventive", "") or ""
        ),
    }


def _odoo_pass_quality_check(check_id: int) -> dict:
    """Pass a quality check (must be in 'none' state)."""
    client, err = safe_get_client()
    if err:
        return err

    # Verify check exists and is in 'none' state
    records = client.search_read(
        "quality.check", [["id", "=", check_id]],
        ["name", "quality_state"], limit=1,
    ) or []
    if not records:
        return {"error": f"Quality check #{check_id} not found"}

    check = records[0]
    if check["quality_state"] != "none":
        return {
            "error": (
                f"Quality check '{check['name']}' is already in state "
                f"'{check['quality_state']}' -- can only pass checks in "
                "'none' state"
            ),
        }

    try:
        client.execute("quality.check", "do_pass", [check_id])
    except Exception as e:
        return {"error": f"Odoo error passing quality check '{check['name']}': {e}"}

    return {"ok": True, "check_id": check_id, "name": check["name"], "quality_state": "pass"}


def _odoo_fail_quality_check(check_id: int) -> dict:
    """Fail a quality check (must be in 'none' state)."""
    client, err = safe_get_client()
    if err:
        return err

    # Verify check exists and is in 'none' state
    records = client.search_read(
        "quality.check", [["id", "=", check_id]],
        ["name", "quality_state"], limit=1,
    ) or []
    if not records:
        return {"error": f"Quality check #{check_id} not found"}

    check = records[0]
    if check["quality_state"] != "none":
        return {
            "error": (
                f"Quality check '{check['name']}' is already in state "
                f"'{check['quality_state']}' -- can only fail checks in "
                "'none' state"
            ),
        }

    try:
        client.execute("quality.check", "do_fail", [check_id])
    except Exception as e:
        return {"error": f"Odoo error failing quality check '{check['name']}': {e}"}

    return {"ok": True, "check_id": check_id, "name": check["name"], "quality_state": "fail"}


def _odoo_create_quality_alert(
    name: str,
    product_id: int = None,
    product_tmpl_id: int = None,
    lot_id: int = None,
    team_id: int = None,
    user_id: int = None,
    priority: str = None,
    description: str = None,
    reason_id: int = None,
) -> dict:
    """Create a new quality alert."""
    client, err = safe_get_client()
    if err:
        return err

    vals: dict = {"name": name}
    if product_id is not None:
        vals["product_id"] = product_id
    if product_tmpl_id is not None:
        vals["product_tmpl_id"] = product_tmpl_id
    if lot_id is not None:
        vals["lot_id"] = lot_id
    if team_id is not None:
        vals["team_id"] = team_id
    if user_id is not None:
        vals["user_id"] = user_id
    if priority is not None:
        vals["priority"] = priority
    if description is not None:
        vals["description"] = description
    if reason_id is not None:
        vals["reason_id"] = reason_id

    try:
        alert_id = client.create("quality.alert", vals)
    except Exception as e:
        return {"error": f"Odoo error creating quality alert: {e}"}

    if alert_id is None:
        return {"error": "Failed to create quality alert in Odoo"}

    # Read back the created alert
    alerts = client.search_read(
        "quality.alert",
        [["id", "=", alert_id]],
        [
            "name", "product_id", "product_tmpl_id", "lot_id", "team_id",
            "stage_id", "user_id", "priority", "create_date",
        ],
    )
    alert = alerts[0] if alerts else {}
    row = flatten_m2o(alert)

    return {
        "ok": True,
        "id": alert_id,
        "name": row.get("name", name),
        "product": row.get("product_id", ""),
        "product_id": row.get("product_id_id"),
        "product_template": row.get("product_tmpl_id", ""),
        "product_tmpl_id": row.get("product_tmpl_id_id"),
        "lot": row.get("lot_id", ""),
        "lot_id": row.get("lot_id_id"),
        "team": row.get("team_id", ""),
        "team_id": row.get("team_id_id"),
        "stage": row.get("stage_id", ""),
        "stage_id": row.get("stage_id_id"),
        "assigned_to": row.get("user_id", ""),
        "assigned_to_id": row.get("user_id_id"),
        "priority": row.get("priority", "0"),
        "created": row.get("create_date", ""),
    }


# ---------------------------------------------------------------------------
# Executor map
# ---------------------------------------------------------------------------

QUALITY_EXECUTORS = {
    "odoo_search_quality_checks": lambda **kw: _odoo_search_quality_checks(**kw),
    "odoo_get_quality_check_details": lambda **kw: _odoo_get_quality_check_details(**kw),
    "odoo_search_quality_alerts": lambda **kw: _odoo_search_quality_alerts(**kw),
    "odoo_get_quality_alert_details": lambda **kw: _odoo_get_quality_alert_details(**kw),
    "odoo_pass_quality_check": lambda **kw: _odoo_pass_quality_check(**kw),
    "odoo_fail_quality_check": lambda **kw: _odoo_fail_quality_check(**kw),
    "odoo_create_quality_alert": lambda **kw: _odoo_create_quality_alert(**kw),
}
