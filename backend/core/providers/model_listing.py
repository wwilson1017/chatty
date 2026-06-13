"""Chatty — shared TTL cache for provider model lists.

Wraps a provider's live "list models" call so the model dropdown doesn't hit
the provider API on every open, and so tier inference can tell a genuine live
fetch from a fallback. Only genuine live fetches are allowed to overwrite
inferred tiers (see tiers.infer_tier_models / model_tiers.set_inferred) — a
transient API failure returns the stale fallback and must NOT clobber good
inferred tiers.

Mirrors the existing per-module cache pattern (anthropic_provider._client_cache,
OllamaProvider._tool_support_cache).
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
import weakref
from typing import Awaitable, Callable

logger = logging.getLogger(__name__)

# 12h — model catalogs change rarely; the price-check skill / connect flow
# can invalidate explicitly when a fresher read is wanted.
DEFAULT_TTL = 12 * 60 * 60

# key -> (monotonic_timestamp, models)
_cache: dict[str, tuple[float, list[str]]] = {}
# key -> asyncio.Lock for single-flight (avoid concurrent cold fetches per key).
# WeakValueDictionary so locks are reclaimed once no coroutine holds one — the
# dict can't grow unboundedly as credentials rotate (each rotation = a new key).
_locks: "weakref.WeakValueDictionary[str, asyncio.Lock]" = weakref.WeakValueDictionary()


def _lock_for(key: str) -> asyncio.Lock:
    lock = _locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _locks[key] = lock  # caller holds a strong ref via `async with`, so it survives
    return lock


def cache_key(provider: str, *secrets: str) -> str:
    """Build a cache key from provider + a hash of its credential(s).

    Hashing keeps the secret out of the key while still segmenting the cache
    per credential, so rotating a key naturally busts the cache.
    """
    digest = hashlib.sha256("\x00".join(s or "" for s in secrets).encode()).hexdigest()[:16]
    return f"{provider}:{digest}"


async def cached_models(
    key: str,
    fetch_fn: Callable[[], Awaitable[list[str]]],
    fallback: list[str],
    ttl: float = DEFAULT_TTL,
) -> tuple[list[str], bool]:
    """Return ``(models, is_live)``.

    ``is_live`` is True ONLY when this call performed a genuine, successful
    live fetch (fresh, non-empty result from ``fetch_fn``). Cache hits,
    last-good-after-error, and ``fallback`` all return ``is_live=False`` so
    callers never persist inferred tiers from stale data.
    """
    now = time.monotonic()
    cached = _cache.get(key)
    if cached is not None and (now - cached[0]) < ttl:
        return list(cached[1]), False

    # Single-flight: serialize concurrent cold/expired fetches for the same key
    # so we don't fan out to the provider API (and race set_inferred writes).
    async with _lock_for(key):
        # Re-check — another coroutine may have refreshed while we waited.
        now = time.monotonic()
        cached = _cache.get(key)
        if cached is not None and (now - cached[0]) < ttl:
            return list(cached[1]), False

        try:
            models = await fetch_fn()
        except Exception as e:
            logger.warning("Live model listing for %s failed: %s", key, e)
            models = None

        if models:
            _cache[key] = (now, list(models))
            return list(models), True

        # Empty or errored fetch → last-good cache, else hardcoded fallback.
        if cached is not None:
            logger.info("Model listing for %s empty/failed; serving last-good cache", key)
            return list(cached[1]), False
        logger.info("Model listing for %s empty/failed; serving hardcoded fallback", key)
        return list(fallback), False


def invalidate(key: str) -> None:
    """Drop a cached entry (e.g. right after a credential change)."""
    _cache.pop(key, None)


def materialize_inference(provider: str, models: list[str], is_live: bool) -> None:
    """Persist name-inferred tier defaults for a provider — ONLY on a live fetch.

    Called by each provider's list_models() after cached_models(). Skipping when
    ``is_live`` is False is what prevents a transient API failure (which returns
    the stale fallback) from overwriting good inferred tiers in the store.
    """
    if not is_live:
        return
    try:
        from core.providers import model_tiers
        from core.providers.tiers import infer_tier_models

        model_tiers.set_inferred(provider, infer_tier_models(provider, models))
    except Exception as e:  # never let inference break the dropdown
        logger.warning("Tier inference/persist for %s failed: %s", provider, e)
