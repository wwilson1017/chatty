"""Gmail operations — each function takes an authenticated Gmail v1 service."""

from __future__ import annotations

import base64
import logging
import re
from email.message import EmailMessage
from html import unescape

logger = logging.getLogger(__name__)

_TAG_RE = re.compile(r"<[^>]+>")
_MULTI_NL = re.compile(r"\n{3,}")


# ── Helpers ──────────────────────────────────────────────────────────────────

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


def _parse_headers(headers: list[dict]) -> dict:
    result = {}
    for h in headers:
        name = h.get("name", "").lower()
        if name in ("from", "to", "subject", "date", "cc", "bcc", "message-id", "references", "in-reply-to"):
            result[name] = h.get("value", "")
    return result


def _get_body_text(payload: dict) -> str:
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


def _encode_rfc2822(msg: EmailMessage) -> str:
    """Encode an EmailMessage as a base64url string for Gmail send."""
    return base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")


# ── Read ops ─────────────────────────────────────────────────────────────────

def list_messages_op(service, query: str = "", max_results: int = 20) -> list[dict]:
    """Search messages and return summary info for each."""
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


def get_message_op(service, message_id: str) -> dict:
    """Get full message content by ID."""
    msg = service.users().messages().get(
        userId="me", id=message_id, format="full"
    ).execute()
    return _format_message(msg)


def get_thread_op(service, thread_id: str) -> dict:
    """Get all messages in a thread."""
    thread = service.users().threads().get(
        userId="me", id=thread_id, format="full"
    ).execute()
    messages = [_format_message(m) for m in thread.get("messages", [])]
    return {
        "thread_id": thread_id,
        "message_count": len(messages),
        "messages": messages,
    }


# ── Write ops ────────────────────────────────────────────────────────────────

def send_email_op(
    service,
    to: str,
    subject: str,
    body: str,
    cc: str = "",
    bcc: str = "",
) -> dict:
    """Send a new email. Returns {id, thread_id}."""
    msg = EmailMessage()
    msg["To"] = to
    if cc:
        msg["Cc"] = cc
    if bcc:
        msg["Bcc"] = bcc
    msg["Subject"] = subject
    msg.set_content(body)

    raw = _encode_rfc2822(msg)
    sent = service.users().messages().send(userId="me", body={"raw": raw}).execute()
    return {
        "ok": True,
        "id": sent.get("id"),
        "thread_id": sent.get("threadId"),
    }


def reply_to_email_op(
    service,
    message_id: str,
    body: str,
    reply_all: bool = False,
) -> dict:
    """Reply to an existing message, preserving threading headers."""
    # Fetch the original to pull headers for proper threading
    original = service.users().messages().get(
        userId="me", id=message_id, format="full"
    ).execute()
    headers = _parse_headers(original.get("payload", {}).get("headers", []))
    thread_id = original.get("threadId")
    original_msg_id = headers.get("message-id", "")
    original_refs = headers.get("references", "")
    subject = headers.get("subject", "")
    if not subject.lower().startswith("re:"):
        subject = f"Re: {subject}"

    reply = EmailMessage()
    reply["To"] = headers.get("from", "")
    if reply_all:
        # Include original to/cc minus our own address (Gmail's "me")
        cc_list = []
        if headers.get("to"):
            cc_list.append(headers["to"])
        if headers.get("cc"):
            cc_list.append(headers["cc"])
        if cc_list:
            reply["Cc"] = ", ".join(cc_list)
    reply["Subject"] = subject
    if original_msg_id:
        reply["In-Reply-To"] = original_msg_id
        reply["References"] = f"{original_refs} {original_msg_id}".strip()
    reply.set_content(body)

    raw = _encode_rfc2822(reply)
    sent = service.users().messages().send(
        userId="me",
        body={"raw": raw, "threadId": thread_id},
    ).execute()
    return {
        "ok": True,
        "id": sent.get("id"),
        "thread_id": sent.get("threadId"),
    }


def create_draft_op(
    service,
    to: str,
    subject: str,
    body: str,
    cc: str = "",
    bcc: str = "",
) -> dict:
    """Create a Gmail draft. Returns {id}."""
    msg = EmailMessage()
    msg["To"] = to
    if cc:
        msg["Cc"] = cc
    if bcc:
        msg["Bcc"] = bcc
    msg["Subject"] = subject
    msg.set_content(body)

    raw = _encode_rfc2822(msg)
    draft = service.users().drafts().create(
        userId="me",
        body={"message": {"raw": raw}},
    ).execute()
    return {
        "ok": True,
        "draft_id": draft.get("id"),
        "message_id": draft.get("message", {}).get("id"),
    }
