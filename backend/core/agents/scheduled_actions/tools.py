"""Chatty — Scheduled action tool handler functions.

Called by ToolRegistry when agents use scheduled action tools.
agent_name is injected by the registry dispatcher.
"""

from . import service


def create_scheduled_action_handler(agent_name: str, **kwargs) -> dict:
    return service.create_action(
        agent=agent_name,
        schedule_type=kwargs.get("schedule_type", "cron"),
        name=kwargs.get("name", ""),
        description=kwargs.get("description", ""),
        cron_expression=kwargs.get("cron_expression"),
        interval_minutes=kwargs.get("interval_minutes"),
        run_at=kwargs.get("run_at"),
        active_hours_start=kwargs.get("active_hours_start"),
        active_hours_end=kwargs.get("active_hours_end"),
        prompt=kwargs.get("prompt", ""),
        action_type="cron",
        always_on=kwargs.get("always_on", False),
    )


def list_scheduled_actions_handler(agent_name: str, **kwargs) -> dict:
    actions = service.list_actions(agent=agent_name)
    return {"actions": actions, "count": len(actions)}


def update_scheduled_action_handler(agent_name: str, **kwargs) -> dict:
    action_id = kwargs.get("action_id", "")
    if not action_id:
        return {"error": "action_id is required"}

    # Verify ownership
    action = service.get_action(action_id)
    if not action:
        return {"error": f"Action {action_id} not found"}
    if action["agent"] != agent_name:
        return {"error": "Cannot modify another agent's action"}

    update_fields = {k: v for k, v in kwargs.items() if k != "action_id" and v is not None}
    return service.update_action(action_id, **update_fields)


def delete_scheduled_action_handler(agent_name: str, **kwargs) -> dict:
    action_id = kwargs.get("action_id", "")
    if not action_id:
        return {"error": "action_id is required"}

    action = service.get_action(action_id)
    if not action:
        return {"error": f"Action {action_id} not found"}
    if action["agent"] != agent_name:
        return {"error": "Cannot delete another agent's action"}

    return service.delete_action(action_id)
