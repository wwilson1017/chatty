"""Chatty — Model tier definitions, inference, and resolution.

Tier labels (top/mid/light) map to concrete model IDs per provider. The
mapping is resolved synchronously (resolve_tier_model) as override -> inferred
-> hardcoded fallback; see model_tiers.py. infer_tier_models() produces the
name-based default from a live model list (called from the async listing path).
"""

from __future__ import annotations

import re


# Hardcoded fallback only. Resolution order is override -> inferred -> this map
# (see resolve_tier_model / model_tiers.py). Kept current by the price-check skill.
TIER_MODELS: dict[str, dict[str, str]] = {
    "anthropic": {
        "top":   "claude-opus-4-8",
        "mid":   "claude-sonnet-4-6",
        "light": "claude-haiku-4-5",
    },
    "openai": {
        "top":   "gpt-5.5",
        "mid":   "gpt-5.4-mini",
        "light": "gpt-5.4-nano",
    },
    "google": {
        "top":   "gemini-2.5-pro",
        "mid":   "gemini-2.5-flash",
        "light": "gemini-2.5-flash-lite",
    },
    "together": {
        "top":   "Qwen/Qwen3.5-32B",
        "mid":   "Qwen/Qwen3.5-14B",
        "light": "Qwen/Qwen3.5-7B",
    },
}

# Fallback display labels. The /tiers endpoint derives labels from the resolved
# model ids; these are used only when no resolved id is available.
TIER_LABELS: dict[str, dict[str, str]] = {
    "anthropic": {"top": "Opus", "mid": "Sonnet", "light": "Haiku"},
    "openai":    {"top": "GPT-5.5", "mid": "Mini", "light": "Nano"},
    "google":    {"top": "Pro", "mid": "Flash", "light": "Flash-Lite"},
    "together":  {"top": "32B", "mid": "14B", "light": "7B"},
}

# Hardcoded fallback for the triage classifier (the cheap "light"-tier model).
# get_triage_classifier() prefers override/inferred and falls back to this.
TRIAGE_CLASSIFIERS: dict[str, str] = {
    "anthropic": "claude-haiku-4-5",
    "openai":    "gpt-5.4-nano",
    "google":    "gemini-2.5-flash-lite",
}


# ── Name-based tier inference (pure; no I/O) ───────────────────────────────────

def _version_key(model: str) -> tuple[int, ...]:
    return tuple(int(n) for n in re.findall(r"\d+", model))


def _best(candidates: list[str]) -> str | None:
    """Pick the highest-version candidate (ties broken by string)."""
    if not candidates:
        return None
    return max(candidates, key=lambda m: (_version_key(m), m))


def infer_tier_models(provider: str, available: list[str]) -> dict[str, str]:
    """Best-guess {top, mid, light} from a live model list, by naming.

    Pure function — no I/O. Falls back per-tier to the hardcoded TIER_MODELS
    entry when no candidate matches. The async listing path calls this and
    persists the result via model_tiers.set_inferred (live fetches only).
    """
    fb = TIER_MODELS.get(provider, {})
    av = [m for m in (available or []) if m]
    top = mid = light = None

    if provider == "anthropic":
        top = _best([m for m in av if "opus" in m.lower()])
        mid = _best([m for m in av if "sonnet" in m.lower()])
        light = _best([m for m in av if "haiku" in m.lower()])
    elif provider == "google":
        top = _best([m for m in av if "pro" in m.lower()])
        light = _best([m for m in av if "lite" in m.lower()])
        mid = _best([m for m in av if "flash" in m.lower() and "lite" not in m.lower()])
    elif provider == "openai":
        light = _best([m for m in av if "-nano" in m.lower()])
        mid = _best([m for m in av if "-mini" in m.lower()])
        top = _best([
            m for m in av
            if "-mini" not in m.lower() and "-nano" not in m.lower()
            and (m.lower().startswith("gpt-") or m.lower().startswith("o"))
        ])
    elif provider == "together":
        def _params(m: str) -> int:
            nums = re.findall(r"(\d+)\s*b", m.lower())
            return int(nums[-1]) if nums else 0
        sized = sorted(av, key=_params, reverse=True)
        if sized:
            top = sized[0]
            light = sized[-1]
            mid = sized[len(sized) // 2]

    return {
        "top": top or fb.get("top", ""),
        "mid": mid or fb.get("mid", ""),
        "light": light or fb.get("light", ""),
    }


def infer_triage_classifier(provider: str, available: list[str]) -> str | None:
    """The cheap triage/classifier model = inferred 'light' tier."""
    return infer_tier_models(provider, available).get("light") or TRIAGE_CLASSIFIERS.get(provider)


# ── Synchronous resolution (override -> inferred -> hardcoded) ──────────────────

def resolve_tier_model(provider: str, tier: str) -> str | None:
    """Resolve a tier to a concrete model id. Synchronous by contract —
    callers (get_ai_provider, agents/router) run in sync context, so this reads
    the materialized model_tiers store and never lists models live."""
    from core.providers.model_tiers import get_resolved
    return get_resolved(provider).get(tier) or None


def _short_label(model_id: str) -> str:
    """Compact display label from a model id (Together 'org/Name' -> 'Name')."""
    return model_id.split("/")[-1] if model_id else ""


def derive_tier_labels(provider: str) -> dict[str, str]:
    """Display labels per tier, derived from the resolved model id, with
    TIER_LABELS as fallback. Always non-empty for a known provider so the
    frontend tier switcher never hides itself."""
    from core.providers.model_tiers import get_resolved
    resolved = get_resolved(provider)
    fb = TIER_LABELS.get(provider, {})
    return {
        t: _short_label(resolved.get(t, "")) or fb.get(t, t.title())
        for t in ("top", "mid", "light")
    }


def get_tier_info(provider: str) -> dict | None:
    from core.providers.model_tiers import get_resolved
    models = get_resolved(provider)
    if not any(models.values()):
        return None
    return {"models": models, "labels": derive_tier_labels(provider)}


def supports_auto_triage(provider: str) -> bool:
    return provider in TRIAGE_CLASSIFIERS


def get_triage_classifier(provider: str) -> str | None:
    """The cheap classifier model: resolved 'light' tier, else hardcoded."""
    from core.providers.model_tiers import get_resolved
    light = get_resolved(provider).get("light")
    return light or TRIAGE_CLASSIFIERS.get(provider)
