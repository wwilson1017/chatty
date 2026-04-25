# Gmail Setup

Connect your Gmail account so your Chatty agents can search, read, send, reply to, and draft emails.

## Prerequisites

- A Google account with Gmail enabled
- Google OAuth credentials configured for Chatty — see [Google OAuth Setup](google-oauth-setup.md)

> Gmail uses the same Google connection as Calendar and Drive. If you've already done the OAuth setup for one of those, you do not need to do it again — just enable the Gmail API in the same Google Cloud project.

## Setup

1. In your Google Cloud project, enable the **Gmail API** under **APIs & Services → Library** (skip if already enabled)
2. In your OAuth consent screen → **Scopes**, add the Gmail scopes for the level of access you want:
   - **Read** — `gmail.readonly`
   - **Send** — `gmail.readonly` + `gmail.send` + `gmail.compose`
   - **Modify** — `gmail.readonly` + `gmail.send` + `gmail.compose` + `gmail.modify`
3. In Chatty, go to **Settings → Integrations** and click **Connect Google**
4. Sign in and choose the Gmail access level you want — Chatty will request the matching scopes from Google
5. Approve and you're connected

> **Note on scopes:** `gmail.readonly` and `gmail.modify` are Google "Restricted" scopes. For self-hosted personal use, this is fine — keep your OAuth app in Testing mode and add yourself as a test user. See the [Google OAuth Setup guide](google-oauth-setup.md#scopes--the-most-important-part) for the full picture.

## What your agents can do

Once connected, your agents can:

- **Search emails** — find messages by sender, subject, date, labels, read status, or any Gmail search query
- **Read full emails** — view the complete content of any message
- **View email threads** — see the full conversation in a thread
- **Send emails** — compose and send new emails to any recipient
- **Reply to emails** — reply to a specific message, or reply-all to the thread
- **Create drafts** — draft an email for you to review and send later
- **Mark as read/unread** — modify message read status (requires `gmail.modify` scope)

Example questions you can ask:

- "Do I have any unread emails from my accountant?"
- "Send an email to jane@example.com — subject: Meeting Tomorrow — let her know I'll be 15 minutes late"
- "Reply to that last email from Sarah and tell her the proposal looks good"
- "Draft a follow-up email to the vendor about the late shipment"
- "Find the last email about the quarterly report"

## Notes

- You choose the access level during setup — **Read** for search/read only, **Send** for full email composition, or **Modify** for everything plus marking read/unread
- Gmail search filters work the same as in Gmail itself (`from:`, `subject:`, `is:unread`, `has:attachment`, etc.)
- HTML emails are automatically converted to readable text
- Gmail uses the same Google connection as Calendar and Drive — connect once, use everywhere
