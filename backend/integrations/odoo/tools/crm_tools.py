"""Chatty — Odoo CRM tools."""

import logging

from ..helpers import safe_get_client, html_to_text

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

CRM_TOOL_DEFS = [
    # --- Read tools ---
    {
        "name": "odoo_search_leads",
        "description": "Search CRM leads and opportunities with optional filters by stage, team, salesperson, dates, keyword, or type.",
        "input_schema": {
            "type": "object",
            "properties": {
                "stage": {
                    "type": "string",
                    "description": "Filter by stage name (case-insensitive partial match).",
                },
                "team_id": {
                    "type": "integer",
                    "description": "Filter by sales team ID.",
                },
                "user_id": {
                    "type": "integer",
                    "description": "Filter by salesperson (user) ID.",
                },
                "date_from": {
                    "type": "string",
                    "description": "Start date for creation date filter (YYYY-MM-DD).",
                },
                "date_to": {
                    "type": "string",
                    "description": "End date for creation date filter (YYYY-MM-DD).",
                },
                "keyword": {
                    "type": "string",
                    "description": "Search keyword matched against lead name.",
                },
                "lead_type": {
                    "type": "string",
                    "enum": ["lead", "opportunity"],
                    "description": "Filter by type: 'lead' or 'opportunity'.",
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
    {
        "name": "odoo_get_lead_details",
        "description": "Get full details for a single CRM lead or opportunity, including address, description, priority, tags, and activity info.",
        "input_schema": {
            "type": "object",
            "properties": {
                "lead_id": {
                    "type": "integer",
                    "description": "The ID of the lead/opportunity to retrieve.",
                },
            },
            "required": ["lead_id"],
        },
        "kind": "integration",
    },
    {
        "name": "odoo_get_pipeline_summary",
        "description": "Get a pipeline summary showing lead counts and total expected revenue grouped by stage.",
        "input_schema": {
            "type": "object",
            "properties": {
                "team_id": {
                    "type": "integer",
                    "description": "Optional sales team ID to filter the pipeline.",
                },
            },
            "required": [],
        },
        "kind": "integration",
    },
    {
        "name": "odoo_search_crm_activities",
        "description": "Search scheduled activities on CRM leads. Can filter by lead, user, activity type, and date range.",
        "input_schema": {
            "type": "object",
            "properties": {
                "lead_id": {
                    "type": "integer",
                    "description": "Filter activities for a specific lead ID.",
                },
                "user_id": {
                    "type": "integer",
                    "description": "Filter activities assigned to a specific user ID.",
                },
                "activity_type": {
                    "type": "string",
                    "description": "Filter by activity type name (case-insensitive partial match, e.g. 'Call', 'Email').",
                },
                "date_from": {
                    "type": "string",
                    "description": "Start date for deadline filter (YYYY-MM-DD).",
                },
                "date_to": {
                    "type": "string",
                    "description": "End date for deadline filter (YYYY-MM-DD).",
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
    # --- Write tools ---
    {
        "name": "odoo_create_lead",
        "description": "Create a new CRM lead/opportunity in Odoo. Automatically sets type to 'opportunity'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Title/name of the lead or opportunity.",
                },
                "partner_name": {
                    "type": "string",
                    "description": "Company or contact name.",
                },
                "email": {
                    "type": "string",
                    "description": "Contact email address.",
                },
                "phone": {
                    "type": "string",
                    "description": "Contact phone number.",
                },
                "expected_revenue": {
                    "type": "number",
                    "description": "Expected revenue amount.",
                },
                "probability": {
                    "type": "number",
                    "description": "Win probability (0-100).",
                },
                "stage_id": {
                    "type": "integer",
                    "description": "Pipeline stage ID to place the lead in.",
                },
                "team_id": {
                    "type": "integer",
                    "description": "Sales team ID.",
                },
                "user_id": {
                    "type": "integer",
                    "description": "Salesperson (user) ID.",
                },
                "description": {
                    "type": "string",
                    "description": "Internal description or notes for the lead.",
                },
            },
            "required": ["name"],
        },
        "kind": "integration",
    },
    {
        "name": "odoo_update_lead",
        "description": "Update fields on an existing CRM lead/opportunity. Provide only the fields you want to change.",
        "input_schema": {
            "type": "object",
            "properties": {
                "lead_id": {
                    "type": "integer",
                    "description": "The ID of the lead to update.",
                },
                "expected_revenue": {
                    "type": "number",
                    "description": "New expected revenue amount.",
                },
                "probability": {
                    "type": "number",
                    "description": "New win probability (0-100).",
                },
                "partner_name": {
                    "type": "string",
                    "description": "Updated company/contact name.",
                },
                "email": {
                    "type": "string",
                    "description": "Updated email address.",
                },
                "phone": {
                    "type": "string",
                    "description": "Updated phone number.",
                },
                "description": {
                    "type": "string",
                    "description": "Updated description.",
                },
                "date_deadline": {
                    "type": "string",
                    "description": "Expected closing date (YYYY-MM-DD).",
                },
                "priority": {
                    "type": "string",
                    "enum": ["0", "1", "2", "3"],
                    "description": "Priority: 0=Normal, 1=Low, 2=High, 3=Very High.",
                },
            },
            "required": ["lead_id"],
        },
        "kind": "integration",
    },
    {
        "name": "odoo_update_lead_stage",
        "description": "Move a CRM lead/opportunity to a different pipeline stage.",
        "input_schema": {
            "type": "object",
            "properties": {
                "lead_id": {
                    "type": "integer",
                    "description": "The ID of the lead to move.",
                },
                "stage_id": {
                    "type": "integer",
                    "description": "The target stage ID.",
                },
            },
            "required": ["lead_id", "stage_id"],
        },
        "kind": "integration",
    },
    {
        "name": "odoo_mark_lead_won",
        "description": "Mark a CRM lead/opportunity as won.",
        "input_schema": {
            "type": "object",
            "properties": {
                "lead_id": {
                    "type": "integer",
                    "description": "The ID of the lead to mark as won.",
                },
            },
            "required": ["lead_id"],
        },
        "kind": "integration",
    },
    {
        "name": "odoo_mark_lead_lost",
        "description": "Mark a CRM lead/opportunity as lost, with an optional reason.",
        "input_schema": {
            "type": "object",
            "properties": {
                "lead_id": {
                    "type": "integer",
                    "description": "The ID of the lead to mark as lost.",
                },
                "lost_reason": {
                    "type": "string",
                    "description": "Optional explanation for why the lead was lost.",
                },
            },
            "required": ["lead_id"],
        },
        "kind": "integration",
    },
    {
        "name": "odoo_create_crm_activity",
        "description": "Schedule a new activity (email, call, meeting, to-do) on a CRM lead.",
        "input_schema": {
            "type": "object",
            "properties": {
                "lead_id": {
                    "type": "integer",
                    "description": "The lead ID to attach the activity to.",
                },
                "activity_type_id": {
                    "type": "integer",
                    "description": "Activity type: 1=Email, 2=Call, 3=Meeting, 4=To-Do.",
                },
                "summary": {
                    "type": "string",
                    "description": "Short summary of the activity.",
                },
                "note": {
                    "type": "string",
                    "description": "Detailed note or instructions for the activity.",
                },
                "date_deadline": {
                    "type": "string",
                    "description": "Due date for the activity (YYYY-MM-DD).",
                },
                "user_id": {
                    "type": "integer",
                    "description": "User ID to assign the activity to.",
                },
            },
            "required": ["lead_id", "activity_type_id", "summary"],
        },
        "kind": "integration",
    },
    {
        "name": "odoo_log_lead_note",
        "description": "Post an internal note on a CRM lead (visible in the chatter, not sent to the customer).",
        "input_schema": {
            "type": "object",
            "properties": {
                "lead_id": {
                    "type": "integer",
                    "description": "The lead ID to post the note on.",
                },
                "message": {
                    "type": "string",
                    "description": "The note text to post.",
                },
            },
            "required": ["lead_id", "message"],
        },
        "kind": "integration",
    },
]

# ---------------------------------------------------------------------------
# Helper: resolve ir.model ID for crm.lead (cached)
# ---------------------------------------------------------------------------

_crm_lead_model_id: int | None = None


def _get_crm_lead_model_id(client) -> int:
    """Look up the ir.model record ID for crm.lead, cached after first call."""
    global _crm_lead_model_id
    if _crm_lead_model_id is not None:
        return _crm_lead_model_id
    records = client.search_read(
        "ir.model", [["model", "=", "crm.lead"]], ["id"], limit=1
    )
    if records:
        _crm_lead_model_id = records[0]["id"]
        return _crm_lead_model_id
    raise RuntimeError("Could not find ir.model ID for crm.lead")


# ---------------------------------------------------------------------------
# Executor functions
# ---------------------------------------------------------------------------


def odoo_search_leads(
    stage: str | None = None,
    team_id: int | None = None,
    user_id: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    keyword: str | None = None,
    lead_type: str | None = None,
    limit: int = 50,
) -> dict:
    """Search CRM leads/opportunities with optional filters."""
    client, err = safe_get_client()
    if err:
        return err

    domain: list = []
    if stage:
        domain.append(["stage_id.name", "ilike", stage])
    if team_id:
        domain.append(["team_id", "=", team_id])
    if user_id:
        domain.append(["user_id", "=", user_id])
    if date_from:
        domain.append(["create_date", ">=", f"{date_from} 00:00:00"])
    if date_to:
        domain.append(["create_date", "<=", f"{date_to} 23:59:59"])
    if keyword:
        domain.append(["name", "ilike", keyword])
    if lead_type:
        domain.append(["type", "=", lead_type])

    fields = [
        "id", "name", "partner_id", "partner_name", "email_from", "phone",
        "stage_id", "probability", "expected_revenue", "user_id", "team_id",
        "create_date", "type", "activity_summary", "activity_date_deadline",
    ]
    records = client.search_read("crm.lead", domain, fields, limit=limit) or []

    leads = []
    for r in records:
        leads.append({
            "id": r["id"],
            "name": r.get("name", ""),
            "partner": (
                r["partner_id"][1] if r.get("partner_id") else r.get("partner_name", "")
            ),
            "partner_id": r["partner_id"][0] if r.get("partner_id") else None,
            "email": r.get("email_from", ""),
            "phone": r.get("phone", ""),
            "stage": r["stage_id"][1] if r.get("stage_id") else None,
            "stage_id": r["stage_id"][0] if r.get("stage_id") else None,
            "probability": r.get("probability", 0),
            "expected_revenue": r.get("expected_revenue", 0),
            "salesperson": r["user_id"][1] if r.get("user_id") else None,
            "team": r["team_id"][1] if r.get("team_id") else None,
            "created": r.get("create_date", ""),
            "type": r.get("type", ""),
            "next_activity": r.get("activity_summary", ""),
            "next_activity_date": r.get("activity_date_deadline", ""),
        })

    return {"leads": leads, "total": len(leads)}


def odoo_get_lead_details(lead_id: int) -> dict:
    """Get full details for a single CRM lead/opportunity."""
    client, err = safe_get_client()
    if err:
        return err

    fields = [
        "id", "name", "partner_id", "partner_name", "email_from", "phone",
        "mobile", "street", "city", "state_id", "zip", "country_id",
        "website", "description", "stage_id", "probability",
        "expected_revenue", "user_id", "team_id", "create_date",
        "write_date", "type", "priority", "tag_ids", "lost_reason_id",
        "date_deadline", "activity_summary", "activity_date_deadline",
    ]
    records = (
        client.search_read("crm.lead", [["id", "=", lead_id]], fields, limit=1) or []
    )
    if not records:
        return {"error": f"Lead #{lead_id} not found"}

    r = records[0]
    return {
        "id": r["id"],
        "name": r.get("name", ""),
        "partner": r["partner_id"][1] if r.get("partner_id") else None,
        "partner_id": r["partner_id"][0] if r.get("partner_id") else None,
        "partner_name": r.get("partner_name", ""),
        "email": r.get("email_from", ""),
        "phone": r.get("phone", ""),
        "mobile": r.get("mobile", ""),
        "address": ", ".join(filter(None, [
            r.get("street", ""),
            r.get("city", ""),
            r["state_id"][1] if r.get("state_id") else "",
            r.get("zip", ""),
        ])),
        "country": r["country_id"][1] if r.get("country_id") else None,
        "website": r.get("website", ""),
        "description": html_to_text(r.get("description", "")),
        "stage": r["stage_id"][1] if r.get("stage_id") else None,
        "stage_id": r["stage_id"][0] if r.get("stage_id") else None,
        "probability": r.get("probability", 0),
        "expected_revenue": r.get("expected_revenue", 0),
        "salesperson": r["user_id"][1] if r.get("user_id") else None,
        "salesperson_id": r["user_id"][0] if r.get("user_id") else None,
        "team": r["team_id"][1] if r.get("team_id") else None,
        "type": r.get("type", ""),
        "priority": r.get("priority", "0"),
        "created": r.get("create_date", ""),
        "updated": r.get("write_date", ""),
        "deadline": r.get("date_deadline", ""),
        "lost_reason": r["lost_reason_id"][1] if r.get("lost_reason_id") else None,
        "next_activity": r.get("activity_summary", ""),
        "next_activity_date": r.get("activity_date_deadline", ""),
    }


def odoo_get_pipeline_summary(team_id: int | None = None) -> dict:
    """Pipeline summary: lead counts and revenue grouped by stage."""
    client, err = safe_get_client()
    if err:
        return err

    domain: list = []
    if team_id:
        domain.append(["team_id", "=", team_id])

    fields = ["stage_id", "expected_revenue"]
    records = client.search_read("crm.lead", domain, fields, limit=500) or []

    stages: dict[str, dict] = {}
    for r in records:
        stage_name = r["stage_id"][1] if r.get("stage_id") else "No Stage"
        stage_id = r["stage_id"][0] if r.get("stage_id") else 0
        key = str(stage_id)
        if key not in stages:
            stages[key] = {
                "stage": stage_name,
                "stage_id": stage_id,
                "count": 0,
                "total_revenue": 0,
            }
        stages[key]["count"] += 1
        stages[key]["total_revenue"] += r.get("expected_revenue", 0) or 0

    summary = sorted(stages.values(), key=lambda s: s["stage_id"])
    return {
        "pipeline": summary,
        "total_leads": sum(s["count"] for s in summary),
        "total_expected_revenue": sum(s["total_revenue"] for s in summary),
    }


def odoo_search_crm_activities(
    lead_id: int | None = None,
    user_id: int | None = None,
    activity_type: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 50,
) -> dict:
    """Search scheduled activities on CRM leads."""
    client, err = safe_get_client()
    if err:
        return err

    domain: list = [["res_model", "=", "crm.lead"]]
    if lead_id:
        domain.append(["res_id", "=", lead_id])
    if user_id:
        domain.append(["user_id", "=", user_id])
    if activity_type:
        domain.append(["activity_type_id.name", "ilike", activity_type])
    if date_from:
        domain.append(["date_deadline", ">=", date_from])
    if date_to:
        domain.append(["date_deadline", "<=", date_to])

    fields = [
        "res_id", "activity_type_id", "summary", "note",
        "date_deadline", "user_id", "create_date",
    ]
    records = client.search_read("mail.activity", domain, fields, limit=limit) or []

    activities = []
    for r in records:
        activities.append({
            "id": r["id"],
            "lead_id": r.get("res_id", 0),
            "type": r["activity_type_id"][1] if r.get("activity_type_id") else None,
            "summary": r.get("summary", ""),
            "note": html_to_text(r.get("note", "") or ""),
            "deadline": r.get("date_deadline", ""),
            "assigned_to": r["user_id"][1] if r.get("user_id") else None,
            "created": r.get("create_date", ""),
        })

    return {"activities": activities, "total": len(activities)}


def odoo_create_lead(
    name: str,
    partner_name: str | None = None,
    email: str | None = None,
    phone: str | None = None,
    expected_revenue: float | None = None,
    probability: float | None = None,
    stage_id: int | None = None,
    team_id: int | None = None,
    user_id: int | None = None,
    description: str | None = None,
) -> dict:
    """Create a new CRM lead/opportunity."""
    client, err = safe_get_client()
    if err:
        return err

    vals: dict = {"name": name, "type": "opportunity"}
    if partner_name:
        vals["partner_name"] = partner_name
    if email:
        vals["email_from"] = email
    if phone:
        vals["phone"] = phone
    if expected_revenue is not None:
        vals["expected_revenue"] = expected_revenue
    if probability is not None:
        vals["probability"] = probability
    if stage_id:
        vals["stage_id"] = stage_id
    if team_id:
        vals["team_id"] = team_id
    if user_id:
        vals["user_id"] = user_id
    if description:
        vals["description"] = description

    try:
        lead_id = client.execute("crm.lead", "create", vals)
    except Exception as e:
        return {"error": f"Odoo error creating lead: {e}"}

    if lead_id is None:
        return {"error": "Failed to create CRM lead in Odoo"}

    # Read back the created lead for confirmation
    leads = client.search_read(
        "crm.lead",
        [["id", "=", lead_id]],
        ["name", "stage_id", "partner_name", "email_from", "expected_revenue"],
    )
    lead = leads[0] if leads else {}

    return {
        "ok": True,
        "id": lead_id,
        "name": lead.get("name", name),
        "stage": lead["stage_id"][1] if lead.get("stage_id") else "New",
        "partner_name": lead.get("partner_name", partner_name or ""),
        "email": lead.get("email_from", email or ""),
        "expected_revenue": lead.get("expected_revenue", expected_revenue or 0),
    }


def odoo_update_lead(
    lead_id: int,
    expected_revenue: float | None = None,
    probability: float | None = None,
    partner_name: str | None = None,
    email: str | None = None,
    phone: str | None = None,
    description: str | None = None,
    date_deadline: str | None = None,
    priority: str | None = None,
) -> dict:
    """Update fields on an existing CRM lead/opportunity."""
    client, err = safe_get_client()
    if err:
        return err

    vals: dict = {}
    if expected_revenue is not None:
        vals["expected_revenue"] = expected_revenue
    if probability is not None:
        vals["probability"] = probability
    if partner_name is not None:
        vals["partner_name"] = partner_name
    if email is not None:
        vals["email_from"] = email
    if phone is not None:
        vals["phone"] = phone
    if description is not None:
        vals["description"] = description
    if date_deadline is not None:
        vals["date_deadline"] = date_deadline
    if priority is not None:
        vals["priority"] = priority

    if not vals:
        return {"error": "Nothing to update — provide at least one field"}

    try:
        result = client.execute("crm.lead", "write", [lead_id], vals)
    except Exception as e:
        return {"error": f"Odoo error updating lead #{lead_id}: {e}"}

    if not result:
        return {"error": f"Failed to update lead #{lead_id}"}

    return {"ok": True, "lead_id": lead_id, "updated": vals}


def odoo_update_lead_stage(lead_id: int, stage_id: int) -> dict:
    """Move a lead to a different pipeline stage."""
    client, err = safe_get_client()
    if err:
        return err

    result = client.execute("crm.lead", "write", [lead_id], {"stage_id": stage_id})
    if result:
        return {"ok": True, "lead_id": lead_id, "new_stage_id": stage_id}
    return {"ok": False, "error": "Failed to update lead stage"}


def odoo_mark_lead_won(lead_id: int) -> dict:
    """Mark a CRM lead/opportunity as won."""
    client, err = safe_get_client()
    if err:
        return err

    try:
        client.execute("crm.lead", "action_set_won", [lead_id])
    except Exception as e:
        return {"error": f"Odoo error marking lead #{lead_id} as won: {e}"}

    return {"ok": True, "lead_id": lead_id, "action": "won"}


def odoo_mark_lead_lost(lead_id: int, lost_reason: str | None = None) -> dict:
    """Mark a CRM lead/opportunity as lost."""
    client, err = safe_get_client()
    if err:
        return err

    try:
        kwargs: dict = {}
        if lost_reason:
            kwargs["lost_feedback"] = lost_reason
        client.execute("crm.lead", "action_set_lost", [lead_id], **kwargs)
    except Exception as e:
        return {"error": f"Odoo error marking lead #{lead_id} as lost: {e}"}

    return {"ok": True, "lead_id": lead_id, "action": "lost", "reason": lost_reason}


def odoo_create_crm_activity(
    lead_id: int,
    activity_type_id: int,
    summary: str,
    note: str | None = None,
    date_deadline: str | None = None,
    user_id: int | None = None,
) -> dict:
    """Schedule an activity on a CRM lead."""
    client, err = safe_get_client()
    if err:
        return err

    try:
        model_id = _get_crm_lead_model_id(client)
    except RuntimeError as e:
        return {"error": str(e)}

    vals: dict = {
        "res_model_id": model_id,
        "res_id": lead_id,
        "activity_type_id": activity_type_id,
        "summary": summary,
    }
    if note:
        vals["note"] = note
    if date_deadline:
        vals["date_deadline"] = date_deadline
    if user_id:
        vals["user_id"] = user_id

    try:
        activity_id = client.execute("mail.activity", "create", vals)
    except Exception as e:
        return {"error": f"Odoo error creating activity: {e}"}

    if activity_id is None:
        return {"error": "Failed to create activity"}

    return {
        "ok": True,
        "activity_id": activity_id,
        "lead_id": lead_id,
        "summary": summary,
        "date_deadline": date_deadline,
    }


def odoo_log_lead_note(lead_id: int, message: str) -> dict:
    """Post an internal note on a CRM lead."""
    client, err = safe_get_client()
    if err:
        return err

    result = client.execute(
        "crm.lead",
        "message_post",
        [lead_id],
        body=message,
        message_type="comment",
        subtype_xmlid="mail.mt_note",
    )
    if result:
        return {"ok": True, "lead_id": lead_id, "message_id": result}
    return {"ok": False, "error": "Failed to post note on lead"}


# ---------------------------------------------------------------------------
# Executor map
# ---------------------------------------------------------------------------

CRM_EXECUTORS = {
    "odoo_search_leads": lambda **kw: odoo_search_leads(**kw),
    "odoo_get_lead_details": lambda **kw: odoo_get_lead_details(**kw),
    "odoo_get_pipeline_summary": lambda **kw: odoo_get_pipeline_summary(**kw),
    "odoo_search_crm_activities": lambda **kw: odoo_search_crm_activities(**kw),
    "odoo_create_lead": lambda **kw: odoo_create_lead(**kw),
    "odoo_update_lead": lambda **kw: odoo_update_lead(**kw),
    "odoo_update_lead_stage": lambda **kw: odoo_update_lead_stage(**kw),
    "odoo_mark_lead_won": lambda **kw: odoo_mark_lead_won(**kw),
    "odoo_mark_lead_lost": lambda **kw: odoo_mark_lead_lost(**kw),
    "odoo_create_crm_activity": lambda **kw: odoo_create_crm_activity(**kw),
    "odoo_log_lead_note": lambda **kw: odoo_log_lead_note(**kw),
}
