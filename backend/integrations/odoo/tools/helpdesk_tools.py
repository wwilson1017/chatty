"""
Chatty -- Odoo Helpdesk agent tools.

10 tools covering helpdesk ticket search, details, messaging, stage management,
assignment, and team member lookup.  Each executor calls safe_get_client()
internally so the agent engine never has to manage Odoo connections.
"""

import logging

from ..helpers import safe_get_client, html_to_text

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

HELPDESK_TOOL_DEFS = [
    # 1 - odoo_search_tickets
    {
        "name": "odoo_search_tickets",
        "description": (
            "Search helpdesk tickets with optional filters for stage, team, "
            "date range, and keyword."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "stage": {
                    "type": "string",
                    "description": "Stage name to filter by (case-insensitive partial match)",
                },
                "team_id": {
                    "type": "integer",
                    "description": "Helpdesk team ID to filter by",
                },
                "date_from": {
                    "type": "string",
                    "description": "Earliest create date (YYYY-MM-DD)",
                },
                "date_to": {
                    "type": "string",
                    "description": "Latest create date (YYYY-MM-DD)",
                },
                "keyword": {
                    "type": "string",
                    "description": "Keyword to search in ticket subject (case-insensitive)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max tickets to return (default 50)",
                    "default": 50,
                },
            },
            "required": [],
        },
        "kind": "integration",
    },
    # 2 - odoo_get_ticket_details
    {
        "name": "odoo_get_ticket_details",
        "description": (
            "Get full details of a helpdesk ticket including description, "
            "priority, tags, and assignment info."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticket_id": {
                    "type": "integer",
                    "description": "Helpdesk ticket ID",
                },
            },
            "required": ["ticket_id"],
        },
        "kind": "integration",
    },
    # 3 - odoo_get_team_members
    {
        "name": "odoo_get_team_members",
        "description": (
            "List members of a helpdesk team. If no team_id is given, "
            "returns all users assigned to any helpdesk team."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "team_id": {
                    "type": "integer",
                    "description": "Helpdesk team ID to filter by (optional)",
                },
            },
            "required": [],
        },
        "kind": "integration",
    },
    # 4 - odoo_get_ticket_messages
    {
        "name": "odoo_get_ticket_messages",
        "description": (
            "Fetch the chatter / message history for a helpdesk ticket. "
            "Skips notification-type messages and returns chronological order."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticket_id": {
                    "type": "integer",
                    "description": "Helpdesk ticket ID",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max messages to return (default 50)",
                    "default": 50,
                },
            },
            "required": ["ticket_id"],
        },
        "kind": "integration",
    },
    # 5 - odoo_resolve_user_partner
    {
        "name": "odoo_resolve_user_partner",
        "description": (
            "Resolve a user to their partner_id (needed for messaging). "
            "Provide at least one of: name, email, or user_id."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "User name to search (case-insensitive partial match)",
                },
                "email": {
                    "type": "string",
                    "description": "User email to search (case-insensitive partial match)",
                },
                "user_id": {
                    "type": "integer",
                    "description": "Odoo user ID to look up directly",
                },
            },
            "required": [],
        },
        "kind": "integration",
    },
    # 6 - odoo_update_ticket_stage
    {
        "name": "odoo_update_ticket_stage",
        "description": (
            "Move a helpdesk ticket to a different stage. "
            "Verifies the stage actually changed (Odoo automations can revert)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticket_id": {
                    "type": "integer",
                    "description": "Helpdesk ticket ID",
                },
                "stage_id": {
                    "type": "integer",
                    "description": "Target stage ID to move the ticket to",
                },
            },
            "required": ["ticket_id", "stage_id"],
        },
        "kind": "integration",
    },
    # 7 - odoo_assign_ticket
    {
        "name": "odoo_assign_ticket",
        "description": "Assign a helpdesk ticket to a user.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ticket_id": {
                    "type": "integer",
                    "description": "Helpdesk ticket ID",
                },
                "user_id": {
                    "type": "integer",
                    "description": "User ID to assign the ticket to",
                },
            },
            "required": ["ticket_id", "user_id"],
        },
        "kind": "integration",
    },
    # 8 - odoo_post_ticket_message
    {
        "name": "odoo_post_ticket_message",
        "description": (
            "Post a message on a helpdesk ticket. Without partner_ids it posts "
            "a quiet internal note; with partner_ids it sends notifications."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticket_id": {
                    "type": "integer",
                    "description": "Helpdesk ticket ID",
                },
                "message": {
                    "type": "string",
                    "description": "Message body (plain text or HTML)",
                },
                "partner_ids": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "Partner IDs to notify (omit for quiet internal note)",
                },
            },
            "required": ["ticket_id", "message"],
        },
        "kind": "integration",
    },
    # 9 - odoo_send_ticket_reply
    {
        "name": "odoo_send_ticket_reply",
        "description": (
            "Send an email reply on a helpdesk ticket to the ticket creator. "
            "Uses mt_comment subtype so the customer receives an email."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticket_id": {
                    "type": "integer",
                    "description": "Helpdesk ticket ID",
                },
                "message": {
                    "type": "string",
                    "description": "Reply message body (plain text or HTML)",
                },
            },
            "required": ["ticket_id", "message"],
        },
        "kind": "integration",
    },
    # 10 - odoo_send_internal_message
    {
        "name": "odoo_send_internal_message",
        "description": (
            "Send a standalone internal notification to a user's Discuss inbox. "
            "Not attached to any specific ticket or record."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "partner_id": {
                    "type": "integer",
                    "description": "Partner ID of the recipient (use odoo_resolve_user_partner to find this)",
                },
                "subject": {
                    "type": "string",
                    "description": "Message subject line",
                },
                "message": {
                    "type": "string",
                    "description": "Message body (plain text)",
                },
            },
            "required": ["partner_id", "subject", "message"],
        },
        "kind": "integration",
    },
]

# ---------------------------------------------------------------------------
# Executor functions
# ---------------------------------------------------------------------------


def _odoo_search_tickets(
    stage: str = None,
    team_id: int = None,
    date_from: str = None,
    date_to: str = None,
    keyword: str = None,
    limit: int = 50,
) -> dict:
    """Search helpdesk tickets with optional filters."""
    client, err = safe_get_client()
    if err:
        return err

    domain = []
    if stage:
        domain.append(["stage_id.name", "ilike", stage])
    if team_id:
        domain.append(["team_id", "=", team_id])
    if date_from:
        domain.append(["create_date", ">=", f"{date_from} 00:00:00"])
    if date_to:
        domain.append(["create_date", "<=", f"{date_to} 23:59:59"])
    if keyword:
        domain.append(["name", "ilike", keyword])

    fields = [
        "id", "name", "partner_id", "partner_email", "team_id",
        "stage_id", "user_id", "create_date", "description",
    ]
    records = client.search_read("helpdesk.ticket", domain, fields, limit=limit) or []

    tickets = []
    for r in records:
        tickets.append({
            "id": r["id"],
            "subject": r.get("name", ""),
            "partner": r["partner_id"][1] if r.get("partner_id") else None,
            "partner_email": r.get("partner_email", ""),
            "team": r["team_id"][1] if r.get("team_id") else None,
            "team_id": r["team_id"][0] if r.get("team_id") else None,
            "stage": r["stage_id"][1] if r.get("stage_id") else None,
            "stage_id": r["stage_id"][0] if r.get("stage_id") else None,
            "assigned_to": r["user_id"][1] if r.get("user_id") else None,
            "created": r.get("create_date", ""),
            "description_preview": html_to_text(r.get("description", ""))[:200],
        })
    return {"tickets": tickets, "total": len(tickets)}


def _odoo_get_ticket_details(ticket_id: int) -> dict:
    """Get full details of a helpdesk ticket."""
    client, err = safe_get_client()
    if err:
        return err

    fields = [
        "id", "name", "partner_id", "partner_email", "partner_name",
        "team_id", "stage_id", "user_id", "create_date", "write_date",
        "description", "priority", "tag_ids",
    ]
    records = client.search_read(
        "helpdesk.ticket", [["id", "=", ticket_id]], fields, limit=1,
    ) or []
    if not records:
        return {"error": f"Ticket #{ticket_id} not found"}

    r = records[0]
    return {
        "id": r["id"],
        "subject": r.get("name", ""),
        "partner": r["partner_id"][1] if r.get("partner_id") else None,
        "partner_email": r.get("partner_email", ""),
        "partner_name": r.get("partner_name", ""),
        "team": r["team_id"][1] if r.get("team_id") else None,
        "team_id": r["team_id"][0] if r.get("team_id") else None,
        "stage": r["stage_id"][1] if r.get("stage_id") else None,
        "stage_id": r["stage_id"][0] if r.get("stage_id") else None,
        "assigned_to": r["user_id"][1] if r.get("user_id") else None,
        "assigned_to_id": r["user_id"][0] if r.get("user_id") else None,
        "created": r.get("create_date", ""),
        "updated": r.get("write_date", ""),
        "priority": r.get("priority", "0"),
        "body_text": html_to_text(r.get("description", "")),
        "body_html": r.get("description", ""),
    }


def _odoo_get_team_members(team_id: int = None) -> dict:
    """List helpdesk team members."""
    client, err = safe_get_client()
    if err:
        return err

    domain = []
    if team_id:
        domain = [["helpdesk_team_ids", "in", [team_id]]]

    fields = ["name", "email", "helpdesk_team_ids", "partner_id"]
    records = client.search_read("res.users", domain, fields, limit=100) or []

    members = []
    for r in records:
        teams = r.get("helpdesk_team_ids", [])
        if not teams and not team_id:
            continue
        members.append({
            "id": r["id"],
            "name": r.get("name", ""),
            "email": r.get("email", ""),
            "partner_id": r["partner_id"][0] if r.get("partner_id") else None,
        })
    return {"members": members, "total": len(members)}


def _odoo_get_ticket_messages(ticket_id: int, limit: int = 50) -> dict:
    """Fetch chatter history for a helpdesk ticket."""
    client, err = safe_get_client()
    if err:
        return err

    fields = [
        "id", "date", "body", "author_id", "message_type",
        "subtype_id", "email_from", "attachment_ids",
    ]
    records = client.search_read(
        "mail.message",
        [["model", "=", "helpdesk.ticket"], ["res_id", "=", ticket_id]],
        fields,
        limit=limit,
    ) or []

    messages = []
    for r in records:
        msg_type = r.get("message_type", "")
        if msg_type == "notification":
            continue
        messages.append({
            "id": r["id"],
            "date": r.get("date", ""),
            "body_html": r.get("body", ""),
            "body_text": html_to_text(r.get("body", "")),
            "author": r["author_id"][1] if r.get("author_id") else None,
            "author_id": r["author_id"][0] if r.get("author_id") else None,
            "message_type": msg_type,
            "subtype": r["subtype_id"][1] if r.get("subtype_id") else None,
            "email_from": r.get("email_from", ""),
            "attachment_count": len(r.get("attachment_ids", [])),
        })

    messages.sort(key=lambda m: m["date"])
    return {"messages": messages, "total": len(messages)}


def _odoo_resolve_user_partner(
    name: str = None, email: str = None, user_id: int = None,
) -> dict:
    """Resolve a user to their partner_id."""
    domain = []
    if user_id:
        domain.append(["id", "=", user_id])
    if name:
        domain.append(["name", "ilike", name])
    if email:
        domain.append(["email", "ilike", email])
    if not domain:
        return {"error": "Provide at least one of: name, email, or user_id"}

    client, err = safe_get_client()
    if err:
        return err

    fields = ["name", "email", "partner_id"]
    records = client.search_read("res.users", domain, fields, limit=10) or []
    if not records:
        return {
            "error": "No matching user found",
            "filters": {"name": name, "email": email, "user_id": user_id},
        }

    users = []
    for r in records:
        users.append({
            "user_id": r["id"],
            "name": r.get("name", ""),
            "email": r.get("email", ""),
            "partner_id": r["partner_id"][0] if r.get("partner_id") else None,
        })
    return {"users": users, "total": len(users)}


def _odoo_update_ticket_stage(ticket_id: int, stage_id: int) -> dict:
    """Move a helpdesk ticket to a different stage."""
    client, err = safe_get_client()
    if err:
        return err

    ticket_id, stage_id = int(ticket_id), int(stage_id)
    client.write("helpdesk.ticket", [ticket_id], {"stage_id": stage_id})

    # Verify the stage actually changed (automations can revert)
    verify = client.search_read(
        "helpdesk.ticket", [["id", "=", ticket_id]], ["stage_id"], limit=1,
    ) or []
    actual = verify[0]["stage_id"][0] if verify and verify[0].get("stage_id") else None
    if actual != stage_id:
        return {
            "ok": False,
            "ticket_id": ticket_id,
            "error": (
                f"Stage write accepted but ticket is still in stage {actual} "
                "-- an Odoo automation may have reverted it"
            ),
        }
    return {"ok": True, "ticket_id": ticket_id, "new_stage_id": stage_id}


def _odoo_assign_ticket(ticket_id: int, user_id: int) -> dict:
    """Assign a helpdesk ticket to a user."""
    client, err = safe_get_client()
    if err:
        return err

    ticket_id, user_id = int(ticket_id), int(user_id)
    client.write("helpdesk.ticket", [ticket_id], {"user_id": user_id})
    return {"ok": True, "ticket_id": ticket_id, "assigned_to_id": user_id}


def _odoo_post_ticket_message(
    ticket_id: int, message: str, partner_ids: list[int] = None,
) -> dict:
    """Post a message on a helpdesk ticket."""
    client, err = safe_get_client()
    if err:
        return err

    kwargs: dict = {"body": message, "message_type": "comment"}
    if partner_ids:
        kwargs["subtype_xmlid"] = "mail.mt_comment"
        kwargs["partner_ids"] = partner_ids
    else:
        kwargs["subtype_xmlid"] = "mail.mt_note"

    result = client.execute("helpdesk.ticket", "message_post", [ticket_id], **kwargs)
    if result:
        return {
            "ok": True,
            "ticket_id": ticket_id,
            "message_id": result,
            "notified_partner_ids": partner_ids or [],
        }
    return {"ok": False, "error": "Failed to post message"}


def _odoo_send_ticket_reply(ticket_id: int, message: str) -> dict:
    """Send an email reply on a helpdesk ticket to the ticket creator."""
    client, err = safe_get_client()
    if err:
        return err

    result = client.execute(
        "helpdesk.ticket", "message_post", [ticket_id],
        body=message, message_type="comment", subtype_xmlid="mail.mt_comment",
    )
    if result:
        return {"ok": True, "ticket_id": ticket_id, "message_id": result}
    return {"ok": False, "error": "Failed to send reply"}


def _odoo_send_internal_message(
    partner_id: int, subject: str, message: str,
) -> dict:
    """Send a standalone internal notification to a user's Discuss inbox."""
    client, err = safe_get_client()
    if err:
        return err

    try:
        result = client.execute(
            "mail.thread", "message_notify",
            body=f"<p>{message}</p>",
            partner_ids=[partner_id],
            subject=subject,
            message_type="comment",
        )
        if result:
            return {
                "ok": True,
                "partner_id": partner_id,
                "subject": subject,
                "message_id": result,
            }
        return {
            "ok": False,
            "error": "message_notify returned falsy -- check partner_id is valid",
        }
    except Exception as e:
        return {"ok": False, "error": f"message_notify failed: {e}"}


# ---------------------------------------------------------------------------
# Executor map
# ---------------------------------------------------------------------------

HELPDESK_EXECUTORS = {
    "odoo_search_tickets": lambda **kw: _odoo_search_tickets(**kw),
    "odoo_get_ticket_details": lambda **kw: _odoo_get_ticket_details(**kw),
    "odoo_get_team_members": lambda **kw: _odoo_get_team_members(**kw),
    "odoo_get_ticket_messages": lambda **kw: _odoo_get_ticket_messages(**kw),
    "odoo_resolve_user_partner": lambda **kw: _odoo_resolve_user_partner(**kw),
    "odoo_update_ticket_stage": lambda **kw: _odoo_update_ticket_stage(**kw),
    "odoo_assign_ticket": lambda **kw: _odoo_assign_ticket(**kw),
    "odoo_post_ticket_message": lambda **kw: _odoo_post_ticket_message(**kw),
    "odoo_send_ticket_reply": lambda **kw: _odoo_send_ticket_reply(**kw),
    "odoo_send_internal_message": lambda **kw: _odoo_send_internal_message(**kw),
}
