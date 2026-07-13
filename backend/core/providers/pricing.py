"""Chatty — Model pricing definitions and cost estimation.

Static USD-per-million-token prices for known models. This table is the
runtime source of truth; it is kept current by the `price-check` skill
(see .claude/skills/price-check/) and mirrored to PRICING.md for review.
Do NOT hand-edit speculative numbers — run price-check, which pulls from
official provider pricing pages. Unknown PAID models are flagged by the
usage dashboard (not silently $0); local/free models (Ollama) are $0.

Pricing tiers used: standard / short-context. Note Gemini 2.5 Pro is the
<=200K-prompt tier (long prompts bill higher).
"""

from __future__ import annotations


# model id -> (input_usd_per_mtok, output_usd_per_mtok)
MODEL_PRICING: dict[str, tuple[float, float]] = {
    # Anthropic
    "claude-fable-5":    (10.00, 50.00),
    "claude-opus-4-8":   (5.00, 25.00),
    "claude-opus-4-7":   (5.00, 25.00),
    "claude-opus-4-6":   (5.00, 25.00),
    "claude-sonnet-5":   (3.00, 15.00),  # standard rate; intro pricing $2/$10 runs through 2026-08-31
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-haiku-4-5":  (1.00, 5.00),
    # OpenAI
    "gpt-5.5":           (5.00, 30.00),
    "gpt-5.4":           (2.50, 15.00),
    "gpt-5.4-mini":      (0.75, 4.50),
    "gpt-5.4-nano":      (0.20, 1.25),
    # Google (Gemini 2.5 Pro = standard <=200K-prompt tier).
    # Gemini 2.0 models were shut down 2026-06-01 but are retained here so the
    # usage dashboard can still price historical rows by model id.
    "gemini-2.5-pro":        (1.25, 10.00),
    "gemini-2.5-flash":      (0.30, 2.50),
    "gemini-2.5-flash-lite": (0.10, 0.40),
    "gemini-2.0-flash":      (0.10, 0.40),
    "gemini-2.0-flash-lite": (0.075, 0.30),
}

# model id -> (source_url, verified_date). Maintained by the price-check skill;
# every MODEL_PRICING entry should have a corresponding source here.
PRICING_SOURCES: dict[str, tuple[str, str]] = {
    "claude-fable-5":    ("https://platform.claude.com/docs/en/about-claude/models/overview", "2026-07-13"),
    "claude-opus-4-8":   ("https://platform.claude.com/docs/en/about-claude/models/overview", "2026-07-13"),
    "claude-opus-4-7":   ("https://platform.claude.com/docs/en/about-claude/models/overview", "2026-07-13"),
    "claude-opus-4-6":   ("https://platform.claude.com/docs/en/about-claude/models/overview", "2026-07-13"),
    "claude-sonnet-5":   ("https://platform.claude.com/docs/en/about-claude/models/overview", "2026-07-13"),
    "claude-sonnet-4-6": ("https://platform.claude.com/docs/en/about-claude/models/overview", "2026-07-13"),
    "claude-haiku-4-5":  ("https://platform.claude.com/docs/en/about-claude/models/overview", "2026-07-13"),
    "gpt-5.5":           ("https://developers.openai.com/api/docs/pricing", "2026-07-13"),
    "gpt-5.4":           ("https://developers.openai.com/api/docs/pricing", "2026-07-13"),
    "gpt-5.4-mini":      ("https://developers.openai.com/api/docs/pricing", "2026-07-13"),
    "gpt-5.4-nano":      ("https://developers.openai.com/api/docs/pricing", "2026-07-13"),
    "gemini-2.5-pro":        ("https://ai.google.dev/gemini-api/docs/pricing", "2026-07-13"),
    "gemini-2.5-flash":      ("https://ai.google.dev/gemini-api/docs/pricing", "2026-07-13"),
    "gemini-2.5-flash-lite": ("https://ai.google.dev/gemini-api/docs/pricing", "2026-07-13"),
    "gemini-2.0-flash":      ("https://ai.google.dev/gemini-api/docs/pricing", "2026-07-13"),
    "gemini-2.0-flash-lite": ("https://ai.google.dev/gemini-api/docs/pricing", "2026-07-13"),
}


# Audio transcription pricing, USD per audio MINUTE (transcription APIs bill
# by duration, not tokens). OpenAI publishes per-minute "estimated cost"
# figures directly. The Gemini rate is derived from documented primitives:
# audio input $1.00/Mtok (pricing page) × 32 tokens per second of audio
# (audio-understanding docs) × 60 s; the transcript's output tokens are
# added separately via MODEL_PRICING (see estimate_transcription_cost).
TRANSCRIPTION_PRICING: dict[str, float] = {
    "gpt-4o-transcribe":      0.006,
    "gpt-4o-mini-transcribe": 0.003,
    "gemini-2.5-flash":       0.00192,
}

TRANSCRIPTION_PRICING_SOURCES: dict[str, tuple[str, str]] = {
    "gpt-4o-transcribe":      ("https://developers.openai.com/api/docs/pricing", "2026-07-13"),
    "gpt-4o-mini-transcribe": ("https://developers.openai.com/api/docs/pricing", "2026-07-13"),
    "gemini-2.5-flash":       ("https://ai.google.dev/gemini-api/docs/pricing", "2026-07-13"),
}


def estimate_transcription_cost(model: str, audio_seconds: int, output_tokens: int = 0) -> float:
    """Estimated USD cost of one transcription. 0.0 when pricing is unknown.

    Duration is billed per minute from TRANSCRIPTION_PRICING; output tokens
    (the transcript text, relevant for Gemini) are added from MODEL_PRICING.
    """
    per_minute = TRANSCRIPTION_PRICING.get(model)
    if per_minute is None:
        return 0.0
    cost = (audio_seconds / 60.0) * per_minute
    if output_tokens:
        pricing = get_model_pricing(model)
        if pricing is not None:
            cost += output_tokens * pricing[1] / 1_000_000
    return cost


def is_transcription_priced(model: str) -> bool:
    """True if we have a published per-minute price for this transcription model."""
    return model in TRANSCRIPTION_PRICING


def get_model_pricing(model: str) -> tuple[float, float] | None:
    """Resolve pricing for a model id.

    Exact match first, then longest-prefix match so dated snapshots
    (e.g. claude-haiku-4-5-20251001) resolve to their base model.
    Returns None for unknown models.
    """
    if not model:
        return None
    exact = MODEL_PRICING.get(model)
    if exact is not None:
        return exact
    best_key = None
    for key in MODEL_PRICING:
        if model.startswith(key) and (best_key is None or len(key) > len(best_key)):
            best_key = key
    return MODEL_PRICING[best_key] if best_key else None


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Estimated USD cost for a single call. 0.0 when pricing is unknown."""
    pricing = get_model_pricing(model)
    if pricing is None:
        return 0.0
    in_price, out_price = pricing
    return (input_tokens * in_price + output_tokens * out_price) / 1_000_000


def is_priced(model: str) -> bool:
    """True if we have a published price for this model.

    Used by the usage dashboard to flag "pricing unknown" PAID models
    instead of silently reporting $0.00. Note: a False result for a
    local/free model (Ollama) is expected and handled by the caller,
    which keys off the row's provider rather than the model name.
    """
    return get_model_pricing(model) is not None
