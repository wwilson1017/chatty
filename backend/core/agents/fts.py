"""Shared FTS5 utilities for chat history and memory search."""

import re

_FTS_SPECIAL = re.compile(r'["\*\(\)\+\-\^~:]')


def sanitize_fts_query(raw: str) -> str:
    """Escape special FTS5 characters and wrap each token in quotes for safety."""
    raw = _FTS_SPECIAL.sub(" ", raw)
    tokens = raw.split()
    if not tokens:
        return '""'
    return " ".join(f'"{t}"' for t in tokens if t.strip())
