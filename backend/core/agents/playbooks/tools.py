"""Playbook tool handlers — dispatched via kind="playbook" in ToolRegistry."""

from . import service


async def execute_playbook_tool(
    tool_name: str,
    tool_args: dict,
    agent_slug: str,
    conversation_id: str | None = None,
    origin: str = "agent",
) -> dict | list:
    """Route playbook tool calls to the appropriate service function."""
    if tool_name == "list_playbooks":
        return service.list_playbooks(agent_slug, include_archived=True)
    elif tool_name == "read_playbook":
        slug = tool_args.get("slug", "")
        result = service.read_playbook(agent_slug, slug, bump=True)
        if not result:
            return {"error": f"Playbook '{slug}' not found"}
        return result
    elif tool_name == "save_playbook":
        return service.save_playbook(
            agent_slug,
            name=tool_args.get("name"),
            description=tool_args.get("description"),
            content=tool_args.get("content"),
            integrations=tool_args.get("integrations"),
            chip=tool_args.get("chip"),
            origin=origin,
            slug=tool_args.get("slug"),
            conversation_id=conversation_id,
        )
    elif tool_name == "archive_playbook":
        return service.archive_playbook(
            agent_slug,
            tool_args.get("slug", ""),
            origin=origin,
            conversation_id=conversation_id,
        )
    else:
        return {"error": f"Unknown playbook tool: {tool_name}"}
