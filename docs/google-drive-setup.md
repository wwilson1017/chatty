# Google Drive Setup

Connect your Google Drive so your Chatty agents can search, read, and upload files.

## Prerequisites

- A Google account with Drive enabled
- **Your own Google Cloud OAuth client** (client ID + client secret) — Chatty does not ship with a bundled OAuth app. The same OAuth client covers Gmail, Calendar, and Drive — if you've already set it up for one of the other services, you can skip the OAuth setup section below.

## Google OAuth Setup

You only need to do this once — the same OAuth client is used for Gmail, Google Calendar, and Google Drive.

1. Go to the [Google Cloud Console](https://console.cloud.google.com) and create (or select) a project
2. **APIs & Services → Library** → enable each API you plan to use:
   - **Google Drive API** (required for this guide)
   - **Gmail API** (if you'll connect Gmail)
   - **Google Calendar API** (if you'll connect Calendar)
3. **APIs & Services → OAuth consent screen** → choose *External* → fill in app name, support email, and developer contact
4. Add the scopes you plan to grant (only add what you'll actually use):
   - `openid`, `email`, `profile`
   - `https://www.googleapis.com/auth/drive.readonly` — browse and read all files
   - `https://www.googleapis.com/auth/drive.file` — read + upload (Chatty can only access files it created)
   - `https://www.googleapis.com/auth/drive` — full access to all files
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

> **Sensitive-scope verification:** The `drive` and `drive.readonly` scopes are classified as "restricted" by Google — the strictest tier. The `drive.file` scope is unrestricted. Unverified apps can serve up to 100 test users — fine for personal use. For wider distribution with restricted scopes, you'll need to submit your OAuth app for Google's verification review including a security assessment (this can take weeks). While unverified, you'll see a "Google hasn't verified this app" warning when connecting; click *Advanced → Go to (your app)* to proceed.

## Connect in Chatty

1. Open your Chatty instance and log in
2. Go to **Settings → Integrations** and click **Connect Google**
3. Sign in with your Google account
4. Choose the access level you want to grant for Drive:
   - **Readonly** — browse and read files
   - **File** — read access plus upload new files (can only access files created by Chatty)
   - **Full** — complete Drive access including all files
5. Click **Allow** — you'll be redirected back to Chatty with the integration enabled

> **Note:** Google Drive uses the same Google connection as Gmail and Google Calendar. You choose the access level for each service during the same sign-in flow.

## What Your Agents Can Do

Once connected, your agents can:

- **Browse files** — list files in your Drive or a specific folder
- **Search files** — find files by name or type
- **Read file content** — view the contents of documents, spreadsheets, and other files
- **Upload files** — create new files in Drive with specified content and file type
- **Organize files** — upload to specific folders

Example questions you can ask:

- "What files are in my Drive?"
- "Find the spreadsheet called Q1 Budget"
- "What does the project proposal document say?"
- "Create a text file called meeting-notes.txt with today's notes"
- "Upload this report to the Financials folder"

## Notes

- You choose the access level during setup — **Readonly** for browsing, **File** for read + upload (Chatty's own files only), or **Full** for complete access
- Google Docs, Sheets, and Slides are automatically exported to readable formats
- Google Drive uses the same Google connection as Gmail and Calendar — one OAuth client covers all three services
