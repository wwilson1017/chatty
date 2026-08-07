# "Agents at Work" Research — CRHQ Operating-Model Ideas for Chatty

> Research compiled 2026-08-07. Primary source: [CRHQ "Agents at Work"](https://crhq.ai/agents-at-work)
> (a documented week of a 45-agent fleet) plus the [CRHQ product page](https://crhq.ai) and
> supplementary 2026 research on approval queues, self-correcting agent memory, and graduated
> autonomy. The full pattern-by-pattern analysis lives in the CAKE OS repo
> (`docs/AGENTS_AT_WORK_RESEARCH.md` there); this doc is the Chatty-shaped subset.

## Why CRHQ is relevant to Chatty specifically

CRHQ sells exactly Chatty's promise at $299/month: your own server, your own agents, bring
your own model, persistent identity and memory, scheduled background work, and a human role
that narrows to judgment and approvals. Chatty is the free, self-hosted version of that
pitch — so the patterns that make CRHQ's operator load "a few part-time hours a day" are
directly the patterns that make Chatty feel magical to a solo user.

## 1. Decision Queue for background turns (highest impact)

**CRHQ:** agents never block on a human; anything needing judgment lands on a standing
"needs a decision from you: 9 open" list the operator reviews daily. This is the consensus
2026 production HITL pattern ([Eucalipse](https://eucalipse.com/articles/ai-agent-approval-queue-human-in-the-loop),
[explainx](https://explainx.ai/blog/human-in-the-loop-ai-when-to-let-agent-run-2026)).

**Chatty today:** write-tool confirmation only exists in a live chat (`tool_mode` normal).
Background turns (heartbeat reminders, scheduled actions) run with full tool access,
bounded only by per-turn write budgets and optional hourly rate limits. So a background
agent either does the write or can't — there is no "tee it up for me" middle.

**Idea:** a `pending_approvals` store: a background turn that wants a gated write records
the proposed tool call + args and moves on; the dashboard shows an approval queue
(and the notification system — web push / Telegram / WhatsApp — carries "2 decisions
waiting", with Telegram inline-button approve/deny as the killer interaction for a
phone-first solo user). Approval executes the stored call and resumes the agent as a
background turn seeded with the result; denial records the reason so the agent sees it
next turn. This makes write budgets a ceiling rather than the whole safety story, and it
is the feature that lets a cautious user turn background work *on* at all.

## 2. Learnings log per agent

**CRHQ:** each agent keeps a `learnings.log` of documented mistakes, re-read in future
runs (the Reflexion pattern — [Fastio](https://fast.io/resources/reflection-pattern-self-correcting-agents/),
[Addy Osmani](https://addyosmani.com/blog/self-improving-agents/)).

**Chatty today:** memory stores facts and the dreaming pass archives dormant context, but
nothing captures "I did X and it was wrong; do Y instead" as a distinct, always-injected
category. Corrections the user makes in chat dissolve into ordinary history.

**Idea:** a small `learnings` table per agent + a `record_learning` tool (agent captures a
lesson the moment the user corrects it) + injection of the most relevant N into the system
prompt, size-capped. Also let the user view/edit the list in the agent's settings — for a
single-user product, "teach it once, it stays taught" is the core retention loop.

## 3. Graduated autonomy on write tools

**CRHQ:** workflows mature (*planned → scaffolded → executable → mature*) and earn
autonomy through proven use.

**Chatty today:** `tool_mode` (readonly / normal / power) is a global per-conversation
choice — all-or-nothing trust.

**Idea:** per-(agent, tool) trust earned from history: after N consecutive approvals of
the same tool with no rejections, offer "auto-approve `create_calendar_event` for this
agent from now on?" — an explicit user opt-in per tool, revocable in settings, with the
approval history as the evidence shown. This is the approval-queue → autonomy ladder in
its simplest single-user form, and it decays (a rejection revokes auto-approve).

## 4. Leverage metrics on the usage dashboard

**CRHQ** leads with ratios: 95.9% tokens from cache, $11.08 of model work per human
message, 73% of messages agent-initiated.

**Chatty today:** the usage dashboard reports tokens and cost per model/provider (with
honest "pricing unknown" flags), but nothing answers "how much did my agents do that I
didn't ask for, and what did it cost per thing I *did* ask?"

**Idea:** add background-vs-interactive turn counts, cache-read share (Anthropic and
OpenAI both report cache usage fields), and cost per human message. Cheap to compute from
existing usage rows; it is also the honest way to show a BYO-API-key user what heartbeat
features cost them before they enable more.

## 5. Report artifacts instead of transcript notifications

**CRHQ:** 113 artifacts in a week — briefs, trackers, dashboards — "replacing transcript
reading."

**Chatty today:** `notify_user` delivers text to push/Telegram/WhatsApp; anything long
lands as a wall of chat text.

**Idea:** a `create_report` tool that renders markdown to a stored, dated report viewable
in the dashboard (and linked from the notification). Morning brief, weekly review, QB
monthly summary — the GTD weekly review page is a natural first consumer. Keep it
markdown-rendered (no arbitrary HTML) to avoid a sanitization project.

## 6. Watch templates

**Chatty today:** scheduled actions + reminders exist; users must invent them from scratch.

**Idea:** a template gallery of one-click background jobs matched to connected
integrations: "QuickBooks: flag invoices unpaid > 30 days", "Gmail: unanswered threads
older than 3 days", "Todoist/Todos: stale next-actions review", "Calendar: tomorrow
briefing". Each is a pre-filled scheduled action the user can edit — adoption surface for
machinery that already exists, and a natural place to route outputs through ideas 1 and 5.

## Suggested order

1. Leverage metrics (small; instruments the rest)
2. Report artifacts (small; immediate daily value)
3. Decision queue (the keystone feature)
4. Learnings log
5. Graduated autonomy (builds on the queue's approval history)
6. Watch templates

## Sources

- [CRHQ — Agents at Work](https://crhq.ai/agents-at-work) · [CRHQ](https://crhq.ai)
- [Eucalipse — The Approval Queue Pattern](https://eucalipse.com/articles/ai-agent-approval-queue-human-in-the-loop)
- [explainx — When to Gate Agents (2026)](https://explainx.ai/blog/human-in-the-loop-ai-when-to-let-agent-run-2026)
- [buildmvpfast — HITL Implementation Patterns (2026)](https://www.buildmvpfast.com/blog/human-in-the-loop-ai-agents-implementation-patterns-2026)
- [Fastio — Reflection Pattern / Self-Correcting Agents](https://fast.io/resources/reflection-pattern-self-correcting-agents/)
- [Addy Osmani — Self-Improving Coding Agents](https://addyosmani.com/blog/self-improving-agents/)
- [Microsoft Learn — Agentic AI adoption maturity model](https://learn.microsoft.com/en-us/agents/adoption-maturity-model/)
