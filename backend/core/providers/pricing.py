"""Chatty — Model pricing definitions and cost estimation.

Static USD-per-million-token prices for known models. This table is the
runtime source of truth; it is kept current by the `price-check` skill
(see .claude/skills/price-check/) and mirrored to PRICING.md for review.
Do NOT hand-edit speculative numbers — run price-check, which pulls from
official provider pricing pages. Unknown PAID models are flagged by the
usage dashboard (not silently $0); local/free models (Ollama) are $0.

Pricing tiers used: standard / short-context. Models that bill long prompts at a
higher rate (Haiku 5.5 over 100K, gpt-5.5/5.4 over 272K, Gemini 2.5 Pro over
200K) carry that tier in MODEL_PRICING_LONG.
"""

from __future__ import annotations

import re


# model id -> (input_usd_per_mtok, output_usd_per_mtok)
MODEL_PRICING: dict[str, tuple[float, float]] = {
    # Anthropic. Claude 4.6+ models (except Haiku 5.5) bill the full 1M context at
    # these rates; Haiku 5.5's >100K-prompt tier is in MODEL_PRICING_LONG.
    "claude-fable-5-1":  (10.00, 50.00),
    "claude-fable-5":    (10.00, 50.00),
    "claude-opus-5-5":   (4.00, 20.00),
    "claude-opus-4-8":   (5.00, 25.00),
    "claude-opus-4-7":   (5.00, 25.00),
    "claude-opus-4-6":   (5.00, 25.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-sonnet-5":   (2.00, 10.00),  # the launch intro price became the standard price (the 2026-09-01 rise to $3/$15 was cancelled)
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-haiku-5-5":  (0.10, 0.50),   # prompts up to 100K tokens; over that see MODEL_PRICING_LONG
    "claude-haiku-4-5":  (1.00, 5.00),
    # OpenAI (short-context tier, <=272K input tokens where tiered).
    "gpt-5.6-sol":       (5.00, 30.00),  # list rate; promotional $4/$20 applies through at least 2026-11-21 (estimates err high until then)
    "gpt-5.6-terra":     (2.00, 12.00),
    "gpt-5.6-luna":      (0.20, 1.20),
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
    # Together AI (serverless/on-demand tier). Only the curated TOGETHER_MODELS
    # set is priced; other Together models a user selects show "pricing unknown".
    # Kimi-K2.6 and gpt-oss-20b were absent from the serverless table on 2026-10-17
    # (fine-tuning only); their last verified rates are kept for historical rows.
    "moonshotai/Kimi-K2.6":                      (1.20, 4.50),
    "zai-org/GLM-5.2":                           (1.40, 4.40),
    "deepseek-ai/DeepSeek-V4-Pro":               (1.74, 3.48),
    "MiniMaxAI/MiniMax-M3":                      (0.30, 1.20),
    "meta-llama/Llama-3.3-70B-Instruct-Turbo":   (1.04, 1.04),
    "google/gemma-4-31B-it":                     (0.39, 0.97),
    "openai/gpt-oss-120b":                       (0.15, 0.60),
    "openai/gpt-oss-20b":                        (0.05, 0.20),
    "Qwen/Qwen3.5-9B":                           (0.17, 0.25),
}

# model id -> (input, output, from_prompt_tokens): the higher rate a model bills
# once a request's prompt exceeds from_prompt_tokens. Only models that publish such
# a tier appear here. Maintained by price-check like MODEL_PRICING; read by
# get_max_rates() (the computer helper reserves budget at the highest rate a call
# could bill at) and rates_for_prompt() (actual cost of a known prompt size).
MODEL_PRICING_LONG: dict[str, tuple[float, float, int]] = {
    "claude-haiku-5-5": (0.50, 2.50, 100_000),   # prompt length counts cache reads and writes
    "gpt-5.5":          (10.00, 45.00, 272_000),
    "gpt-5.4":          (5.00, 22.50, 272_000),
    "gemini-2.5-pro":   (2.50, 15.00, 200_000),
}

# model id -> (source_url, verified_date). Maintained by the price-check skill;
# every MODEL_PRICING entry should have a corresponding source here.
_ANTHROPIC = "https://platform.claude.com/docs/en/about-claude/pricing"
PRICING_SOURCES: dict[str, tuple[str, str]] = {
    "claude-fable-5-1":  (_ANTHROPIC, "2026-10-17"),
    "claude-fable-5":    (_ANTHROPIC, "2026-10-17"),
    "claude-opus-5-5":   (_ANTHROPIC, "2026-10-17"),
    "claude-opus-4-8":   (_ANTHROPIC, "2026-10-17"),
    "claude-opus-4-7":   (_ANTHROPIC, "2026-10-17"),
    "claude-opus-4-6":   (_ANTHROPIC, "2026-10-17"),
    "claude-sonnet-5-5": (_ANTHROPIC, "2026-10-17"),
    "claude-sonnet-5":   (_ANTHROPIC, "2026-10-17"),
    "claude-sonnet-4-6": (_ANTHROPIC, "2026-10-17"),
    "claude-haiku-5-5":  (_ANTHROPIC, "2026-10-17"),
    "claude-haiku-4-5":  (_ANTHROPIC, "2026-10-17"),
    "gpt-5.6-sol":       ("https://developers.openai.com/api/docs/pricing", "2026-10-17"),
    "gpt-5.6-terra":     ("https://developers.openai.com/api/docs/pricing", "2026-10-17"),
    "gpt-5.6-luna":      ("https://developers.openai.com/api/docs/pricing", "2026-10-17"),
    "gpt-5.5":           ("https://developers.openai.com/api/docs/pricing", "2026-10-17"),
    "gpt-5.4":           ("https://developers.openai.com/api/docs/pricing", "2026-10-17"),
    "gpt-5.4-mini":      ("https://developers.openai.com/api/docs/pricing", "2026-10-17"),
    "gpt-5.4-nano":      ("https://developers.openai.com/api/docs/pricing", "2026-10-17"),
    "gemini-2.5-pro":        ("https://ai.google.dev/gemini-api/docs/pricing", "2026-10-17"),
    "gemini-2.5-flash":      ("https://ai.google.dev/gemini-api/docs/pricing", "2026-10-17"),
    "gemini-2.5-flash-lite": ("https://ai.google.dev/gemini-api/docs/pricing", "2026-10-17"),
    # Gemini 2.0 is no longer on the pricing page; the last verified rates stand.
    "gemini-2.0-flash":      ("https://ai.google.dev/gemini-api/docs/pricing", "2026-07-19"),
    "gemini-2.0-flash-lite": ("https://ai.google.dev/gemini-api/docs/pricing", "2026-07-19"),
    "moonshotai/Kimi-K2.6":                    ("https://www.together.ai/pricing", "2026-07-31"),
    "zai-org/GLM-5.2":                         ("https://www.together.ai/pricing", "2026-10-17"),
    # The page now lists "DeepSeek V4 Pro 0813" at $1.32/$3.96; not confirmed to be this id, so the
    # last verified rate for the serverless id is kept.
    "deepseek-ai/DeepSeek-V4-Pro":             ("https://www.together.ai/pricing", "2026-07-31"),
    "MiniMaxAI/MiniMax-M3":                    ("https://www.together.ai/pricing", "2026-10-17"),
    "meta-llama/Llama-3.3-70B-Instruct-Turbo": ("https://www.together.ai/pricing", "2026-10-17"),
    "google/gemma-4-31B-it":                   ("https://www.together.ai/pricing", "2026-10-17"),
    "openai/gpt-oss-120b":                     ("https://www.together.ai/pricing", "2026-10-17"),
    "openai/gpt-oss-20b":                      ("https://www.together.ai/pricing", "2026-07-31"),
    "Qwen/Qwen3.5-9B":                         ("https://www.together.ai/pricing", "2026-10-17"),
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
    "gpt-4o-transcribe":      ("https://developers.openai.com/api/docs/pricing", "2026-10-17"),
    "gpt-4o-mini-transcribe": ("https://developers.openai.com/api/docs/pricing", "2026-10-17"),
    "gemini-2.5-flash":       ("https://ai.google.dev/gemini-api/docs/pricing", "2026-10-17"),
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


# A snapshot suffix: "-YYYYMMDD" (claude-haiku-4-5-20251001) or "@…" (Vertex/Bedrock
# style ids). Only these fall back to their base model's price; any other longer id is a
# different model and stays unpriced until price-check adds it (claude-sonnet-5-5 used to
# resolve to claude-sonnet-5 this way).
_SNAPSHOT_SUFFIX = re.compile(r"^(?:-\d{8}|@.+)$")


def get_model_pricing(model: str) -> tuple[float, float] | None:
    """Resolve pricing for a model id: exact match, else the base model of a dated snapshot.
    Returns None for unknown models."""
    key = _resolve_key(model)
    return MODEL_PRICING[key] if key else None


def _resolve_key(model: str) -> str | None:
    if not model:
        return None
    if model in MODEL_PRICING:
        return model
    best_key = None
    for key in MODEL_PRICING:
        if model.startswith(key) and _SNAPSHOT_SUFFIX.match(model[len(key):]) and (best_key is None or len(key) > len(best_key)):
            best_key = key
    return best_key


def get_max_rates(model: str) -> tuple[float, float] | None:
    """The highest listed (input, output) rates for a model — the long-context tier when it has
    one — for conservative cost reservations. None when unpriced."""
    key = _resolve_key(model)
    if not key:
        return None
    std = MODEL_PRICING[key]
    long = MODEL_PRICING_LONG.get(key)
    return (max(std[0], long[0]), max(std[1], long[1])) if long else std


def rates_for_prompt(model: str, prompt_tokens: int) -> tuple[float, float] | None:
    """The (input, output) rates a request with `prompt_tokens` of input (cache reads and writes
    included) bills at: the long-context tier past its threshold, else the standard rate."""
    key = _resolve_key(model)
    if not key:
        return None
    long = MODEL_PRICING_LONG.get(key)
    if long and prompt_tokens > long[2]:
        return long[0], long[1]
    return MODEL_PRICING[key]


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
