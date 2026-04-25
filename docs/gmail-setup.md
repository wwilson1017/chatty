# Gmail Setup

Connect your Gmail account so your Chatty agents can search, read, send, reply to, and draft emails.

## Prerequisites

- A Google account with Gmail enabled
- **Your own Google Cloud OAuth client** (client ID + client secret) — Chatty does not ship with a bundled OAuth app. See [Google OAuth Setup](#google-oauth-setup) below.

## Google OAuth Setup

You only need to do this once — the same OAuth client is used for Gmail, Google Calendar, and Google Drive.

1. Go to the [Google Cloud Console](https://console.cloud.google.com) and create (or select) a project
2. **APIs & Services → Library** → enable each API you plan to use:
   - **Gmail API** (required for this guide)
   - **Google Calendar API** (if you'll connect Calendar)
   - **Google Drive API** (if you'll connect Drive)
3. **APIs & Services → OAuth consent screen** → choose *External* → fill in app name, support email, and developer contact
4. Add the scopes you plan to grant (only add what you'll actually use):
   - `openid`, `email`, `profile`
   - `https://www.googleapis.com/auth/gmail.readonly` — read emails
   - `https://www.googleapis.com/auth/gmail.send` — send emails
   - `https://www.googleapis.com/auth/gmail.compose` — create drafts
5. **APIs & Services → Credentials → Create Credentials → OAuth client ID** → choose *Web application*
6. Under **Authorized redirect URIs**, add your Chatty instance's callback URL:
   - **Local dev:** `http://localhost:8000/api/oauth/callback`
   - **Railway:** `https://your-chatty-url.up.railway.app/api/oauth/callback` (replace with your actual Railway URL)
   - **Custom domain:** `https://your-domain.com/api/oauth/callback`
7. Click **Create** and copy the **Client ID** and **Client secret**
8. Set these as environment variables on your Chatty instance:
   ```env
   GOOGLE_CLIENT_ID=your-client-id
   GOOGLE_CLIENT_SECRET=your-client-secret
   OAUTH_REDIRECT_URI=https://your-chatty-url/api/oauth/callback
   ```
   On Railway, add them under **Variables**. Locally, add them to `.env`.
9. Restart Chatty (Railway redeploys automatically when you change variables)

> **Sensitive-scope verification:** Gmail scopes are classified as "sensitive" by Google. Unverified apps can serve up to 100 test users — fine for personal use. For wider distribution, submit your OAuth app for Google's verification review (takes a few days to a few weeks). While unverified, you'll see a "Google hasn't verified this app" warning when connecting; click *Advanced → Go to (your app)* to proceed.

## Connect in Chatty

1. Open your Chatty instance and log in
2. Go to **Settings → Integrations** and click **Connect Google**
3. Sign in with your Google account
4. Choose the access level you want to grant for Gmail:
   - **Read** — search and read emails
   - **Send** — read access plus send, reply, and draft emails
5. Click **Allow** — you'll be redirected back to Chatty with the integration enabled

> **Note:** Gmail uses the same Google connection as Google Calendar and Google Drive. You choose the access level for each service during the same sign-in flow.

## What Your Agents Can Do

Once connected, your agents can:

- **Search emails** — find messages by sender, subject, date, labels, read status, or any Gmail search query
- **Read full emails** — view the complete content of any message
- **View email threads** — see the full conversation in a thread
- **Send emails** — compose and send new emails to any recipient
- **Reply to emails** — reply to a specific message, or reply-all to the thread
- **Create drafts** — draft an email for you to review and send later

Example questions you can ask:

- "Do I have any unread emails from my accountant?"
- "Send an email to jane@example.com — subject: Meeting Tomorrow — let her know I'll be 15 minutes late"
- "Reply to that last email from Sarah and tell her the proposal looks good"
- "Draft a follow-up email to the vendor about the late shipment"
- "Find the last email about the quarterly report"

## Notes

- You choose the access level during setup — **Read** for search/read only, or **Send** for full email capabilities
- Gmail search filters work the same as in Gmail itself (`from:`, `subject:`, `is:unread`, `has:attachment`, etc.)
- HTML emails are automatically converted to readable text
- Gmail uses the same Google connection as Calendar and Drive — one OAuth client covers all three services
