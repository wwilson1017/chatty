"""Chatty — per-provider tier assignments (inferred defaults + user overrides).

The tier system (top/mid/light) must resolve *synchronously* because
resolve_tier_model() is called from synchronous code paths (get_ai_provider,
agents/router). The provider model APIs are async, so we can't list models at
resolution time. Instead:

  * the async listing path materializes name-based inference into this store
    (set_inferred), only on a genuine live fetch; and
  * the user's explicit choices are stored as overrides (set_overrides).

resolve_tier_model() then reads this store synchronously:
    per-tier override -> inferred -> hardcoded TIER_MODELS fallback.

Stored in plaintext data/model-tiers.json (not a secret). A module-level lock
guards only the read-modify-write of the JSON file — never held across async
or network work.
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

from core.storage import atomic_write_json

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent.parent.parent / "data"
TIERS_PATH = DATA_DIR / "model-tiers.json"

TIERS = ("top", "mid", "light")
_lock = threading.Lock()


def _load() -> dict:
    if TIERS_PATH.exists():
        try:
            return json.loads(TIERS_PATH.read_text(encoding="utf-8"))
        except Exception as e:
            logger.error("Failed to read model-tiers.json: %s", e)
    return {}


def get_resolved(provider: str) -> dict[str, str]:
    """Return {top, mid, light} using override -> inferred -> hardcoded fallback."""
    from core.providers.tiers import TIER_MODELS

    entry = _load().get(provider, {}) or {}
    overrides = entry.get("overrides", {}) or {}
    inferred = entry.get("inferred", {}) or {}
    fallback = TIER_MODELS.get(provider, {})
    return {
        t: overrides.get(t) or inferred.get(t) or fallback.get(t, "")
        for t in TIERS
    }


def get_overrides(provider: str) -> dict[str, str]:
    return (_load().get(provider, {}) or {}).get("overrides", {}) or {}


# Sanity cap on persisted model ids — guards against a misbehaving/compromised
# provider API returning absurd strings (matches the override length check).
_MAX_MODEL_ID_LEN = 200


def set_inferred(provider: str, mapping: dict[str, str]) -> None:
    """Persist the name-inferred tier defaults for a provider (live-fetch only)."""
    with _lock:
        data = _load()
        entry = data.setdefault(provider, {})
        entry["inferred"] = {
            t: mapping[t]
            for t in TIERS
            if mapping.get(t) and len(mapping[t]) <= _MAX_MODEL_ID_LEN
        }
        atomic_write_json(TIERS_PATH, data)


def set_overrides(provider: str, mapping: dict[str, str | None]) -> None:
    """Persist user tier overrides. A falsy value for a tier clears that override.

    Only the tier keys present in ``mapping`` are touched; others are left as-is.
    """
    with _lock:
        data = _load()
        entry = data.setdefault(provider, {})
        overrides = entry.get("overrides", {}) or {}
        for t in TIERS:
            if t in mapping:
                value = mapping[t]
                if value:
                    overrides[t] = value
                else:
                    overrides.pop(t, None)
        entry["overrides"] = overrides
        atomic_write_json(TIERS_PATH, data)
