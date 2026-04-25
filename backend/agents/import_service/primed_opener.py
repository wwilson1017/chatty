"""Generate the primed opener message for a newly-imported agent.

Uses a one-shot Claude call (same pattern as consolidate_memory) to produce
a warm 1-2 sentence greeting that demonstrates the agent internalized
the imported knowledge.
"""

from __future__ import annotations

import logging

from core.agents.context_manager import ContextManager
from core.providers.credentials import CredentialStore

logger = logging.getLogger(__name__)


def generate_opener(ctx_manager: ContextManager, agent_name: str) -> str:
    """Read the agent's freshly-written context and generate a primed greeting.

    Falls back to a generic greeting if no API key is available or the call fails.
    """
    context = ctx_manager.load_all_context(agent_name=agent_name)
    if not context:
        return _fallback(agent_name)

    store = CredentialStore()
    _, profile = store.get_active_profile(provider_override="anthropic")
    api_key = (profile or {}).get("key", "")
    if not api_key:
        return _fallback(agent_name)

    system_prompt = (
        f"You are {agent_name}, an AI agent that just finished importing knowledge "
        "from another system. Your context files have been populated with personality, "
        "memory, and user information.\n\n"
        "Write a warm, natural 1-2 sentence opening message. Demonstrate that you "
        "absorbed the imported knowledge by referencing something specific — a project, "
        "a preference, the user's name, or a detail from your memory.\n\n"
        "Do NOT mention 'importing' or 'migration' or technical details. Just greet "
        "your human like you already know them. Be yourself.\n\n"
        "Output ONLY the greeting message, no preamble."
    )

    user_message = (
        "Here is your full context (personality, memory, user info, etc.):\n\n"
        f"{context[:8000]}\n\n"
        "Now write your opening greeting."
    )

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=256,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )
    except Exception as e:
        logger.warning("Primed opener generation failed: %s", e)
        return _fallback(agent_name)

    text = ""
    for block in response.content:
        if getattr(block, "type", None) == "text":
            text += block.text

    return text.strip() or _fallback(agent_name)


def _fallback(agent_name: str) -> str:
    return (
        f"Hey — I'm {agent_name}. I just finished going through everything you "
        "brought over. Ready to pick up where we left off?"
    )
