---
title: Context-fullness meter stuck at 0% — Anthropic prompt-cache token accounting
date: 2026-06-15
category: logic-errors
module: core/agents/ai_service, core/providers/windows
tags: [anthropic, prompt-caching, sse, token-accounting, context-window, cli]
problem_type: bug
---

## Problem
The agent chat "context fullness" meter always showed 0%, even in long
conversations that clearly filled much of the model's context window.

## Symptoms
- Composer hint rendered `0% ctx · ⏎ send` on essentially every Anthropic turn.
- Backend emitted a `usage` SSE event with a small `input_tokens` over a
  hardcoded `200000` window → `~300 / 200000 ≈ 0%`.

## What Didn't Work
- **Naively summing the cache tokens into `input_tokens`** (redefining the
  field to be cache-inclusive). This fixed the meter but silently broke the
  CLI: `backend/cli/output.py` accumulates every `usage` event's `input_tokens`
  into the session total, so re-read cache tokens got summed every turn and
  inflated the count. The same field is consumed by two different clients (the
  React hook and the terminal harness).

## Solution
1. Emit a NEW `context_tokens` field = `input_tokens +
   cache_creation_input_tokens + cache_read_input_tokens` for the meter; leave
   `input_tokens`/`output_tokens` RAW for the CLI + cost log.
2. Source the window per-model from the provider (`AIProvider.context_window`;
   Anthropic reports its real window) instead of a hardcoded 200000. `None`
   hides the meter (graceful for providers not yet wired).
3. Plan-mode-exit and pending-confirmation wrap-up turns emit `meter_only=True`
   events (raw token fields zeroed) so the meter updates without the CLI
   double-counting those extra API calls.
4. Frontend reads `context_tokens`, guards divide-by-zero, clamps 0–100%, and
   clears the meter on conversation switch.

## Why This Works
Anthropic reports cached prompt tokens under `cache_read_input_tokens` /
`cache_creation_input_tokens`, NOT under `input_tokens`. With aggressive prompt
caching (system + tools + conversation prefix all cache-controlled),
`input_tokens` is only the uncached delta — a few hundred tokens — so it never
reflects true window occupancy. The fix measures the full prompt the model
actually read while keeping the raw billing fields intact for other consumers.

## Prevention
- Treat the chat SSE stream as having MULTIPLE consumers (web hook + CLI
  StreamRenderer). Before changing a `usage` field's meaning, check every
  consumer.
- When a single event serves both "display" and "accounting", separate the
  concerns (distinct fields / a `meter_only` flag) rather than overloading one.
- Reset per-conversation derived UI state in the conversation-load handler, not
  only in `clear()`, or it shows a stale reading from the previous conversation.
