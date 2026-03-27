"""Shared utilities for Odoo tools."""

import re
from html import unescape

_TAG_RE = re.compile(r"<[^>]+>")
_MULTI_NL = re.compile(r"\n{3,}")


def html_to_text(html: str) -> str:
    """Strip HTML tags and decode entities to plain text."""
    if not html:
        return ""
    text = html.replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
    text = text.replace("</p>", "\n\n").replace("</div>", "\n")
    text = _TAG_RE.sub("", text)
    text = unescape(text)
    text = _MULTI_NL.sub("\n\n", text).strip()
    return text


def flatten_m2o(record: dict) -> dict:
    """Flatten Many2one fields from [id, name] to name string + _id int."""
    row = {}
    for key, val in record.items():
        if isinstance(val, list) and len(val) == 2 and isinstance(val[0], int):
            row[key] = val[1]
            row[f"{key}_id"] = val[0]
        else:
            row[key] = val
    return row


def safe_get_client():
    """Return (client, None) or (None, error_dict)."""
    from .client import get_client

    client = get_client()
    if not client:
        return None, {"error": "Odoo not configured or unavailable"}
    return client, None
