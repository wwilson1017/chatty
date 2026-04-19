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
        if profile.get("type") == "setup_token":
            return AnthropicProvider(api_key=profile.get("token", ""), model=model or "claude-opus-4-6")
        return AnthropicProvider(api_key=profile.get("key", ""), model=model or "claude-opus-4-6")

    elif profile_name.startswith("openai:"):
        from core.providers.openai_provider import OpenAIProvider
        if profile.get("type") == "api_key":
            return OpenAIProvider(access_token=profile.get("key", ""), model=model or "gpt-5.4")
        if profile.get("type") == "chatgpt_oauth":
            access_token = profile.get("access", "")
            # Refresh token if expired
            if store.is_token_expired("openai"):
                try:
                    import asyncio
                    from core.providers.chatgpt_refresh import refresh_chatgpt_token
                    tokens = asyncio.get_event_loop().run_until_complete(
                        refresh_chatgpt_token(profile.get("refresh", ""))
                    )
                    access_token = tokens["access_token"]
                    store.set_chatgpt_oauth(
                        access_token=tokens["access_token"],
                        refresh_token=tokens["refresh_token"],
                        expires_in=tokens["expires_in"],
                        model=model or "gpt-5.4",
                    )
                except Exception as e:
                    import logging
                    logging.getLogger(__name__).warning("ChatGPT token refresh failed: %s", e)
            return OpenAIProvider(access_token=access_token, model=model or "gpt-5.4", use_chatgpt_api=True)
        access_token = profile.get("access", "")
        return OpenAIProvider(access_token=access_token, model=model or "gpt-5.4")

    elif profile_name.startswith("google:"):
        from core.providers.google_provider import GoogleProvider
        if profile.get("type") == "api_key":
            return GoogleProvider(api_key=profile.get("key", ""), model=model or "gemini-2.0-flash-exp")
        access_token = profile.get("access", "")
        return GoogleProvider(access_token=access_token, model=model or "gemini-2.0-flash-exp")

    elif profile_name.startswith("ollama:"):
        from core.providers.ollama_provider import OllamaProvider
        base_url = profile.get("base_url", "http://localhost:11434")
        return OllamaProvider(base_url=base_url, model=model or "")

    elif profile_name.startswith("together:"):
        from core.providers.together_provider import TogetherProvider
        return TogetherProvider(api_key=profile.get("key", ""), model=model or "Qwen/Qwen3.5-7B")

    return None
