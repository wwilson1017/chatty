# Google Drive Setup

Connect your Google Drive so your Chatty agents can search, read, and upload files.

## Prerequisites

- A Google account with Drive enabled

## Local Setup

1. Add your Google OAuth credentials to the `.env` file in the project root:
   ```env
   GOOGLE_CLIENT_ID=your-client-id
   GOOGLE_CLIENT_SECRET=your-client-secret
   ```
2. Start Chatty with `python run.py`
3. Go to **Settings** > **Integrations** and click **Connect Google**
4. Sign in with your Google account and choose the access level you want to grant:
   - **Readonly** — browse and read files
   - **File** — read access plus upload new files (can only access files created by Chatty)
   - **Full** — complete Drive access including all files

> **Note:** Google Drive uses the same Google OAuth connection as Gmail and Google Calendar. You choose the access level for each service during the same sign-in flow.

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
