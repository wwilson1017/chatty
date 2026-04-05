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
   http://localhost:9876/oauth/callback
   ```
3. Click **Save**

> **Note:** If you've deployed Chatty to Railway or another host, you still use the localhost redirect URI. The OAuth flow opens a browser on your local machine and captures the callback locally.

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

- **Query any QuickBooks data** — invoices, customers, vendors, bills, payments, items, and more using QuickBooks SQL-style queries
- **Pull financial reports** — Profit & Loss statements for any date range

Example questions you can ask your agent:
- "Show me all unpaid invoices"
- "Who are my top 5 customers by revenue?"
- "What's my profit and loss for Q1 2026?"
- "List all bills due this month"

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
