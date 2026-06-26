"""Google Slides operations — each function takes an authenticated Slides v1 service.

Curated CRUD: get (read), create, add_slide, insert_text, replace_all_text (write).
Deleting a presentation is delete_drive_file. No public reference implementation
existed; built fresh from the Slides batchUpdate API.
"""

from __future__ import annotations

import logging
import secrets

logger = logging.getLogger(__name__)

_SLIDES_URL = "https://docs.google.com/presentation/d/{}/edit"

# Default text-box geometry (EMU). A standard slide is 9144000 x 6858000 EMU.
_BOX_W, _BOX_H = 6858000, 1200000
_BOX_X, _BOX_Y = 1143000, 1000000


def _new_id(prefix: str) -> str:
    """Generate a unique objectId (5-50 chars, [a-zA-Z0-9_-])."""
    return f"{prefix}_{secrets.token_hex(8)}"


def _extract_slide_text(page: dict) -> str:
    """Flatten all text runs on a single slide/page into plain text."""
    parts: list[str] = []
    for el in page.get("pageElements", []):
        text = el.get("shape", {}).get("text", {})
        for te in text.get("textElements", []):
            run = te.get("textRun", {})
            if run.get("content"):
                parts.append(run["content"])
    return "".join(parts)


# ── Read ─────────────────────────────────────────────────────────────────────

def get_presentation_op(service, presentation_id: str, max_chars: int = 50000) -> dict:
    """Read a presentation's title and per-slide plain text."""
    pres = service.presentations().get(presentationId=presentation_id).execute()
    slides = []
    total = 0
    truncated = False
    for page in pres.get("slides", []):
        text = _extract_slide_text(page)
        if total + len(text) > max_chars:
            text = text[: max(max_chars - total, 0)]
            truncated = True
        total += len(text)
        slides.append({"slide_object_id": page.get("objectId", ""), "text": text})
        if truncated:
            break
    return {
        "presentation_id": pres.get("presentationId", presentation_id),
        "title": pres.get("title", ""),
        "slide_count": len(pres.get("slides", [])),
        "slides": slides,
        "truncated": truncated,
        "web_link": _SLIDES_URL.format(presentation_id),
    }


# ── Write ────────────────────────────────────────────────────────────────────

def create_presentation_op(service, title: str) -> dict:
    """Create a new presentation (starts with one default slide)."""
    pres = service.presentations().create(body={"title": title}).execute()
    pres_id = pres.get("presentationId", "")
    first_slide = ""
    if pres.get("slides"):
        first_slide = pres["slides"][0].get("objectId", "")
    return {
        "ok": True, "presentation_id": pres_id,
        "title": pres.get("title", title),
        "first_slide_object_id": first_slide,
        "web_link": _SLIDES_URL.format(pres_id),
    }


def add_slide_op(service, presentation_id: str, layout: str = "BLANK") -> dict:
    """Add a new slide using a predefined layout (e.g. BLANK, TITLE, TITLE_AND_BODY)."""
    slide_id = _new_id("slide")
    service.presentations().batchUpdate(
        presentationId=presentation_id,
        body={"requests": [{
            "createSlide": {
                "objectId": slide_id,
                "slideLayoutReference": {"predefinedLayout": layout},
            }
        }]},
    ).execute()
    return {
        "ok": True, "presentation_id": presentation_id,
        "slide_object_id": slide_id, "layout": layout,
        "web_link": _SLIDES_URL.format(presentation_id),
    }


def insert_text_op(service, presentation_id: str, slide_object_id: str, text: str) -> dict:
    """Create a text box on the given slide and insert text into it."""
    box_id = _new_id("txt")
    requests = [
        {
            "createShape": {
                "objectId": box_id,
                "shapeType": "TEXT_BOX",
                "elementProperties": {
                    "pageObjectId": slide_object_id,
                    "size": {
                        "width": {"magnitude": _BOX_W, "unit": "EMU"},
                        "height": {"magnitude": _BOX_H, "unit": "EMU"},
                    },
                    "transform": {
                        "scaleX": 1, "scaleY": 1,
                        "translateX": _BOX_X, "translateY": _BOX_Y, "unit": "EMU",
                    },
                },
            }
        },
        {"insertText": {"objectId": box_id, "text": text, "insertionIndex": 0}},
    ]
    service.presentations().batchUpdate(
        presentationId=presentation_id, body={"requests": requests},
    ).execute()
    return {
        "ok": True, "presentation_id": presentation_id,
        "slide_object_id": slide_object_id, "text_box_object_id": box_id,
        "characters": len(text),
        "web_link": _SLIDES_URL.format(presentation_id),
    }


def replace_all_text_op(
    service, presentation_id: str, find: str, replace: str, match_case: bool = False,
) -> dict:
    """Replace all occurrences of `find` with `replace` across the presentation."""
    resp = service.presentations().batchUpdate(
        presentationId=presentation_id,
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
        "ok": True, "presentation_id": presentation_id,
        "occurrences_changed": changed,
        "web_link": _SLIDES_URL.format(presentation_id),
    }
