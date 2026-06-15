"""Tests for context-window resolution and the context-usage SSE payload."""

from core.providers.windows import get_context_window, context_usage_event
from core.providers.anthropic_provider import AnthropicProvider


class TestGetContextWindow:
    def test_exact_match(self):
        assert get_context_window("claude-opus-4-6") == 200_000

    def test_longest_prefix_match_for_dated_snapshot(self):
        # claude-haiku-4-5-20251001 resolves to the claude-haiku-4-5 base.
        assert get_context_window("claude-haiku-4-5-20251001") == 200_000

    def test_unknown_model_returns_none(self):
        assert get_context_window("gpt-4o") is None

    def test_empty_model_returns_none(self):
        assert get_context_window("") is None


class TestContextUsageEvent:
    def test_cache_inclusive_total(self):
        ev = context_usage_event(
            {"input_tokens": 300, "output_tokens": 50,
             "cache_creation_input_tokens": 1_000,
             "cache_read_input_tokens": 48_700},
            200_000,
        )
        assert ev["type"] == "usage"
        assert ev["input_tokens"] == 300            # raw stays raw
        assert ev["output_tokens"] == 50
        assert ev["context_tokens"] == 50_000       # 300 + 1000 + 48700
        assert ev["context_window"] == 200_000

    def test_no_cache_fields_falls_back_to_input(self):
        ev = context_usage_event({"input_tokens": 10, "output_tokens": 5}, 200_000)
        assert ev["context_tokens"] == 10

    def test_none_when_usage_empty(self):
        assert context_usage_event({}, 200_000) is None

    def test_none_when_window_unknown(self):
        assert context_usage_event({"input_tokens": 10}, None) is None

    def test_coerces_explicit_none_fields(self):
        # A provider that supplies an explicit None must not raise.
        ev = context_usage_event(
            {"input_tokens": 10, "output_tokens": None,
             "cache_creation_input_tokens": None, "cache_read_input_tokens": 5},
            200_000,
        )
        assert ev["context_tokens"] == 15          # 10 + 0 + 5
        assert ev["output_tokens"] == 0


class TestAnthropicContextWindow:
    def test_known_model(self):
        prov = AnthropicProvider(api_key="x", model="claude-sonnet-4-6")
        assert prov.context_window == 200_000

    def test_dated_snapshot_resolves_via_prefix(self):
        prov = AnthropicProvider(api_key="x", model="claude-haiku-4-5-20251001")
        assert prov.context_window == 200_000

    def test_unknown_claude_model_uses_family_floor(self):
        prov = AnthropicProvider(api_key="x", model="claude-opus-9-9")
        assert prov.context_window == 200_000

    def test_non_claude_model_returns_none(self):
        prov = AnthropicProvider(api_key="x", model="some-other-model")
        assert prov.context_window is None
