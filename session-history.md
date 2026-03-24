# Chatty — Session History (March 24, 2026)

## What Was Built (Planning Only — No Code Written)

This session was entirely planning. The working directory `C:\ai\chatty` is empty and ready to build.

---

## Project Summary

**Chatty** is a generic, brandable personal AI agent platform.
- **Repo**: `C:\ai\chatty`, GitHub `WWilson1017/chatty`
- **Single user, multiple agents** — one password login, spawn/manage multiple agents from a dashboard
- **Optional branding** — upload logo + company name + accent color
- **Local-only** for Phase 1

---

## Key Decisions

| Topic | Decision |
|---|---|
| AI providers | Anthropic (API key from platform.claude.com), OpenAI (PKCE OAuth), Google Gemini (PKCE OAuth) |
| Provider auth | Anthropic bans OAuth for third-party apps — API key only. OpenAI/Google use PKCE + localhost callback like OpenClaw |
| Agent UI | Mirrors CAKE OS AgentPage exactly — Chat + Knowledge tabs, floating input, collapsible sidebar. No voice tab |
| Onboarding | Conversational onboarding per agent, saves soul.md + user-profile.md + business-overview.md + workflow.md |
| Integrations | Odoo, QuickBooks Online, BambooHR — toggleable in Settings; onboarding kicks in when enabled |
| Auth | Password login (JWT). Multi-user roughed in behind flag for Phase 2 |
| Blueprints | CAKE OS (`C:\ai\cake_os`) for agent engine + frontend; OpenClaw (`C:\ai\openclaw`) for multi-provider auth |

---

## CAKE OS Weekend Commits to Incorporate

All commits from March 21–23, 2026:

| Commit | What It Adds |
|---|---|
| `a8d4eea` | Floating Claude-style chat input (`AgentChatPanel.tsx`) |
| `2b3c1c5` | Collapsible sidebar (`AgentPage.tsx`, `ConversationSidebar.tsx`) |
| `0f491d6` | Editable + AI-generated chat titles |
| `5bf748c` | Knowledge auto-update — `[KNOWLEDGE CHECKPOINT]` every 4th message |
| `1673ae5` | Expanded soul.md identity framework |
| `094f6b6` | Background note-saving (only uploads changed file) |
| `58d517c` | Auto-start onboarding interview |
| `4311ca7` | Granular tool access controls per agent |
| `ee588b6` | Expandable tool call pills + chunked training saves (on `feature/ai-tool-call-details` branch) |

---

## Plan File

Full 14-step build plan at:
`C:\Users\Will\.claude\plans\lovely-hugging-galaxy.md`

### Build Order (Summary)

1. Repo setup + GitHub init
2. Backend config, password auth (JWT), Gmail/Calendar clients from CAKE OS
3. AI provider abstraction — `AIProvider` ABC + Anthropic/OpenAI/Gemini implementations + PKCE OAuth + credential store
4. Agent engine — adapted from CAKE OS (provider-agnostic, all weekend upgrades, no Odoo/DIMM/voice)
5. Multi-agent management — SQLite registry, LRU engine factory, CRUD router, generic onboarding
6. Branding backend (logo/name/color upload + serve)
7. `main.py`
8. Integrations — Odoo (from CAKE OS), QuickBooks (new), BambooHR (from CAKE OS), WhatsApp stub
9. Frontend scaffold — Vite + React + TypeScript + Tailwind
10. Frontend core — auth context, API client
11. Dashboard UI — agent grid, New Agent modal, Settings, Integrations tab
12. Provider setup UI — OAuth cards for OpenAI/Google, API key entry for Anthropic
13. Agent UI — full CAKE OS AgentPage + all weekend upgrades, no voice
14. App shell routing — `/login` → `/` dashboard → `/agent/:id`

---

## Memory Files

Saved at `C:\Users\Will\.claude\projects\C--ai-cocorico-personal-ai-agent\memory\`:
- `project_overview.md` — Project context and key decisions
- `reference_cake_os.md` — CAKE OS file paths and patterns
- `MEMORY.md` — Index

These persist across sessions and will be loaded automatically.
