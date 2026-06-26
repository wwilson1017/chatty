"""Google Docs operations — each function takes an authenticated Docs v1 service.

Curated CRUD: get (read), create, insert_text, append_text, replace_text.
Listing/finding Docs is done via Drive search; deleting is delete_drive_file.
batchUpdate request-building patterns adapted from the Hermes agent.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_DOC_URL = "https://docs.google.com/document/d/{}/edit"


def _extract_doc_text(doc: dict) -> str:
    """Flatten a Docs document's structured body into plain text."""
    parts: list[str] = []
    for element in doc.get("body", {}).get("content", []):
        paragraph = element.get("paragraph", {})
        for pe in paragraph.get("elements", []):
            run = pe.get("textRun", {})
            if run.get("content"):
                parts.append(run["content"])
    return "".join(parts)


def _end_index(doc: dict) -> int:
    """Return the insert index just before the document body's trailing newline.

    Docs indexes are 1-based and the body always ends with a newline at the
    last index, so we insert at endIndex - 1 to append at the true end.
    """
    end = 1
    for element in doc.get("body", {}).get("content", []):
        ei = element.get("endIndex")
        if isinstance(ei, int) and ei > end:
            end = ei
    return max(end - 1, 1)


# ── Read ─────────────────────────────────────────────────────────────────────

def get_document_op(service, document_id: str, max_chars: int = 50000) -> dict:
    """Read a Google Doc's title and plain-text body (truncated to max_chars)."""
    doc = service.documents().get(documentId=document_id).execute()
    body = _extract_doc_text(doc)
    return {
        "document_id": doc.get("documentId", document_id),
        "title": doc.get("title", ""),
        "content": body[:max_chars],
        "truncated": len(body) > max_chars,
        "char_count": len(body),
        "web_link": _DOC_URL.format(document_id),
    }


# ── Write ────────────────────────────────────────────────────────────────────

def create_document_op(service, title: str, content: str = "") -> dict:
    """Create a new Google Doc, optionally seeded with initial body text."""
    doc = service.documents().create(body={"title": title}).execute()
    doc_id = doc.get("documentId", "")
    if content and doc_id:
        service.documents().batchUpdate(
            documentId=doc_id,
            body={"requests": [{"insertText": {"location": {"index": 1}, "text": content}}]},
        ).execute()
    return {
        "ok": True,
        "document_id": doc_id,
        "title": doc.get("title", title),
        "web_link": _DOC_URL.format(doc_id),
    }


def insert_text_op(service, document_id: str, text: str, index: int = 1) -> dict:
    """Insert text at a 1-based character index (default 1 = start of body)."""
    if index < 1:
        index = 1
    service.documents().batchUpdate(
        documentId=document_id,
        body={"requests": [{"insertText": {"location": {"index": index}, "text": text}}]},
    ).execute()
    return {
        "ok": True, "document_id": document_id,
        "inserted_at": index, "characters": len(text),
        "web_link": _DOC_URL.format(document_id),
    }


def append_text_op(service, document_id: str, text: str) -> dict:
    """Append text to the end of the document body."""
    doc = service.documents().get(documentId=document_id).execute()
    index = _end_index(doc)
    body_text = text if text.startswith("\n") else "\n" + text
    service.documents().batchUpdate(
        documentId=document_id,
        body={"requests": [{"insertText": {"location": {"index": index}, "text": body_text}}]},
    ).execute()
    return {
        "ok": True, "document_id": document_id,
        "inserted_at": index, "characters": len(body_text),
        "web_link": _DOC_URL.format(document_id),
    }


def replace_text_op(
    service, document_id: str, find: str, replace: str, match_case: bool = False,
) -> dict:
    """Find-and-replace all occurrences of `find` with `replace`."""
    resp = service.documents().batchUpdate(
        documentId=document_id,
        body={"requests": [{
            "replaceAllText": {
                "containsText": {"text": find, "matchCase": match_case},
                "replaceText": replace,
            }
        }]},
    ).execute()
    replies = resp.get("replies", [])
    changed = 0
    if replies:
        changed = replies[0].get("replaceAllText", {}).get("occurrencesChanged", 0) or 0
    return {
        "ok": True, "document_id": document_id,
        "occurrences_changed": changed,
        "web_link": _DOC_URL.format(document_id),
    }
