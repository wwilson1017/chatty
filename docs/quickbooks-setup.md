# Connecting QuickBooks Online to Chatty

This guide walks you through connecting your QuickBooks Online account to Chatty so your AI agents can query invoices, customers, bills, and financial reports.

## Prerequisites

- A QuickBooks Online account (any plan)
- A running Chatty instance (local or deployed on Railway)

## Step 1: Create an Intuit Developer Account

1. Go to [developer.intuit.com](https://developer.intuit.com/)
2. Sign in with your existing QuickBooks/Intuit credentials (or create a new account)

## Step 2: Create an App

1. From the Intuit Developer dashboard, click **Create an app**
2. Select **QuickBooks Online and Payments**
3. Name your app (e.g. "Chatty")
4. Select the **com.intuit.quickbooks.accounting** scope
5. Click **Create app**

## Step 3: Get Your Credentials

1. In your app, go to **Keys and credentials** in the left sidebar
2. Select the **Development** tab (for testing with sandbox data) or **Production** tab (for your real QuickBooks data)
3. Toggle **Show credentials** and copy your **Client ID** and **Client Secret**

## Step 4: Set the Redirect URI

1. On the Keys and credentials page, click the **redirect urls** link (or go to **Settings** in the left sidebar)
2. Add the following redirect URI:
   ```
   https://auth.mechatty.com/callback
   ```
3. Click **Save**

> **Note:** This is the same redirect URI for all Chatty instances — local dev and Railway. The auth.mechatty.com proxy securely forwards the OAuth callback to your specific instance. If you're hosting on a different platform, see [Domain Allowlist](#domain-allowlist) below.

## Step 5: Add Credentials to Chatty

Add these environment variables to your Chatty `.env` file (in the `backend/` directory):

```env
QUICKBOOKS_CLIENT_ID=your-client-id-here
QUICKBOOKS_CLIENT_SECRET=your-client-secret-here
```

If you're using your real QuickBooks account (not sandbox), also set:

```env
QUICKBOOKS_API_BASE_URL=https://quickbooks.api.intuit.com/v3/company
```

Restart the Chatty backend after updating the `.env` file.

## Step 6: Connect QuickBooks in Chatty

1. Open Chatty in your browser
2. Go to **Settings** (gear icon) > **Integrations** tab, or run through the onboarding wizard
3. Click **Connect QuickBooks**
4. A browser window will open to Intuit's login page
5. Sign in and authorize Chatty to access your QuickBooks data
6. You'll see a "Connected!" confirmation — the window can be closed

## What Your Agents Can Do

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
Your `QUICKBOOKS_CLIENT_ID` is not set. Check your `.env` file in the `backend/` directory and restart the backend.

### "QuickBooks did not return a company ID (realmId)"
The OAuth flow completed but QuickBooks didn't return a company ID. Try disconnecting and reconnecting.

### 403 Forbidden errors on API calls
You're likely using Development credentials with the production API URL (or vice versa). Make sure:
- **Development credentials** → don't set `QUICKBOOKS_API_BASE_URL` (defaults to sandbox)
- **Production credentials** → set `QUICKBOOKS_API_BASE_URL=https://quickbooks.api.intuit.com/v3/company`

### Token expired
QuickBooks access tokens expire after 1 hour. Chatty automatically refreshes them using the refresh token. If refresh fails, reconnect QuickBooks through Settings > Integrations.

## Domain Allowlist

The auth.mechatty.com OAuth proxy validates that callbacks are only forwarded to trusted domains. Currently allowed:

- `*.up.railway.app` — Railway deployments
- `localhost` / `127.0.0.1` — local development

If you're hosting Chatty on a different domain, the proxy will reject the callback with "Callback domain not allowed." To add your domain, open a pull request adding your domain pattern to `website/auth/callback/index.php`, or message Will directly on [WhatsApp](https://wa.me/qr/TX3OGA6ME6LHD1).

### Advanced: Direct OAuth (bypassing the proxy)

If you prefer not to use the proxy, you can configure QuickBooks OAuth to redirect directly to your instance:

1. In the Intuit developer portal, create your own app and set the redirect URI to `https://your-domain.com/api/oauth/callback`
2. In your `.env` file, set:
   ```env
   OAUTH_REDIRECT_URI=https://your-domain.com/api/oauth/callback
   ```

This bypasses the proxy entirely — your Intuit app redirects directly to your backend.
