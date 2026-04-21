# Gmail Setup

Connect your Gmail account so your Chatty agents can search, read, send, reply to, and draft emails.

## Prerequisites

- A Google account with Gmail enabled

## Local Setup

1. Add your Google OAuth credentials to the `.env` file in the project root:
   ```env
   GOOGLE_CLIENT_ID=your-client-id
   GOOGLE_CLIENT_SECRET=your-client-secret
   ```
2. Start Chatty with `python run.py`
3. Go to **Settings** > **Integrations** and click **Connect Google**
4. Sign in with your Google account and choose the access level you want to grant:
   - **Read** — search and read emails
   - **Send** — read access plus send, reply, and draft emails

> **Note:** Gmail uses the same Google OAuth connection as Google Calendar and Google Drive. You choose the access level for each service during the same sign-in flow.

## Railway Setup

1. In your Railway dashboard, add these environment variables to your Chatty service:
   ```
   GOOGLE_CLIENT_ID=your-client-id
   GOOGLE_CLIENT_SECRET=your-client-secret
   ```
2. In your [Google Cloud Console](https://console.cloud.google.com/apis/credentials), add your Railway URL as an authorized redirect URI:
   ```
   https://your-app.up.railway.app/api/auth/google/callback
   ```
3. Redeploy the service (or it will pick up the new env vars on next deploy)
4. Open your Chatty instance, go to **Settings** > **Integrations**, and click **Connect Google**
5. Sign in and choose your access levels

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
