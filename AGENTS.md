# Chatty — Project Instructions

Free, open-source, single-user personal assistant with a browser UI: FastAPI backend (`backend/`), React/Vite frontend (`frontend/`), SQLite storage, deployed to Railway. Multiple agents, multi-provider AI, optional integrations. This file is the always-loaded core; detail lives in the topic docs below.

## Commands

```bash
python run.py                          # one-shot launcher: venv, deps, .env, frontend build, server
# backend/
../.venv/bin/python -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload
../.venv/bin/python -m cli             # CLI test harness, no web server needed
ruff check .
python -m pytest -x -q --tb=short
# frontend/
npm run dev                            # Vite on 5173, proxies /api to 8000
npm run build && npm run lint && npm run test
```

## Rules

- Keep deployment simple: SQLite only, never require Postgres, Redis or another external service.
- Only `AUTH_PASSWORD` is a required env var; AI provider keys are entered in-app, not via env vars.
- `ai_service.py` calls the `AIProvider` ABC, never a provider SDK directly.
- Chatty is a personal assistant first; CRM-focused features belong in CakeCRM, not here.
- Single user only (multi-user stays behind `MULTI_USER_ENABLED=false`); no voice tab.
- Todos (GTD) is a core feature in `core/todo/`, not an integration.
- A globally connected integration gives its tools to all agents; never add per-agent opt-in flags. Follow the wiring checklist in `docs/agents/integrations.md`.
- Tools that modify external data set `writes: True`.
- Any PR that adds/changes models or touches `core/providers/` or `core/agents/usage/` runs the `price-check` skill first (`.claude/skills/price-check/SKILL.md`; other agents follow its steps by hand) and ships its `pricing.py` / `PRICING.md` changes in the same PR.
- Read `docs/agents/connector-internals.md` before touching `integrations/claude_code/` or `connector/`; its trust model and invariants are load-bearing.
- Worktrees live in `.claude/worktrees/` (`git worktree add .claude/worktrees/<name> -b <branch> origin/master`). Run the backend there with the main checkout's absolute venv path (`<main clone>/.venv/bin/python`); the relative `../.venv` resolves to nothing.
- Before re-deriving a fix or pattern, `grep -ri <keyword> docs/solutions/`; write up non-trivial solves there.

## Topic docs

| When you… | Read |
|-----------|------|
| need product scope, deployment model, architecture, project layout or blueprint repos | `docs/agents/overview.md` |
| set up locally, use the CLI harness flags, or debug production on Railway | `docs/agents/development.md` |
| add or change an integration | `docs/agents/integrations.md` |
| touch memory backends or the brain server | `docs/agents/second-brain.md` |
| touch the Claude Code connector | `docs/agents/connector-internals.md` |
| touch model lists, tiers or pricing | `docs/agents/model-pricing.md` |
| investigate a bug | `docs/solutions/` (grep first) |

## Keeping docs current

New detail goes to a topic doc (add a row above if it's a new file); change this file only for core rules. `CLAUDE.md` is only the `@AGENTS.md` import; edit this file.
