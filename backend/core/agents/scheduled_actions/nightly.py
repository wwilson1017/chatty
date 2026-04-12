"""Nightly memory and dreaming jobs — runs per-agent at 11 PM CT.

Three jobs per agent (in order):
1. Daily note summarization — Claude Haiku summarizes yesterday's chat
2. Memory consolidation — Claude Sonnet rewrites MEMORY.md from daily notes
3. Dreaming — score files, archive dormant ones, rebuild load order
"""

import logging

logger = logging.getLogger(__name__)


def run_nightly_jobs() -> None:
    """Run nightly memory/dreaming jobs for all agents with completed onboarding."""
    try:
        from agents.db import list_agents
        from agents.engine import get_context_manager, get_chat_service, build_agent_config
        from core.providers.credentials import CredentialStore
    except Exception as e:
        logger.error("nightly: failed to import dependencies: %s", e)
        return

    agents = list_agents()
    if not agents:
        return

    # Get Anthropic API key for Claude calls
    store = CredentialStore()
    _, anthropic_profile = store.get_active_profile(provider_override="anthropic")
    api_key = (anthropic_profile or {}).get("api_key", "")

    for agent in agents:
        if not agent.get("onboarding_complete"):
            continue

        slug = agent["slug"]
        agent_name = agent["agent_name"]
        ctx_manager = get_context_manager(slug)
        chat_service = get_chat_service(slug)

        # 1. Daily note summarization
        try:
            from core.agents.memory.processor import process_daily_note_summary
            result = process_daily_note_summary(agent_name, ctx_manager, chat_service, api_key)
            logger.info("nightly daily_note_summary %s: %s", agent_name, result.get("status"))
        except Exception as e:
            logger.warning("nightly daily_note_summary failed for %s: %s", agent_name, e)

        # 2. Memory consolidation
        if api_key:
            try:
                from core.agents.memory.processor import process_memory_consolidation
                result = process_memory_consolidation(agent_name, ctx_manager, api_key, days=7)
                logger.info("nightly memory_consolidation %s: ok=%s", agent_name, result.get("ok"))
            except Exception as e:
                logger.warning("nightly memory_consolidation failed for %s: %s", agent_name, e)

        # 3. Dreaming (context file scoring + archival)
        try:
            from core.agents.dreaming.processor import process_dreaming
            result = process_dreaming(agent_name, ctx_manager)
            logger.info("nightly dreaming %s: archived=%d", agent_name, result.get("files_archived", 0))
        except Exception as e:
            logger.warning("nightly dreaming failed for %s: %s", agent_name, e)

        # 4. Archive old daily notes (>90 days)
        try:
            result = ctx_manager.archive_old_daily_notes(max_age_days=90)
            if result.get("archived", 0) > 0:
                logger.info("nightly archive %s: archived %d old daily notes", agent_name, result["archived"])
        except Exception as e:
            logger.warning("nightly archive failed for %s: %s", agent_name, e)

    logger.info("nightly jobs complete for %d agents", len(agents))
