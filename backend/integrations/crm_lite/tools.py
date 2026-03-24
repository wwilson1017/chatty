"""Chatty — CRM Lite agent tools."""

from . import client as crm

CRM_LITE_TOOL_DEFS = [
    {
        "name": "crm_find_contact",
        "description": "Search CRM Lite contacts by name, email, company, or notes.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search term"},
            },
            "required": ["query"],
        },
        "kind": "integration",
    },
    {
        "name": "crm_create_contact",
        "description": "Create a new contact in CRM Lite.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "email": {"type": "string", "default": ""},
                "phone": {"type": "string", "default": ""},
                "company": {"type": "string", "default": ""},
                "notes": {"type": "string", "default": ""},
            },
            "required": ["name"],
        },
        "kind": "integration",
    },
    {
        "name": "crm_log_note",
        "description": "Log a note or activity against a contact or deal.",
        "input_schema": {
            "type": "object",
            "properties": {
                "activity": {"type": "string", "description": "Activity type (e.g. 'call', 'email', 'meeting')"},
                "note": {"type": "string", "description": "Note content", "default": ""},
                "contact_id": {"type": "integer", "description": "Contact ID (optional)"},
                "deal_id": {"type": "integer", "description": "Deal ID (optional)"},
            },
            "required": ["activity"],
        },
        "kind": "integration",
    },
    {
        "name": "crm_get_pipeline",
        "description": "Get all deals in the CRM Lite pipeline, optionally filtered by stage.",
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
        "name": "crm_update_deal_stage",
        "description": "Move a deal to a new stage in the pipeline.",
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
]


def crm_find_contact(query: str) -> dict:
    contacts = crm.search_contacts(query)
    return {"contacts": contacts, "count": len(contacts)}


def crm_create_contact(name: str, email: str = "", phone: str = "", company: str = "", notes: str = "") -> dict:
    return crm.create_contact(name=name, email=email, phone=phone, company=company, notes=notes)


def crm_log_note(activity: str, note: str = "", contact_id: int | None = None, deal_id: int | None = None) -> dict:
    return crm.log_activity(activity=activity, note=note, contact_id=contact_id, deal_id=deal_id)


def crm_get_pipeline(stage: str | None = None) -> dict:
    deals = crm.get_pipeline(stage=stage)
    return {"deals": deals, "count": len(deals)}


def crm_update_deal_stage(deal_id: int, stage: str) -> dict:
    deal = crm.update_deal_stage(deal_id, stage)
    if not deal:
        return {"error": f"Deal not found or invalid stage: {stage}"}
    return deal


TOOL_EXECUTORS = {
    "crm_find_contact": lambda **kw: crm_find_contact(**kw),
    "crm_create_contact": lambda **kw: crm_create_contact(**kw),
    "crm_log_note": lambda **kw: crm_log_note(**kw),
    "crm_get_pipeline": lambda **kw: crm_get_pipeline(**kw),
    "crm_update_deal_stage": lambda **kw: crm_update_deal_stage(**kw),
}
