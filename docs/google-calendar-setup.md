# Google Calendar Setup

Connect your Google Calendar so your Chatty agents can view, search, create, update, and delete events on your schedule.

## Prerequisites

- A Google account with Calendar enabled
- Google OAuth credentials configured for Chatty — see [Google OAuth Setup](google-oauth-setup.md)

> Google Calendar uses the same Google connection as Gmail and Drive. If you've already done the OAuth setup for one of those, you do not need to do it again — just enable the Google Calendar API in the same Google Cloud project.

## Setup

1. In your Google Cloud project, enable the **Google Calendar API** under **APIs & Services → Library** (skip if already enabled)
2. In your OAuth consent screen → **Scopes**, add the Calendar scopes for the level of access you want:
   - **Read** — `calendar.readonly`
   - **Full** — `calendar` (read + create/update/delete events)
3. In Chatty, go to **Settings → Integrations** and click **Connect Google**
4. Sign in and choose the Calendar access level you want — Chatty will request the matching scopes from Google
5. Approve and you're connected

> **Note on scopes:** Both Calendar scopes are Google "Sensitive" scopes (not Restricted), which means they don't require the CASA security assessment if you ever submit for verification. For self-hosted personal use, Testing mode with yourself as a test user is fine.

## What your agents can do

Once connected, your agents can:

- **List upcoming events** — see what's on your calendar for any date range
- **Search events** — find events by title, description, or other details
- **View event details** — attendees, location, video call links, organizer, and recurrence info
- **Find free time** — look for open slots in your schedule
- **Create events** — schedule new events with title, time, location, description, and attendees
- **Update events** — change the time, title, attendees, or other details of existing events
- **Delete events** — remove events from your calendar

Example questions you can ask:

- "What's on my calendar today?"
- "Schedule a meeting with Sarah tomorrow at 2pm for 30 minutes"
- "Find me a free 1-hour slot this week"
- "Move my Friday standup to 10am"
- "Cancel the team lunch on Thursday"
- "Add jane@example.com to the project kickoff meeting"

## Notes

- You choose the access level during setup — **Read** for view-only, or **Full** for complete calendar management
- Uses your primary calendar by default (other calendars can be specified by ID)
- All-day events and timed events are both supported
- Attendee response status (accepted, declined, tentative) is included in event details
- Google Calendar uses the same Google connection as Gmail and Drive — connect once, use everywhere
