"""Tests for dynamic model tiers: name inference, sync resolution, and the
model-listing cache's live-vs-fallback signal."""

import asyncio

import pytest

from core.providers import model_listing, model_tiers, tiers


@pytest.fixture
def tier_store(monkeypatch, tmp_path):
    """Point the tier store at a temp file so tests don't touch real data/."""
    monkeypatch.setattr(model_tiers, "TIERS_PATH", tmp_path / "model-tiers.json")
    yield


# ── Inference (pure) ────────────────────────────────────────────────────────────


class TestTierInference:
    def test_anthropic(self):
        out = tiers.infer_tier_models(
            "anthropic", ["claude-opus-4-8", "claude-sonnet-4-6", "claude-haiku-4-5"]
        )
        assert out == {"top": "claude-opus-4-8", "mid": "claude-sonnet-4-6", "light": "claude-haiku-4-5"}

    def test_prefers_highest_version(self):
        out = tiers.infer_tier_models(
            "anthropic",
            ["claude-opus-4-6", "claude-opus-4-8", "claude-sonnet-4-6", "claude-haiku-4-5"],
        )
        assert out["top"] == "claude-opus-4-8"

    def test_openai_suffixes(self):
        out = tiers.infer_tier_models("openai", ["gpt-5.5", "gpt-5.4", "gpt-5.4-mini", "gpt-5.4-nano"])
        assert out == {"top": "gpt-5.5", "mid": "gpt-5.4-mini", "light": "gpt-5.4-nano"}

    def test_google_lite_vs_flash(self):
        out = tiers.infer_tier_models(
            "google", ["gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.5-flash-lite",
                       "gemini-2.0-flash", "gemini-2.0-flash-lite"]
        )
        assert out == {"top": "gemini-2.5-pro", "mid": "gemini-2.5-flash", "light": "gemini-2.5-flash-lite"}

    def test_together_by_param_count(self):
        out = tiers.infer_tier_models(
            "together", ["Qwen/Qwen3.5-32B", "Qwen/Qwen3.5-14B", "Qwen/Qwen3.5-7B"]
        )
        assert out["top"] == "Qwen/Qwen3.5-32B"
        assert out["light"] == "Qwen/Qwen3.5-7B"

    def test_fallback_to_hardcoded_when_empty(self):
        out = tiers.infer_tier_models("anthropic", [])
        assert out["top"] == tiers.TIER_MODELS["anthropic"]["top"]

    def test_triage_classifier_is_light(self):
        assert tiers.infer_triage_classifier("openai", ["gpt-5.5", "gpt-5.4-nano"]) == "gpt-5.4-nano"


# ── Synchronous resolution (override → inferred → hardcoded) ─────────────────────


class TestResolution:
    def test_precedence(self, tier_store):
        # No store yet → hardcoded fallback
        assert tiers.resolve_tier_model("anthropic", "top") == tiers.TIER_MODELS["anthropic"]["top"]

        # Inferred beats hardcoded
        model_tiers.set_inferred("anthropic", {"top": "claude-opus-4-7", "mid": "claude-sonnet-4-6", "light": "claude-haiku-4-5"})
        assert tiers.resolve_tier_model("anthropic", "top") == "claude-opus-4-7"

        # Override beats inferred
        model_tiers.set_overrides("anthropic", {"top": "claude-opus-4-6"})
        assert tiers.resolve_tier_model("anthropic", "top") == "claude-opus-4-6"

        # Clearing the override falls back to inferred
        model_tiers.set_overrides("anthropic", {"top": ""})
        assert tiers.resolve_tier_model("anthropic", "top") == "claude-opus-4-7"

    def test_get_triage_classifier_uses_resolved_light(self, tier_store):
        model_tiers.set_inferred("openai", {"top": "gpt-5.5", "mid": "gpt-5.4-mini", "light": "gpt-5.4-nano"})
        assert tiers.get_triage_classifier("openai") == "gpt-5.4-nano"

    def test_derive_labels_always_nonempty(self, tier_store):
        labels = tiers.derive_tier_labels("anthropic")
        assert all(labels[t] for t in ("top", "mid", "light"))


class TestResolvedDefaultModel:
    """Guards the connect-time default resolver against the recursion bug."""

    def test_unknown_provider_returns_empty_without_recursing(self, tier_store):
        from core.providers.credentials import _resolved_default_model
        # No inferred entry and no hardcoded TIER_MODELS entry → must return ""
        # (PROVIDER_DEFAULTS), NOT recurse into itself.
        assert _resolved_default_model("nonexistent-provider") == ""

    def test_known_provider_falls_back_to_hardcoded_top(self, tier_store):
        from core.providers.credentials import _resolved_default_model
        assert _resolved_default_model("anthropic") == tiers.TIER_MODELS["anthropic"]["top"]


# ── Listing cache: live-vs-fallback signal ──────────────────────────────────────


class TestCachedModels:
    def test_live_then_cached(self):
        calls = {"n": 0}

        async def fetch():
            calls["n"] += 1
            return ["a", "b"]

        async def run():
            m1, live1 = await model_listing.cached_models("k-live", fetch, ["fb"], ttl=100)
            m2, live2 = await model_listing.cached_models("k-live", fetch, ["fb"], ttl=100)
            return m1, live1, m2, live2

        m1, live1, m2, live2 = asyncio.run(run())
        assert (m1, live1) == (["a", "b"], True)
        assert (m2, live2) == (["a", "b"], False)  # served from cache, not a live fetch
        assert calls["n"] == 1

    def test_error_uses_fallback_and_is_not_live(self):
        async def boom():
            raise RuntimeError("network down")

        async def run():
            return await model_listing.cached_models("k-err", boom, ["fb1", "fb2"], ttl=100)

        models, is_live = asyncio.run(run())
        assert models == ["fb1", "fb2"]
        assert is_live is False  # crucial: fallback must NOT trigger tier inference

    def test_empty_result_uses_fallback_and_is_not_live(self):
        async def empty():
            return []

        async def run():
            return await model_listing.cached_models("k-empty", empty, ["fb"], ttl=100)

        models, is_live = asyncio.run(run())
        assert models == ["fb"]
        assert is_live is False
