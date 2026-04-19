"""Shared knowledge bootstrap — auto-populate shared context on second agent creation.

When a second agent is created, reads all existing agents' knowledge files,
uses AI to extract universally useful facts (user name, company, preferences),
and writes them as shared context entries. A marker file prevents re-runs.
"""

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from . import db

logger = logging.getLogger(__name__)

CT_TZ = ZoneInfo("America/Chicago")
DATA_DIR = Path(__file__).resolve().parent.parent.parent.parent / "data"
SHARED_DIR = DATA_DIR / "shared"
BOOTSTRAP_MARKER = SHARED_DIR / ".bootstrap-complete"

MAX_KNOWLEDGE_CHARS = 50_000

EXTRACTION_PROMPT = """\
You are analyzing an AI assistant's knowledge files to extract universally useful \
information that should be shared across all agents in a multi-agent system.

Below are knowledge files from existing agents. Extract facts that ANY agent would \
benefit from knowing — information about the user, their company, contacts, processes, \
and preferences.

DO NOT extract:
- Agent-specific personality traits or identity (soul.md content about the agent itself)
- Template/placeholder content (e.g., "(figured out during onboarding)", "Not yet discussed")
- Conversation logs or daily notes details
- Internal operational notes about the agent's own behavior
- The agent's name or role

DO extract:
- User's name, title, timezone, contact preferences
- Company name, industry, team members, products/services
- Key contacts and their roles
- Communication preferences that apply to all agents
- Business processes and workflows
- Tools and systems the user works with

Output ONLY a JSON array of entries. Each entry has:
{
  "category": one of "user-profile", "company-info", "preferences", "contacts", "processes", "tools-and-systems",
  "title": "short descriptive title (under 80 chars)",
  "content": "the extracted information (1-5 sentences, factual)"
}

If there is nothing meaningful to extract (all templates, no real content), return: []

IMPORTANT: Output ONLY the JSON array, no markdown fences, no commentary."""


def should_bootstrap() -> bool:
    return not BOOTSTRAP_MARKER.exists()


def _mark_bootstrap_complete() -> None:
    SHARED_DIR.mkdir(parents=True, exist_ok=True)
    BOOTSTRAP_MARKER.write_text(
        datetime.now(CT_TZ).isoformat(),
        encoding="utf-8",
    )


def _gather_all_agent_knowledge() -> dict[str, str]:
    from agents.db import list_agents
    from core.agents.context_manager import ContextManager

    agents = list_agents()
    results = {}

    for agent in agents:
        slug = agent["slug"]
        context_dir = DATA_DIR / "agents" / slug / "context"
        if not context_dir.exists():
            continue

        cm = ContextManager(data_dir=context_dir, gcs_prefix=f"agents/{slug}/context/")
        text = cm.load_all_context()

        if len(text.strip()) < 500:
            logger.debug("Skipping agent %s — too little content (%d chars)", slug, len(text))
            continue

        results[slug] = text

    return results


async def _extract_shared_knowledge(knowledge_texts: dict[str, str]) -> list[dict] | None:
    """Returns list of entries, or None if no AI provider is available."""
    from core.providers import get_ai_provider

    provider = get_ai_provider()
    if not provider:
        logger.warning("No AI provider configured — cannot run shared knowledge bootstrap")
        return None

    combined = ""
    for slug, text in knowledge_texts.items():
        combined += f"\n\n--- Agent: {slug} ---\n\n{text}"

    if len(combined) > MAX_KNOWLEDGE_CHARS:
        combined = combined[:MAX_KNOWLEDGE_CHARS]

    messages = [{"role": "user", "content": combined}]
    accumulated_text = ""

    async for event in provider.stream_turn(messages, [], EXTRACTION_PROMPT):
        etype = event.get("type", "")
        if etype == "text":
            accumulated_text += event["text"]

    accumulated_text = accumulated_text.strip()
    if accumulated_text.startswith("```"):
        lines = accumulated_text.split("\n")
        if lines and lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        accumulated_text = "\n".join(lines).strip()

    try:
        entries = json.loads(accumulated_text)
    except json.JSONDecodeError:
        logger.error("Failed to parse AI response as JSON: %.200s", accumulated_text)
        return None

    if not isinstance(entries, list):
        logger.error("AI response is not a list: %s", type(entries))
        return None

    valid_categories = {
        "user-profile", "company-info", "preferences",
        "contacts", "processes", "tools-and-systems",
    }
    validated = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        title = entry.get("title", "").strip()
        content = entry.get("content", "").strip()
        category = entry.get("category", "").strip()
        if not title or not content:
            continue
        title = title[:200]
        content = content[:2000]
        if category not in valid_categories:
            category = "user-profile"
        validated.append({"category": category, "title": title, "content": content})

    return validated


def _populate_shared_context(entries: list[dict]) -> int:
    count = 0
    for entry in entries:
        db.add_entry(
            agent_name="system-bootstrap",
            title=entry["title"],
            content=entry["content"],
            category=entry["category"],
        )
        count += 1

    if count > 0:
        try:
            db.backup_to_gcs()
        except Exception as e:
            logger.warning("GCS backup after bootstrap failed: %s", e)

    return count


async def run_bootstrap(force: bool = False) -> dict:
    if not force and not should_bootstrap():
        return {"status": "skipped", "reason": "already_complete"}

    if force and BOOTSTRAP_MARKER.exists():
        BOOTSTRAP_MARKER.unlink()

    knowledge = _gather_all_agent_knowledge()
    if not knowledge:
        _mark_bootstrap_complete()
        return {"status": "complete", "entries_added": 0, "agents_analyzed": 0, "reason": "no_content"}

    entries = await _extract_shared_knowledge(knowledge)

    if entries is None:
        return {"status": "failed", "reason": "no_provider"}

    count = _populate_shared_context(entries)
    _mark_bootstrap_complete()

    logger.info("Shared knowledge bootstrap complete: %d entries from %d agents", count, len(knowledge))
    return {"status": "complete", "entries_added": count, "agents_analyzed": len(knowledge)}


def run_bootstrap_sync(force: bool = False) -> dict:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(asyncio.run, run_bootstrap(force))
            return future.result(timeout=300)
    else:
        return asyncio.run(run_bootstrap(force))
