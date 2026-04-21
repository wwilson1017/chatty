# Deploying Chatty on Railway

This guide walks you through deploying your own Chatty instance on [Railway](https://railway.com). Total setup time: about 5 minutes. Cost: ~$5-6/month.

## Prerequisites

- A [Railway](https://railway.com) account (Hobby tier, $5/month — includes $5 usage credit)
- An AI provider API key (at least one of):
  - **Anthropic** — Create at [console.anthropic.com](https://console.anthropic.com)
  - **OpenAI** — Create at [platform.openai.com](https://platform.openai.com)
  - **Google AI (Gemini)** — Create at [aistudio.google.com](https://aistudio.google.com)

## One-Click Deploy

1. Click the deploy button in the [README](README.md) or go to your Railway template URL
2. Set **`AUTH_PASSWORD`** — this is your login password (the only required field)
3. Click **Deploy**

Railway will:
- Build the Docker image (~3 minutes)
- Start the container
- Run the health check at `/api/health`
- Give you a public URL like `https://chatty-production-xxxx.up.railway.app`

## After Deploying

1. Open your Chatty URL in a browser
2. Log in with the password you set
3. The setup wizard will ask you to connect an AI provider — paste your API key
4. Create your first agent and start chatting

## Environment Variables

### Required

| Variable | Description |
|----------|-------------|
| `AUTH_PASSWORD` | Your login password |

### Auto-Generated (optional override)

These auto-generate if not set. You can override them for extra control:

| Variable | Description |
|----------|-------------|
| `JWT_SECRET` | Secret key for session tokens. Auto-generates on each deploy if not set, which means you'll need to log in again after each deploy. Set this for persistent sessions. Generate with: `python3 -c "import secrets; print(secrets.token_hex(32))"` |
| `ENCRYPTION_KEY` | Fernet key for encrypting stored credentials (API keys, OAuth tokens). Auto-generates and saves to the persistent volume. Set this env var as a backup in case your volume is ever lost. Generate with: `python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |

### Optional Integrations

| Variable | Description |
|----------|-------------|
| `GOOGLE_CLIENT_ID` | Google OAuth client ID (for Gmail + Calendar + Drive). Defaults to the Chatty-owned OAuth app provided by the Railway template. |
| `GOOGLE_CLIENT_SECRET` | Google OAuth client secret (paired with `GOOGLE_CLIENT_ID`) |
| `OAUTH_REDIRECT_URI` | Override the OAuth callback URL. Auto-computed from `BACKEND_URL` + `/api/oauth/callback` — only set this if you have an unusual networking setup. |
| `QUICKBOOKS_CLIENT_ID` | QuickBooks OAuth client ID |
| `QUICKBOOKS_CLIENT_SECRET` | QuickBooks OAuth client secret |
| `WHATSAPP_BRIDGE_URL` | WhatsApp Baileys bridge URL (advanced) |
| `WHATSAPP_BRIDGE_API_KEY` | WhatsApp bridge API key |
| `WEBBY_GITHUB_TOKEN` | GitHub token for Webby website builder |
| `WEBBY_GITHUB_REPO` | GitHub repo for Webby (e.g. `user/repo`) |

## Google integration (Gmail + Calendar + Drive)

Chatty agents can read, send, and draft emails; create and edit calendar events;
and list, read, and upload files in Google Drive. Access is OAuth-based — you
authorize Chatty once from **Dashboard → Integrations → Google** and pick exactly
which scopes (read vs send, read-only vs full Drive access, etc.) you want to
grant.

You need a Google OAuth client (a **client ID** and **client secret** pair) for
this to work. There are two paths:

### Path 1: Use the bundled Chatty OAuth client (default, easiest)

The Railway template ships with `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`
pre-populated, pointing at a Chatty-owned Google Cloud OAuth app. If you deployed
via the "Deploy on Railway" button in the README, you already have this — you
can go straight to **Dashboard → Integrations → Google** and connect.

The bundled app is subject to Google's verification limits for sensitive scopes
(Gmail, Drive). Early adopters will see a warning screen; the Chatty maintainers
submit the app for verification as user count grows.

### Path 2: Bring your own Google Cloud OAuth client (recommended for production)

If you want full control, your own verification status, or a separate app for
your organization, create your own Google Cloud project:

1. Go to [console.cloud.google.com](https://console.cloud.google.com) → create a project
2. **APIs & Services → Library** → enable **Gmail API**, **Google Calendar API**, and **Google Drive API**
3. **OAuth consent screen** → choose *External* → fill in app name, support email, and developer contact
4. Add these scopes (only add what you plan to actually use):
   - `openid`, `email`, `profile`
   - `https://www.googleapis.com/auth/gmail.readonly`
   - `https://www.googleapis.com/auth/gmail.send`
   - `https://www.googleapis.com/auth/gmail.compose`
   - `https://www.googleapis.com/auth/calendar.readonly`
   - `https://www.googleapis.com/auth/calendar`
   - `https://www.googleapis.com/auth/drive.file`
   - `https://www.googleapis.com/auth/drive.readonly`
   - `https://www.googleapis.com/auth/drive`
5. **Credentials → Create Credentials → OAuth client ID** → *Web application*
6. Under **Authorized redirect URIs**, add:
   - `http://localhost:8000/api/oauth/callback` (for local dev)
   - `https://<your-railway-domain>/api/oauth/callback` (for your deployed Chatty)
   - If you use a custom domain, add that too
7. Copy the **Client ID** and **Client secret**
8. In Railway, set the `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` env vars to the new values
9. Trigger a redeploy so the new values take effect
10. Open Chatty → **Dashboard → Integrations → Google** → pick your scopes → click **Connect Google**

**Sensitive-scope verification:** Gmail and Drive scopes are "sensitive" or
"restricted" in Google's classification. Unverified apps can serve up to 100
test users; for more than that, submit your OAuth app for Google's verification
review (takes a few days to a few weeks).

### Server Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `CORS_ORIGINS` | Auto-detected | Additional CORS origins (comma-separated). Railway domain is added automatically. |
| `FRONTEND_URL` | Auto-detected | Override the public URL. Auto-detected from Railway. |
| `BACKEND_URL` | Auto-detected | Override the backend URL. Auto-detected from Railway. |

## Persistent Storage

Chatty uses SQLite for all data storage. On Railway, a **persistent volume** is automatically mounted at `/app/backend/data` so your data survives redeploys and updates. This volume stores:

- Agent databases (chat history, conversations)
- Agent knowledge files (context documents)
- AI provider credentials (encrypted)
- Branding assets (logo, colors)
- Integration data (CRM, reminders)
- Memory, dreaming, and shared context data

The volume is completely separate from the application code. When Chatty is updated, only the code changes — your data stays exactly as it is.

### Volume Pricing

Railway charges $0.15/GB/month for volume storage. A typical single-user Chatty instance uses well under 1 GB.

### Backups

Chatty has built-in backup and restore. The easiest way is through the Chatty UI:

1. Log in to your Chatty instance
2. Go to **Settings** (gear icon) > **Data** tab
3. Click **Download Backup** to save a ZIP of all your data
4. Use **Restore Backup** to upload a previously downloaded ZIP

These use the `/api/backup/download` and `/api/backup/restore` API endpoints under the hood (both require authentication).

## Custom Domain

1. In Railway dashboard, go to your service > **Settings** > **Networking**
2. Click **Add Custom Domain**
3. Add the CNAME records Railway provides to your DNS
4. Railway auto-provisions HTTPS (LetsEncrypt) — usually within an hour

## Updating

### Automatic updates (default)

When you deploy Chatty from the template, Railway keeps a connection to the upstream Chatty repo. When we release updates:

1. You'll see a notification in your Railway project dashboard
2. Click to apply — Railway creates a pull request with the changes
3. Merge the pull request
4. Railway automatically rebuilds and redeploys

Your data is safe — updates only change the application code. Your agents, chat history, API keys, and branding are stored on the persistent volume and are never touched by code updates.

### Manual updates (ejected users)

If you've clicked "Eject" in your service settings (which creates a separate copy of the repo), you won't receive automatic update notifications. To update manually:

```bash
git remote add upstream https://github.com/WWilson1017/chatty.git
git pull upstream master
git push origin master
```

### Factory reset

To completely reset your Chatty instance to a fresh state (as if you just deployed for the first time):

1. Go to your Railway project and click on **chatty-volume**
2. Scroll down and click **Wipe Volume**
3. Confirm the wipe — Railway will redeploy automatically
4. The setup wizard will appear on next login as if it's a fresh install

This deletes all agents, chat history, and saved credentials. Your `AUTH_PASSWORD` is preserved since it's an environment variable.

## Cost Breakdown

| Item | Cost |
|------|------|
| Railway Hobby plan | $5/month (includes $5 usage credit) |
| Volume storage (1 GB) | ~$0.15/month |
| **Total** | **~$5.15/month** |

A single-user Chatty instance with light usage typically stays well within the included $5 credit, so your effective cost is just the subscription + volume storage.

## Troubleshooting

### Health check failing

Check the Railway logs (service > Logs tab). Common causes:
- Missing `AUTH_PASSWORD` env var
- Docker build failure (check build logs)
- Port binding issue (Chatty uses the `PORT` env var that Railway injects automatically)

### Data not persisting after redeploy

Make sure you have a persistent volume mounted at `/app/backend/data`. Check Railway logs for:
- `"Persistent volume verified"` — volume is working
- `"First boot — wrote volume marker"` — if this appears on every deploy, the volume isn't configured

### Sessions reset after redeploy

Set the `JWT_SECRET` env var to a fixed value. Without it, a new secret is generated on each deploy, which invalidates all existing sessions.

### Encrypted credentials lost

If you see errors about decryption after a volume change, you may need to re-enter your API keys. To prevent this, set the `ENCRYPTION_KEY` env var so the encryption key is stable regardless of volume state.

### Build takes too long

The first build takes 3-4 minutes (downloading dependencies). Subsequent builds use Docker layer caching and are faster.

## Architecture

Chatty runs as a single service on Railway:
- **Backend**: Python FastAPI (Gunicorn + Uvicorn)
- **Frontend**: React SPA, pre-built and served by FastAPI as static files
- **Database**: SQLite with WAL mode on persistent volume
- **Scheduler**: APScheduler for reminders and scheduled actions (runs in-process)

No external database, Redis, or additional services are required.
