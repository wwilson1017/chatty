"""Chatty CLI — Agent session state and factory."""

import logging
from dataclasses import dataclass, field
from pathlib import Path

from core.agents.config import AgentConfig
from core.agents.context_manager import ContextManager
from core.agents.chat_history.service import ChatHistoryService
from core.providers.base import AIProvider
from core.agents.tool_registry import ToolRegistry

logger = logging.getLogger(__name__)


@dataclass
class Session:
    agent: dict
    config: AgentConfig
    provider: AIProvider
    registry: ToolRegistry
    ctx_manager: ContextManager
    chat_service: ChatHistoryService
    messages: list[dict] = field(default_factory=list)
    conversation_id: str | None = None
    tool_mode: str = "normal"
    persist: bool = True
    verbose: bool = False
    usage: dict = field(default_factory=lambda: {"input_tokens": 0, "output_tokens": 0})
    integration_tool_defs: list[dict] | None = None
    integration_tool_modes: dict[str, str] | None = None
    anthropic_api_key: str = ""
    kind_map: dict[str, str] = field(default_factory=dict)
    writes_map: dict[str, bool] = field(default_factory=dict)


def create_session(slug: str, tool_mode: str = "normal",
                   persist: bool = True, verbose: bool = False) -> Session:
    from agents.db import get_agent_by_slug
    from agents.engine import (
        build_agent_config, get_context_manager, get_chat_service, ensure_memory_db,
    )
    from core.providers import get_ai_provider
    from core.providers.credentials import CredentialStore
    from agents.tool_loader import load_integration_tools, build_agent_handlers, INTEGRATION_MODULES
    from integrations.registry import get_tool_mode
    from integrations.google.policy import google_capabilities
    from core.agents.tool_definitions import get_tool_definitions, build_writes_map
    from core.agents.ai_service import _build_kind_map
    from core.agents.tools.real_tools import load_all_real_tools

    agent = get_agent_by_slug(slug)
    if not agent:
        raise SystemExit(f"Agent not found: {slug}")

    config = build_agent_config(agent)
    ctx_manager = get_context_manager(slug)
    chat_service = get_chat_service(slug)

    try:
        ensure_memory_db(slug)
    except Exception as e:
        logger.warning("Memory DB init failed for %s: %s", slug, e)

    provider = get_ai_provider(
        agent_provider=config.provider_override or None,
        agent_model=config.model_override or None,
        agent_model_tier=config.model_tier,
    )
    if not provider:
        raise SystemExit("No AI provider configured. Set one up in the web UI first.")

    ga = config.google_accounts if hasattr(config, "google_accounts") else {}
    gmail_ids = ga.get("gmail", [])
    calendar_ids = ga.get("calendar", [])
    drive_ids = ga.get("drive", [])
    google_connected = bool(gmail_ids or calendar_ids or drive_ids)

    from integrations.registry import list_google_accounts as _list_ga
    all_ga = _list_ga()
    account_info_map = {
        aid: {"email": a.get("email", ""), "scope_grants": a.get("scope_grants", {}), "connection_status": a.get("connection_status", "ok")}
        for aid, a in all_ga.items()
    }

    integration_tool_defs, integration_executors = load_integration_tools()

    from integrations.registry import get_credentials
    integration_tool_modes = {
        name: get_tool_mode(name)
        for name in INTEGRATION_MODULES
        if "tool_mode" in get_credentials(name)
    }

    reminder_handlers, sa_handlers = build_agent_handlers(slug)
    registry = ToolRegistry(
        context_dir=config.context_dir,
        gcs_prefix=config.gcs_prefix,
        google_connected=google_connected,
        gmail_account_ids=gmail_ids,
        calendar_account_ids=calendar_ids,
        drive_account_ids=drive_ids,
        account_info_map=account_info_map,
        integration_executors=integration_executors,
        agent_slug=slug,
        agent_name=config.agent_name,
        reminder_handlers=reminder_handlers,
        scheduled_action_handlers=sa_handlers,
    )

    store = CredentialStore()
    _, anthropic_profile = store.get_active_profile(provider_override="anthropic")
    anthropic_api_key = (anthropic_profile or {}).get("key", "")

    real_tools_dir = str(Path(config.context_dir).parent / "real_tools")
    dynamic_real_tools = load_all_real_tools(real_tools_dir)
    google_caps = google_capabilities()
    tool_defs = get_tool_definitions(
        integration_tools=integration_tool_defs or None,
        dynamic_real_tools=dynamic_real_tools or None,
        **google_caps,
    )
    kind_map = _build_kind_map(tool_defs)
    writes_map = build_writes_map(tool_defs)

    return Session(
        agent=agent,
        config=config,
        provider=provider,
        registry=registry,
        ctx_manager=ctx_manager,
        chat_service=chat_service,
        tool_mode=tool_mode,
        persist=persist,
        verbose=verbose,
        integration_tool_defs=integration_tool_defs or None,
        integration_tool_modes=integration_tool_modes,
        anthropic_api_key=anthropic_api_key,
        kind_map=kind_map,
        writes_map=writes_map,
    )


def reset_conversation(session: Session):
    session.messages.clear()
    session.conversation_id = None
    session.usage = {"input_tokens": 0, "output_tokens": 0}


def switch_agent(session: Session, new_slug: str) -> Session:
    return create_session(
        new_slug,
        tool_mode=session.tool_mode,
        persist=session.persist,
        verbose=session.verbose,
    )


async def execute_approved_tool(session: Session, tool_name: str,
                                tool_args: dict, tool_use_id: str) -> dict:
    from core.agents.ai_service import _sync_context_after_tool, _build_kind_map
    from core.agents.tool_definitions import get_tool_definitions, build_writes_map
    from core.agents.tools.real_tools import load_all_real_tools
    from integrations.google.policy import google_capabilities

    real_tools_dir = str(Path(session.config.context_dir).parent / "real_tools")
    dynamic_real_tools = load_all_real_tools(real_tools_dir)
    google_caps = google_capabilities()
    tool_defs = get_tool_definitions(
        integration_tools=session.integration_tool_defs,
        dynamic_real_tools=dynamic_real_tools or None,
        **google_caps,
    )
    session.kind_map = _build_kind_map(tool_defs)
    session.writes_map = build_writes_map(tool_defs)

    if session.tool_mode == "read-only":
        return {"error": "Write operations are not permitted in read-only mode"}

    if not session.writes_map.get(tool_name, False):
        logger.error("Confirm event for non-write tool: %s", tool_name)
        return {"error": f"Tool {tool_name} is not a write operation"}

    tool_def = next((t for t in tool_defs if t["name"] == tool_name), None)
    integ_name = (tool_def or {}).get("integration", "")
    if integ_name:
        from integrations.registry import get_tool_mode as _get_tm
        if _get_tm(integ_name) == "read-only":
            return {"error": f"Write operations disabled for {integ_name} (read-only)"}

    kind = session.kind_map.get(tool_name, "context")
    result = await session.registry.execute_tool(tool_name, tool_args, kind)
    _sync_context_after_tool(tool_name, result, session.ctx_manager)

    return {
        "tool": tool_name,
        "args": tool_args,
        "toolUseId": tool_use_id,
        "result": result,
    }


def create_agent_interactive() -> dict:
    from agents.db import create_agent
    from agents.templates import seed_context_files
    from agents.engine import _context_dir

    name = input("Agent name: ").strip()
    if not name:
        raise SystemExit("Agent name is required.")
    personality = input("Personality (optional, press Enter to skip): ").strip()

    agent = create_agent(name, personality or "")

    context_dir = _context_dir(agent["slug"])
    context_dir.mkdir(parents=True, exist_ok=True)
    seed_context_files(context_dir, name)

    return agent
