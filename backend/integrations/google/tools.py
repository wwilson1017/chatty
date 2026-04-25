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


def mark_email_as_read(message_id: str) -> dict:
    return _wrap(get_gmail_service, gmail_ops.mark_as_read_op,
                 message_id=message_id)


_MAX_BATCH_MARK_READ = 50


def batch_mark_emails_as_read(message_ids: list[str]) -> dict:
    if not message_ids:
        return {"error": "message_ids must be a non-empty list"}
    if len(message_ids) > _MAX_BATCH_MARK_READ:
        return {"error": f"Too many message IDs ({len(message_ids)}). Maximum is {_MAX_BATCH_MARK_READ}."}
    return _wrap(get_gmail_service, gmail_ops.batch_mark_as_read_op,
                 message_ids=message_ids)


def download_email_attachment(message_id: str, filename: str, cache_dir: str | None = None) -> dict:
    """Download an email attachment, extract text, and cache for forwarding."""
    import base64 as b64

    from integrations.google.client import get_gmail_service as _get_svc, call_with_refresh, GoogleAuthError
    from core.agents.tools.text_extraction import (
        classify_mimetype, is_text_extractable, extract_text,
        MAX_FILE_SIZE,
    )

    MAX_VISION_BYTES = 5 * 1024 * 1024
    _MAX_MIME_DEPTH = 20

    def _find_attachment_part(payload: dict, target: str, depth: int = 0) -> dict | None:
        if depth > _MAX_MIME_DEPTH:
            return None
        fn = payload.get("filename", "")
        if fn and fn.lower() == target.lower():
            return payload
        for part in payload.get("parts", []):
            found = _find_attachment_part(part, target, depth + 1)
            if found:
                return found
        return None

    def _list_attachment_names(payload: dict, depth: int = 0) -> list[str]:
        if depth > _MAX_MIME_DEPTH:
            return []
        names = []
        fn = payload.get("filename", "")
        if fn:
            names.append(fn)
        for part in payload.get("parts", []):
            names.extend(_list_attachment_names(part, depth + 1))
        return names

    def _fetch_message(service, message_id: str) -> dict:
        return service.users().messages().get(
            userId="me", id=message_id, format="full"
        ).execute()

    try:
        msg = call_with_refresh(_get_svc, _fetch_message, message_id=message_id)
    except GoogleAuthError as e:
        return {"error": str(e), "needs_reconnect": True}
    except Exception as e:
        return {"error": f"Failed to get message: {e}"}

    payload = msg.get("payload", {})
    target_part = _find_attachment_part(payload, filename)

    if not target_part:
        available = _list_attachment_names(payload)
        return {"error": f"Attachment '{filename}' not found in message", "available_attachments": available}

    attachment_id = target_part.get("body", {}).get("attachmentId", "")
    mime_type = target_part.get("mimeType", "")
    size = target_part.get("body", {}).get("size", 0)

    if size and size > MAX_FILE_SIZE:
        return {"error": f"Attachment too large ({size / (1024*1024):.1f} MB, limit {MAX_FILE_SIZE / (1024*1024):.0f} MB)"}

    if not attachment_id:
        data_b64 = target_part.get("body", {}).get("data", "")
        if data_b64:
            try:
                raw = b64.urlsafe_b64decode(data_b64 + "=" * (-len(data_b64) % 4))
            except Exception as e:
                return {"error": f"Failed to decode inline attachment data: {e}"}
        else:
            return {"error": "Attachment has no downloadable content"}
    else:
        try:
            raw = call_with_refresh(_get_svc, gmail_ops.get_attachment_content_op,
                                    message_id=message_id, attachment_id=attachment_id)
        except Exception as e:
            return {"error": f"Failed to download attachment: {e}"}

    if not raw:
        return {"error": "Attachment content is empty"}

    if len(raw) > MAX_FILE_SIZE:
        return {"error": f"Attachment too large ({len(raw) / (1024*1024):.1f} MB, limit {MAX_FILE_SIZE / (1024*1024):.0f} MB)"}

    file_type = classify_mimetype(mime_type, filename)

    file_ref = None
    if cache_dir:
        from core.agents.tools.file_cache import cache_file
        file_ref = cache_file(cache_dir, raw, filename, mime_type)

    _VISION_MEDIA_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
    if file_type == "image":
        content_base64 = b64.b64encode(raw).decode("ascii")
        result: dict = {
            "ok": True, "filename": filename, "mime_type": mime_type,
            "size_bytes": len(raw), "file_type": "image",
        }
        if file_ref:
            result["file_ref"] = file_ref
        if mime_type in _VISION_MEDIA_TYPES and len(raw) <= MAX_VISION_BYTES:
            result["_vision_image"] = {"media_type": mime_type, "data": content_base64}
        elif len(raw) > MAX_VISION_BYTES:
            result["note"] = f"Image too large for visual analysis ({len(raw) / (1024*1024):.1f} MB, limit {MAX_VISION_BYTES / (1024*1024):.0f} MB)"
        else:
            result["note"] = f"Image format {mime_type} is not supported for visual analysis"
        return result

    text_content = None
    truncated = False
    if is_text_extractable(file_type):
        text_content, truncated = extract_text(raw, file_type, 50_000)

    result = {
        "ok": True, "filename": filename, "mime_type": mime_type,
        "size_bytes": len(raw), "file_type": file_type,
        "text_extracted": bool(text_content),
    }
    if file_ref:
        result["file_ref"] = file_ref
    if text_content:
        result["text_content"] = text_content
    if truncated:
        result["truncated"] = True
    if not text_content and file_type == "binary":
        result["note"] = "Binary file — text extraction not supported. Use file_ref to forward the original."

    return result


# Max base64-encoded attachment length (~30 MB decoded)
_MAX_ATTACHMENT_BASE64_LEN = 40 * 1024 * 1024


def _resolve_attachment(
    attachment_base64: str, attachment_filename: str,
    attachment_mime_type: str, file_ref: str, cache_dir: str | None,
) -> tuple[str, str, str, dict | None]:
    """Resolve attachment content from file_ref or direct base64."""
    import base64 as b64

    if attachment_base64:
        return attachment_base64, attachment_filename, attachment_mime_type, None

    if not file_ref:
        return "", attachment_filename, attachment_mime_type, {
            "ok": False, "error": "Either file_ref or attachment_base64 is required.",
        }

    from core.agents.tools.file_cache import load_cached_file
    cached = load_cached_file(cache_dir, file_ref)
    if not cached:
        return "", attachment_filename, attachment_mime_type, {
            "ok": False, "error": "Cached file not found. The file may have expired. Please re-download it.",
        }

    b64_str = b64.b64encode(cached["raw"]).decode("ascii")
    fn = attachment_filename or cached["filename"]
    mt = cached.get("mime_type", attachment_mime_type)
    return b64_str, fn, mt, None


def send_email_with_attachment(
    to: str, subject: str, body: str,
    attachment_filename: str,
    attachment_base64: str = "",
    attachment_mime_type: str = "application/pdf",
    cc: str = "", bcc: str = "",
    file_ref: str = "",
    cache_dir: str | None = None,
) -> dict:
    """Send a new email with a file attachment."""
    att_b64, att_fn, att_mt, err = _resolve_attachment(
        attachment_base64, attachment_filename, attachment_mime_type, file_ref, cache_dir,
    )
    if err:
        return err

    if len(att_b64) > _MAX_ATTACHMENT_BASE64_LEN:
        decoded_mb = (len(att_b64) * 3 / 4) / (1024 * 1024)
        return {"ok": False, "error": f"Attachment too large (~{decoded_mb:.1f} MB). Gmail rejects messages over ~35 MB."}

    attachments = [{"filename": att_fn, "content_base64": att_b64, "mime_type": att_mt}]
    return _wrap(get_gmail_service, gmail_ops.send_email_op,
                 to=to, subject=subject, body=body, cc=cc, bcc=bcc,
                 attachments=attachments)


def reply_to_email_with_attachment(
    message_id: str, body: str,
    attachment_filename: str,
    attachment_base64: str = "",
    attachment_mime_type: str = "application/pdf",
    reply_all: bool = False,
    file_ref: str = "",
    cache_dir: str | None = None,
) -> dict:
    """Reply to an existing email thread with a file attachment."""
    att_b64, att_fn, att_mt, err = _resolve_attachment(
        attachment_base64, attachment_filename, attachment_mime_type, file_ref, cache_dir,
    )
    if err:
        return err

    if len(att_b64) > _MAX_ATTACHMENT_BASE64_LEN:
        decoded_mb = (len(att_b64) * 3 / 4) / (1024 * 1024)
        return {"ok": False, "error": f"Attachment too large (~{decoded_mb:.1f} MB). Gmail rejects messages over ~35 MB."}

    attachments = [{"filename": att_fn, "content_base64": att_b64, "mime_type": att_mt}]
    return _wrap(get_gmail_service, gmail_ops.reply_to_email_op,
                 message_id=message_id, body=body,
                 reply_all=reply_all, attachments=attachments)


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

def search_drive_files(query: str, max_results: int = 20) -> dict:
    result = _wrap(get_drive_service, drive_ops.search_files_op,
                   query=query, max_results=max_results)
    if isinstance(result, list):
        return {"count": len(result), "query": query, "files": result}
    return result


def list_drive_folder(folder_id: str = "root", max_results: int = 50) -> dict:
    result = _wrap(get_drive_service, drive_ops.list_folder_op,
                   folder_id=folder_id, max_results=max_results)
    if isinstance(result, list):
        return {"count": len(result), "folder_id": folder_id, "files": result}
    return result


def get_drive_file_info(file_id: str) -> dict:
    return _wrap(get_drive_service, drive_ops.get_file_info_op, file_id=file_id)


def read_drive_file_content(file_id: str, max_chars: int = 50000) -> dict:
    return _wrap(get_drive_service, drive_ops.read_file_content_op,
                 file_id=file_id, max_chars=max_chars)


def create_drive_folder(name: str, parent_folder_id: str = "root") -> dict:
    return _wrap(get_drive_service, drive_ops.create_folder_op,
                 name=name, parent_folder_id=parent_folder_id)


def create_drive_file(
    name: str, content: str = "", file_type: str = "document", folder_id: str = "root",
) -> dict:
    return _wrap(get_drive_service, drive_ops.create_file_op,
                 name=name, content=content, file_type=file_type, folder_id=folder_id)


def move_drive_file(file_id: str, new_parent_id: str) -> dict:
    return _wrap(get_drive_service, drive_ops.move_file_op,
                 file_id=file_id, new_parent_id=new_parent_id)


def rename_drive_file(file_id: str, new_name: str) -> dict:
    return _wrap(get_drive_service, drive_ops.rename_file_op,
                 file_id=file_id, new_name=new_name)


def copy_drive_file(file_id: str, new_name: str | None = None, folder_id: str | None = None) -> dict:
    return _wrap(get_drive_service, drive_ops.copy_file_op,
                 file_id=file_id, new_name=new_name, folder_id=folder_id)
