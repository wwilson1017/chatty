# Connecting QuickBooks Online to Chatty

This guide walks you through connecting your QuickBooks Online account to Chatty so your AI agents can query invoices, customers, bills, and financial reports.

## How this works

Because Chatty is self-hosted, **you create your own private Intuit Developer app** and use it to authorize your own Chatty instance against your own QuickBooks company. Chatty does not have a shared, central QuickBooks app that all installations connect through — every self-hosted user is the operator of their own app.

This is a one-time setup. Once your app is created, your agents can talk to your QuickBooks data indefinitely.

You will:

1. Create a free Intuit Developer account
2. Create an app in their dashboard (this is your private app, not published anywhere)
3. Copy your Client ID, Client Secret, and Redirect URI into Chatty's `.env`
4. Click **Connect QuickBooks** in Chatty and authorize your own app

## Prerequisites

- A QuickBooks Online account (Simple Start or higher — Self-Employed plans don't expose the v3 Accounting API)
- A running Chatty instance (local or deployed on Railway)
- The public URL where your Chatty instance is reachable (e.g. `http://localhost:8000`, your Railway URL, or your custom domain)

## Step 1: Create an Intuit Developer account

1. Go to [developer.intuit.com](https://developer.intuit.com/)
2. Sign in with your existing QuickBooks/Intuit credentials, or create a new account

The developer account is free and separate from your QuickBooks subscription. You can use the same email.

## Step 2: Create your app

1. From the Intuit Developer dashboard, click **Create an app**
2. Select **QuickBooks Online and Payments**
3. Name your app — `Chatty` is fine, but it can be anything (e.g. `Acme Co Chatty`). Only you will see this name.
4. Under scopes, select **com.intuit.quickbooks.accounting**
5. Click **Create app**

Because this app is for your own private use, you do **not** need to submit it for Intuit App Review or publish it to the App Store. App Review is only required if you want to distribute the app to other QuickBooks users — which a self-hoster doesn't.

## Step 3: Get your credentials

Intuit gives every app two sets of credentials — keep them straight, this trips people up:

| Tab | What it does | When to use |
|---|---|---|
| **Development** | Connects only to Intuit's *sandbox* (a fake test company) | Trying things out before touching real books |
| **Production** | Connects to your real QuickBooks company data | Actual day-to-day use |

For real use:

1. In your app, open **Keys and credentials** in the left sidebar
2. Switch to the **Production** tab
3. Toggle **Show credentials** and copy the **Client ID** and **Client Secret**

> Intuit may ask you to complete a short security questionnaire before issuing Production keys (data handling, where the app runs, etc.). For a personal self-hosted instance the answers are straightforward — the app runs on your own machine or your own Railway deployment, data is stored locally, and you are the only user.

## Step 4: Set the Redirect URI

The Redirect URI is the URL Intuit sends users to after they approve the connection. It must match **exactly** between your Intuit app and your Chatty config.

Pick the option that matches how you're running Chatty:

### Option A — Direct to your Chatty instance (recommended for self-hosters)

Use the URL where Chatty is reachable, with `/api/oauth/callback` appended:

| Where Chatty runs | Redirect URI |
|---|---|
| Local development | `http://localhost:8000/api/oauth/callback` |
| Railway | `https://your-app.up.railway.app/api/oauth/callback` |
| Custom domain | `https://chatty.yourdomain.com/api/oauth/callback` |

In your Intuit app, on the **Keys and credentials** page, click **redirect urls** (or open **Settings**), paste the URL, and click **Save**.

Then in your Chatty `.env`:

```env
OAUTH_REDIRECT_URI=https://your-app.up.railway.app/api/oauth/callback
```

This is the cleanest setup — your Intuit app talks directly to your Chatty backend, no third party in between.

### Option B — Use the auth.mechatty.com proxy (Railway convenience option)

If you're on Railway and don't want to keep updating the Intuit app every time your Railway URL changes, you can use Chatty's shared callback proxy. Set the redirect URI in your Intuit app to:

```
https://auth.mechatty.com/callback
```

Leave `OAUTH_REDIRECT_URI` **unset** in your `.env`. The proxy receives the callback from Intuit and forwards it to your Chatty instance based on the state parameter. No customer data flows through it — only the short-lived authorization code.

Allowed forwarding destinations: `*.up.railway.app`, `localhost`, `127.0.0.1`. See [Domain Allowlist](#domain-allowlist) below to add your own.

## Step 5: Add credentials to Chatty

In your Chatty `backend/.env` file:

```env
QUICKBOOKS_CLIENT_ID=your-client-id-here
QUICKBOOKS_CLIENT_SECRET=your-client-secret-here
```

If you're using **Production** credentials (real QuickBooks data), also set:

```env
QUICKBOOKS_API_BASE_URL=https://quickbooks.api.intuit.com/v3/company
```

If you're using **Development** credentials (sandbox), leave that line out — Chatty defaults to the sandbox URL.

If you chose **Option A** above, also set:

```env
OAUTH_REDIRECT_URI=https://your-app.up.railway.app/api/oauth/callback
```

Restart the Chatty backend so it picks up the new `.env`.

## Step 6: Connect QuickBooks in Chatty

1. Open Chatty in your browser
2. Go to **Settings** (gear icon) → **Integrations**, or run through the onboarding wizard
3. Click **Connect QuickBooks**
4. A browser window opens to Intuit's login page
5. Sign in (or pick the QuickBooks company you want to authorize) and approve the connection
6. You'll see a "Connected!" confirmation — the window can be closed

## What your agents can do

Once connected, your AI agents can:

- **Query any QuickBooks data** — invoices, customers, vendors, bills, payments, items, and more using SQL-style queries
- **Pull financial reports** — Profit & Loss and Balance Sheet reports for any date range
- **Create invoices and estimates** — generate and email invoices and quotes to customers
- **Update invoices** — modify existing invoices or void them
- **Record payments** — log payments received from customers
- **Create entities** — add new customers, vendors, items, bills, expenses, and credit memos
- **Update entities** — modify existing customers, vendors, and items
- **Send documents** — email invoices and estimates directly to customers from QuickBooks

Example questions you can ask your agent:

- "Show me all unpaid invoices"
- "Who are my top 5 customers by revenue?"
- "What's my profit and loss for Q1 2026?"
- "Create an invoice for Acme Corp — 10 hours of consulting at $150/hr"
- "Send the latest estimate to Jane at jane@example.com"
- "Record a $5,000 payment from Acme Corp against invoice #1042"
- "Add a new vendor: Office Supply Co"

## Troubleshooting

### "OAuth not configured for quickbooks: missing client_id in .env"
Your `QUICKBOOKS_CLIENT_ID` is not set. Check your `.env` file in `backend/` and restart the backend.

### "redirect_uri did not match" / "invalid_redirect_uri"
The URL in your Intuit app's Redirect URIs list does not match what Chatty is sending. They must match character-for-character, including `http` vs `https` and the trailing `/api/oauth/callback`. Update one or the other so they line up exactly.

### "QuickBooks did not return a company ID (realmId)"
The OAuth flow completed but Intuit didn't return a company ID. Disconnect and reconnect; if it persists, confirm your app has the **com.intuit.quickbooks.accounting** scope enabled.

### 403 Forbidden errors on API calls
You're likely mixing Development credentials with the production API URL (or vice versa):
- **Development credentials** → leave `QUICKBOOKS_API_BASE_URL` unset (defaults to sandbox)
- **Production credentials** → set `QUICKBOOKS_API_BASE_URL=https://quickbooks.api.intuit.com/v3/company`

### Token expired
QuickBooks access tokens expire after 1 hour. Chatty automatically refreshes them using the refresh token. Refresh tokens themselves last 100 days and rotate on each use, so as long as you connect at least once every 100 days you'll stay connected. If refresh fails, just reconnect from **Settings → Integrations**.

### "Sandbox not found" or empty data
Your Development app needs a sandbox company attached. In the Intuit Developer dashboard, go to **Sandboxes** and create one. Then re-authorize from Chatty.

## Domain Allowlist

If you're using **Option B** (the `auth.mechatty.com` proxy), the proxy only forwards callbacks to a known list of trusted destinations. Currently allowed:

- `*.up.railway.app` — Railway deployments
- `localhost` / `127.0.0.1` — local development

If you're hosting Chatty on a different domain and want to keep using the proxy, open a pull request adding your domain pattern to `website/auth/callback/index.php`, or just switch to **Option A** (Direct to your Chatty instance) — that approach has no domain restrictions because there's no proxy involved.

## Why does Chatty work this way?

Most consumer SaaS products hide all of this — you click "Connect QuickBooks" and it just works, because the company runs a single shared Intuit app on your behalf. Chatty is open source and self-hosted, so there is no central operator. You become the operator of your own private app, which:

- Gives you full control over your QuickBooks credentials (they never leave your machine)
- Avoids any per-user data passing through a third party
- Keeps the project free — there's no centralized cost to fund

The trade-off is the 10 minutes of one-time setup above. If that ever becomes a barrier, see the project README for the optional managed hosted service that handles this for you.
