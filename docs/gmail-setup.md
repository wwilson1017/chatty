# Gmail Setup

Connect your Gmail account so your Chatty agents can search and read your email.

## Prerequisites

- A Google account with Gmail enabled
- A Google Cloud project with the **Gmail API** enabled
- OAuth credentials (Client ID and Client Secret) from the [Google Cloud Console](https://console.cloud.google.com/apis/credentials)

## Local Setup

1. Add your Google OAuth credentials to the `.env` file in the project root:
   ```env
   GOOGLE_CLIENT_ID=your-client-id
   GOOGLE_CLIENT_SECRET=your-client-secret
   ```
2. Start Chatty with `python run.py`
3. Go to **Settings** > **Providers** and click **Connect Google**
4. Sign in with your Google account and authorize access
5. Gmail is included in the Google OAuth flow — no extra steps after connecting

> **Note:** Gmail uses the same Google OAuth connection as Google Gemini and Google Calendar. Connecting one connects them all.

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
4. Open your Chatty instance, go to **Settings** > **Providers**, and click **Connect Google**
5. Sign in and authorize access

## What Your Agents Can Do

Once connected, your agents can:

- **Search emails** — find messages by sender, subject, date, labels, read status, or any Gmail search query
- **Read full emails** — view the complete content of any message
- **View email threads** — see the full conversation in a thread

Example questions you can ask:

- "Do I have any unread emails from my accountant?"
- "Find the last email about the quarterly report"
- "Show me all emails from last week with attachments"
- "What did Sarah say in her most recent email?"

## Notes

- Gmail search filters work the same as in Gmail itself (`from:`, `subject:`, `is:unread`, `has:attachment`, etc.)
- HTML emails are automatically converted to readable text
- Gmail uses the same Google OAuth connection as Calendar and Gemini
