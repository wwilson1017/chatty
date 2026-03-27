"""Chatty — Reminder tool handler functions.

Called by ToolRegistry when agents use reminder tools.
agent_name is injected by the registry dispatcher.
"""

from . import service


def create_reminder_handler(agent_name: str, **kwargs) -> dict:
    return service.create_reminder(
        agent=agent_name,
        message=kwargs.get("message", ""),
        due_at=kwargs.get("due_at", ""),
        context=kwargs.get("context"),
    )


def list_reminders_handler(agent_name: str, **kwargs) -> dict:
    status = kwargs.get("status", "pending")
    reminders = service.list_reminders(agent=agent_name, status=status)
    return {"reminders": reminders, "count": len(reminders)}


def cancel_reminder_handler(agent_name: str = "", **kwargs) -> dict:
    reminder_id = kwargs.get("reminder_id", "")
    if not reminder_id:
        return {"error": "reminder_id is required"}
    return service.cancel_reminder(reminder_id)
