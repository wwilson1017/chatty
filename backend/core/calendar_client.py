"""
Chatty — Google Calendar API Client

Uses the user's OAuth access token (from data/auth-profiles.json under
google:default) instead of a service account. No admin/domain-wide delegation
required — the user authorizes Calendar access during the Google OAuth flow.
"""

import logging

logger = logging.getLogger(__name__)


def get_calendar_service(access_token: str):
    """Build an authenticated Google Calendar API service from a user OAuth access token.

    Args:
        access_token: The user's Google OAuth access token.
                      Stored in data/auth-profiles.json under google:default.
    """
    if not access_token:
        logger.warning("No Google access token provided for Calendar")
        return None

    try:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
    except ImportError:
        logger.warning("Google API libraries not installed")
        return None

    try:
        credentials = Credentials(token=access_token)
        service = build("calendar", "v3", credentials=credentials)
        return service
    except Exception as e:
        logger.error("Calendar service build failed: %s", e)
        return None


def list_events(service, time_min: str, time_max: str,
                calendar_id: str = "primary", max_results: int = 50) -> list[dict]:
    """List calendar events in a time range.

    Args:
        service: Google Calendar API service.
        time_min: Start time in RFC3339 (e.g. '2026-03-24T00:00:00-05:00').
        time_max: End time in RFC3339.
        calendar_id: Calendar ID (default 'primary').
        max_results: Maximum events to return.
    """
    try:
        result = service.events().list(
            calendarId=calendar_id,
            timeMin=time_min,
            timeMax=time_max,
            maxResults=max_results,
            singleEvents=True,
            orderBy="startTime",
        ).execute()

        events = result.get("items", [])
        return [_format_event(e) for e in events]
    except Exception as e:
        logger.error("Calendar list_events failed: %s", e)
        raise


def get_event(service, event_id: str, calendar_id: str = "primary") -> dict:
    """Get a single calendar event by ID."""
    try:
        event = service.events().get(
            calendarId=calendar_id, eventId=event_id
        ).execute()
        return _format_event(event)
    except Exception as e:
        logger.error("Calendar get_event failed: %s", e)
        raise


def search_events(service, query: str, time_min: str | None = None,
                  time_max: str | None = None, max_results: int = 20,
                  calendar_id: str = "primary") -> list[dict]:
    """Search calendar events by text query."""
    try:
        kwargs = {
            "calendarId": calendar_id,
            "q": query,
            "maxResults": max_results,
            "singleEvents": True,
            "orderBy": "startTime",
        }
        if time_min:
            kwargs["timeMin"] = time_min
        if time_max:
            kwargs["timeMax"] = time_max

        result = service.events().list(**kwargs).execute()
        events = result.get("items", [])
        return [_format_event(e) for e in events]
    except Exception as e:
        logger.error("Calendar search_events failed: %s", e)
        raise


def _format_event(event: dict) -> dict:
    """Format a Google Calendar event into a clean dict."""
    start = event.get("start", {})
    end = event.get("end", {})

    attendees = []
    for a in event.get("attendees", []):
        attendees.append({
            "email": a.get("email", ""),
            "name": a.get("displayName", ""),
            "response": a.get("responseStatus", ""),
            "organizer": a.get("organizer", False),
        })

    return {
        "id": event.get("id"),
        "summary": event.get("summary", "(No title)"),
        "description": event.get("description", ""),
        "location": event.get("location", ""),
        "start": start.get("dateTime") or start.get("date", ""),
        "end": end.get("dateTime") or end.get("date", ""),
        "all_day": "date" in start and "dateTime" not in start,
        "status": event.get("status", ""),
        "organizer": event.get("organizer", {}).get("email", ""),
        "attendees": attendees,
        "hangout_link": event.get("hangoutLink", ""),
        "html_link": event.get("htmlLink", ""),
        "recurring": bool(event.get("recurringEventId")),
    }
