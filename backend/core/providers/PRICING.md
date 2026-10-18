# Model Pricing

Last verified: 2026-10-17 (price-check)

USD per 1M tokens, standard / short-context tier. Generated from `pricing.py`
(`MODEL_PRICING` + `MODEL_PRICING_LONG` + `PRICING_SOURCES`) by the `price-check` skill — do not
hand-edit; run `price-check` to refresh. Local models (Ollama) are free; paid models without an
entry here are flagged "pricing unknown" by the usage dashboard, never silently $0.

Only an **exact** id, or a dated snapshot of one (`-YYYYMMDD` / `@…`), resolves to a price. A
longer id (`claude-sonnet-5-5` against a `claude-sonnet-5` entry) is a different model and stays
unknown until it is listed here. The computer helper only accepts exactly listed models.

## Anthropic

| Model | Input $/M | Output $/M | Source | Verified |
|---|---|---|---|---|
| `claude-fable-5-1` | 10.00 | 50.00 | [pricing](https://platform.claude.com/docs/en/about-claude/pricing) | 2026-10-17 |
| `claude-fable-5` | 10.00 | 50.00 | [pricing](https://platform.claude.com/docs/en/about-claude/pricing) | 2026-10-17 |
| `claude-opus-5-5` | 4.00 | 20.00 | [pricing](https://platform.claude.com/docs/en/about-claude/pricing) | 2026-10-17 |
| `claude-opus-4-8` | 5.00 | 25.00 | [pricing](https://platform.claude.com/docs/en/about-claude/pricing) | 2026-10-17 |
| `claude-opus-4-7` | 5.00 | 25.00 | [pricing](https://platform.claude.com/docs/en/about-claude/pricing) | 2026-10-17 |
| `claude-opus-4-6` | 5.00 | 25.00 | [pricing](https://platform.claude.com/docs/en/about-claude/pricing) | 2026-10-17 |
| `claude-sonnet-5-5` | 2.00 | 10.00 | [pricing](https://platform.claude.com/docs/en/about-claude/pricing) | 2026-10-17 |
| `claude-sonnet-5` | 2.00 | 10.00 | [pricing](https://platform.claude.com/docs/en/about-claude/pricing) | 2026-10-17 |
| `claude-sonnet-4-6` | 3.00 | 15.00 | [pricing](https://platform.claude.com/docs/en/about-claude/pricing) | 2026-10-17 |
| `claude-haiku-5-5` | 0.10 | 0.50 | [pricing](https://platform.claude.com/docs/en/about-claude/pricing) | 2026-10-17 |
| `claude-haiku-4-5` | 1.00 | 5.00 | [pricing](https://platform.claude.com/docs/en/about-claude/pricing) | 2026-10-17 |

> Claude 4.6 and later models (except Haiku 5.5) bill the full 1M-token context window at these rates.
> `claude-sonnet-5`: the $2/$10 launch price became the standard price; the increase to $3/$15 scheduled for 2026-09-01 did not happen (was listed here at 3.00/15.00 until this pass).
> `claude-haiku-5-5` is priced by prompt length: up to 100K prompt tokens at the rate above, over 100K at the long-context rate below. Cache reads are 0.05× the input rate on Opus 5.5 and Sonnet 5.5 (0.025× on Fable 5.1), 0.1× elsewhere; the usage dashboard prices raw input/output tokens only.

## OpenAI

| Model | Input $/M | Output $/M | Source | Verified |
|---|---|---|---|---|
| `gpt-5.6-sol` | 5.00 | 30.00 | [pricing](https://developers.openai.com/api/docs/pricing) | 2026-10-17 |
| `gpt-5.6-terra` | 2.00 | 12.00 | [pricing](https://developers.openai.com/api/docs/pricing) | 2026-10-17 |
| `gpt-5.6-luna` | 0.20 | 1.20 | [pricing](https://developers.openai.com/api/docs/pricing) | 2026-10-17 |
| `gpt-5.5` | 5.00 | 30.00 | [pricing](https://developers.openai.com/api/docs/pricing) | 2026-10-17 |
| `gpt-5.4` | 2.50 | 15.00 | [pricing](https://developers.openai.com/api/docs/pricing) | 2026-10-17 |
| `gpt-5.4-mini` | 0.75 | 4.50 | [pricing](https://developers.openai.com/api/docs/pricing) | 2026-10-17 |
| `gpt-5.4-nano` | 0.20 | 1.25 | [pricing](https://developers.openai.com/api/docs/pricing) | 2026-10-17 |

> `gpt-5.6-sol` is billed at a promotional $4/$20 through at least 2026-11-21; the list rate is kept here so estimates err high rather than low. `gpt-5.6-terra` (was 2.50/15.00) and `gpt-5.6-luna` (was 1.00/6.00) dropped on the official page in this pass.
> `gpt-5.5` and `gpt-5.4` are the ≤272K-input-token tier; longer inputs bill the long-context rate below.

## Google

| Model | Input $/M | Output $/M | Source | Verified |
|---|---|---|---|---|
| `gemini-2.5-pro` | 1.25 | 10.00 | [pricing](https://ai.google.dev/gemini-api/docs/pricing) | 2026-10-17 |
| `gemini-2.5-flash` | 0.30 | 2.50 | [pricing](https://ai.google.dev/gemini-api/docs/pricing) | 2026-10-17 |
| `gemini-2.5-flash-lite` | 0.10 | 0.40 | [pricing](https://ai.google.dev/gemini-api/docs/pricing) | 2026-10-17 |
| `gemini-2.0-flash` | 0.10 | 0.40 | [pricing](https://ai.google.dev/gemini-api/docs/pricing) | 2026-07-19 |
| `gemini-2.0-flash-lite` | 0.075 | 0.30 | [pricing](https://ai.google.dev/gemini-api/docs/pricing) | 2026-07-19 |

> `gemini-2.5-pro` is the standard ≤200K-prompt tier; longer prompts bill the long-context rate below.
> `gemini-2.0-*` models were shut down 2026-06-01 and are no longer on the pricing page; they are retained to price historical usage rows.

## Together AI

| Model | Input $/M | Output $/M | Source | Verified |
|---|---|---|---|---|
| `moonshotai/Kimi-K2.6` | 1.20 | 4.50 | [pricing](https://www.together.ai/pricing) | 2026-07-31 |
| `zai-org/GLM-5.2` | 1.40 | 4.40 | [pricing](https://www.together.ai/pricing) | 2026-10-17 |
| `deepseek-ai/DeepSeek-V4-Pro` | 1.74 | 3.48 | [pricing](https://www.together.ai/pricing) | 2026-07-31 |
| `MiniMaxAI/MiniMax-M3` | 0.30 | 1.20 | [pricing](https://www.together.ai/pricing) | 2026-10-17 |
| `meta-llama/Llama-3.3-70B-Instruct-Turbo` | 1.04 | 1.04 | [pricing](https://www.together.ai/pricing) | 2026-10-17 |
| `google/gemma-4-31B-it` | 0.39 | 0.97 | [pricing](https://www.together.ai/pricing) | 2026-10-17 |
| `openai/gpt-oss-120b` | 0.15 | 0.60 | [pricing](https://www.together.ai/pricing) | 2026-10-17 |
| `openai/gpt-oss-20b` | 0.05 | 0.20 | [pricing](https://www.together.ai/pricing) | 2026-07-31 |
| `Qwen/Qwen3.5-9B` | 0.17 | 0.25 | [pricing](https://www.together.ai/pricing) | 2026-10-17 |

> Only the curated model set above (`TOGETHER_MODELS` in `together_provider.py`) is priced. Together's live catalog is much larger; any other model a user selects flags "pricing unknown" in the usage dashboard (never $0).
> Not re-verifiable on 2026-10-17: `moonshotai/Kimi-K2.6` and `openai/gpt-oss-20b` appear only in Together's fine-tuning table now, and the serverless table lists "DeepSeek V4 Pro 0813" at $1.32/$3.96, which was not confirmed to be the `deepseek-ai/DeepSeek-V4-Pro` id; their last verified rates stand.
>
> Every curated model is documented by Together as supporting function calling. `Qwen/Qwen3.7-Max` and `Qwen/Qwen3.7-Plus` were dropped from the set on 2026-07-31: capable chat models, but no tool calling, so Chatty cannot use them at all.

## Long-context tiers

From `MODEL_PRICING_LONG`: the rate a request bills once its prompt (cache reads and writes
included) exceeds the threshold. The computer helper reserves budget at these rates for every call
(`get_max_rates`); `rates_for_prompt` prices a known prompt size.

| Model | Over (prompt tokens) | Input $/M | Output $/M | Verified |
|---|---|---|---|---|
| `claude-haiku-5-5` | 100K | 0.50 | 2.50 | 2026-10-17 |
| `gpt-5.5` | 272K | 10.00 | 45.00 | 2026-10-17 |
| `gpt-5.4` | 272K | 5.00 | 22.50 | 2026-10-17 |
| `gemini-2.5-pro` | 200K | 2.50 | 15.00 | 2026-10-17 |

## Audio transcription (per audio minute)

USD per minute of recording, from `TRANSCRIPTION_PRICING` (meeting-recording
transcription bills by duration, not tokens).

| Model | $/minute | Notes | Source | Verified |
|---|---|---|---|---|
| `gpt-4o-transcribe` | 0.006 | OpenAI's published per-minute estimate (all-inclusive) | [pricing](https://developers.openai.com/api/docs/pricing) | 2026-10-17 |
| `gpt-4o-mini-transcribe` | 0.003 | OpenAI's published per-minute estimate (all-inclusive) | [pricing](https://developers.openai.com/api/docs/pricing) | 2026-10-17 |
| `gemini-2.5-flash` | 0.00192 | Derived: $1.00/Mtok audio input × 32 tok/s × 60 s; transcript output tokens billed additionally at the model's output rate | [pricing](https://ai.google.dev/gemini-api/docs/pricing), [audio docs](https://ai.google.dev/gemini-api/docs/audio) | 2026-10-17 |

## Not yet priced

- **Newer models seen on the official pages but outside Chatty's model set** (`claude-opus-5`, `gpt-5.5-pro`, `gpt-5.4-pro`, `gpt-5.2`, `gpt-5.1`, `gemini-4-argon`, `gemini-3.x`) — added when they enter a provider's `*_MODELS` list or a user's live model list.
- **Legacy OpenAI** (`o3`, `o4-mini`, `gpt-4o`, `gpt-4o-mini`) — removed from OpenAI's current pricing page; historical usage rows referencing them flag as unknown.
- **`whisper-1`** — no longer on OpenAI's pricing page; Chatty transcribes with `gpt-4o-transcribe` instead.
