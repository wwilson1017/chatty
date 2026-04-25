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
| `GOOGLE_CLIENT_ID` | Google OAuth client ID (for Gmail + Calendar + Drive). Required if you want to use any Google integration — you must create your own OAuth client. See [Google integration](#google-integration-gmail--calendar--drive) below. |
| `GOOGLE_CLIENT_SECRET` | Google OAuth client secret (paired with `GOOGLE_CLIENT_ID`) |
| `OAUTH_REDIRECT_URI` | The OAuth callback URL registered with your provider. Set this to `{your-chatty-url}/api/oauth/callback` (e.g. `https://chatty-production-xxxx.up.railway.app/api/oauth/callback`). Required for Google integrations. |
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

**Chatty does not ship with a bundled Google OAuth app.** To use Gmail, Calendar,
or Drive, you must create your own Google Cloud OAuth client and provide the
client ID and secret as environment variables. This keeps you in full control of
your data, your verification status, and your usage quotas — and means Google
sees your own app name on the consent screen instead of a third-party one.

### Create your Google Cloud OAuth client

1. Go to [console.cloud.google.com](https://console.cloud.google.com) → create a project (or select an existing one)
2. **APIs & Services → Library** → enable each API you plan to use:
   - **Gmail API** (for Gmail integration)
   - **Google Calendar API** (for Calendar integration)
   - **Google Drive API** (for Drive integration)
3. **APIs & Services → OAuth consent screen** → choose *External* → fill in app name, support email, and developer contact
4. Add the scopes you plan to use (only add what you'll actually use):
   - `openid`, `email`, `profile`
   - `https://www.googleapis.com/auth/gmail.readonly`
   - `https://www.googleapis.com/auth/gmail.send`
   - `https://www.googleapis.com/auth/gmail.compose`
   - `https://www.googleapis.com/auth/calendar.readonly`
   - `https://www.googleapis.com/auth/calendar`
   - `https://www.googleapis.com/auth/drive.file`
   - `https://www.googleapis.com/auth/drive.readonly`
   - `https://www.googleapis.com/auth/drive`
5. **APIs & Services → Credentials → Create Credentials → OAuth client ID** → choose *Web application*
6. Under **Authorized redirect URIs**, add your Chatty instance's callback URL:
   - **Railway:** `https://your-chatty-url.up.railway.app/api/oauth/callback`
   - **Custom domain:** `https://your-domain.com/api/oauth/callback`
   - **Local dev:** `http://localhost:8000/api/oauth/callback`
7. Click **Create** and copy the **Client ID** and **Client secret**
8. In Railway, set these three environment variables under **Variables**:
   - `GOOGLE_CLIENT_ID` — your client ID
   - `GOOGLE_CLIENT_SECRET` — your client secret
   - `OAUTH_REDIRECT_URI` — the same callback URL you registered (e.g. `https://your-chatty-url.up.railway.app/api/oauth/callback`)
9. Railway will automatically redeploy. Open Chatty → **Dashboard → Integrations → Google** → pick your scopes → click **Connect Google**.

**Sensitive-scope verification:** Gmail and Drive scopes are "sensitive" or
"restricted" in Google's classification. Unverified apps can serve up to 100
test users — fine for personal/single-user use. For wider distribution, submit
your OAuth app for Google's verification review (takes a few days to a few
weeks for sensitive scopes; restricted scopes also require a security
assessment). While unverified, you'll see a "Google hasn't verified this app"
warning when connecting — click *Advanced → Go to (your app)* to proceed.

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
