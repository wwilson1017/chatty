"""
Chatty — AI provider factory.

Returns the active AIProvider based on credentials in data/auth-profiles.json.
"""

from core.providers.base import AIProvider
from core.providers.credentials import CredentialStore


def get_ai_provider(agent_provider: str | None = None, agent_model: str | None = None) -> AIProvider | None:
    """
    Return an initialized AIProvider for the active (or specified) provider.

    Args:
        agent_provider: Optional per-agent provider override ("anthropic", "openai", "google").
        agent_model: Optional per-agent model override.

    Returns None if no provider is configured.
    """
    store = CredentialStore()
    profile_name, profile = store.get_active_profile(provider_override=agent_provider)

    if not profile:
        return None

    provider_type = profile.get("type")
    raw_model = agent_model or store.data.get("active_model", "")
    model = raw_model if raw_model and raw_model != "default" else ""

    if profile_name.startswith("anthropic:"):
        from core.providers.anthropic_provider import AnthropicProvider
        return AnthropicProvider(api_key=profile.get("key", ""), model=model or "claude-opus-4-6")

    elif profile_name.startswith("openai:"):
        from core.providers.openai_provider import OpenAIProvider
        access_token = profile.get("access", "")
        return OpenAIProvider(access_token=access_token, model=model or "gpt-4o")

    elif profile_name.startswith("google:"):
        from core.providers.google_provider import GoogleProvider
        access_token = profile.get("access", "")
        return GoogleProvider(access_token=access_token, model=model or "gemini-2.0-flash-exp")

    return None
