"""Scrub secrets and credential-like values from text before LLM processing."""

from __future__ import annotations

import re

REPLACEMENT = "[REDACTED:credential]"
FRONT_MATTER_RE = re.compile(r"^---\n[\s\S]*?\n---\n?")

_PATTERNS: list[re.Pattern] = [
    re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"AIza[A-Za-z0-9_-]{30,}"),
    re.compile(r"ghp_[A-Za-z0-9]{36,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"xox[abpr]-[A-Za-z0-9-]{10,}"),
    re.compile(r"(?<![A-Za-z0-9])AKIA[A-Z0-9]{16}"),
    re.compile(r"gho_[A-Za-z0-9]{36,}"),
    re.compile(r"glpat-[A-Za-z0-9_-]{20,}"),
    # JWT-shaped: three base64url segments separated by dots
    re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
    # Generic long hex string tagged as a token/key (preceded by key= or token= etc.)
    re.compile(r"(?:key|token|secret|password|credential)\s*[=:]\s*['\"]?([A-Fa-f0-9]{32,})['\"]?", re.IGNORECASE),
]

SKIP_FILENAME_PATTERNS: list[re.Pattern] = [
    re.compile(r"\.env", re.IGNORECASE),
    re.compile(r"secret", re.IGNORECASE),
    re.compile(r"credential", re.IGNORECASE),
    re.compile(r"\.git[\\/]"),
    re.compile(r"node_modules[\\/]"),
    re.compile(r"\.dev\.md$", re.IGNORECASE),
]


def scrub(text: str) -> tuple[str, int]:
    """Remove credential-like values from text.

    Returns (scrubbed_text, redaction_count).
    """
    count = 0
    for pattern in _PATTERNS:
        matches = pattern.findall(text)
        if matches:
            count += len(matches)
            text = pattern.sub(REPLACEMENT, text)
    return text, count


def should_skip_file(filename: str) -> bool:
    """Return True if a filename matches skip patterns."""
    return any(p.search(filename) for p in SKIP_FILENAME_PATTERNS)
