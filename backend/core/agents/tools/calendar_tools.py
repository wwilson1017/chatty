"""
Chatty — Google Calendar tools for agents.

Uses the user's OAuth access token (stored in CredentialStore).
Adapted from CAKE OS personal_agent/tools/calendar_tools.py.
"""

import logging

from core.calendar_client import list_events, get_event, search_events

logger = logging.getLogger(__name__)


def list_calendar_events(
    access_token: str,
    calendar_id: str = "primary",
    max_results: int = 10,
    time_min: str = "",
    time_max: str = "",
) -> dict:
    """List upcoming calendar events."""
    try:
        events = list_events(
            access_token,
            calendar_id=calendar_id,
            max_results=max_results,
            time_min=time_min or None,
            time_max=time_max or None,
        )
        return {"events": events, "count": len(events)}
    except Exception as e:
        logger.error("Calendar list_events error: %s", e)
        return {"error": str(e)}


def get_calendar_event(
    access_token: str,
    event_id: str,
    calendar_id: str = "primary",
) -> dict:
    """Get a specific calendar event by ID."""
    try:
        event = get_event(access_token, event_id, calendar_id=calendar_id)
        return event
    except Exception as e:
        logger.error("Calendar get_event error: %s", e)
        return {"error": str(e)}


def search_calendar_events(
    access_token: str,
    query: str,
    max_results: int = 10,
    calendar_id: str = "primary",
) -> dict:
    """Search calendar events by text query."""
    try:
        events = search_events(access_token, query=query, max_results=max_results, calendar_id=calendar_id)
        return {"events": events, "count": len(events)}
    except Exception as e:
        logger.error("Calendar search_events error: %s", e)
        return {"error": str(e)}
