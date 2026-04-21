# Google Drive Setup

Connect your Google Drive so your Chatty agents can search, read, and upload files.

## Prerequisites

- A Google account with Drive enabled

## Local Setup

1. Start Chatty with `python run.py`
2. Go to **Settings** > **Integrations** and click **Connect Google**
3. Sign in with your Google account and choose the access level you want to grant:
   - **Readonly** — browse and read files
   - **File** — read access plus upload new files (can only access files created by Chatty)
   - **Full** — complete Drive access including all files

## Railway Setup

1. Open your Chatty instance
2. Go to **Settings** > **Integrations** and click **Connect Google**
3. Sign in with your Google account and choose your access levels

That's it — Chatty handles the OAuth flow through its hosted service at `auth.mechatty.com`, so there's no Google Cloud project or credentials to configure.

> **Note:** Google Drive uses the same Google connection as Gmail and Google Calendar. You choose the access level for each service during the same sign-in flow.

### Self-hosted OAuth (advanced)

If you prefer to use your own Google OAuth credentials instead of the hosted service:

1. Create a project in the [Google Cloud Console](https://console.cloud.google.com/apis/credentials) and enable the **Google Drive API**
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
- Google Drive uses the same Google connection as Gmail and Calendar
