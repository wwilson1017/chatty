"""Calendar operations — each function takes an authenticated Calendar v3 service."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _format_event(event: dict) -> dict:
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


def _event_body(
    summary: str,
    start: str,
    end: str,
    description: str = "",
    location: str = "",
    attendees: list[str] | None = None,
    timezone_str: str = "UTC",
) -> dict:
    """Build a Google Calendar event body dict.

    Accepts start/end as RFC 3339 datetimes (e.g. '2026-04-20T14:00:00-05:00')
    or as YYYY-MM-DD dates (for all-day events — not commonly used here).
    """
    is_all_day = "T" not in start
    if is_all_day:
        start_field = {"date": start}
        end_field = {"date": end}
    else:
        start_field = {"dateTime": start, "timeZone": timezone_str}
        end_field = {"dateTime": end, "timeZone": timezone_str}

    body = {
        "summary": summary,
        "start": start_field,
        "end": end_field,
    }
    if description:
        body["description"] = description
    if location:
        body["location"] = location
    if attendees:
        body["attendees"] = [{"email": e} for e in attendees]
    return body


# ── Read ops ─────────────────────────────────────────────────────────────────

def list_events_op(
    service,
    time_min: str = "",
    time_max: str = "",
    calendar_id: str = "primary",
    max_results: int = 10,
) -> list[dict]:
    """List calendar events in a time range."""
    kwargs = {
        "calendarId": calendar_id,
        "maxResults": max_results,
        "singleEvents": True,
        "orderBy": "startTime",
    }
    if time_min:
        kwargs["timeMin"] = time_min
    else:
        # Default to now
        kwargs["timeMin"] = datetime.now(timezone.utc).isoformat()
    if time_max:
        kwargs["timeMax"] = time_max

    result = service.events().list(**kwargs).execute()
    events = result.get("items", [])
    return [_format_event(e) for e in events]


def get_event_op(service, event_id: str, calendar_id: str = "primary") -> dict:
    event = service.events().get(calendarId=calendar_id, eventId=event_id).execute()
    return _format_event(event)


def search_events_op(
    service,
    query: str,
    time_min: str = "",
    time_max: str = "",
    max_results: int = 20,
    calendar_id: str = "primary",
) -> list[dict]:
    """Search events by text query. Defaults time_min to 'now' — otherwise
    orderBy=startTime expands every recurring event from the beginning of time."""
    kwargs = {
        "calendarId": calendar_id,
        "q": query,
        "maxResults": max_results,
        "singleEvents": True,
        "orderBy": "startTime",
    }
    kwargs["timeMin"] = time_min or datetime.now(timezone.utc).isoformat()
    if time_max:
        kwargs["timeMax"] = time_max

    result = service.events().list(**kwargs).execute()
    events = result.get("items", [])
    return [_format_event(e) for e in events]


def find_free_slot_op(
    service,
    duration_minutes: int,
    between_start: str,
    between_end: str,
    calendar_ids: list[str] | None = None,
    timezone_str: str = "UTC",
) -> dict:
    """Find the earliest free window of `duration_minutes` in [between_start, between_end].

    Uses calendar.freebusy.query across the supplied calendars.
    Returns {start, end, timezone} or {error} if no window fits.
    """
    cals = calendar_ids or ["primary"]
    resp = service.freebusy().query(body={
        "timeMin": between_start,
        "timeMax": between_end,
        "timeZone": timezone_str,
        "items": [{"id": c} for c in cals],
    }).execute()

    # Merge busy spans from all calendars
    busy_spans: list[tuple[datetime, datetime]] = []
    for cal_id, cal in resp.get("calendars", {}).items():
        for span in cal.get("busy", []):
            busy_spans.append((
                datetime.fromisoformat(span["start"].replace("Z", "+00:00")),
                datetime.fromisoformat(span["end"].replace("Z", "+00:00")),
            ))
    busy_spans.sort()

    start_dt = datetime.fromisoformat(between_start.replace("Z", "+00:00"))
    end_dt = datetime.fromisoformat(between_end.replace("Z", "+00:00"))
    duration = timedelta(minutes=duration_minutes)

    cursor = start_dt
    for busy_start, busy_end in busy_spans:
        if busy_end <= cursor:
            continue
        if busy_start - cursor >= duration:
            return {
                "start": cursor.isoformat(),
                "end": (cursor + duration).isoformat(),
                "timezone": timezone_str,
            }
        cursor = max(cursor, busy_end)

    if end_dt - cursor >= duration:
        return {
            "start": cursor.isoformat(),
            "end": (cursor + duration).isoformat(),
            "timezone": timezone_str,
        }
    return {"error": "No free slot of the requested duration available in the given window"}


# ── Write ops ────────────────────────────────────────────────────────────────

def create_event_op(
    service,
    summary: str,
    start: str,
    end: str,
    description: str = "",
    location: str = "",
    attendees: list[str] | None = None,
    calendar_id: str = "primary",
    timezone_str: str = "UTC",
) -> dict:
    body = _event_body(
        summary=summary,
        start=start,
        end=end,
        description=description,
        location=location,
        attendees=attendees,
        timezone_str=timezone_str,
    )
    event = service.events().insert(calendarId=calendar_id, body=body).execute()
    return {"ok": True, **_format_event(event)}


def update_event_op(
    service,
    event_id: str,
    calendar_id: str = "primary",
    summary: str | None = None,
    start: str | None = None,
    end: str | None = None,
    description: str | None = None,
    location: str | None = None,
    attendees: list[str] | None = None,
    timezone_str: str = "UTC",
) -> dict:
    """Patch-update an event. Only the non-None fields are modified."""
    patch: dict = {}
    if summary is not None:
        patch["summary"] = summary
    if description is not None:
        patch["description"] = description
    if location is not None:
        patch["location"] = location
    if start is not None:
        is_all_day = "T" not in start
        patch["start"] = {"date": start} if is_all_day else {"dateTime": start, "timeZone": timezone_str}
    if end is not None:
        is_all_day = "T" not in end
        patch["end"] = {"date": end} if is_all_day else {"dateTime": end, "timeZone": timezone_str}
    if attendees is not None:
        patch["attendees"] = [{"email": e} for e in attendees]

    event = service.events().patch(
        calendarId=calendar_id,
        eventId=event_id,
        body=patch,
    ).execute()
    return {"ok": True, **_format_event(event)}


def delete_event_op(service, event_id: str, calendar_id: str = "primary") -> dict:
    service.events().delete(calendarId=calendar_id, eventId=event_id).execute()
    return {"ok": True, "deleted_event_id": event_id}
