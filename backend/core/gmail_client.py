"""
Chatty — Gmail API Client

Uses the user's OAuth access token (from data/auth-profiles.json under
google:default) instead of a service account. No admin/domain-wide delegation
required — the user authorizes Gmail access during the Google OAuth flow.
"""

import base64
import logging
import re
from html import unescape

logger = logging.getLogger(__name__)

_TAG_RE = re.compile(r"<[^>]+>")
_MULTI_NL = re.compile(r"\n{3,}")


def _html_to_text(html: str) -> str:
    """Strip HTML tags and decode entities to plain text."""
    if not html:
        return ""
    text = html.replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
    text = text.replace("</p>", "\n\n").replace("</div>", "\n")
    text = _TAG_RE.sub("", text)
    text = unescape(text)
    text = _MULTI_NL.sub("\n\n", text).strip()
    return text


def get_gmail_service(access_token: str):
    """Build an authenticated Gmail API service from a user OAuth access token.

    Args:
        access_token: The user's Google OAuth access token.
                      Stored in data/auth-profiles.json under google:default.
    """
    if not access_token:
        logger.warning("No Google access token provided for Gmail")
        return None

    try:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
    except ImportError:
        logger.warning("Google API libraries not installed")
        return None

    try:
        credentials = Credentials(token=access_token)
        service = build("gmail", "v1", credentials=credentials)
        return service
    except Exception as e:
        logger.error("Gmail service build failed: %s", e)
        return None


def _parse_headers(headers: list[dict]) -> dict:
    """Extract common headers into a flat dict."""
    result = {}
    for h in headers:
        name = h.get("name", "").lower()
        if name in ("from", "to", "subject", "date", "cc", "bcc"):
            result[name] = h.get("value", "")
    return result


def _get_body_text(payload: dict) -> str:
    """Recursively extract the plain text body from a message payload."""
    mime_type = payload.get("mimeType", "")

    if mime_type == "text/plain":
        data = payload.get("body", {}).get("data", "")
        if data:
            return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")

    if mime_type == "text/html":
        data = payload.get("body", {}).get("data", "")
        if data:
            html = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
            return _html_to_text(html)

    parts = payload.get("parts", [])
    plain_text = ""
    html_text = ""
    for part in parts:
        part_mime = part.get("mimeType", "")
        if part_mime == "text/plain":
            data = part.get("body", {}).get("data", "")
            if data:
                plain_text = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
        elif part_mime == "text/html":
            data = part.get("body", {}).get("data", "")
            if data:
                html = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
                html_text = _html_to_text(html)
        elif part_mime.startswith("multipart/"):
            nested = _get_body_text(part)
            if nested:
                return nested

    return plain_text or html_text


def _get_attachments(payload: dict) -> list[dict]:
    """Extract attachment metadata from a message payload."""
    attachments = []
    parts = payload.get("parts", [])
    for part in parts:
        filename = part.get("filename", "")
        if filename:
            attachments.append({
                "filename": filename,
                "mime_type": part.get("mimeType", ""),
                "size": part.get("body", {}).get("size", 0),
            })
        if part.get("parts"):
            attachments.extend(_get_attachments(part))
    return attachments


def _format_message(msg: dict) -> dict:
    """Format a full Gmail message into a clean dict."""
    payload = msg.get("payload", {})
    headers = _parse_headers(payload.get("headers", []))
    label_ids = msg.get("labelIds", [])

    return {
        "id": msg.get("id"),
        "thread_id": msg.get("threadId"),
        "from": headers.get("from", ""),
        "to": headers.get("to", ""),
        "cc": headers.get("cc", ""),
        "subject": headers.get("subject", ""),
        "date": headers.get("date", ""),
        "snippet": msg.get("snippet", ""),
        "is_unread": "UNREAD" in label_ids,
        "labels": label_ids,
        "body": _get_body_text(payload),
        "attachments": _get_attachments(payload),
    }


def list_messages(service, query: str = "", max_results: int = 20) -> list[dict]:
    """Search messages and return summary info for each."""
    try:
        results = service.users().messages().list(
            userId="me", q=query, maxResults=max_results
        ).execute()

        messages = results.get("messages", [])
        if not messages:
            return []

        summaries = []
        for msg_ref in messages:
            msg = service.users().messages().get(
                userId="me", id=msg_ref["id"], format="metadata",
                metadataHeaders=["From", "To", "Subject", "Date"],
            ).execute()
            headers = _parse_headers(msg.get("payload", {}).get("headers", []))
            label_ids = msg.get("labelIds", [])
            summaries.append({
                "id": msg["id"],
                "thread_id": msg.get("threadId"),
                "from": headers.get("from", ""),
                "to": headers.get("to", ""),
                "subject": headers.get("subject", ""),
                "date": headers.get("date", ""),
                "snippet": msg.get("snippet", ""),
                "is_unread": "UNREAD" in label_ids,
            })

        return summaries
    except Exception as e:
        logger.error("Gmail list_messages failed: %s", e)
        raise


def get_message(service, message_id: str) -> dict:
    """Get full message content by ID."""
    try:
        msg = service.users().messages().get(
            userId="me", id=message_id, format="full"
        ).execute()
        return _format_message(msg)
    except Exception as e:
        logger.error("Gmail get_message failed: %s", e)
        raise


def get_thread(service, thread_id: str) -> dict:
    """Get all messages in a thread."""
    try:
        thread = service.users().threads().get(
            userId="me", id=thread_id, format="full"
        ).execute()
        messages = [_format_message(m) for m in thread.get("messages", [])]
        return {
            "thread_id": thread_id,
            "message_count": len(messages),
            "messages": messages,
        }
    except Exception as e:
        logger.error("Gmail get_thread failed: %s", e)
        raise
