# Chatty — Phase 1 Plan

## Context

Building **Chatty** — a standalone, brandable personal AI agent platform. Single user (password login), multiple agents. The user can create agents, each with its own name, personality, knowledge, and onboarding. Optional branding — user can upload a logo and company name to personalize the platform.

**Repo**: `C:\ai\chatty`, GitHub `WWilson1017/chatty`

**This is local-only until fully functional** — no cloud deployment in Phase 1.

**Blueprints**:
- **CAKE OS** (`C:\ai\cake_os`) — Core agent engine, frontend AgentPage, Gmail/Calendar tools, personal agent per-user factory
- **OpenClaw** (`C:\ai\openclaw`) — Multi-provider AI auth: OAuth for OpenAI/Google, setup token for Anthropic

**Key decisions**:
- **Single user, multiple agents** — one login, can spawn/manage multiple agents
- **AI provider**: User chooses per-agent or globally — Anthropic (API key), OpenAI (OAuth), Google Gemini (OAuth)
- **Agent creation**: "New Agent" from dashboard → onboarding flow → personalized assistant
- **Optional branding**: Upload logo + company name to customize the platform look
- **Web UI matches CAKE OS** — same AgentPage with Chat + Knowledge tabs (no voice)
- **Auth**: Password login for now. Multi-user (Google OAuth, user accounts) roughed in but not active — Phase 2
- **Gmail & Calendar**: Copy working tools from CAKE OS (service account + domain-wide delegation)
- **Local only** for now

## Project Structure

```
chatty/
├── CLAUDE.md
├── .gitignore
├── .env.example
│
├── backend/
│   ├── main.py                        # FastAPI entry point
│   ├── requirements.txt
│   │
│   ├── core/
│   │   ├── config.py                  # Settings (JWT, auth, Google creds, CORS)
│   │   ├── auth.py                    # Password login + JWT + get_current_user
│   │   ├── storage.py                 # GCS adapter (from CAKE OS, no-ops locally)
│   │   ├── gmail_client.py            # Gmail service (from CAKE OS)
│   │   ├── calendar_client.py         # Calendar service (from CAKE OS)
│   │   │
│   │   ├── providers/                 # Multi-provider AI abstraction
│   │   │   ├── __init__.py            # get_ai_provider() factory
│   │   │   ├── base.py               # AIProvider ABC
│   │   │   ├── anthropic_provider.py  # Claude (streaming + tool_use)
│   │   │   ├── openai_provider.py     # OpenAI (streaming + function calling)
│   │   │   ├── google_provider.py     # Gemini (streaming + function calling)
│   │   │   ├── credentials.py        # Auth profile store + token refresh
│   │   │   └── oauth.py              # PKCE OAuth flow (OpenAI + Google)
│   │   │
│   │   └── agents/
│   │       ├── config.py              # AgentConfig dataclass
│   │       ├── ai_service.py          # Streaming orchestrator (provider-agnostic)
│   │       ├── tool_registry.py       # Tool dispatch
│   │       ├── context_manager.py     # Markdown context file manager (from CAKE OS)
│   │       ├── tool_definitions.py    # Context + Gmail + Calendar tool defs
│   │       ├── router_factory.py      # Shared router factory (from CAKE OS)
│   │       ├── chat_history/
│   │       │   ├── db.py              # SQLite + WAL (from CAKE OS)
│   │       │   └── service.py         # CRUD + search (from CAKE OS)
│   │       └── tools/
│   │           ├── context_tools.py   # Context file CRUD (from CAKE OS)
│   │           ├── gmail_tools.py     # Gmail search/read (from CAKE OS)
│   │           └── calendar_tools.py  # Calendar list/search/get (from CAKE OS)
│   │
│   ├── agents/                        # Multi-agent management
│   │   ├── db.py                      # SQLite agent registry (from CAKE OS personal_agent/db.py)
│   │   ├── engine.py                 # Agent factory: create, cache, load (from CAKE OS personal_agent/engine.py)
│   │   ├── router.py                 # Agent CRUD endpoints + per-agent chat routing
│   │   └── onboarding.py            # Default onboarding prompt (customizable per agent)
│   │
│   ├── branding/                      # Optional platform branding
│   │   ├── router.py                 # Upload logo, set company name
│   │   └── storage.py               # Save branding assets to data/branding/
│   │
│   ├── integrations/                  # Toggleable integration modules
│   │   ├── __init__.py
│   │   ├── registry.py               # Integration registry: available integrations + status
│   │   ├── quickbooks/
│   │   │   ├── client.py             # QBO OAuth2 client, token refresh
│   │   │   ├── tools.py              # QBO tool definitions (reports, invoices, etc.)
│   │   │   └── onboarding.py         # Setup flow: OAuth2 connection, company selection
│   │   ├── odoo/
│   │   │   ├── client.py             # Odoo XML-RPC/JSON-RPC client (from CAKE OS)
│   │   │   ├── tools.py              # Odoo tool definitions (from CAKE OS)
│   │   │   └── onboarding.py         # Setup flow: URL, database, API key
│   │   ├── bamboohr/
│   │   │   ├── client.py             # BambooHR API client (from CAKE OS Alex)
│   │   │   ├── tools.py              # BambooHR tool definitions (from CAKE OS Alex)
│   │   │   └── onboarding.py         # Setup flow: subdomain, API key
│   │   └── whatsapp/
│   │       └── connector.py          # Stub for future phase
│   │
│   └── data/                          # All runtime data (gitignored)
│       ├── agents/                    # Per-agent dirs: agents/{slug}/context/*.md, chat.db
│       ├── auth-profiles.json         # Provider credentials
│       ├── agents.db                  # Agent registry SQLite
│       └── branding/                  # Logo, company name config
│
└── frontend/
    ├── package.json
    ├── vite.config.ts
    ├── index.html
    └── src/
        ├── main.tsx
        ├── App.tsx                    # Login → Dashboard → Agent
        ├── index.css                  # Tailwind + customizable brand colors
        ├── core/
        │   ├── api/client.ts          # Fetch wrapper with JWT (from CAKE OS)
        │   ├── auth/
        │   │   ├── AuthContext.tsx     # Password auth (from CAKE OS, adapted)
        │   │   └── ProtectedRoute.tsx # Route guard (from CAKE OS)
        │   └── types.ts
        ├── dashboard/                 # Agent management home screen
        │   ├── DashboardPage.tsx      # Grid of agent cards + "New Agent" button
        │   ├── AgentCard.tsx          # Card: avatar, name, last active, enter/delete
        │   ├── CreateAgentModal.tsx   # Name your agent → start onboarding
        │   ├── SettingsPanel.tsx      # Provider setup, integrations, branding, preferences
        │   └── IntegrationsTab.tsx    # Enable/disable Odoo, QuickBooks with setup flows
        ├── setup/                     # AI provider selection
        │   ├── ProviderSetup.tsx      # Provider cards (OAuth or API key entry)
        │   ├── OAuthConnect.tsx       # OAuth button → opens browser → polls completion (OpenAI, Google)
        │   ├── ApiKeyEntry.tsx        # API key paste + validate (Anthropic)
        │   └── ModelSelector.tsx      # Model dropdown after auth
        └── agent/                     # Full CAKE OS agent UI
            ├── AgentPage.tsx          # Chat + Knowledge tabs (from CAKE OS, no voice)
            ├── types.ts
            ├── hooks/
            │   ├── useAgentChat.ts    # SSE streaming (from CAKE OS)
            │   └── useConversations.ts
            └── components/            # All from CAKE OS shared/agent/
                ├── AgentChatPanel.tsx
                ├── AgentMessageBubble.tsx
                ├── AgentContextEditor.tsx
                ├── ConversationSidebar.tsx
                └── LoginPage.tsx
```

## Multi-Agent Architecture

### How It Works (mirrors CAKE OS personal agent pattern)

Each agent is an isolated instance with its own:
- **Context files** (knowledge) — `data/agents/{slug}/*.md`
- **Chat history** — `data/agents/{slug}/chat.db`
- **Onboarding progress** — tracked in context files
- **Personality** — stored in `soul.md` during onboarding
- **Avatar** — optional, stored in agent data dir

All agents share:
- **AI provider credentials** — global (from `data/auth-profiles.json`)
- **Core engine** — same ai_service, tool_registry, context_manager
- **Gmail/Calendar tools** — same service account, same tools
- **Branding** — platform-level logo/company name

### Agent Registry (SQLite — `data/agents.db`)
```sql
CREATE TABLE agents (
    id TEXT PRIMARY KEY,           -- UUID
    slug TEXT UNIQUE NOT NULL,     -- filesystem-safe name
    agent_name TEXT DEFAULT '',    -- display name (set during onboarding)
    avatar_url TEXT DEFAULT '',
    personality TEXT DEFAULT '',
    onboarding_complete INTEGER DEFAULT 0,
    provider TEXT DEFAULT '',      -- override global provider (optional)
    model TEXT DEFAULT '',         -- override global model (optional)
    gmail_enabled INTEGER DEFAULT 0,
    calendar_enabled INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);
```

### Agent Factory (from CAKE OS `personal_agent/engine.py`)
```python
def get_or_create_agent(agent_id: str) -> CachedAgent:
    """Load agent from registry, build config/registry/context_manager, cache with LRU."""
    # 1. Look up in agents.db
    # 2. Build AgentConfig with agent's personality, instructions
    # 3. Build ToolRegistry (context tools + optionally Gmail/Calendar)
    # 4. Build ContextManager pointing to data/agents/{slug}/
    # 5. Init chat history DB at data/agents/{slug}/chat.db
    # 6. Cache and return
```

### Dashboard → Agent Flow
1. Login → Dashboard shows grid of agent cards
2. Click agent card → `/agent/{id}` → full AgentPage (Chat, Knowledge)
3. "New Agent" button → modal: enter a name → creates agent row → redirects to agent page in onboarding/training mode
4. Settings gear → provider setup, branding upload, preferences

## Onboarding & Training (mirrors CAKE OS personal agent exactly)

The onboarding system is copied directly from the CAKE OS personal agent pattern:

**Training mode** — agent enters a structured conversation to learn about the user and their business. Works through topics one at a time, saves answers to context files.

**How it works** (from CAKE OS `personal_agent/onboarding.py`):
1. Agent reads existing context files to avoid re-asking
2. Checks `_onboarding-progress.md` to resume if partial
3. Works through topics, asking 1-2 questions at a time
4. Summarizes answers back to user, saves to context files
5. Training mode forces "power" tool mode so agent can freely read/write context

**Default onboarding topics** (user can customize per agent):
- **Your Personality** → saves to `soul.md` — agent name, how to address user, tone, communication style
- **About You** → saves to `user-profile.md` — role, background, what you do
- **Your Business** → saves to `business-overview.md` — company, industry, products, what makes it special
- **Daily Workflow** → saves to `workflow.md` — routines, tools, processes
- **Pain Points** → appends to `workflow.md` — bottlenecks, what's frustrating
- **How I Can Help** → appends to `workflow.md` — priorities for the agent
- **Communication Preferences** → appends to `soul.md` — preferred style, response length, formality

**Context files created during onboarding**:
- `soul.md` — Agent personality and identity (always loaded first into system prompt)
- `user-profile.md` — Who the user is
- `business-overview.md` — Business details
- `workflow.md` — Daily operations, pain points, how agent helps
- `_onboarding-progress.md` — Tracks which topics are complete

These context files are the agent's long-term knowledge — loaded into the system prompt on every chat. The ContextManager from CAKE OS handles loading, saving, and enforcing the 200k character limit.

**Chunked training saves** (from CAKE OS commit `ee588b6`):
Training mode instructions tell the agent to save incrementally in small chunks via `append_to_context_file` rather than one giant `write_context_file` at the end. This prevents data loss if a session is interrupted and gives better UX (user sees progress as files grow). The training instructions in `ai_service.py` include:
> "When saving to context files, save incrementally in small chunks. Use append_to_context_file to add sections as you learn them, rather than one giant write_context_file at the end."

**Expandable tool call details** (same commit):
Tool pills in chat messages are clickable — expand to show input args, result preview, and execution duration. Live elapsed timer on running tools turns red after 30s to flag stuck tools. Backend SSE events enriched with `tool_use_id`, `args`, `result` preview, and `duration_ms`. This requires:
- `ai_service.py`: New `tool_args` SSE event after input is parsed, enriched `tool_end` event with result preview + duration
- `types.ts`: `ToolCallInfo` expanded with `toolUseId`, `args`, `description`, `result`, `startedAt`, `durationMs`
- `useAgentChat.ts`: Handle `tool_args` event, match tool events by `toolUseId`
- `AgentMessageBubble.tsx`: New `ToolCallBubble` component with expand/collapse, elapsed timer, args/result display

These changes are on the CAKE OS `feature/ai-tool-call-details` branch (commit `ee588b6`). We'll pull from that branch when copying the agent engine and frontend components.

## Weekend CAKE OS Improvements to Include

The following features were committed to CAKE OS over March 21-23, 2026. All should be incorporated when copying code:

### Must-have (directly affect agent UX)

1. **Floating Claude-style chat input** (`a8d4eea`) — Pill-shaped input hovering above messages with shadow, gradient fade, icon send/stop buttons. Replaces docked border-t bar. File: `AgentChatPanel.tsx`.

2. **Collapsible chat sidebar** (`2b3c1c5`) — Sidebar starts collapsed on mobile (< 640px), opens as overlay with backdrop. Toggle button when collapsed. Auto-closes on conversation select (mobile). Files: `AgentPage.tsx`, `ConversationSidebar.tsx`.

3. **Editable chat titles + AI smart titles** (`0f491d6`) — After 3rd user message, generates descriptive title via Claude Haiku. User can rename via pencil icon / double-click. `title_update` SSE event updates sidebar in real-time. DB migration adds `title_edited_by_user` column. Files: `ai_service.py`, `chat_history/db.py`, `chat_history/service.py`, `router_factory.py`, `AgentPage.tsx`, `ConversationSidebar.tsx`, `useAgentChat.ts`, `useConversations.ts`.

4. **Knowledge auto-update system** (`5bf748c`) — Shared Knowledge Management Protocol with explicit rules forbidding narrating saves without tool calls. `[KNOWLEDGE CHECKPOINT]` injected every 4th user message to nudge saves. Soul.md prioritized first in system prompt. Files: `ai_service.py`, `context_manager.py`, `config.py`.

5. **Soul.md identity framework** (`1673ae5`) — Richer identity documents with core truths, boundaries, vibe, and continuity guidance. Config instructions tell agent to read soul.md at session start. We'll use this as the template for onboarding's personality topic.

6. **Background note-saving** (`094f6b6`) — Context file writes upload only the changed file (not all files) in a background thread so SSE stream isn't blocked. Also fixes delete sync to GCS. Files: `ai_service.py`, `router_factory.py`.

7. **Auto-start onboarding** (`58d517c`) — After naming agent, onboarding interview starts immediately without button clicks. Auto-advances to avatar picker when all topics complete. Files: `AgentPage.tsx`, `OnboardingFlow.tsx`.

### Include structure, adapt for our platform

8. **Granular tool access controls** (`4311ca7`) — Per-agent toggle switches for tool groups (Gmail, Calendar, etc.). We'll adapt this: instead of admin-managed, the user controls their own agents' tool access from the dashboard settings. Files: `personal_agent/db.py`, `personal_agent/engine.py`, `tools/tool_groups.py`.

### Reference for future phases

9. **WhatsApp + Telegram channels** (`e9dab32`) — Unified messaging app with webhook endpoints, admin-managed user mappings, per-agent channel toggles. Extracts shared agent loader (`core/agents/loader.py`). We should include the `loader.py` extraction now and reference this for the WhatsApp connector phase. Files: `apps/messaging/*`, `core/agents/loader.py`.

## Toggleable Integrations (Odoo + QuickBooks)

Integrations are optional modules that can be turned on/off in Settings. When enabled, each triggers its own onboarding flow to collect credentials and configure the connection.

### Integration Registry (`integrations/registry.py`)
```python
INTEGRATIONS = {
    "quickbooks": {
        "name": "QuickBooks Online",
        "description": "Accounting, invoicing, expense tracking",
        "onboarding_fields": ["oauth2"],
        "tools_module": "integrations.quickbooks.tools",
    },
    "odoo": {
        "name": "Odoo ERP",
        "description": "CRM, inventory, manufacturing, helpdesk",
        "onboarding_fields": ["url", "database", "api_key"],
        "tools_module": "integrations.odoo.tools",
    },
    "bamboohr": {
        "name": "BambooHR",
        "description": "HR, employee directory, PTO, payroll",
        "onboarding_fields": ["subdomain", "api_key"],
        "tools_module": "integrations.bamboohr.tools",
    },
}
```

### Integration Onboarding Flow
1. User goes to Settings → Integrations tab
2. Sees cards for QuickBooks and Odoo (disabled by default)
3. Clicks "Enable" on one → opens integration-specific setup:
   - **QuickBooks**: OAuth2 flow — browser opens Intuit login → callback captures tokens → stores in `data/integrations/quickbooks.json`
   - **Odoo**: Form entry — Odoo URL, database name, API key/username → validates connection → stores in `data/integrations/odoo.json`
   - **BambooHR**: Form entry — company subdomain, API key → validates with test API call → stores in `data/integrations/bamboohr.json`
4. Once connected, integration's tools become available to all agents (or per-agent via tool access controls)
5. Integration can be disabled (tools removed from agents) without deleting credentials

### Integration Credential Storage (`data/integrations/`)
```
data/integrations/
├── quickbooks.json    # {client_id, client_secret, access_token, refresh_token, realm_id, ...}
└── odoo.json          # {url, database, username, api_key, ...}
```

### Odoo Tools (from CAKE OS)
Copy the proven Odoo integration from CAKE OS:
- `core/odoo.py` → Odoo XML-RPC client (from CAKE OS `backend/core/odoo.py`)
- Odoo tool definitions from CAKE OS agents (search, read, write, custom tools)
- The custom Odoo tool system (declarative markdown tools) is available but optional

### QuickBooks Tools
Build using the patterns from the original Elodie CLAUDE.md brainstorm:
- Reports (P&L, Balance Sheet, Cash Flow, AR/AP Aging)
- Invoices, bills, payments, vendors, customers
- Journal entries, chart of accounts
- Preview-confirm pattern for all write operations

### BambooHR Tools (from CAKE OS Alex)
Copy the proven BambooHR integration from CAKE OS's Alex agent:
- Employee directory, contact info, org chart
- PTO balances, time-off requests, who's out today
- Payroll analysis, compensation data
- Source: CAKE OS `backend/apps/alex/` (Alex is the HR agent)

## Optional Branding

User can customize the platform appearance:
- **Logo**: Upload image → stored in `data/branding/logo.png` → served at `/api/branding/logo`
- **Company name**: Stored in `data/branding/config.json` → shown in header, login page
- **Accent color**: Optional hex color → applied via CSS variable

Backend serves branding assets. Frontend reads branding config on load and applies it. If no branding set, shows a clean default look.

## Multi-Provider AI (unchanged from previous plan)

### Provider Auth Per Type
| Provider | Auth | Flow |
|----------|------|------|
| **OpenAI** | OAuth (PKCE) | Browser opens → login to ChatGPT → localhost callback captures token |
| **Google Gemini** | OAuth (PKCE) | Browser opens → login to Google → localhost callback captures token |
| **Anthropic** | API key entry | User creates key at platform.claude.com → pastes into app (Anthropic bans OAuth tokens in third-party apps per ToS) |

### Credential Store (`data/auth-profiles.json`)
```json
{
    "active_provider": "openai",
    "active_model": "gpt-4o",
    "profiles": {
        "anthropic:default": { "type": "api_key", "key": "sk-ant-api03-..." },
        "openai:default": { "type": "oauth", "access": "...", "refresh": "...", "expires": 1704067200000 },
        "google:default": { "type": "oauth", "access": "...", "refresh": "...", "expires": 1704067200000, "projectId": "..." }
    }
}
```

Individual agents can optionally override the global provider/model.

## What Gets Copied from CAKE OS

### Copy verbatim (update imports only)
| Source (CAKE OS) | Target |
|---|---|
| `backend/core/agents/context_manager.py` | `core/agents/context_manager.py` |
| `backend/core/agents/tools/context_tools.py` | `core/agents/tools/context_tools.py` |
| `backend/core/agents/chat_history/db.py` | `core/agents/chat_history/db.py` |
| `backend/core/agents/chat_history/service.py` | `core/agents/chat_history/service.py` |
| `backend/core/storage.py` | `core/storage.py` |
| `backend/core/gmail_client.py` | `core/gmail_client.py` |
| `worktree/.../core/calendar_client.py` | `core/calendar_client.py` |
| `backend/apps/jordan/tools/gmail_tools.py` | `core/agents/tools/gmail_tools.py` |
| `worktree/.../personal_agent/tools/calendar_tools.py` | `core/agents/tools/calendar_tools.py` |
| Frontend `shared/agent/*` | `src/agent/*` (AgentPage: Chat + Knowledge tabs, remove voice tab) |
| Frontend `core/api/client.ts` | `src/core/api/client.ts` |
| Frontend `core/auth/*` | `src/core/auth/*` |

### Adapt significantly
| File | Changes |
|---|---|
| `core/agents/ai_service.py` | Provider-agnostic (AIProvider ABC). Remove Odoo/DIMM/reports. Keep streaming, tool loop, confirmation, training |
| `core/agents/tool_registry.py` | Remove Odoo/DIMM kinds. Keep context, chat_history, gmail, calendar. Add integration kind |
| `core/agents/router_factory.py` | Remove Odoo, remove voice endpoints. Provider from credentials. Keep training, context, conversations |
| `core/agents/config.py` | Provider-agnostic. No hardcoded model |
| `core/config.py` | JWT, auth password, Google service account, Gmail, CORS. No Odoo/BambooHR/etc. |
| CAKE OS `personal_agent/engine.py` | Adapt as `agents/engine.py` — agent factory, same LRU cache pattern |
| CAKE OS `personal_agent/db.py` | Adapt as `agents/db.py` — agent registry table |
| CAKE OS `personal_agent/onboarding.py` | Adapt as `agents/onboarding.py` — generic onboarding (not TNC-specific) |

### Write from scratch
| File | Purpose |
|---|---|
| `core/providers/*` | Multi-provider layer (ABC, 3 providers, credentials, OAuth) |
| `agents/router.py` | Agent CRUD: list, create, delete, get. Per-agent chat routing |
| `branding/router.py` | Upload logo, set company name/color |
| `branding/storage.py` | Save/load branding from `data/branding/` |
| `frontend/src/dashboard/*` | Dashboard page, agent cards, create modal, settings |
| `frontend/src/setup/*` | Provider setup (OAuth + token entry) |
| `CLAUDE.md` | Project instructions |

## Build Order

### Step 1: Repository setup
- `git init`, `.gitignore`, `CLAUDE.md`, `.env.example`
- Create GitHub repo (`WWilson1017/personal-ai-agent`)

### Step 2: Backend core — config, auth, Google clients
- `core/config.py`, `core/auth.py`, `core/storage.py`
- Auth: Password login (single user) with JWT. Rough in the multi-user path (user accounts table, Google OAuth settings in config) but don't activate — keep it behind a `MULTI_USER_ENABLED=false` flag for Phase 2
- `core/gmail_client.py`, `core/calendar_client.py` (from CAKE OS)
- `requirements.txt`

### Step 3: Backend core — provider abstraction
- `core/providers/base.py` (AIProvider ABC)
- `core/providers/anthropic_provider.py`, `openai_provider.py`, `google_provider.py`
- `core/providers/credentials.py` (auth profile store + refresh)
- `core/providers/oauth.py` (PKCE flow for OpenAI + Google)
- `core/providers/__init__.py` (factory)

### Step 4: Backend core — agent engine
- `core/agents/config.py`, `context_manager.py`, `tool_definitions.py`
- `core/agents/tools/` (context, gmail, calendar — from CAKE OS)
- `core/agents/tool_registry.py`, `chat_history/`, `ai_service.py`, `router_factory.py`

### Step 5: Backend — multi-agent management
- `agents/db.py` — SQLite agent registry (adapted from CAKE OS personal_agent/db.py)
- `agents/engine.py` — Agent factory with LRU cache (adapted from CAKE OS)
- `agents/onboarding.py` — Generic onboarding prompt
- `agents/router.py` — CRUD: `GET /api/agents`, `POST /api/agents`, `DELETE /api/agents/{id}`, plus per-agent chat/context/conversations mounted at `/api/agents/{id}/...`

### Step 6: Backend — branding
- `branding/router.py` — `POST /api/branding/logo`, `PUT /api/branding/config`, `GET /api/branding`
- `branding/storage.py` — Save/load from `data/branding/`

### Step 7: Backend — main.py
- Mount: auth, provider, agents, branding routers
- Health check, CORS, lifespan (init dirs, init agent DB)
- Static file serving for production

### Step 8: Backend — integrations
- `integrations/registry.py` — Integration registry: available integrations, status, enable/disable
- `integrations/quickbooks/client.py` — QBO OAuth2 client (connect, refresh, query)
- `integrations/quickbooks/tools.py` — Tool definitions for reports, invoices, bills, etc.
- `integrations/quickbooks/onboarding.py` — OAuth2 setup flow endpoints
- `integrations/odoo/client.py` — Odoo XML-RPC client (adapted from CAKE OS `core/odoo.py`)
- `integrations/odoo/tools.py` — Odoo tool definitions (adapted from CAKE OS)
- `integrations/odoo/onboarding.py` — Setup flow: URL, database, API key validation
- `integrations/bamboohr/client.py` — BambooHR API client (adapted from CAKE OS Alex)
- `integrations/bamboohr/tools.py` — BambooHR tool definitions (adapted from CAKE OS Alex)
- `integrations/bamboohr/onboarding.py` — Setup flow: subdomain, API key validation
- `integrations/whatsapp/connector.py` — Stub for future phase
- API endpoints: `GET /api/integrations`, `POST /api/integrations/{name}/enable`, `POST /api/integrations/{name}/setup`, `POST /api/integrations/{name}/disable`

### Step 9: Frontend scaffold
- Vite + React + TypeScript + Tailwind
- Proxy `/api` → `localhost:8000`

### Step 10: Frontend core
- `index.css` — Tailwind + CSS variables for brand customization
- `core/api/client.ts`, `core/auth/*` (from CAKE OS)

### Step 11: Frontend — dashboard
- `dashboard/DashboardPage.tsx` — Agent grid + "New Agent" + settings gear
- `dashboard/AgentCard.tsx` — Avatar, name, last active, enter button
- `dashboard/CreateAgentModal.tsx` — Name input → creates agent → redirects to onboarding
- `dashboard/SettingsPanel.tsx` — Provider setup, branding upload

### Step 12: Frontend — provider setup
- `setup/ProviderSetup.tsx`, `OAuthConnect.tsx` (OpenAI/Google), `ApiKeyEntry.tsx` (Anthropic), `ModelSelector.tsx`

### Step 13: Frontend — agent UI (match CAKE OS, no voice)
- Copy `shared/agent/` from CAKE OS, remove voice tab and voice-related hooks/components
- Keep: Chat tab, Knowledge tab, training mode, tool modes, conversation sidebar
- All hooks: `useAgentChat.ts`, `useConversations.ts`
- All components: ChatPanel, MessageBubble, ContextEditor, ConversationSidebar

### Step 14: App shell
- `App.tsx` — Routes: `/login`, `/` (dashboard), `/agent/:id` (agent page)
- Redirect: no auth → login, no provider → settings, otherwise → dashboard

## Verification (Local)

1. `cd backend && pip install -r requirements.txt && cp .env.example .env`
2. `uvicorn main:app --reload --port 8000`
3. `cd frontend && npm install && npm run dev`
4. Login with password → redirected to dashboard (empty, no agents yet)
5. Settings → connect AI provider (e.g., OpenAI OAuth) → success
6. "New Agent" → name it → enters onboarding mode
7. Complete 1-2 onboarding topics → context files saved
8. Chat with agent → SSE streaming works
9. Knowledge tab → view/edit context files
10. Back to dashboard → agent card shows
11. Create a second agent → verify isolation (separate context, chat history)
12. Settings → upload logo, set company name → branding appears in header/login
13. Settings → Integrations → enable Odoo or QuickBooks → setup flow collects credentials → tools appear in agent
