# Chatty — Project Instructions

## What This Is

**Chatty** — a free, open-source personal AI agent platform built for small business owners.
- **Free and open source** — no paid tiers, no vendor lock-in, no SaaS fees. Users only pay for their own AI provider API usage
- **Target audience**: small business owners who want a powerful AI chatbot without enterprise pricing or technical complexity
- Single user (password login), multiple agents
- User creates agents from a dashboard; each has name/personality/knowledge via onboarding wizard
- Optional branding: logo, company name, accent color
- Multi-provider AI: Anthropic, OpenAI, Google Gemini — all via API key paste (no OAuth for AI providers)
- Integrations: QuickBooks Online (OAuth), QuickBooks CSV import, Gmail, Google Calendar, WhatsApp (Baileys bridge), Telegram, CRM Lite, HubSpot, Salesforce, Odoo, BambooHR
- Agent features: memory system, dreaming/reflection, shared context across agents, scheduled actions, reminders
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

## Local Development

```bash
git clone https://github.com/WWilson1017/chatty.git
cd chatty
python run.py
```

Requires Python 3.10+ and Node.js 18+. The launcher handles venv, deps, `.env`, frontend build, and starts the server.

For dev mode with hot reload, run backend and frontend separately:
- Backend: `cd backend && ../.venv/bin/python -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload`
- Frontend: `cd frontend && npm run dev` (Vite dev server on port 5173, proxies `/api` to backend)

## Key Architecture

- **Provider-agnostic engine** — `ai_service.py` calls an `AIProvider` ABC, never Anthropic/OpenAI directly
- **Per-agent isolation** — each agent has its own context files, chat.db, and slug dir under `data/agents/{slug}/`
- **Global credentials** — provider auth lives in `data/auth-profiles.json`, shared across all agents
- **Encryption at rest** — API keys and OAuth tokens encrypted via Fernet; key stored in OS keychain (local) or env var (Railway)
- **No voice tab** — explicitly removed from scope
- **Single user only** — multi-user roughed in behind `MULTI_USER_ENABLED=false` flag for Phase 2

## Project Structure

```
backend/
├── main.py                          # FastAPI entry point
├── agents/                          # Multi-agent management (db, engine, router, onboarding, templates)
├── core/
│   ├── config.py                    # Settings from env vars
│   ├── auth.py                      # Password login + JWT
│   ├── encryption.py                # Fernet encryption for credentials
│   ├── providers/                   # AI provider abstraction (Anthropic, OpenAI, Gemini)
│   └── agents/                      # Agent engine (ai_service, tool_registry, context_manager, chat_history, memory, dreaming, shared_context, reminders, scheduled_actions)
├── integrations/                    # QuickBooks, QB CSV, Telegram, WhatsApp, CRM, HubSpot, Salesforce, Odoo, BambooHR
├── branding/                        # Logo/name/color
└── whatsapp-bridge/                 # Node.js Baileys sidecar

frontend/src/
├── agent/                           # Agent chat page + components
├── dashboard/                       # Agent grid, settings, integrations
├── onboarding/                      # Agent creation wizard
├── setup/                           # First-run provider setup
├── login/                           # Login page
├── core/                            # API client, auth context, types
└── crm/                             # CRM interface
```

## Worktrees

Worktrees live in `.claude/worktrees/` within the repo. Use `/wt <feature name>` to create one, `/dwt` to clean up. Branch from `master`, PR back to `master`.

## Blueprints

| Blueprint | Location | What to use it for |
|---|---|---|
| **CAKE OS** | `~/ai/cake_os` | Agent engine, frontend AgentPage, Gmail/Calendar tools, onboarding |
| **OpenClaw** | `~/ai/openclaw` | Multi-provider OAuth (PKCE flows, credential store pattern) |
