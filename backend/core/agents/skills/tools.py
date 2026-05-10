"""Skill pack tool handlers — dispatched via kind="skill" in ToolRegistry."""

from . import db


async def execute_skill_tool(tool_name: str, tool_args: dict, data_dir: str) -> dict:
    """Route skill tool calls to the appropriate handler."""
    if tool_name == "list_skills":
        return db.list_skills(data_dir, category=tool_args.get("category"))
    elif tool_name == "run_skill":
        name = tool_args.get("name", "")
        params = tool_args.get("params")
        return db.run_skill(data_dir, name, params)
    elif tool_name == "save_skill":
        return db.save_skill(
            data_dir=data_dir,
            name=tool_args.get("name", ""),
            prompt=tool_args.get("prompt", ""),
            description=tool_args.get("description", ""),
            category=tool_args.get("category"),
            tags=tool_args.get("tags"),
            trigger_pattern=tool_args.get("trigger_pattern"),
        )
    elif tool_name == "delete_skill":
        return db.delete_skill(data_dir, tool_args.get("name", ""))
    else:
        return {"error": f"Unknown skill tool: {tool_name}"}
