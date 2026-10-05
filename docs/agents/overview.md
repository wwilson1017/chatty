# Chatty overview

Product scope, deployment model, architecture and layout. Moved verbatim from the root `AGENTS.md`.

## What This Is

**Chatty** — a free, open-source **personal assistant** (business or personal) with a browser-based UI: simple, easy, web-based. Positioning: personal assistant first, with business connection options — CRM-focused users belong in CakeCRM (separate product), not here.
- **Free and open source** — no paid tiers, no vendor lock-in, no SaaS fees. Users only pay for their own AI provider API usage
- **Target audience**: small business owners and individuals who want a powerful AI assistant without enterprise pricing or technical complexity
- **Browser-based** — full dashboard UI for creating agents, chatting, managing integrations, and settings. Also includes a CLI test harness for terminal-based agent interaction.
- Single user (password login + optional TOTP 2FA), multiple agents
- User creates agents from a dashboard; each has name/personality/knowledge via conversational onboarding (training mode)
- Optional branding: logo, company name, accent color
- Multi-provider AI: Anthropic, OpenAI, Google Gemini, Ollama (local), Together AI — all via API key paste (no OAuth for AI providers)
- Integrations: QuickBooks Online (OAuth), QuickBooks CSV import, Gmail (multiple accounts), Google Calendar, Google Drive, WhatsApp (Baileys bridge), Telegram (multiple bots), CRM Lite (optional, default OFF), Odoo, BambooHR, Paperclip (agent orchestration), Todoist, Claude Code (agents delegate tasks to the user's own Claude Code/Codex via `chatty-connector`)
- **Todos (GTD)** — core always-on feature (NOT an integration): global store in `core/todo/`, 11 `todo_*` agent tools, multi-page UI at `/todos`, GTD coaching block injected into every agent's system prompt (admin setting `gtd_coaching_text`), public no-login `/capture` page (optional secret token), no-login `/todo[/{token}]` web app serving the whole todo UI outside the dashboard (`core/todo/web.py`, off by default), deterministic Telegram "capture" intercept
- Agent features: memory system, dreaming/context archival, shared context across agents, scheduled actions (heartbeat), reminders (one-time and recurring), notifications (web push, Telegram, WhatsApp), knowledge import (OpenClaw, paste, folder, ZIP)
- File uploads: PDF, DOCX, and text files via drag-and-drop in chat
- BYO OAuth: users can bring their own Google and QuickBooks OAuth app credentials
- One-click cloud deployment via Railway

## Deployment

- **Primary deploy target**: Railway (one-click "Deploy on Railway" button in README)
- **Railway template**: `https://railway.com/deploy/chatty`
- Users get a cloud URL accessible from phone or desktop — no local setup required
- SQLite-based, no external database needed — persistent volume on Railway handles storage
- Only required env var: `AUTH_PASSWORD` — `JWT_SECRET` and `ENCRYPTION_KEY` auto-generate
- AI provider API keys are entered in-app via setup wizard, not as env vars
- Keep deployment simple — avoid requiring Postgres, Redis, or any external services
- See `DEPLOY.md` for full Railway setup guide

## Key Architecture

- **Provider-agnostic engine** — `ai_service.py` calls an `AIProvider` ABC, never Anthropic/OpenAI directly
- **Per-agent isolation** — each agent has its own context files, chat.db, and slug dir under `data/agents/{slug}/`
- **Global credentials** — provider auth lives in `data/auth-profiles.json`, shared across all agents
- **Encryption at rest** — API keys and OAuth tokens encrypted via Fernet; key stored in OS keychain (local) or env var (Railway)
- **Heartbeat system** — APScheduler fires every 60s, processing due reminders and scheduled actions as background AI turns with full tool access
- **Notifications** — AI-driven notification system: during background execution, the AI decides when findings are worth alerting the user via `notify_user` tool. Delivers to browser push (Web Push / VAPID), Telegram, and WhatsApp. Notification log in chat UI, channel settings in dashboard.
- **Alerts** — reserved for system-level issues (e.g. 3+ consecutive heartbeat failures). Golden banner + dashboard badge.
- **Knowledge import** — `agents/import_service/` with pluggable source adapters (OpenClaw, paste, folder, ZIP); auto-detects OpenClaw installations via `~/.openclaw/openclaw.json`
- **Dreaming** — nightly background process that scores context file usage and archives dormant files to prevent knowledge bloat (no AI calls, pure algorithmic scoring)
- **No voice tab** — explicitly removed from scope
- **Single user only** — multi-user roughed in behind `MULTI_USER_ENABLED=false` flag for Phase 2

## Project Structure

```
backend/
├── main.py                          # FastAPI entry point
├── cli/                             # CLI test harness (terminal REPL, no web server needed)
│   ├── __main__.py                  # Entry point, agent selection, arg parsing
│   ├── app.py                       # REPL loop, message sending, tool confirmation flow
│   ├── bootstrap.py                 # Lightweight backend init (DB, encryption, seed data)
│   ├── commands.py                  # Slash command dispatcher (/search, /memory, /mode, etc.)
│   ├── output.py                    # SSE parser, StreamRenderer for terminal output
│   └── session.py                   # Session state, agent switching, tool execution
├── agents/                          # Multi-agent management (db, engine, router, onboarding, templates)
│   └── import_service/              # Knowledge import with source adapters (OpenClaw, paste, folder, ZIP)
├── core/
│   ├── config.py                    # Settings from env vars
│   ├── auth.py                      # Password login + JWT
│   ├── auth_2fa.py                  # Optional TOTP two-factor authentication
│   ├── encryption.py                # Fernet encryption for credentials
│   ├── providers/                   # AI provider abstraction (Anthropic, OpenAI, Gemini, Ollama, Together AI)
│   ├── todo/                        # Todo (GTD) core feature: db, service, tools, REST router, /capture page, coaching
│   └── agents/                      # Agent engine (ai_service, tool_registry, context_manager, chat_history, memory, dreaming, shared_context, reminders, scheduled_actions, alerts, notifications)
├── integrations/                    # Google (Gmail/Calendar/Drive), QuickBooks, QB CSV, Telegram, WhatsApp, CRM (optional), Odoo, BambooHR, Paperclip, Claude Code
├── branding/                        # Logo/name/color
└── whatsapp-bridge/                 # Node.js Baileys sidecar

connector/                           # chatty-connector: separate pip package the user runs next to their Claude Code

frontend/src/
├── agent/                           # Agent chat page + components (includes heartbeat panel, reminders panel)
├── dashboard/                       # Agent grid, settings, integrations
├── onboarding/                      # Agent creation wizard
├── setup/                           # First-run provider setup
├── login/                           # Login page
├── core/                            # API client, auth context, types
├── crm/                             # CRM interface (nav gated on the crm_lite integration being enabled)
├── todo/                            # Todos (GTD) interface: inbox triage, next actions, projects, review
└── shared/                          # Shared components and utilities (incl. sectionStyles shared by crm/ + todo/)
```

## Blueprints

| Blueprint | Location | What to use it for |
|---|---|---|
| **CAKE OS** | `~/ai/cake_os` | Agent engine, frontend AgentPage, Gmail/Calendar tools, onboarding |
| **OpenClaw** | `~/ai/openclaw` | Multi-provider OAuth (PKCE flows, credential store pattern) |
