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

    def test_error_falls_back_to_last_good_cache(self):
        async def good():
            return ["live-x"]

        async def boom():
            raise RuntimeError("provider down")

        async def run():
            m1, l1 = await model_listing.cached_models("k-stale", good, ["fb"], ttl=100)
            # Expire the entry, then fail the next fetch.
            ts, models = model_listing._cache["k-stale"]
            model_listing._cache["k-stale"] = (ts - 10_000, models)
            m2, l2 = await model_listing.cached_models("k-stale", boom, ["fb"], ttl=100)
            return m1, l1, m2, l2

        m1, l1, m2, l2 = asyncio.run(run())
        assert (m1, l1) == (["live-x"], True)
        # On error with a prior cache, serve last-good — NOT the hardcoded fallback.
        assert m2 == ["live-x"]
        assert l2 is False


class TestModelFilters:
    @pytest.mark.parametrize("model_id,expected", [
        ("gpt-5.5", True), ("gpt-5.4-nano", True), ("o3", True), ("o4-mini", True),
        ("chatgpt-4o", True),
        ("text-embedding-3-large", False), ("whisper-1", False),
        ("gpt-4o-realtime-preview", False), ("dall-e-3", False), ("tts-1", False),
        ("gpt-3.5-turbo-instruct", False), ("gpt-image-1", False),
        ("gpt-4o-search-preview", False),
    ])
    def test_openai_chat_filter(self, model_id, expected):
        from core.providers.openai_provider import _is_openai_chat_model
        assert _is_openai_chat_model(model_id) is expected

    def test_together_filter_by_type(self):
        from core.providers.together_provider import _is_together_chat

        class M:
            def __init__(self, id, type=None):
                self.id = id
                self.type = type

        assert _is_together_chat(M("x", "chat")) is True
        assert _is_together_chat(M("x", "language")) is True
        assert _is_together_chat(M("x", "embedding")) is False

    def test_together_filter_name_fallback(self):
        from core.providers.together_provider import _is_together_chat

        class M:
            def __init__(self, id):
                self.id = id
                self.type = None

        assert _is_together_chat(M("Qwen/Qwen3.5-32B")) is True
        assert _is_together_chat(M("BAAI/bge-large-embedding")) is False
        assert _is_together_chat(M("black-forest-labs/flux")) is False


class TestInferenceEdges:
    def test_unknown_provider_returns_empty(self):
        assert tiers.infer_tier_models("ollama", ["llama3.2"]) == {"top": "", "mid": "", "light": ""}

    def test_together_two_models_mid_not_equal_light(self):
        out = tiers.infer_tier_models("together", ["Qwen/Qwen3.5-32B", "Qwen/Qwen3.5-7B"])
        assert out["top"] == "Qwen/Qwen3.5-32B"
        assert out["light"] == "Qwen/Qwen3.5-7B"
        assert out["mid"] != out["light"]

    def test_inferred_tiers_coerced_to_available(self):
        # OpenAI live list missing -mini/-nano: those tiers must NOT resolve to
        # the hardcoded (unavailable) models — they collapse to an available one.
        out = tiers.infer_tier_models("openai", ["gpt-5.5"])
        assert set(out.values()) == {"gpt-5.5"}

    def test_together_ignores_unsized_model_for_light(self):
        # DeepSeek-V3 is unsized → must not be chosen as the cheap 'light' tier.
        out = tiers.infer_tier_models(
            "together",
            ["Qwen/Qwen3.5-32B", "Qwen/Qwen3.5-7B", "deepseek-ai/DeepSeek-V3-0324"],
        )
        assert out["top"] == "Qwen/Qwen3.5-32B"
        assert out["light"] == "Qwen/Qwen3.5-7B"


class TestLabelsAndTriageFallback:
    def test_derive_labels_strips_together_org(self, tier_store):
        model_tiers.set_inferred("together", {
            "top": "Qwen/Qwen3.5-32B", "mid": "Qwen/Qwen3.5-14B", "light": "Qwen/Qwen3.5-7B",
        })
        assert tiers.derive_tier_labels("together")["top"] == "Qwen3.5-32B"

    def test_triage_falls_back_to_hardcoded(self, tier_store):
        # Empty store → resolved 'light' is the hardcoded tier, matching TRIAGE_CLASSIFIERS.
        assert tiers.get_triage_classifier("anthropic") == tiers.TRIAGE_CLASSIFIERS["anthropic"]

    def test_triage_unknown_provider_is_none(self, tier_store):
        assert tiers.get_triage_classifier("nonexistent") is None


class TestMaterializeDoesNotOverrideActiveModel:
    def test_active_model_preserved(self, monkeypatch, tmp_path, tier_store):
        import asyncio
        import core.providers as providers_pkg
        import core.providers.credentials as creds

        monkeypatch.setattr(creds, "PROFILES_PATH", tmp_path / "auth-profiles.json")
        store = creds.CredentialStore()
        store.data = {
            "active_provider": "google",
            "active_model": "gemini-2.5-flash",
            "profiles": {"google:default": {"type": "api_key", "key": "x"}},
        }
        store._save()

        class FakeProvider:
            async def list_models(self):
                return ["gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.5-flash-lite"]

        monkeypatch.setattr(providers_pkg, "get_ai_provider", lambda **kw: FakeProvider())

        from core.providers.router import _materialize_inferred_tiers
        returned = asyncio.run(_materialize_inferred_tiers("google", "gemini-2.5-flash"))

        # The inferred top is gemini-2.5-pro, but active_model must NOT be flipped.
        assert returned == "gemini-2.5-flash"
        assert creds.CredentialStore().data["active_model"] == "gemini-2.5-flash"
