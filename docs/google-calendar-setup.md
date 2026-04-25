# Google Calendar Setup

Connect your Google Calendar so your Chatty agents can view, search, create, update, and delete events on your schedule.

## Prerequisites

- A Google account with Calendar enabled
- **Your own Google Cloud OAuth client** (client ID + client secret) — Chatty does not ship with a bundled OAuth app. The same OAuth client covers Gmail, Calendar, and Drive — if you've already set it up for one of the other services, you can skip the OAuth setup section below.

## Google OAuth Setup

You only need to do this once — the same OAuth client is used for Gmail, Google Calendar, and Google Drive.

1. Go to the [Google Cloud Console](https://console.cloud.google.com) and create (or select) a project
2. **APIs & Services → Library** → enable each API you plan to use:
   - **Google Calendar API** (required for this guide)
   - **Gmail API** (if you'll connect Gmail)
   - **Google Drive API** (if you'll connect Drive)
3. **APIs & Services → OAuth consent screen** → choose *External* → fill in app name, support email, and developer contact
4. Add the scopes you plan to grant (only add what you'll actually use):
   - `openid`, `email`, `profile`
   - `https://www.googleapis.com/auth/calendar.readonly` — view events
   - `https://www.googleapis.com/auth/calendar` — view + create, update, delete events
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

> **App verification:** Calendar scopes are not classified as sensitive, so most users won't need to submit for Google verification. Unverified apps can serve up to 100 test users. While unverified, you may see a "Google hasn't verified this app" warning when connecting; click *Advanced → Go to (your app)* to proceed.

## Connect in Chatty

1. Open your Chatty instance and log in
2. Go to **Settings → Integrations** and click **Connect Google**
3. Sign in with your Google account
4. Choose the access level you want to grant for Calendar:
   - **Read** — view and search events
   - **Full** — read access plus create, update, and delete events
5. Click **Allow** — you'll be redirected back to Chatty with the integration enabled

> **Note:** Google Calendar uses the same Google connection as Gmail and Google Drive. You choose the access level for each service during the same sign-in flow.

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
- Google Calendar uses the same Google connection as Gmail and Drive — one OAuth client covers all three services
