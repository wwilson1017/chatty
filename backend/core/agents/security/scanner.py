"""Prompt injection scanner for knowledge import.

Three-position toggle (off / flag / block), configured via admin settings.
Runs at import time only -- not on every tool result (delimiters handle that).

Pattern list derived from Hermes (tools/threat_patterns.py) and OpenClaw
(src/security/external-content.ts), scoped to Chatty's attack surface.
"""

import re
from dataclasses import dataclass, field


@dataclass
class ScanResult:
    clean: bool
    findings: list[dict] = field(default_factory=list)


THREAT_PATTERNS: list[tuple[str, re.Pattern]] = [
    # Instruction override / role hijacking
    ("instruction_override", re.compile(
        r"ignore\s+(?:\w+\s+){0,5}(?:previous|all|above|prior)\s+(?:\w+\s+){0,5}instructions?",
        re.IGNORECASE,
    )),
    ("role_hijack", re.compile(
        r"you\s+are\s+(?:\w+\s+){0,5}now\s+(?:a|an|the)\s+",
        re.IGNORECASE,
    )),
    ("disregard_rules", re.compile(
        r"disregard\s+(?:\w+\s+){0,5}(?:your|all|any)\s+(?:\w+\s+){0,5}(?:instructions|rules|guidelines)",
        re.IGNORECASE,
    )),
    ("pretend_role", re.compile(
        r"pretend\s+(?:that\s+)?(?:you\s+are|to\s+be)\s+",
        re.IGNORECASE,
    )),
    ("new_instructions", re.compile(
        r"(?:new|updated|revised)\s+instructions?\s*:",
        re.IGNORECASE,
    )),

    # System prompt extraction
    ("system_prompt_extract", re.compile(
        r"(?:repeat|show|print|output|reveal|display)\s+(?:your\s+)?(?:system\s+)?(?:prompt|instructions|rules)",
        re.IGNORECASE,
    )),

    # Tool / action invocation attempts
    ("tool_invocation", re.compile(
        r"(?:call|use|invoke|execute|run)\s+(?:the\s+)?(?:tool|function)\s+",
        re.IGNORECASE,
    )),
    ("send_email_directive", re.compile(
        r"(?:send|forward)\s+(?:an?\s+)?email\s+to\s+[a-zA-Z0-9@]",
        re.IGNORECASE,
    )),
    ("destructive_action", re.compile(
        r"delete\s+(?:all|every)\s+(?:emails?|files?|data|context|memories?)",
        re.IGNORECASE,
    )),

    # Data exfiltration
    ("data_exfiltration", re.compile(
        r"(?:send|email|forward|share|post|upload|transmit)\s+(?:all\s+)?(?:data|information|files?|context|knowledge|memories?)\s+to",
        re.IGNORECASE,
    )),

    # Delimiter / boundary escape
    ("delimiter_escape", re.compile(
        r"</?\s*untrusted_tool_result[\s>]",
        re.IGNORECASE,
    )),
    ("fake_system_marker", re.compile(
        r"<system>|<\|im_start\|>system|\[System\s*Message\]|END\s+OF\s+SYSTEM\s+PROMPT|BEGIN\s+USER\s+INPUT",
        re.IGNORECASE,
    )),

    # Hidden unicode (zero-width chars used to hide instructions)
    ("hidden_unicode", re.compile(
        "[​‌‍‎‏⁠⁡⁢⁣⁤"
        "‪‫‬‭‮"
        "⁦⁧⁨⁩﻿]",
    )),

    # Encoded instruction obfuscation
    ("encoded_instructions", re.compile(
        r"(?:base64|decode|eval)\s*[:(]\s*['\"]?[A-Za-z0-9+/]{20,}={0,2}",
        re.IGNORECASE,
    )),

    # Markdown role spoofing
    ("formatting_injection", re.compile(
        r"```(?:system|assistant|user)\b",
        re.IGNORECASE,
    )),
]


# ── Memory content sanitization ──────────────────────────────────────────────
# Applied at injection time (not storage time) so stored data is unmodified.

_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_ZERO_WIDTH_RE = re.compile(
    "[​‌‍‎‏"   # ZWS, ZWNJ, ZWJ, LRM, RLM
    "⁠⁡⁢⁣⁤"     # WJ, invisible operators
    "‪‫‬‭‮"     # bidi controls
    "⁦⁧⁨⁩"           # bidi isolates
    "﻿]"                            # BOM / ZWNBSP
)
_TEMPLATE_SYNTAX_RE = re.compile(r"\{\{.*?\}\}|\$\{.*?\}")
_SCRIPT_TAG_RE = re.compile(r"<script\b[^>]*>.*?</script>", re.IGNORECASE | re.DOTALL)
_JS_URI_RE = re.compile(r"javascript\s*:", re.IGNORECASE)
_EVENT_HANDLER_RE = re.compile(
    r"\bon(?:error|load|click|mouseover|focus|blur|submit|change|input"
    r"|keydown|keyup|keypress)\s*=",
    re.IGNORECASE,
)
_SYSTEM_PREFIX_PATTERNS = [
    re.compile(
        r"ignore\s+(?:\w+\s+){0,5}(?:previous|all|above|prior)\s+(?:\w+\s+){0,5}instructions?",
        re.IGNORECASE,
    ),
    re.compile(
        r"you\s+are\s+(?:\w+\s+){0,3}now\s+(?:a|an|the)\s+"
        r"(?:helpful|evil|new|different|unrestricted|unfiltered|jailbroken|DAN)\b",
        re.IGNORECASE,
    ),
    re.compile(r"(?:new|updated|revised)\s+instructions?\s*:", re.IGNORECASE),
    re.compile(
        r"disregard\s+(?:\w+\s+){0,5}(?:your|all|any)\s+(?:\w+\s+){0,5}"
        r"(?:instructions|rules|guidelines)",
        re.IGNORECASE,
    ),
    re.compile(
        r"pretend\s+(?:that\s+)?(?:you\s+are|to\s+be)\s+(?:a\s+)?(?:\w+\s+){0,2}"
        r"(?:AI|assistant|chatbot|system|admin|hacker|agent)\b",
        re.IGNORECASE,
    ),
]
_EXCESSIVE_NEWLINES_RE = re.compile(r"\n{4,}")
_EXCESSIVE_SPACES_RE = re.compile(r" {8,}")


def sanitize_memory_content(text: str | None) -> str:
    """Strip injection patterns from memory content before system prompt injection."""
    if not text:
        return text or ""
    text = _CONTROL_CHARS_RE.sub("", text)
    text = _ZERO_WIDTH_RE.sub("", text)
    text = _TEMPLATE_SYNTAX_RE.sub("[REDACTED]", text)
    text = _SCRIPT_TAG_RE.sub("[REDACTED]", text)
    text = _JS_URI_RE.sub("[REDACTED]", text)
    text = _EVENT_HANDLER_RE.sub("[REDACTED]=", text)
    for pattern in _SYSTEM_PREFIX_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    text = _EXCESSIVE_NEWLINES_RE.sub("\n\n", text)
    text = _EXCESSIVE_SPACES_RE.sub(" ", text)
    return text


def scan_content(text: str) -> ScanResult:
    findings: list[dict] = []
    for line_num, line in enumerate(text.splitlines(), 1):
        for name, pattern in THREAT_PATTERNS:
            match = pattern.search(line)
            if match:
                findings.append({
                    "pattern_name": name,
                    "matched_text": match.group()[:100],
                    "line_number": line_num,
                })
    return ScanResult(clean=len(findings) == 0, findings=findings)
