---
title: Guaranteed delivery for cron scheduled actions (don't bet on the model calling notify_user)
date: 2026-06-16
category: architecture-patterns
module: core/agents/scheduled_actions/processor, core/agents/notifications/delivery, core/providers
tags: [heartbeat, cron, scheduled-actions, notifications, delivery, model-tiers, silent-failure]
problem_type: pattern
---

## Context

Cron scheduled actions (e.g. a 5:15 AM "morning brief") exist to *report back* to the
user. Their output reaches the user only through a notification. Originally
`_process_cron` told the model to "Use `notify_user` to alert the user…" and then,
after the run, computed a `notified` flag (`any(tc.get("tool") in
("notify_user","post_message") …)`) — but **did nothing when it was false**.
Delivery was a bet on model behavior.

## Symptom

After PR #127 (dynamic model selection by tier), the morning brief ran every day,
generated full output, used its tools — but stopped sending notifications. The brief
just sat in `execution_history`.

Two layers:

1. **Trigger.** #127 made `get_ai_provider()` resolve the model from the agent's
   `model_tier`. On the production deploy `data/model-tiers.json` didn't exist, so
   tier resolution fell through to the hardcoded
   `TIER_MODELS["anthropic"]["top"] = claude-opus-4-8`, silently replacing the user's
   configured `active_model` (`claude-opus-4-6`). The new model simply chose not to
   call the notification tool.
2. **Root cause.** Delivery depended on the model. *Any* change — a model swap, a
   prompt tweak, a model "mood" — could drop the report silently. This is why
   "the heartbeat didn't send" recurred.

## Resolution — make delivery a system step, not a model choice

This mirrors how OpenClaw (`src/cron/isolated-agent/delivery-dispatch.ts`) and Hermes
(`cron/scheduler.py`) handle it: the background run produces its report as its
*final response*, and the **system delivers that text** afterward. The model is told
*not* to call a send tool. The only suppressor is an explicit model-emitted silent
marker. **Neither uses a "playbook" for delivery** — a playbook is still
model-followed instructions and shares the same failure mode.

Implemented in `_process_cron` (`core/agents/scheduled_actions/processor.py`):

1. **Inverted prompt.** "Your final response will be delivered automatically… you do
   not need to call `notify_user`. If there is genuinely nothing to report, respond
   with exactly `[SILENT]`."
2. **Auto-delivery fallback.** When `status == "ok"`, the final text is non-empty, it
   isn't `[SILENT]`, and the model didn't already deliver, call the existing
   `deliver_notification(agent_slug, title, message)` (the same path `notify_user`
   uses — web push + Telegram + WhatsApp + in-app log).
3. **Detect *successful* delivery, not a tool call.** `_delivered_via_tool()` parses
   each `notify_user`/`post_message` `tool_log` result and only counts `{"ok": true}`.
   This is critical: `background_runner` records write-budget / hourly-rate rejections
   under the same tool name with an `{"error": …}` result, and `notify_user` can error
   on bad args. A name-only guard would treat those failures as "delivered" and
   re-drop the report. Bias is conservative — anything unparseable/ambiguous falls
   through to auto-delivery (a possible duplicate beats a silent miss).

### Model-resolution fix (prevents the trigger from recurring)

`get_ai_provider()` now prefers the user's configured `active_model` over the
hardcoded `TIER_MODELS` fallback for the **top/auto** tier when no override/inferred
value exists (`model_tiers.has_explicit_tier()` checks the raw store, not
`get_resolved()` which always returns a fallback). So a fresh deploy — or a PR that
bumps `TIER_MODELS` — can't silently change the model background runs use.
mid/light keep the hardcoded fallback (they were never the user's explicit pick).

## Cron and heartbeat — one rule, two silent markers

Both use the same rule: **deliver the run's output unless the model emits the silent
marker.** This matches OpenClaw, which applies guaranteed delivery to its heartbeat
too — `shouldSkipHeartbeatOnlyDelivery()` in `src/cron/heartbeat-policy.ts` suppresses
delivery only when the payload is the `HEARTBEAT_OK` token (with a ~300-char ack
tolerance); anything else is delivered. Neither relies on a notify tool.

- **Cron = report:** silent marker `[SILENT]`; delivers the final response.
- **Heartbeat = monitor:** silent marker `HEARTBEAT_OK`; delivers the `ACTION_TAKEN:`
  report with the marker stripped from the body (`_strip_action_marker`, mirroring
  OpenClaw's `stripHeartbeatToken`). If the model already delivered via `notify_user`,
  the double-send guard skips the fallback.

**Spam control for the frequent (~30 min) heartbeat** is not a code judgment gate —
it's (a) the cheap triage + empty-checklist early-returns that skip most ticks before
any full run, and (b) the prompt instructing the model to report only what is NEW
since the last check (OpenClaw uses the same "do not repeat old tasks" discipline).
The model cannot silently swallow a finding: if the response isn't `HEARTBEAT_OK`,
it's delivered.

## Gotchas

- **Observability:** the durable signal is the `execution_history.notification_sent`
  **column** (`status == "ok"` + `notification_sent == False` = "ran but not
  notified"). The supplementary `{"tool": "auto_deliver", …}` marker must be
  **prepended** to `tool_calls`, because `history.record_complete` truncates the
  serialized `tool_calls` to 10 KB — an appended marker can be lost on a busy run.
- **Empty `channels_sent` is NOT an error** — `deliver_notification` always writes the
  in-app log, so empty channels just means "in-app only" (no push sub / external
  channels off). Log it at `info`; reserve `warning` for `ok is not True` / exceptions.
- **Scope:** this guarantees delivery against *model behavior*, not a process crash in
  the narrow window between `_mark_and_alert` advancing `next_run` and the delivery
  call. No pending-delivery/idempotency table was added (single-user SQLite app;
  keep it simple). Call it "model-independent best-effort," not "crash-proof."
- **Agent-authored prompts:** the tool guidance in `tool_definitions.py` ("Notifying
  the User") was split so agents creating cron actions don't re-encode the old
  notify-or-nothing behavior.
