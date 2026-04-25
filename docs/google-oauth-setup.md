# Google OAuth Setup

This is the one-time Google Cloud setup that powers Gmail, Google Calendar, and Google Drive in Chatty. You only need to do this once — the same OAuth app is used for all three services, even if you only use one of them today.

## How this works

Because Chatty is self-hosted, **you must create your own Google Cloud project and bring your own OAuth Client ID and Client Secret.** The project does not provide a shared Google app, Client ID, or Client Secret — every Chatty user is the operator of their own private Google Cloud project, which authorizes their own Chatty instance against their own Google account.

This setup is the price of admission for using any Google service with Chatty. Once it's done, your agents can talk to Gmail, Calendar, and Drive indefinitely.

You will:

1. Create a free Google Cloud project
2. Enable the APIs for the Google services you want to use
3. Configure the OAuth consent screen with your scopes
4. Create OAuth 2.0 credentials (Client ID + Client Secret)
5. Add the Redirect URI for your Chatty instance
6. Drop the credentials into Chatty's `.env`

## Prerequisites

- A Google account
- A running Chatty instance (local or deployed on Railway)
- The public URL where your Chatty instance is reachable (e.g. `http://localhost:8000`, your Railway URL, or your custom domain)

## Step 1: Create a Google Cloud project

1. Go to the [Google Cloud Console](https://console.cloud.google.com/)
2. Click the project dropdown at the top → **New Project**
3. Name it something like `Chatty` and click **Create**
4. Wait a few seconds, then select the new project from the project picker

The project is free. Google does not charge for OAuth or for the API calls Chatty makes — you only pay for billable services if you opt into them, which Chatty does not require.

## Step 2: Enable the APIs you need

For each Google service you want to use, you have to enable its API in your project.

1. In the Cloud Console, open the navigation menu → **APIs & Services** → **Library**
2. Search for and enable each of:
   - **Gmail API** — required for the [Gmail integration](gmail-setup.md)
   - **Google Calendar API** — required for the [Google Calendar integration](google-calendar-setup.md)
   - **Google Drive API** — required for the [Google Drive integration](google-drive-setup.md)

You only need to enable the APIs for services you actually want to use. You can come back later and enable more in the same project — no need to start over.

## Step 3: Configure the OAuth consent screen

This is the screen Google shows when you click "Connect Google" in Chatty. It tells Google what your app is and what permissions it asks for.

1. In the Cloud Console, go to **APIs & Services** → **OAuth consent screen**
2. Choose **External** as the user type and click **Create**
   - "Internal" is only available if you have a Google Workspace organization. External works for everyone else.
3. Fill in the basics:
   - **App name** — `Chatty` (or whatever you want — only you will see this)
   - **User support email** — your email
   - **Developer contact** — your email
4. Click **Save and Continue**

### Scopes — the most important part

On the **Scopes** step, click **Add or Remove Scopes** and select the scopes for the services you enabled. Chatty supports tiered access — pick whichever level matches what you want your agents to be able to do:

**Gmail scopes:**

| Scope | What it grants | Google's classification |
|---|---|---|
| `https://www.googleapis.com/auth/gmail.readonly` | Read emails | Restricted |
| `https://www.googleapis.com/auth/gmail.send` | Send emails | Sensitive |
| `https://www.googleapis.com/auth/gmail.compose` | Draft emails | Sensitive |
| `https://www.googleapis.com/auth/gmail.modify` | Modify labels, mark read/unread | Restricted |

**Calendar scopes:**

| Scope | What it grants | Google's classification |
|---|---|---|
| `https://www.googleapis.com/auth/calendar.readonly` | View events | Sensitive |
| `https://www.googleapis.com/auth/calendar` | Full calendar access (create/update/delete) | Sensitive |

**Drive scopes:**

| Scope | What it grants | Google's classification |
|---|---|---|
| `https://www.googleapis.com/auth/drive.file` | Read/write only files Chatty creates | Recommended (no verification) |
| `https://www.googleapis.com/auth/drive.readonly` | Read all Drive files | Restricted |
| `https://www.googleapis.com/auth/drive` | Full Drive access | Restricted |

Click **Update**, then **Save and Continue** through the rest of the wizard.

### Test users (important for personal use)

On the **Test users** step, click **Add Users** and add the Google email address(es) you'll be using with Chatty.

By default a new OAuth app is in **Testing** mode, which means only the test users you list here can authorize it. This is fine and free for personal/self-hosted use — you just add yourself as a test user and you're done. **Verification is not required** for your own use.

> **Important:** Apps in Testing mode have a 7-day refresh token expiry. That means after a week without using Chatty, you'll have to click "Connect Google" again. If you use Chatty regularly this never matters — the token rotates on every API call. If you're going on vacation for two weeks, expect to reconnect when you get back.

If you want longer refresh tokens, you can submit your app for **Verification** (free, takes ~2–6 weeks, requires a privacy policy URL and a YouTube demo of each scope being used). This makes sense if you're going to host Chatty for others. For personal use, Testing mode is fine.

> **Restricted scopes (`gmail.readonly`, `gmail.modify`, `drive`, `drive.readonly`)** require an annual third-party security assessment called CASA on top of regular verification — typically $1,500+/year. For self-hosters using only their own Google account, Testing mode sidesteps this entirely. Just add yourself as a test user.

## Step 4: Create OAuth credentials

1. In the Cloud Console, go to **APIs & Services** → **Credentials**
2. Click **Create Credentials** → **OAuth client ID**
3. Application type: **Web application**
4. Name: `Chatty` (or whatever)
5. Under **Authorized redirect URIs**, click **Add URI** and paste the URL where your Chatty instance is reachable, with `/api/oauth/callback` appended:

   | Where Chatty runs | Redirect URI |
   |---|---|
   | Local development | `http://localhost:8000/api/oauth/callback` |
   | Railway | `https://your-app.up.railway.app/api/oauth/callback` |
   | Custom domain | `https://chatty.yourdomain.com/api/oauth/callback` |

6. Click **Create**
7. Copy the **Client ID** and **Client Secret** that Google shows you

Your Google app talks directly to your Chatty backend — there is no Chatty-operated proxy or shared callback URL.

## Step 5: Add credentials to Chatty

In your Chatty `backend/.env` file:

```env
GOOGLE_CLIENT_ID=your-client-id-here
GOOGLE_CLIENT_SECRET=your-client-secret-here
OAUTH_REDIRECT_URI=https://your-app.up.railway.app/api/oauth/callback
```

Use the exact same Redirect URI you configured in Step 4 — they must match character-for-character.

Restart the Chatty backend so it picks up the new `.env`.

## Step 6: Connect Google in Chatty

1. Open Chatty in your browser
2. Go to **Settings** (gear icon) → **Integrations** and click **Connect Google**
3. A browser window opens to Google's consent screen
4. Sign in with the Google account you added as a test user in Step 3
5. You'll see an **"unverified app"** warning — this is expected for apps in Testing mode. Click **Advanced** → **Go to Chatty (unsafe)**. It says "unsafe" because Google has not verified your app, but it's *your* app authorizing *your* account, so it's exactly as safe as you make it.
6. Choose the access level for each service (Gmail/Calendar/Drive) and approve
7. You'll see a "Connected!" confirmation — the window can be closed

## Troubleshooting

### "Error 400: redirect_uri_mismatch"
The Redirect URI in your Google Cloud OAuth credentials does not match what Chatty is sending. They must match exactly, including `http` vs `https`, the port, and the trailing `/api/oauth/callback`. Update one or the other.

### "Access blocked: Chatty has not completed the Google verification process"
Your Google account is not in the test users list. Go back to **OAuth consent screen** → **Test users** and add the email address you're trying to sign in with.

### "This app isn't verified" warning every time
Expected behavior for apps in Testing mode. Click **Advanced** → **Go to Chatty (unsafe)** to proceed. This is your own app — the warning is Google's standard caution for unverified apps. To remove the warning, submit for verification (free, ~2–6 weeks for Sensitive scopes).

### Refresh token suddenly stopped working
If your app is in Testing mode, refresh tokens expire after 7 days of inactivity. Just click **Connect Google** again in **Settings → Integrations** to get a fresh token. To eliminate this, submit for verification.

### Missing capabilities (e.g. agent says it can't read email but you connected Gmail)
You probably granted only some scopes during the consent screen. Disconnect Google in **Settings → Integrations** and reconnect, this time choosing the access level you actually want. Or check the **OAuth consent screen → Scopes** in Google Cloud to confirm the right scopes are configured for your app.

### "The OAuth client was not found" / "invalid_client"
Your `GOOGLE_CLIENT_ID` or `GOOGLE_CLIENT_SECRET` in `.env` is wrong. Re-copy them from Google Cloud and restart the backend.

## Why does Chatty work this way?

Most consumer products hide all of this — you click "Connect Google" and it just works, because the company runs a single shared Google app on your behalf. Chatty is open source and self-hosted, so **there is no shared Google app, Client ID, or Client Secret provided by the project**. Every Chatty user creates their own Google Cloud project and uses their own credentials.

The benefits:

- You have full control over your Google credentials — they live in your `.env` and never leave your machine
- No third-party infrastructure sits in the OAuth path
- The project stays free to run, with no centralized cost to fund
- Whatever Google data your agents access flows directly between Google and your Chatty instance — Chatty's project does not see it

The trade-off is the 15 minutes of one-time setup above and the weekly re-auth in Testing mode. If that ever becomes a barrier, see the project README for the optional managed hosted service that handles this for you.
