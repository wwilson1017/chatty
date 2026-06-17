---
title: Reconstructed provider message arrays must end on a user turn
date: 2026-06-17
category: logic-errors
module: core/agents/context_assembly, core/agents/ai_service, core/providers/google_provider
tags: [multi-provider, context-reconstruction, gemini, anthropic, approval-flow, compaction]
problem_type: bug
---

## Problem
When Chatty rebuilds the provider `messages` array from `chat_history.db` each turn
(server-side reconstruction), the array could end on an **assistant** message — which
Gemini resends as the user turn and Anthropic treats as a prefill, corrupting the next
response.

## Symptoms
- After approving a write tool, **Gemini answers its OWN "Shall I send it?" question**
  (it sends `messages[-1]` as the user turn); **Anthropic** continues the wrap-up
  sentence mid-thought into a fresh bubble.
- Hit the approval-reconcile path AND the stale/duplicate-approval no-op path.
- A compaction gist or approval ack folded onto a tool-result turn could be silently
  dropped from Gemini's history (non-`_type` parts were skipped).

## What Didn't Work
- **Persisting the confirm wrap-up narration** (a correct fix for the *no-approval*
  branch, so the next turn sees the agent's own question) made the *approval* branch
  worse: the wrap-up became the last DB row, so the assembled array ended on an
  assistant turn. A fix to one path created a bug on another.
- **Gating the user-ack append on `_approved_reconciled`** missed the stale/duplicate
  path (reconcile becomes a no-op, but the tail is still assistant).

## Solution
- On any approved-tool turn whose assembled tail is an assistant message, append a
  **transient (unpersisted) user ack** (`[Approved — <tool> executed; its result is
  shown above.]`). Guard only on `current_messages[-1]["role"] == "assistant"` — the
  live-injection paths already end on a user/tool turn, so they never trigger it.
- Teach Google's history loop **and** its `send_msg` builder to emit text `Part`s for
  coalesced `{"type":"text"}` blocks (previously silently dropped).
- On a failed user-row save, splice the client message back in and run it through
  `_coalesce_consecutive` so the turn never answers the previous message nor sends two
  consecutive user turns — in **both** `chat()` and `run_sync()` (Telegram).

## Why This Works
Both providers key behavior off the last message: Gemini's `stream_turn` sends
`messages[-1]` with a hardcoded `role="user"`; Anthropic treats a trailing assistant as
assistant-prefill. The reconstruction layer's invariant — *the array ends with the
latest user turn* — must hold on every code path, including ones that don't save a new
user row (approval reconcile, stale duplicate, failed save).

## Prevention
- For any path that rebuilds context without saving a fresh user row, assert
  `messages[-1]["role"] == "user"` (or spy the provider's seen messages) in a test.
- When a fix changes **what** gets persisted, re-derive the reconstructed message
  sequence for **every** provider — a new assistant row can flip the tail, and a
  provider-neutral coalescer can emit Anthropic-shaped blocks a provider drops.
