# Joshua Platform Research — Agent Ideas Mined (Aug 2026)

**Source:** `https://joshua.umbrellainc.org:4430` — "Joshua," an Executive Chief of Staff & AI Operations
Platform built by Vertex Data Labs for the Umbrella Group of Companies (Tidal, CMN, Apsis). A single
agent (on a framework called Hermes) with 13 core tools and 175 "skills" across 20 categories, doing
full DevOps lifecycle management, business intelligence, creative production, and executive support
across 3 self-hosted Ubuntu servers and 26 Docker containers. The site is IP-restricted; this research
was done from a full 42-page capture of the site (overview, complete skill catalog, core tools, CLI
usage guide, infrastructure/hosting/operational-excellence pages).

**Purpose of this doc:** the complete mined idea list, mapped to CAKE OS and Chatty, filtered through
our goals: **exit Odoo (December cutover)** and **streamline operations to increase flow**. Five ideas
were filed as issues (see bottom); the rest are archived here so nothing is lost.

**Sibling copy:** the same archive lives in the CAKE OS repo at `docs/JOSHUA_PLATFORM_RESEARCH.md` (listed in its CLAUDE.md References table).

---

## What Joshua is, in our terms

One agent + a skill library, where a "skill" ≈ our playbook (markdown workflow with exact commands,
pitfalls, and verification steps) and the 13 core tools ≈ our shared engine tool groups. The closest
CAKE analogs already exist: playbooks (incl. self-authoring + digest), scheduled actions/heartbeats,
workers, memory, per-agent knowledge, chat-history search. What Joshua does differently is mostly in
the *shapes* of automation it supports and in how it packages/markets capability. The infra third of
its catalog (nginx/SNI, acme.sh, container fleets, SSH healers) is moot for us on Cloud Run.

---

## A. Platform-level patterns (apply to both CAKE OS and Chatty)

1. **Conditional self-terminating jobs** (`recurring-conditional-job`) — "run on schedule, check a
   condition, stop when met; escalate if never met by deadline." Neither platform has this shape.
   → **Filed: cake_os #1510.**
2. **Watchdog of the watchdogs** (`global-cron-monitor`) — one monitor verifying every scheduled
   action/heartbeat/background job actually *ran*; self-heals or escalates; runs every 4h; uses
   change-detection gating so it only alerts on state transitions. CAKE has many heartbeats but
   nothing that notices a heartbeat that silently stopped firing. Chatty alerts on 3+ consecutive
   heartbeat *failures* but not on jobs that never fire.
3. **Webhook-triggered agent runs** (`webhook-subscriptions`) — generic inbound HTTP triggers:
   "when this URL is called, run this task." CAKE has purpose-built webhooks (doorbell, WhatsApp)
   but no generic primitive; Chatty has none (big on Railway: Stripe/Zapier/form events → agent).
4. **Scripted orchestration over the agent's own tools** (`execute_code`) — for 3+ tool calls with
   logic (loops, filtering, retries), run one sandboxed Python script that calls tools
   programmatically instead of N model round-trips. CAKE's `run_analysis` is the read-only seed;
   extending it to invoke any read-only registered tool would enable "loop over all open POs and
   check each vendor" in one call. Chatty has nothing like it.
5. **Per-person memory auto-loaded by sender** (`webex-people-memory`) — a profile per messaging
   user (identity, history, notes) injected automatically whenever that person messages an agent.
   CAKE: keyed on Cliq/Telegram sender. Chatty: contact memory for Telegram/WhatsApp senders.
6. **Channel/topic gating for outbound messages** (`webex-gating`) — deterministic policy for which
   data classes may be posted to which channels/recipients (e.g. financials never to floor
   channels). Same fail-closed philosophy as `ar_forward_guard`, applied to Cliq sends.
7. **Deterministic no-LLM scheduled jobs** (`no_agent` cron mode) — first-class "no model in the
   loop" job type. CAKE learned this at #1150 (freezer alarms) but treats it as a one-off
   exception; making it a job type gives the policy a home. For Chatty it's also a token-cost
   feature.
8. **Self-healing escalation ladders** (`hush-ssh-healer`) — automated recovery that escalates
   through tiers (restart → rollback → reboot → page a human) instead of alert-and-wait. CAKE
   candidates: WhatsApp bridge, IoT bridge, Gmail sync, Cliq token.
9. **Capability catalog page** — the Joshua site itself is the idea: a browsable, searchable
   catalog of everything the agent can do, with a copyable example invocation per skill. Both
   platforms have the same discovery problem. → **Filed: cake_os #1512** (CAKE version,
   auto-generated from registries).
10. **"Think harder" model escalation phrases** (`model-escalation`) — verbal tier bump: default →
    "more" (reasoning model) → "much more" (top cloud model). Chatty already has top/mid/light
    tiers; nearly free to wire. CAKE could map onto the Sonnet/Opus split per turn.

## B. CAKE OS — agent & app ideas

11. **The Monday Report pattern** (`the-monday-report`) — weekly pull (aging, new opps, quotes,
    won/lost) **with week-over-week comparison**, auto-posted Monday morning to chat. The WoW delta
    framing is what makes it executive-readable. Post-cutover version reads native CAKE data (CRM,
    Orders, oven log, Packaging Ops) rather than Odoo. Rides scheduled actions + Cliq as-is —
    mostly a config exercise for Casey/Sam.
12. **Dogfood agent → Auto Issues** (`dogfood`) — a scheduled agent that walks a CAKE app headless
    (Playwright per the #1162 recipe), tries real flows, and files well-evidenced issues into the
    existing Auto Issues pipeline.
13. **Incident lifecycle on the alerts app** (`incident-response`) — Detect → Alert → Assign →
    Escalate → Track → Resolve → Report. Our alerts app stops at "banner until manually cleared";
    adding acknowledgment, assignment, escalation timers, and a post-incident record on the audit
    chain turns freezer/downtime alerts into tracked incidents. HACCP-friendly.
14. **Integration health dashboard + Odoo dependency burn-down** — per-integration last-success/
    failure cards (passive call tracking via the `app_usage` pattern + active read-only probes with
    change-detection gating), plus per-app Odoo call counts as a live cutover burn-down.
    → **Filed: cake_os #1511.**
15. **On/Offboarding app (People Ops)** (`cmn-onboarding-portal`) — checklists generated from
    BambooHR roster changes (#975 sync is already the trigger): accounts, PIN + `app_access`
    provisioning, Skills Matrix training assignments, equipment issue. Touches four systems we
    already integrate.
16. **Employee recognition portal** (`umbrella-recognition-portal`) — peer nominations + admin
    approval + rewards; natural notifications-bell consumer; could feed Team Status celebrations
    (#1387).
17. **Physical alert channel via the IoT bridge** — Joshua drives Hue/speakers; we already have
    Sonos on the IoT bridge and a freezer alarm that only reaches Cliq. Audible floor announcements
    / light cues as a second **deterministic** delivery path — floor staff aren't watching Cliq.
18. **Voice capture on the floor** (`audio-transcription`, faster-whisper) — speak a maintenance
    request or quality observation; transcription → structured filing via the existing Take a
    Photo / Maintenance path. Gloves + flour make typing terrible.
19. **Model Lab replay-based evals** (`evaluating-llms-harness`) — before an admin swaps the cheap
    seam model (#1244), replay the last N real triage/title requests against the candidate and diff
    outcomes vs the incumbent. Upgrades the swap gate from "probe passed" to "measured on our own
    workload."
20. **Vendor-doc → micro-portal** (`vendor-incentive-portal`) — turn dense external documents
    (retailer routing guides, GS1 requirements, supplier spec sheets) into small internal reference
    pages; fits the SOPs app as an "import a document" authoring mode.
21. **Prospect research for Casey** (`linkedin-profile-analyzer`, generalized) — a
    `research_prospect` tool compiling a public-sources brief on an account before CRM outreach.
22. **Grounded citations as a platform rule** (`grounded-citations`) — every figure an agent
    reports carries a link to its source record (Odoo MO today, DIMM item, oven-log event). Could
    be a shared prompt directive like `DATA_COMPUTATION_GUIDANCE`.
23. **Demo mode with synthetic data** (`demo-architecture`) — a seeded synthetic-data mode is the
    prerequisite to ever showing CAKE externally. (Joshua's builders monetize exactly this way —
    the site ends in a corporate-email-gated "Get This System" lead form.)

## C. Chatty — feature & positioning ideas

24. **Playbooks engine port** — Chatty's biggest capability gap vs Joshua; CAKE is the blueprint.
    → **Filed: chatty #143.**
25. **Document generation suite** (docx/xlsx/pptx/pdf) — the deliverable half of office work.
    → **Filed: chatty #144.**
26. **"Chief of Staff" preset bundle** — one-click preset wiring morning calendar digest + 10-min
    meeting warnings (via Telegram/WhatsApp) + inbox triage summary + weekly review. Every
    ingredient exists; the packaging is the feature, and "Executive Chief of Staff" is proven
    positioning (it's Joshua's tagline).
27. **Voice-memo capture into GTD** — Telegram/WhatsApp voice message → local whisper transcription
    → the existing deterministic capture intercept → GTD inbox. Lowest-friction capture there is;
    local model fits the no-SaaS ethos.
28. **RSS/blog watcher integration** (`blogwatcher`) — "watch these feeds, brief me on what
    matters" as a heartbeat-driven integration (feedparser + state). CAKE variant: Casey watching
    industry/competitor news.
29. **Advisor-council agent template** (`ceo-council`) — pressure-test a decision through several
    named advisor personas and synthesize the disagreement. A template + prompt; demos brilliantly.
    Ship more persona templates alongside (Joshua's `book-editor` "Max Perkins" shows the pattern).
30. **Knowledge packs** — Joshua's curated corpora (Hormozi 587 files, Naval, value investing,
    6,500-prompt libraries) are knowledge-import bundles with a name. Chatty's import service
    already has pluggable adapters; installable community-shareable packs are an open-source
    flywheel.
31. **Humanizer / AI-tic editing** (`humanizer`, `prose-line-editing`) — a de-AI pass on anything
    an agent writes for external eyes (email, posts). CAKE variant: Casey's customer-facing copy.
32. **Weekly "what your agents did" digest** (`session-knowledge-digest`) — Sunday summary of tasks
    completed, notifications sent, cost by agent, via existing notification channels. Closes the
    trust loop on background automation.
33. **Personality layer** (`petdex`, `hermes-themes`, custom banners) — mascots/themes/banners as
    the "make it feel owned" layer for a free product. Low priority, real word-of-mouth value.

## Deliberately not copied

- The self-hosted infra estate (nginx/SNI routing, acme.sh SSL, container fleet management, SSH
  healers as literal SSH, fail2ban, nightly container-image backups) — Cloud Run and Railway
  obviate this entire third of Joshua's catalog.
- `obliteratus` (LLM refusal abliteration) and `godmode` (jailbreak libraries) — not aligned with
  either product.
- macOS computer-use / iMessage / FindMy / Hue-as-desktop-toy — platform-specific to their
  Mac-centric deployment; our Telegram/WhatsApp/Cliq paths cover the need portably.
- Most one-off creative skills (ASCII video, pixel art, Suno songwriting, Minecraft/Pokemon) — fun,
  not flow.

## Filed issues (Aug 2026)

| Issue | Repo | Idea |
|---|---|---|
| tncheesecake/cake_os#1510 | CAKE OS | Conditional self-terminating scheduled actions (A1) |
| tncheesecake/cake_os#1511 | CAKE OS | Integration health dashboard + Odoo burn-down (B14) |
| tncheesecake/cake_os#1512 | CAKE OS | Agent capability catalog (A9) |
| wwilson1017/chatty#143 | Chatty | Playbooks engine port (C24) |
| wwilson1017/chatty#144 | Chatty | Document generation suite (C25) |

Selection rationale: capped at five by request; chosen for direct alignment with the Odoo exit
(#1511 instruments it; #1510 services every cutover step's verification watch) and flow (#1512
drives agent adoption; chatty#143/#144 are Chatty's two highest-leverage capability gaps). The
remaining 28 ideas above are intentionally unfiled — pull from this doc when capacity opens.
