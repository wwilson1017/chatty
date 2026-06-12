---
title: Compact-marker + ephemeral-expansion pattern for invoking stored prompts in chat
date: 2026-06-12
category: architecture-patterns
module: core/agents/playbooks, agents/router, frontend chat
tags: [playbooks, prompt-injection, chat-history, markers, system-prompt, tokens]
problem_type: pattern
---

## Context

Playbook quick-action chips and the "/" slash menu need the full procedure text
delivered to the AI provider when invoked — but persisting the multi-KB expansion
in chat history would bloat the visible transcript, re-pay the tokens on every
subsequent turn (the frontend re-sends full history), and pollute downstream
consumers of the conversation (auto-titles, the background learning review).

## Guidance

Split the invocation into a **persisted compact marker** and an **ephemeral
provider-bound expansion**:

1. **Frontend** sends two things on the invocation turn: `payload.playbook_slug`
   (the trigger) and a compact `[playbook:slug]` marker embedded in the message
   text (the durable record — same convention as the `[via Telegram from X]`
   prefix). The marker survives history reloads with zero schema changes.

2. **Backend** (`agents/router.py:_build_playbook_expansion`) validates the slug,
   strips the marker from the user text (unanchored, `count=1`, targeting the
   invoked slug specifically), and builds the activation message
   (`service.build_activation_message`: activation note + sanitized body wrapped
   in `<playbook>` tags + the user's extra text). A missing/archived playbook is
   a 404 — silently proceeding would show the invocation pill in the UI while
   the model never saw the procedure.

3. **`ai_service.chat()`** persists the original marker text to chat.db, then
   substitutes the expansion into the **provider-bound copy only**
   (`current_messages`), for that turn only. History re-sends pass through
   without re-expansion — only the current request's `playbook_slug` triggers one.

## Four subtleties (all found in review, all real)

1. **Later turns lose the procedure.** Turn 2+ re-sends the compact marker, so
   the provider no longer has the steps. Fix: a system-prompt instruction —
   "a `[playbook:slug]` marker in an earlier user message means that playbook
   was invoked; call `read_playbook(slug)` again if you're continuing the
   procedure without its steps in context." Cheaper than re-expanding every turn.
2. **Post-turn analyzers must get the marker, not the expansion.** The learning
   review initially received `current_messages` — the full playbook body
   attributed to the USER, which blew the transcript budget and false-triggered
   the "user explained a procedure" heuristic. Pass the original `messages`.
3. **Auto-titles leak the marker.** Strip `[playbook:slug]` before
   `chat_service.auto_title(...)`.
4. **Don't anchor marker regexes at `^`.** The upload path prepends attached-file
   text before the marker, so both the backend strip and the frontend display
   regex must match the first occurrence anywhere, not string-start.

## Why This Matters

The marker/expansion split keeps history compact (tokens paid once), display
clean (frontend strips the marker and shows a pill), and the invocation
re-derivable (agent can re-read by slug). Every consumer of message content —
titles, learning loops, transcripts, future channels — must decide which view
it wants: the durable marker or the ephemeral expansion. Defaulting new
consumers to the marker view is almost always correct.

## When to Apply

Any new invocation surface (e.g. Telegram playbook triggers) or any feature
that injects stored content into a chat turn on demand (saved prompts,
templates, canned replies).
