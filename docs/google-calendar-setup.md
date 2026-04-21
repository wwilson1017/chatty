# Google Calendar Setup

Connect your Google Calendar so your Chatty agents can view, search, create, update, and delete events on your schedule.

## Prerequisites

- A Google account with Calendar enabled

## Local Setup

1. Start Chatty with `python run.py`
2. Go to **Settings** > **Integrations** and click **Connect Google**
3. Sign in with your Google account and choose the access level you want to grant:
   - **Read** — view and search events
   - **Full** — read access plus create, update, and delete events

## Railway Setup

1. Open your Chatty instance
2. Go to **Settings** > **Integrations** and click **Connect Google**
3. Sign in with your Google account and choose your access levels

That's it — Chatty handles the OAuth flow through its hosted service at `auth.mechatty.com`, so there's no Google Cloud project or credentials to configure.

> **Note:** Google Calendar uses the same Google connection as Gmail and Google Drive. You choose the access level for each service during the same sign-in flow.

### Self-hosted OAuth (advanced)

If you prefer to use your own Google OAuth credentials instead of the hosted service:

1. Create a project in the [Google Cloud Console](https://console.cloud.google.com/apis/credentials) and enable the **Google Calendar API**
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
- Google Calendar uses the same Google connection as Gmail and Drive
