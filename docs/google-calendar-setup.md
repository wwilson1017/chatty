# Google Calendar Setup

Connect your Google Calendar so your Chatty agents can view, search, create, update, and delete events on your schedule.

## Prerequisites

- A Google account with Calendar enabled

## Local Setup

1. Add your Google OAuth credentials to the `.env` file in the project root:
   ```env
   GOOGLE_CLIENT_ID=your-client-id
   GOOGLE_CLIENT_SECRET=your-client-secret
   ```
2. Start Chatty with `python run.py`
3. Go to **Settings** > **Integrations** and click **Connect Google**
4. Sign in with your Google account and choose the access level you want to grant:
   - **Read** — view and search events
   - **Full** — read access plus create, update, and delete events

> **Note:** Google Calendar uses the same Google OAuth connection as Gmail and Google Drive. You choose the access level for each service during the same sign-in flow.

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
