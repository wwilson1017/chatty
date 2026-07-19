# Chatty — Project Instructions

## What This Is

**Chatty** — a free, open-source personal AI agent platform with a browser-based UI, built for small business owners.
- **Free and open source** — no paid tiers, no vendor lock-in, no SaaS fees. Users only pay for their own AI provider API usage
- **Target audience**: small business owners who want a powerful AI chatbot without enterprise pricing or technical complexity
- **Browser-based** — full dashboard UI for creating agents, chatting, managing integrations, and settings. Also includes a CLI test harness for terminal-based agent interaction.
- Single user (password login + optional TOTP 2FA), multiple agents
- User creates agents from a dashboard; each has name/personality/knowledge via conversational onboarding (training mode)
- Optional branding: logo, company name, accent color
- Multi-provider AI: Anthropic, OpenAI, Google Gemini, Ollama (local), Together AI — all via API key paste (no OAuth for AI providers)
- Integrations: QuickBooks Online (OAuth), QuickBooks CSV import, Gmail (multiple accounts), Google Calendar, Google Drive, WhatsApp (Baileys bridge), Telegram (multiple bots), CRM Lite, Odoo, BambooHR, Paperclip (agent orchestration)
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

### Railway CLI

For debugging production or running diagnostics against the deployed instance:

```bash
brew install railway
railway login          # opens browser for auth
railway link           # select project, environment, and service
railway ssh -- "cd /app/backend && python3 -c 'print(\"hello\")'"
```

SSH requires a registered key: `railway ssh keys add --key ~/.ssh/id_ed25519.pub`

If host key verification fails, add Railway's SSH host: `ssh-keyscan -H ssh.railway.com >> ~/.ssh/known_hosts`

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

### CLI Test Harness

Chat with agents from the terminal — no web server required:

```bash
cd backend && ../.venv/bin/python -m cli
```

- `--agent <slug>` — select agent by slug (auto-selects if only one exists)
- `--ephemeral` — don't save conversation to chat.db
- `--power` — skip write tool confirmations
- `--readonly` — disable all write tools
- `--verbose` / `-v` — show full tool args and results
- `--list` / `-l` — list all agents and exit
- `--new` — create a new agent interactively

Slash commands inside the REPL: `/help`, `/search`, `/facts`, `/memory`, `/context`, `/read`, `/daily`, `/history`, `/dreams`, `/shared`, `/reset`, `/agent`, `/agents`, `/switch`, `/new`, `/usage`, `/mode`, `/verbose`, `/quit`

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
│   └── agents/                      # Agent engine (ai_service, tool_registry, context_manager, chat_history, memory, dreaming, shared_context, reminders, scheduled_actions, alerts, notifications)
├── integrations/                    # Google (Gmail/Calendar/Drive), QuickBooks, QB CSV, Telegram, WhatsApp, CRM, Odoo, BambooHR, Paperclip
├── branding/                        # Logo/name/color
└── whatsapp-bridge/                 # Node.js Baileys sidecar

frontend/src/
├── agent/                           # Agent chat page + components (includes heartbeat panel, reminders panel)
├── dashboard/                       # Agent grid, settings, integrations
├── onboarding/                      # Agent creation wizard
├── setup/                           # First-run provider setup
├── login/                           # Login page
├── core/                            # API client, auth context, types
├── crm/                             # CRM interface
└── shared/                          # Shared components and utilities
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
7. **Delimiter wrapping**: if the integration fetches data from external APIs, its tools are automatically wrapped in `<untrusted_tool_result>` delimiters (tools with `kind: "integration"` are wrapped by default). If the integration reads from local user data (like CRM Lite), add its tool name prefix to `_UNWRAPPED_INTEGRATION_PREFIXES` in `core/agents/security/delimiters.py`

### Tool auto-discovery

Tools appear for agents automatically when their integration is enabled globally:
- **QB/Odoo/BambooHR/CRM/QB CSV/Paperclip**: `_load_integration_tools()` in `agents/router.py` checks `is_enabled(name)` and injects tools + executors
- **Google (Gmail/Calendar/Drive)**: `google_capabilities()` in `integrations/google/policy.py` reads scope grants from `google.json` and returns capability flags passed to `get_tool_definitions()`. Supports multiple Google accounts with per-agent, per-service assignment.
- **Telegram**: each agent gets its own bot token; a single Telegram user can be linked to multiple agents simultaneously
- **Do NOT require per-agent flags** for new integrations. Connect once → all agents get the tools.

### Write tools

Tools that modify external data (send email, create event, upload file) must set `writes: True` in their tool definition. Chatty's `tool_mode` system will require user confirmation before executing write tools in "normal" mode. Write tools (excluding `context_memory` tools) are also subject to per-turn write budgets and optional hourly rate limits configured in admin settings.

## Model Pricing

The model selector is **dynamic** — each provider's `list_models()` fetches live from the provider's API (Anthropic/OpenAI/Google/Together/Ollama), cached with a fallback to the hardcoded `*_MODELS` constants. New models appear automatically; no code change needed to add one to the dropdown.

**Tiers** (top/mid/light) are inferred from model naming and persisted to `data/model-tiers.json`; the user can override them in Provider Setup. `resolve_tier_model()` stays synchronous (override → inferred → hardcoded).

**Pricing is the one thing no provider API exposes**, so it is maintained manually in `backend/core/providers/pricing.py` (`MODEL_PRICING` + `PRICING_SOURCES`), mirrored to `backend/core/providers/PRICING.md`. The usage dashboard flags paid models with no price entry as "pricing unknown" (it never silently reports $0 for a paid model; only local Ollama is free).

**Every PR that adds/changes models or touches `core/providers/` or `core/agents/usage/` MUST run the `price-check` skill first** (`.claude/skills/price-check/`) and include any resulting `pricing.py` / `PRICING.md` changes in the same PR. The skill pulls current rates from official pricing pages, never fabricates a rate, and skips re-fetching if pricing was already verified in the chat.

## Session Knowledge

Two shared knowledge resources live in the repo. Read them at the start of a session when the work touches areas they cover; run `/coach` (`.claude/skills/coach/`) at the end of a session to capture new lessons.

### Coach Lessons (`.claude/coach-lessons.md`)

Behavioral instincts extracted from past development sessions, each carrying an evidence record:

```
- `[✓2 ✗0 · 2026-07-19]` **When** <trigger> → **do** <action> → **because** <reason>
```

`✓` = sessions where the instinct was followed, `✗` = sessions where a correction had to happen, date = last evidence event. Scan the `## Index` block at the top, grep the quoted phrase for the full instinct, and apply what's relevant. Instincts with ✓ ≥ 3 get promoted into this file's "Proven Instincts (coach)" section below; the `/coach` skill maintains evidence, lifecycle, and the index automatically.

### Solution Docs (`docs/solutions/`)

Non-trivial problems solved in past sessions are written up in `docs/solutions/` (categorized, with YAML frontmatter). Search there before re-deriving a fix or pattern: `grep -ri <keyword> docs/solutions/`.

## Proven Instincts (coach)

Promoted from `.claude/coach-lessons.md` after ≥3 confirmed sessions; `/coach` maintains this section.

- **When** running the backend from a git worktree → **do** use the main checkout's absolute venv path (e.g. `/Users/willwilson/ai/chatty/.venv/bin/python`), not relative (`../../.venv/bin/python`) → **because** worktrees live under `.claude/worktrees/<name>/backend/` and the relative path resolves to a nonexistent location

## Worktrees

Worktrees live in `.claude/worktrees/` within the repo. Use `/wt <feature name>` to create one, `/dwt` to clean up. Branch from `master`, PR back to `master`.

## Blueprints

| Blueprint | Location | What to use it for |
|---|---|---|
| **CAKE OS** | `~/ai/cake_os` | Agent engine, frontend AgentPage, Gmail/Calendar tools, onboarding |
| **OpenClaw** | `~/ai/openclaw` | Multi-provider OAuth (PKCE flows, credential store pattern) |
