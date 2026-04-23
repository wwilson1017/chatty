# Chatty — Project Instructions

## What This Is

**Chatty** — a free, open-source personal AI agent platform built for small business owners.
- **Free and open source** — no paid tiers, no vendor lock-in, no SaaS fees. Users only pay for their own AI provider API usage
- **Target audience**: small business owners who want a powerful AI chatbot without enterprise pricing or technical complexity
- Single user (password login), multiple agents
- User creates agents from a dashboard; each has name/personality/knowledge via onboarding wizard
- Optional branding: logo, company name, accent color
- Multi-provider AI: Anthropic, OpenAI, Google Gemini, Ollama (local), Together AI — all via API key paste (no OAuth for AI providers)
- Integrations: QuickBooks Online (OAuth), QuickBooks CSV import, Gmail, Google Calendar, Google Drive, WhatsApp (Baileys bridge), Telegram, CRM Lite, Odoo, BambooHR
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
│   ├── providers/                   # AI provider abstraction (Anthropic, OpenAI, Gemini, Ollama, Together AI)
│   └── agents/                      # Agent engine (ai_service, tool_registry, context_manager, chat_history, memory, dreaming, shared_context, reminders, scheduled_actions)
├── integrations/                    # Google (Gmail/Calendar/Drive), QuickBooks, QB CSV, Telegram, WhatsApp, CRM, Odoo, BambooHR
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

## Adding Integrations

New integrations follow a consistent pattern. When connected globally, ALL agents automatically get the integration's tools — no per-agent opt-in required. This is a single-user app; if the user connected a service, they want their agents to use it.

### File structure

Mirror `integrations/quickbooks/` for credential-based integrations, or `integrations/google/` for OAuth-scoped integrations:

```
integrations/{name}/
├── __init__.py
├── client.py          # Authenticated API client (token refresh, retry)
├── onboarding.py      # setup_from_oauth() or setup() — persists credentials
├── tools.py           # Tool handler functions called by ToolRegistry
└── *_ops.py           # Raw API operations (each takes a service/client object)
```

### Wiring checklist

1. **Register** in `integrations/registry.py` → `AVAILABLE_INTEGRATIONS` dict
2. **Add routes** in `integrations/router.py` → setup, setup/complete (for OAuth), disconnect
3. **Add tool definitions** in `core/agents/tool_definitions.py` — each tool needs `name`, `description`, `input_schema`, `kind`, and `writes: bool`
4. **Add dispatch** in `core/agents/tool_registry.py` — add a `_execute_{name}` method and wire it in `execute_tool`
5. **For OAuth integrations**: use the shared two-step flow in `core/providers/oauth.py` — `start_oauth_flow()` returns `{flow_id, auth_url}`, frontend opens popup + polls, `/setup/complete` calls `consume_flow()`
6. **Frontend**: add a card component in `dashboard/` and wire it into `IntegrationsTab.tsx`

### Tool auto-discovery

Tools appear for agents automatically when their integration is enabled globally:
- **QB/Odoo/BambooHR/CRM/QB CSV**: `_load_integration_tools()` in `agents/router.py` checks `is_enabled(name)` and injects tools + executors
- **Google (Gmail/Calendar/Drive)**: `google_capabilities()` in `integrations/google/policy.py` reads scope grants from `google.json` and returns capability flags passed to `get_tool_definitions()`
- **Do NOT require per-agent flags** for new integrations. Connect once → all agents get the tools.

### Write tools

Tools that modify external data (send email, create event, upload file) must set `writes: True` in their tool definition. Chatty's `tool_mode` system will require user confirmation before executing write tools in "normal" mode.

## Worktrees

Worktrees live in `.claude/worktrees/` within the repo. Use `/wt <feature name>` to create one, `/dwt` to clean up. Branch from `master`, PR back to `master`.

## Blueprints

| Blueprint | Location | What to use it for |
|---|---|---|
| **CAKE OS** | `~/ai/cake_os` | Agent engine, frontend AgentPage, Gmail/Calendar tools, onboarding |
| **OpenClaw** | `~/ai/openclaw` | Multi-provider OAuth (PKCE flows, credential store pattern) |
