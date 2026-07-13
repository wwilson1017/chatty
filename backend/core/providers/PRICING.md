# Model Pricing

Last verified: 2026-07-13 (price-check)

USD per 1M tokens, standard / short-context tier. Generated from `pricing.py`
(`MODEL_PRICING` + `PRICING_SOURCES`) by the `price-check` skill — do not hand-edit;
run `price-check` to refresh. Local models (Ollama) are free; paid models without an
entry here are flagged "pricing unknown" by the usage dashboard, never silently $0.

## Anthropic

| Model | Input $/M | Output $/M | Source | Verified |
|---|---|---|---|---|
| `claude-fable-5` | 10.00 | 50.00 | [overview](https://platform.claude.com/docs/en/about-claude/models/overview) | 2026-07-13 |
| `claude-opus-4-8` | 5.00 | 25.00 | [overview](https://platform.claude.com/docs/en/about-claude/models/overview) | 2026-07-13 |
| `claude-opus-4-7` | 5.00 | 25.00 | [overview](https://platform.claude.com/docs/en/about-claude/models/overview) | 2026-07-13 |
| `claude-opus-4-6` | 5.00 | 25.00 | [overview](https://platform.claude.com/docs/en/about-claude/models/overview) | 2026-07-13 |
| `claude-sonnet-5` | 3.00 | 15.00 | [overview](https://platform.claude.com/docs/en/about-claude/models/overview) | 2026-07-13 |
| `claude-sonnet-4-6` | 3.00 | 15.00 | [overview](https://platform.claude.com/docs/en/about-claude/models/overview) | 2026-07-13 |
| `claude-haiku-4-5` | 1.00 | 5.00 | [overview](https://platform.claude.com/docs/en/about-claude/models/overview) | 2026-07-13 |

> `claude-sonnet-5` is listed at its standard rate; introductory pricing of $2/$10 per MTok applies through 2026-08-31 (dashboard estimates slightly high until then).

## OpenAI

| Model | Input $/M | Output $/M | Source | Verified |
|---|---|---|---|---|
| `gpt-5.5` | 5.00 | 30.00 | [pricing](https://developers.openai.com/api/docs/pricing) | 2026-07-13 |
| `gpt-5.4` | 2.50 | 15.00 | [pricing](https://developers.openai.com/api/docs/pricing) | 2026-07-13 |
| `gpt-5.4-mini` | 0.75 | 4.50 | [pricing](https://developers.openai.com/api/docs/pricing) | 2026-07-13 |
| `gpt-5.4-nano` | 0.20 | 1.25 | [pricing](https://developers.openai.com/api/docs/pricing) | 2026-07-13 |

## Google

| Model | Input $/M | Output $/M | Source | Verified |
|---|---|---|---|---|
| `gemini-2.5-pro` | 1.25 | 10.00 | [pricing](https://ai.google.dev/gemini-api/docs/pricing) | 2026-07-13 |
| `gemini-2.5-flash` | 0.30 | 2.50 | [pricing](https://ai.google.dev/gemini-api/docs/pricing) | 2026-07-13 |
| `gemini-2.5-flash-lite` | 0.10 | 0.40 | [pricing](https://ai.google.dev/gemini-api/docs/pricing) | 2026-07-13 |
| `gemini-2.0-flash` | 0.10 | 0.40 | [pricing](https://ai.google.dev/gemini-api/docs/pricing) | 2026-07-13 |
| `gemini-2.0-flash-lite` | 0.075 | 0.30 | [pricing](https://ai.google.dev/gemini-api/docs/pricing) | 2026-07-13 |

> `gemini-2.5-pro` is the standard ≤200K-prompt tier; long prompts bill higher.
> `gemini-2.0-*` models were shut down 2026-06-01 but are retained to price historical usage rows.

## Audio transcription (per audio minute)

USD per minute of recording, from `TRANSCRIPTION_PRICING` (meeting-recording
transcription bills by duration, not tokens).

| Model | $/minute | Notes | Source | Verified |
|---|---|---|---|---|
| `gpt-4o-transcribe` | 0.006 | OpenAI's published per-minute estimate (all-inclusive) | [pricing](https://developers.openai.com/api/docs/pricing) | 2026-07-13 |
| `gpt-4o-mini-transcribe` | 0.003 | OpenAI's published per-minute estimate (all-inclusive) | [pricing](https://developers.openai.com/api/docs/pricing) | 2026-07-13 |
| `gemini-2.5-flash` | 0.00192 | Derived: $1.00/Mtok audio input × 32 tok/s × 60 s; transcript output tokens billed additionally at the model's output rate | [pricing](https://ai.google.dev/gemini-api/docs/pricing), [audio docs](https://ai.google.dev/gemini-api/docs/audio) | 2026-07-13 |

## Not yet priced

- **Together AI** (paid, Qwen/Llama/etc.) — pull from <https://www.together.ai/pricing> via `price-check`. The tier models (`Qwen/Qwen3.5-32B/14B/7B`) are not listed on the current pricing page, so Together rows are flagged "pricing unknown" in the usage dashboard (never $0).
- **Legacy OpenAI** (`o3`, `o4-mini`, `gpt-4o`, `gpt-4o-mini`) — removed from OpenAI's current pricing page; historical usage rows referencing them flag as unknown.
- **`whisper-1`** — no longer on OpenAI's pricing page; Chatty transcribes with `gpt-4o-transcribe` instead.
