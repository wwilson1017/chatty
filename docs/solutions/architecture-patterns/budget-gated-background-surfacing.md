---
title: Peek/claim pattern for budget-capped content surfaced into gated background runs
date: 2026-06-12
category: architecture-patterns
module: core/agents/memory/commitments, core/agents/scheduled_actions/processor
tags: [heartbeat, budget, rate-cap, surfacing, concurrency, sqlite, triage, commitments]
problem_type: pattern
---

## Context

Commitments (inferred follow-ups) are surfaced into heartbeat system prompts under
a rolling 24-hour cap. The heartbeat pipeline has multiple abort points *after*
prompt assembly begins — triage ALL_CLEAR, empty checklist, lost lease, provider
error — and there are two independent surfacing paths (the scheduled heartbeat in
`scheduled_actions/processor.py` and the reminders heartbeat in
`reminders/heartbeat.py`), plus the owner resolving items from the UI, all racing
each other against one per-agent SQLite connection.

The naive design (build the block → mark items surfaced as a side effect) burned
the daily budget on runs that never reached a model, and a later peek/mark split
without atomicity could double-surface or push owner-resolved items into prompts
stale. The final shape converged over three Codex review turns.

## Guidance

1. **Never consume budget while building a prompt.** Split surfacing into:
   - `peek_due_followups()` — a pure SELECT: free, repeatable, no side effects.
     Use it for gating decisions (skip the empty-checklist early-return, force a
     full run past triage).
   - `claim_followups_for_surfacing(peeked)` — called only at the
     committed-to-execute point (after the triage bypass and the lease re-check).
     Under the SQLite write lock it re-validates status + surfacing recency,
     recomputes the remaining cap, marks what survives, and returns only the
     claimed rows. Format the prompt block from the claimed rows, never the
     peeked ones.

2. **Short-circuit the placeholder run.** If the run existed *only* to surface
   the peeked items (checklist was empty → placeholder substituted) and the claim
   comes back empty because another path won the race, record completion exactly
   like the triage ALL_CLEAR path and return before `run_background_turn` — don't
   spend a full model turn on a prompt with nothing actionable.

3. **The cap bounds surfacing EVENTS, not outstanding items.** Resolving an item
   must NOT free its budget slot: a surface→resolve→surface loop would otherwise
   nag without bound inside one window. Two reviewers independently proposed the
   "fairer" status-filtered count at max confidence; it inverts the guarantee.

4. **Mirror the janitor's cutoffs in the read query.** Expiry runs only in the
   nightly job; a deploy or crash landing on that window must not let a
   stale-but-unexpired row keep surfacing. `due_commitments` applies the same
   cutoffs (`due_at` within 7 days past due, undated within 14 days, absolute
   60-day backstop) as exclusions, so surfacing self-corrects.

5. **Back up surfacing-state mutations.** On Railway, a GCS snapshot restore
   that predates a claim would resurrect spent budget and re-surface the same
   items — `claim`/`mark` back up after commit (best-effort, debug-logged).

## Why This Matters

Each refinement closed a real failure: consume-on-build burned the cap on triage
skips with nothing delivered; mark-after-peek without re-validation double-surfaced
under concurrent paths and surfaced items the owner had just dismissed; nightly-only
expiry let hallucinated far-future due dates and missed sweeps defeat the
"never a nag machine" guarantee.

## When to Apply

Any capped, proactively-surfaced content riding background turns that have gates
or multiple delivery paths — digests, alerts, nudges, re-engagement prompts, or
future "things the agent noticed" features.
