"""Chatty — Model tier definitions and resolution.

Maps tier labels (top/mid/light) to concrete model IDs per provider.
Hardcoded, updated occasionally when new models are released.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.agents.config import AgentConfig

TIER_MODELS: dict[str, dict[str, str]] = {
    "anthropic": {
        "top":   "claude-opus-4-6",
        "mid":   "claude-sonnet-4-6",
        "light": "claude-haiku-4-5-20251001",
    },
    "openai": {
        "top":   "gpt-5.4",
        "mid":   "gpt-5.4-mini",
        "light": "gpt-5.4-nano",
    },
    "google": {
        "top":   "gemini-2.5-pro",
        "mid":   "gemini-2.5-flash",
        "light": "gemini-2.0-flash-lite",
    },
    "together": {
        "top":   "Qwen/Qwen3.5-32B",
        "mid":   "Qwen/Qwen3.5-14B",
        "light": "Qwen/Qwen3.5-7B",
    },
}

TIER_LABELS: dict[str, dict[str, str]] = {
    "anthropic": {"top": "Opus", "mid": "Sonnet", "light": "Haiku"},
    "openai":    {"top": "GPT-5.4", "mid": "Mini", "light": "Nano"},
    "google":    {"top": "Pro", "mid": "Flash", "light": "Lite"},
    "together":  {"top": "32B", "mid": "14B", "light": "7B"},
}

TRIAGE_CLASSIFIERS: dict[str, str] = {
    "anthropic": "claude-haiku-4-5-20251001",
    "openai":    "gpt-5.4-nano",
    "google":    "gemini-2.0-flash-lite",
}


def resolve_tier_model(provider: str, tier: str) -> str | None:
    return TIER_MODELS.get(provider, {}).get(tier)


def get_tier_info(provider: str) -> dict | None:
    models = TIER_MODELS.get(provider)
    labels = TIER_LABELS.get(provider)
    if not models or not labels:
        return None
    return {"models": models, "labels": labels}


def supports_auto_triage(provider: str) -> bool:
    return provider in TRIAGE_CLASSIFIERS


def get_triage_classifier(provider: str) -> str | None:
    return TRIAGE_CLASSIFIERS.get(provider)


def resolve_model_for_agent(config: AgentConfig, provider: str) -> str | None:
    """Full resolution: model_override > model_tier > None.

    Returns None if the tier/provider combination has no mapping,
    letting the caller fall back to the global active_model.
    """
    if config.model_override:
        return config.model_override
    tier = config.model_tier or "auto"
    if tier == "auto":
        tier = "top"
    return resolve_tier_model(provider, tier)
