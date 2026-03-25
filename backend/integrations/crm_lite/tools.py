"""Chatty — CRM Lite agent tools (17 tools).

Contacts, deals, tasks, activities, and analytics — all accessible
to the AI agent for managing customer relationships conversationally.
"""

from . import client as crm

# ═══════════════════════════════════════════════════════════════════════════════
# Tool Definitions (schema only — sent to the AI provider)
# ═══════════════════════════════════════════════════════════════════════════════

CRM_LITE_TOOL_DEFS = [
    # ── Contacts (6 tools) ────────────────────────────────────────────────────
    {
        "name": "crm_find_contact",
        "description": (
            "Search CRM contacts by name, email, company, or notes. "
            "Use this when the user mentions a person or company and you need to look them up."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search term (name, email, company, or keyword)"},
                "status": {"type": "string", "description": "Filter by status: active, inactive, archived"},
                "tags": {"type": "string", "description": "Filter by tag (partial match)"},
            },
            "required": ["query"],
        },
        "kind": "integration",
    },
    {
        "name": "crm_create_contact",
        "description": (
            "Create a new contact in the CRM. Use when the user mentions a new customer, prospect, "
            "or person they want to track."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Full name"},
                "email": {"type": "string", "default": ""},
                "phone": {"type": "string", "default": ""},
                "company": {"type": "string", "default": ""},
                "title": {"type": "string", "description": "Job title", "default": ""},
                "source": {"type": "string", "description": "How they found you: referral, website, cold_call, social, event, other", "default": ""},
                "status": {"type": "string", "description": "active, inactive, or archived", "default": "active"},
                "tags": {"type": "string", "description": "Comma-separated tags", "default": ""},
                "notes": {"type": "string", "default": ""},
            },
            "required": ["name"],
        },
        "kind": "integration",
    },
    {
        "name": "crm_update_contact",
        "description": (
            "Update an existing contact's information. Use when the user wants to change a "
            "contact's details like email, phone, company, status, or tags."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "contact_id": {"type": "integer", "description": "Contact ID to update"},
                "name": {"type": "string"},
                "email": {"type": "string"},
                "phone": {"type": "string"},
                "company": {"type": "string"},
                "title": {"type": "string"},
                "source": {"type": "string"},
                "status": {"type": "string", "description": "active, inactive, or archived"},
                "tags": {"type": "string"},
                "notes": {"type": "string"},
            },
            "required": ["contact_id"],
        },
        "kind": "integration",
    },
    {
        "name": "crm_get_contact",
        "description": (
            "Get a contact's full profile including their deals, tasks, and recent activity. "
            "Use this to see everything about a specific customer."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "contact_id": {"type": "integer", "description": "Contact ID"},
            },
            "required": ["contact_id"],
        },
        "kind": "integration",
    },
    {
        "name": "crm_list_contacts",
        "description": (
            "List contacts with optional filtering. Use to browse the customer list or "
            "see contacts by status."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "description": "Filter: active, inactive, archived"},
                "limit": {"type": "integer", "description": "Max results (default 50)", "default": 50},
                "offset": {"type": "integer", "description": "Pagination offset", "default": 0},
            },
            "required": [],
        },
        "kind": "integration",
    },
    {
        "name": "crm_delete_contact",
        "description": "Delete a contact and all their associated activities and tasks.",
        "input_schema": {
            "type": "object",
            "properties": {
                "contact_id": {"type": "integer", "description": "Contact ID to delete"},
            },
            "required": ["contact_id"],
        },
        "kind": "integration",
    },

    # ── Deals (5 tools) ──────────────────────────────────────────────────────
    {
        "name": "crm_get_pipeline",
        "description": (
            "Get the deal pipeline with value summaries per stage. "
            "Use when the user asks about their pipeline, deals, or sales status."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "stage": {
                    "type": "string",
                    "description": "Filter by stage: lead, qualified, proposal, negotiation, won, lost",
                },
            },
            "required": [],
        },
        "kind": "integration",
    },
    {
        "name": "crm_create_deal",
        "description": (
            "Create a new deal/opportunity. Use when the user mentions a potential sale, "
            "project, or business opportunity with a customer."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Deal title"},
                "contact_id": {"type": "integer", "description": "Associated contact ID"},
                "stage": {"type": "string", "description": "Pipeline stage (default: lead)", "default": "lead"},
                "value": {"type": "number", "description": "Deal value in dollars", "default": 0},
                "notes": {"type": "string", "default": ""},
                "expected_close_date": {"type": "string", "description": "Expected close date (YYYY-MM-DD)", "default": ""},
                "probability": {"type": "integer", "description": "Win probability 0-100%", "default": 0},
                "currency": {"type": "string", "default": "USD"},
            },
            "required": ["title"],
        },
        "kind": "integration",
    },
    {
        "name": "crm_update_deal",
        "description": (
            "Update a deal's details — value, stage, close date, probability, notes, etc."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "deal_id": {"type": "integer", "description": "Deal ID to update"},
                "title": {"type": "string"},
                "stage": {"type": "string", "description": "lead, qualified, proposal, negotiation, won, lost"},
                "value": {"type": "number"},
                "notes": {"type": "string"},
                "expected_close_date": {"type": "string", "description": "YYYY-MM-DD"},
                "probability": {"type": "integer", "description": "0-100"},
                "currency": {"type": "string"},
                "contact_id": {"type": "integer"},
            },
            "required": ["deal_id"],
        },
        "kind": "integration",
    },
    {
        "name": "crm_update_deal_stage",
        "description": "Move a deal to a new pipeline stage. Quick way to advance or close a deal.",
        "input_schema": {
            "type": "object",
            "properties": {
                "deal_id": {"type": "integer"},
                "stage": {"type": "string", "description": "New stage: lead, qualified, proposal, negotiation, won, lost"},
            },
            "required": ["deal_id", "stage"],
        },
        "kind": "integration",
    },
    {
        "name": "crm_get_deal",
        "description": "Get full details for a specific deal including contact info and activity history.",
        "input_schema": {
            "type": "object",
            "properties": {
                "deal_id": {"type": "integer", "description": "Deal ID"},
            },
            "required": ["deal_id"],
        },
        "kind": "integration",
    },

    # ── Activities (2 tools) ──────────────────────────────────────────────────
    {
        "name": "crm_log_activity",
        "description": (
            "Log a note or activity (call, email, meeting, note, follow_up) against a contact or deal. "
            "Use this after the user mentions an interaction with a customer."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "activity": {"type": "string", "description": "Activity type: call, email, meeting, note, follow_up"},
                "note": {"type": "string", "description": "Details about the activity", "default": ""},
                "contact_id": {"type": "integer", "description": "Contact ID (optional)"},
                "deal_id": {"type": "integer", "description": "Deal ID (optional)"},
            },
            "required": ["activity"],
        },
        "kind": "integration",
    },
    {
        "name": "crm_get_activity_log",
        "description": "Get the activity history for a contact or deal, or recent activity across the CRM.",
        "input_schema": {
            "type": "object",
            "properties": {
                "contact_id": {"type": "integer", "description": "Filter by contact"},
                "deal_id": {"type": "integer", "description": "Filter by deal"},
                "limit": {"type": "integer", "description": "Max results (default 20)", "default": 20},
            },
            "required": [],
        },
        "kind": "integration",
    },

    # ── Tasks (3 tools) ──────────────────────────────────────────────────────
    {
        "name": "crm_create_task",
        "description": (
            "Create a follow-up task or reminder. Use when the user mentions needing to "
            "follow up, check in, or do something by a certain date for a customer or deal."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "What needs to be done"},
                "description": {"type": "string", "default": ""},
                "due_date": {"type": "string", "description": "Due date (YYYY-MM-DD)", "default": ""},
                "contact_id": {"type": "integer", "description": "Associated contact"},
                "deal_id": {"type": "integer", "description": "Associated deal"},
                "priority": {"type": "string", "description": "low, medium, or high", "default": "medium"},
            },
            "required": ["title"],
        },
        "kind": "integration",
    },
    {
        "name": "crm_list_tasks",
        "description": (
            "List CRM tasks with filters. Use to check what follow-ups are due, "
            "what's overdue, or what tasks exist for a customer."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "contact_id": {"type": "integer", "description": "Filter by contact"},
                "deal_id": {"type": "integer", "description": "Filter by deal"},
                "completed": {"type": "boolean", "description": "Filter: true=done, false=pending"},
                "due_before": {"type": "string", "description": "Show tasks due before this date (YYYY-MM-DD)"},
                "priority": {"type": "string", "description": "Filter: low, medium, high"},
                "limit": {"type": "integer", "default": 50},
            },
            "required": [],
        },
        "kind": "integration",
    },
    {
        "name": "crm_complete_task",
        "description": "Mark a CRM task as completed.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "integer", "description": "Task ID to complete"},
            },
            "required": ["task_id"],
        },
        "kind": "integration",
    },

    # ── Analytics (1 tool) ────────────────────────────────────────────────────
    {
        "name": "crm_dashboard",
        "description": (
            "Get a CRM summary dashboard with pipeline value, contact counts, overdue tasks, "
            "recent activity, and top deals. Use when the user asks for an overview, summary, "
            "or 'how's my pipeline'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
        "kind": "integration",
    },
]


# ═══════════════════════════════════════════════════════════════════════════════
# Tool Executor Functions
# ═══════════════════════════════════════════════════════════════════════════════

# ── Contacts ──────────────────────────────────────────────────────────────────

def crm_find_contact(query: str, status: str | None = None, tags: str | None = None) -> dict:
    contacts = crm.search_contacts(query, status=status, tags=tags)
    return {"contacts": contacts, "count": len(contacts)}


def crm_create_contact(name: str, **kwargs) -> dict:
    return crm.create_contact(name=name, **kwargs)


def crm_update_contact(contact_id: int, **kwargs) -> dict:
    result = crm.update_contact(contact_id, **kwargs)
    if not result:
        return {"error": f"Contact {contact_id} not found"}
    return result


def crm_get_contact(contact_id: int) -> dict:
    result = crm.get_contact_detail(contact_id)
    if not result:
        return {"error": f"Contact {contact_id} not found"}
    return result


def crm_list_contacts(status: str | None = None, limit: int = 50, offset: int = 0) -> dict:
    return crm.list_contacts(offset=offset, limit=limit, status=status)


def crm_delete_contact(contact_id: int) -> dict:
    if crm.delete_contact(contact_id):
        return {"deleted": True, "contact_id": contact_id}
    return {"error": f"Contact {contact_id} not found"}


# ── Deals ─────────────────────────────────────────────────────────────────────

def crm_get_pipeline(stage: str | None = None) -> dict:
    return crm.get_pipeline(stage=stage)


def crm_create_deal(title: str, **kwargs) -> dict:
    return crm.create_deal(title=title, **kwargs)


def crm_update_deal(deal_id: int, **kwargs) -> dict:
    result = crm.update_deal(deal_id, **kwargs)
    if not result:
        return {"error": f"Deal {deal_id} not found or invalid stage"}
    return result


def crm_update_deal_stage(deal_id: int, stage: str) -> dict:
    deal = crm.update_deal_stage(deal_id, stage)
    if not deal:
        return {"error": f"Deal not found or invalid stage: {stage}"}
    return deal


def crm_get_deal(deal_id: int) -> dict:
    result = crm.get_deal_detail(deal_id)
    if not result:
        return {"error": f"Deal {deal_id} not found"}
    return result


# ── Activities ────────────────────────────────────────────────────────────────

def crm_log_activity(activity: str, note: str = "", contact_id: int | None = None, deal_id: int | None = None) -> dict:
    return crm.log_activity(activity=activity, note=note, contact_id=contact_id, deal_id=deal_id)


def crm_get_activity_log(contact_id: int | None = None, deal_id: int | None = None, limit: int = 20) -> dict:
    activities = crm.get_activity_log(contact_id=contact_id, deal_id=deal_id, limit=limit)
    return {"activities": activities, "count": len(activities)}


# ── Tasks ─────────────────────────────────────────────────────────────────────

def crm_create_task(title: str, **kwargs) -> dict:
    return crm.create_task(title=title, **kwargs)


def crm_list_tasks(
    contact_id: int | None = None, deal_id: int | None = None,
    completed: bool | None = None, due_before: str | None = None,
    priority: str | None = None, limit: int = 50,
) -> dict:
    tasks = crm.list_tasks(
        contact_id=contact_id, deal_id=deal_id, completed=completed,
        due_before=due_before, priority=priority, limit=limit,
    )
    return {"tasks": tasks, "count": len(tasks)}


def crm_complete_task(task_id: int) -> dict:
    result = crm.complete_task(task_id)
    if not result:
        return {"error": f"Task {task_id} not found"}
    return result


# ── Analytics ─────────────────────────────────────────────────────────────────

def crm_dashboard() -> dict:
    return crm.get_dashboard_stats()


# ═══════════════════════════════════════════════════════════════════════════════
# Executor Mapping (used by ToolRegistry)
# ═══════════════════════════════════════════════════════════════════════════════

TOOL_EXECUTORS = {
    # Contacts
    "crm_find_contact": lambda **kw: crm_find_contact(**kw),
    "crm_create_contact": lambda **kw: crm_create_contact(**kw),
    "crm_update_contact": lambda **kw: crm_update_contact(**kw),
    "crm_get_contact": lambda **kw: crm_get_contact(**kw),
    "crm_list_contacts": lambda **kw: crm_list_contacts(**kw),
    "crm_delete_contact": lambda **kw: crm_delete_contact(**kw),
    # Deals
    "crm_get_pipeline": lambda **kw: crm_get_pipeline(**kw),
    "crm_create_deal": lambda **kw: crm_create_deal(**kw),
    "crm_update_deal": lambda **kw: crm_update_deal(**kw),
    "crm_update_deal_stage": lambda **kw: crm_update_deal_stage(**kw),
    "crm_get_deal": lambda **kw: crm_get_deal(**kw),
    # Activities
    "crm_log_activity": lambda **kw: crm_log_activity(**kw),
    "crm_get_activity_log": lambda **kw: crm_get_activity_log(**kw),
    # Tasks
    "crm_create_task": lambda **kw: crm_create_task(**kw),
    "crm_list_tasks": lambda **kw: crm_list_tasks(**kw),
    "crm_complete_task": lambda **kw: crm_complete_task(**kw),
    # Analytics
    "crm_dashboard": lambda **kw: crm_dashboard(**kw),
    # Backwards compat alias
    "crm_log_note": lambda **kw: crm_log_activity(**kw),
}
