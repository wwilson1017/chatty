# Google Drive Setup

Connect your Google Drive so your Chatty agents can search, read, and upload files.

## Prerequisites

- A Google account with Drive enabled
- Google OAuth credentials configured for Chatty — see [Google OAuth Setup](google-oauth-setup.md)

> Google Drive uses the same Google connection as Gmail and Calendar. If you've already done the OAuth setup for one of those, you do not need to do it again — just enable the Google Drive API in the same Google Cloud project.

## Setup

1. In your Google Cloud project, enable the **Google Drive API** under **APIs & Services → Library** (skip if already enabled)
2. In your OAuth consent screen → **Scopes**, add the Drive scopes for the level of access you want:
   - **File** — `drive.file` (read/write only files Chatty creates or you explicitly open with it)
   - **Readonly** — `drive.readonly` (browse and read all your Drive files)
   - **Full** — `drive` (complete Drive access — read, write, and delete)
3. In Chatty, go to **Settings → Integrations** and click **Connect Google**
4. Sign in and choose the Drive access level you want — Chatty will request the matching scopes from Google
5. Approve and you're connected

> **Note on scopes:** `drive.file` is a "Recommended" scope and works without verification. `drive.readonly` and `drive` are "Restricted" scopes — for self-hosted personal use, Testing mode with yourself as a test user sidesteps the CASA assessment requirement. See [Google OAuth Setup](google-oauth-setup.md#scopes--the-most-important-part) for details.

## What your agents can do

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

- You choose the access level during setup — **File** for Chatty's own files only, **Readonly** for browsing all files, or **Full** for complete access including delete
- Google Docs, Sheets, and Slides are automatically exported to readable formats
- Google Drive uses the same Google connection as Gmail and Calendar — connect once, use everywhere
