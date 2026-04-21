"""
Chatty — Google tool handlers (Gmail + Calendar + Drive).

These are the functions that ToolRegistry._execute_gmail /
_execute_calendar / _execute_drive dispatch to. Each wraps the underlying
ops with call_with_refresh() for automatic token refresh on 401.
"""

from __future__ import annotations

import logging

from .client import (
    GoogleAuthError,
    call_with_refresh,
    get_calendar_service,
    get_drive_service,
    get_gmail_service,
)
from . import gmail_ops, calendar_ops, drive_ops

logger = logging.getLogger(__name__)


def _wrap(service_factory, op, **kwargs):
    """Call an op with auto-refresh; surface GoogleAuthError + generic errors as dicts."""
    try:
        return call_with_refresh(service_factory, op, **kwargs)
    except GoogleAuthError as e:
        return {"error": str(e), "needs_reconnect": True}
    except Exception as e:
        logger.error("Google op %s failed: %s", getattr(op, "__name__", op), e)
        return {"error": str(e)}


# ── Gmail ────────────────────────────────────────────────────────────────────

def search_emails(query: str, max_results: int = 10) -> dict:
    result = _wrap(get_gmail_service, gmail_ops.list_messages_op, query=query, max_results=max_results)
    if isinstance(result, list):
        return {"messages": result, "count": len(result)}
    return result


def get_email(message_id: str) -> dict:
    return _wrap(get_gmail_service, gmail_ops.get_message_op, message_id=message_id)


def get_email_thread(thread_id: str) -> dict:
    return _wrap(get_gmail_service, gmail_ops.get_thread_op, thread_id=thread_id)


def send_email(to: str, subject: str, body: str, cc: str = "", bcc: str = "") -> dict:
    return _wrap(get_gmail_service, gmail_ops.send_email_op,
                 to=to, subject=subject, body=body, cc=cc, bcc=bcc)


def reply_to_email(message_id: str, body: str, reply_all: bool = False) -> dict:
    return _wrap(get_gmail_service, gmail_ops.reply_to_email_op,
                 message_id=message_id, body=body, reply_all=reply_all)


def create_draft(to: str, subject: str, body: str, cc: str = "", bcc: str = "") -> dict:
    return _wrap(get_gmail_service, gmail_ops.create_draft_op,
                 to=to, subject=subject, body=body, cc=cc, bcc=bcc)


# ── Calendar ─────────────────────────────────────────────────────────────────

def _user_timezone() -> str:
    """Read the cached timezone from data/integrations/google.json."""
    try:
        from integrations.registry import get_credentials
        creds = get_credentials("google")
        return creds.get("calendar_timezone", "UTC") or "UTC"
    except Exception:
        return "UTC"


def list_calendar_events(
    time_min: str = "",
    time_max: str = "",
    calendar_id: str = "primary",
    max_results: int = 10,
) -> dict:
    result = _wrap(
        get_calendar_service, calendar_ops.list_events_op,
        time_min=time_min, time_max=time_max,
        calendar_id=calendar_id, max_results=max_results,
    )
    if isinstance(result, list):
        return {"events": result, "count": len(result)}
    return result


def get_calendar_event(event_id: str, calendar_id: str = "primary") -> dict:
    return _wrap(get_calendar_service, calendar_ops.get_event_op,
                 event_id=event_id, calendar_id=calendar_id)


def search_calendar_events(
    query: str,
    time_min: str = "",
    time_max: str = "",
    max_results: int = 20,
    calendar_id: str = "primary",
) -> dict:
    result = _wrap(
        get_calendar_service, calendar_ops.search_events_op,
        query=query, time_min=time_min, time_max=time_max,
        max_results=max_results, calendar_id=calendar_id,
    )
    if isinstance(result, list):
        return {"events": result, "count": len(result)}
    return result


def find_free_slot(
    duration_minutes: int,
    between_start: str,
    between_end: str,
    calendar_ids: list[str] | None = None,
) -> dict:
    return _wrap(
        get_calendar_service, calendar_ops.find_free_slot_op,
        duration_minutes=duration_minutes,
        between_start=between_start, between_end=between_end,
        calendar_ids=calendar_ids, timezone_str=_user_timezone(),
    )


def create_calendar_event(
    summary: str,
    start: str,
    end: str,
    description: str = "",
    location: str = "",
    attendees: list[str] | None = None,
    calendar_id: str = "primary",
) -> dict:
    return _wrap(
        get_calendar_service, calendar_ops.create_event_op,
        summary=summary, start=start, end=end,
        description=description, location=location,
        attendees=attendees, calendar_id=calendar_id,
        timezone_str=_user_timezone(),
    )


def update_calendar_event(
    event_id: str,
    calendar_id: str = "primary",
    summary: str | None = None,
    start: str | None = None,
    end: str | None = None,
    description: str | None = None,
    location: str | None = None,
    attendees: list[str] | None = None,
) -> dict:
    return _wrap(
        get_calendar_service, calendar_ops.update_event_op,
        event_id=event_id, calendar_id=calendar_id,
        summary=summary, start=start, end=end,
        description=description, location=location, attendees=attendees,
        timezone_str=_user_timezone(),
    )


def delete_calendar_event(event_id: str, calendar_id: str = "primary") -> dict:
    return _wrap(get_calendar_service, calendar_ops.delete_event_op,
                 event_id=event_id, calendar_id=calendar_id)


# ── Drive ────────────────────────────────────────────────────────────────────

def list_drive_files(query: str = "", folder_id: str = "", max_results: int = 20) -> dict:
    result = _wrap(get_drive_service, drive_ops.list_files_op,
                   query=query, folder_id=folder_id, max_results=max_results)
    if isinstance(result, list):
        return {"files": result, "count": len(result)}
    return result


def search_drive_files(name_contains: str = "", mime_type: str = "", max_results: int = 20) -> dict:
    result = _wrap(get_drive_service, drive_ops.search_files_op,
                   name_contains=name_contains, mime_type=mime_type, max_results=max_results)
    if isinstance(result, list):
        return {"files": result, "count": len(result)}
    return result


def get_drive_file_content(file_id: str, as_format: str = "default") -> dict:
    return _wrap(get_drive_service, drive_ops.get_file_content_op,
                 file_id=file_id, as_format=as_format)


def upload_drive_file(
    filename: str,
    content: str,
    mime_type: str = "text/plain",
    parent_folder_id: str = "",
) -> dict:
    return _wrap(
        get_drive_service, drive_ops.upload_file_op,
        filename=filename, content=content,
        mime_type=mime_type, parent_folder_id=parent_folder_id,
    )
