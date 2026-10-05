# Model pricing

Moved verbatim from the root `AGENTS.md`.

## Model Pricing

The model selector is **dynamic** — each provider's `list_models()` fetches live from the provider's API (Anthropic/OpenAI/Google/Together/Ollama), cached with a fallback to the hardcoded `*_MODELS` constants. New models appear automatically; no code change needed to add one to the dropdown.

**Tiers** (top/mid/light) are inferred from model naming and persisted to `data/model-tiers.json`; the user can override them in Provider Setup. `resolve_tier_model()` stays synchronous (override → inferred → hardcoded).

**Pricing is the one thing no provider API exposes**, so it is maintained manually in `backend/core/providers/pricing.py` (`MODEL_PRICING` + `PRICING_SOURCES`), mirrored to `backend/core/providers/PRICING.md`. The usage dashboard flags paid models with no price entry as "pricing unknown" (it never silently reports $0 for a paid model; only local Ollama is free).

**Every PR that adds/changes models or touches `core/providers/` or `core/agents/usage/` MUST run the `price-check` skill first** (`.claude/skills/price-check/SKILL.md` — a Claude Code skill; any other agent follows the steps in that file by hand) and include any resulting `pricing.py` / `PRICING.md` changes in the same PR. The skill pulls current rates from official pricing pages, never fabricates a rate, and skips re-fetching if pricing was already verified in the chat.
