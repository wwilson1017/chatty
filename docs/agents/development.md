# Development

Local setup, the CLI test harness and Railway diagnostics. Moved verbatim from the root `AGENTS.md`.

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
