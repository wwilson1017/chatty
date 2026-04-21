# Gmail Setup

Connect your Gmail account so your Chatty agents can search, read, send, reply to, and draft emails.

## Prerequisites

- A Google account with Gmail enabled

## Local Setup

1. Start Chatty with `python run.py`
2. Go to **Settings** > **Integrations** and click **Connect Google**
3. Sign in with your Google account and choose the access level you want to grant:
   - **Read** — search and read emails
   - **Send** — read access plus send, reply, and draft emails

## Railway Setup

1. Open your Chatty instance
2. Go to **Settings** > **Integrations** and click **Connect Google**
3. Sign in with your Google account and choose your access levels

That's it — Chatty handles the OAuth flow through its hosted service at `auth.mechatty.com`, so there's no Google Cloud project or credentials to configure.

> **Note:** Gmail uses the same Google connection as Google Calendar and Google Drive. You choose the access level for each service during the same sign-in flow.

### Self-hosted OAuth (advanced)

If you prefer to use your own Google OAuth credentials instead of the hosted service:

1. Create a project in the [Google Cloud Console](https://console.cloud.google.com/apis/credentials) and enable the **Gmail API**
2. Create OAuth 2.0 credentials (Client ID and Client Secret)
3. Add your redirect URI (e.g., `http://localhost:8000/api/oauth/callback` for local)
4. Set these in your `.env` file:
   ```env
   GOOGLE_CLIENT_ID=your-client-id
   GOOGLE_CLIENT_SECRET=your-client-secret
   ```
5. Remove or leave `OAUTH_REDIRECT_URI` unset

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
- Gmail uses the same Google connection as Calendar and Drive
