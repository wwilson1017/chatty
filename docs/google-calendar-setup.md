# Google Calendar Setup

Connect your Google Calendar so your Chatty agents can view and search your schedule.

## Prerequisites

- A Google account with Calendar enabled
- A Google Cloud project with the **Google Calendar API** enabled
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
5. Calendar is included in the Google OAuth flow — no extra steps after connecting

> **Note:** Google Calendar uses the same Google OAuth connection as Gmail and Google Gemini. Connecting one connects them all.

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

- **List upcoming events** — see what's on your calendar for any date range
- **Search events** — find events by title, description, or other details
- **View event details** — attendees, location, video call links, organizer, and recurrence info

Example questions you can ask:

- "What's on my calendar today?"
- "Do I have any meetings with the design team this week?"
- "When is my next dentist appointment?"
- "Show me everything on my schedule for next Monday"

## Notes

- Calendar access is **read-only** — your agent can view events but cannot create, edit, or delete them
- Uses your primary calendar by default
- All-day events and timed events are both supported
- Attendee response status (accepted, declined, tentative) is included in event details
- Google Calendar uses the same Google OAuth connection as Gmail and Gemini
