"""Chatty — Model pricing definitions and cost estimation.

Static USD-per-million-token prices for known models. Hardcoded,
updated occasionally when providers change published prices.
Unknown models (including local/Ollama) estimate to $0.00.
"""

from __future__ import annotations


# model id -> (input_usd_per_mtok, output_usd_per_mtok)
MODEL_PRICING: dict[str, tuple[float, float]] = {
    "claude-opus-4-6":   (5.00, 25.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-haiku-4-5":  (1.00, 5.00),
}


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
