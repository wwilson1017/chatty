# Chatty — Project Instructions

## What This Is

**Chatty** — a generic, brandable personal AI agent platform.
- Single user (password login), multiple agents
- User creates agents from a dashboard; each has name/personality/knowledge via onboarding
- Optional branding: logo, company name, accent color
- Multi-provider AI: Anthropic (API key), OpenAI (OAuth), Google Gemini (OAuth)
- Toggleable integrations: Odoo, QuickBooks Online, BambooHR
- Local-only for Phase 1

**Full plan**: `PLAN.md` in this directory — read this before starting any work.

## Blueprints

| Blueprint | Location | What to use it for |
|---|---|---|
| **CAKE OS** | `C:\ai\cake_os` | Agent engine, frontend AgentPage, Gmail/Calendar tools, onboarding |
| **OpenClaw** | `C:\ai\openclaw` | Multi-provider OAuth (PKCE flows, credential store pattern) |

## Key Architecture Rules

- **Provider-agnostic engine** — `ai_service.py` calls an `AIProvider` ABC, never Anthropic/OpenAI directly
- **Per-agent isolation** — each agent has its own context files, chat.db, and slug dir under `data/agents/{slug}/`
- **Global credentials** — provider auth lives in `data/auth-profiles.json`, shared across all agents
- **CAKE OS weekend upgrades** — all commits from March 21–23, 2026 must be incorporated (see PLAN.md for full list)
- **No voice tab** — explicitly removed from scope
- **Single user only** — multi-user roughed in behind `MULTI_USER_ENABLED=false` flag for Phase 2

## Anthropic Auth Note

Anthropic **bans OAuth tokens** in third-party apps (only allowed for claude.ai and Claude Code per ToS). Use API key entry only — user creates key at `platform.claude.com` and pastes it in. OpenAI and Google use PKCE OAuth like OpenClaw.

## Build Order (14 Steps)

1. Repo setup — `git init`, `.gitignore`, `CLAUDE.md`, `.env.example`, GitHub `WWilson1017/chatty`
2. Backend core — `config.py`, `auth.py` (password + JWT), `gmail_client.py`, `calendar_client.py`
3. Provider abstraction — `AIProvider` ABC + Anthropic/OpenAI/Gemini + PKCE OAuth + credential store
4. Agent engine — `ai_service.py`, `tool_registry.py`, `context_manager.py`, `chat_history/` (all adapted from CAKE OS)
5. Multi-agent management — `agents/db.py`, `agents/engine.py` (LRU factory), `agents/router.py`, `agents/onboarding.py`
6. Branding backend — logo/name/color upload + serve
7. `main.py`
8. Integrations — Odoo (from CAKE OS), QuickBooks (new), BambooHR (from CAKE OS Alex), WhatsApp stub
9. Frontend scaffold — Vite + React + TypeScript + Tailwind
10. Frontend core — auth context, API client
11. Dashboard UI — agent grid, New Agent modal, Settings, Integrations tab
12. Provider setup UI — OAuth cards (OpenAI/Google), API key entry (Anthropic), model selector
13. Agent UI — full CAKE OS AgentPage + all weekend upgrades, no voice
14. App shell routing — `/login` → `/` dashboard → `/agent/:id`

## Worktrees

Use `C:\ai\chatty-worktrees\` for feature branches. See global CLAUDE.md for worktree conventions.

## Key CAKE OS Files to Copy/Adapt

**Copy verbatim** (update imports only):
- `backend/core/agents/context_manager.py`
- `backend/core/agents/tools/context_tools.py`
- `backend/core/agents/chat_history/db.py` + `service.py`
- `backend/core/storage.py`, `gmail_client.py`, `calendar_client.py`
- `backend/apps/jordan/tools/gmail_tools.py`
- Frontend `shared/agent/` components (remove voice tab)
- Frontend `core/api/client.ts`, `core/auth/*`

**Adapt significantly**:
- `core/agents/ai_service.py` — make provider-agnostic, remove Odoo/DIMM/reports
- `core/agents/tool_registry.py` — remove Odoo/DIMM, add integration kind
- `apps/personal_agent/engine.py` → `agents/engine.py` — multi-agent factory
- `apps/personal_agent/onboarding.py` → `agents/onboarding.py` — generic (not TNC-specific)

**Note**: The expandable tool pills + chunked training saves are on the `feature/ai-tool-call-details` branch (commit `ee588b6`), not master. Pull from that branch for `ai_service.py` and `AgentMessageBubble.tsx`.
