"""AI-powered contact import — parses any file format into CRM contacts.

Layered strategy: deterministic parsing for known formats (vCard, standard CSV),
AI fallback for everything else (Google CSV, JSON, plain text, etc.).
"""

import asyncio
import csv
import io
import json
import logging
import re
import quopri
from dataclasses import dataclass, field

from core.providers import get_ai_provider

logger = logging.getLogger(__name__)

MAX_AI_CONTENT_BYTES = 200_000

CONTACT_FIELDS = ("name", "email", "phone", "company", "title", "source", "tags", "notes")

COLUMN_ALIASES = {
    "name": ["name", "full_name", "full name", "contact_name", "contact name"],
    "email": ["email", "email_address", "email address", "e-mail"],
    "phone": ["phone", "phone_number", "phone number", "tel", "telephone"],
    "company": ["company", "company_name", "company name", "organization", "org"],
    "title": ["title", "job_title", "job title", "position", "role"],
    "source": ["source", "lead_source", "lead source", "origin"],
    "tags": ["tags", "labels", "categories"],
    "notes": ["notes", "note", "comments", "description"],
}

_AI_SYSTEM_PROMPT = """You are a contact data extraction specialist. Parse the provided file content and extract all contacts you can find.

Return a JSON array of contacts. Each contact object should have these fields (all optional except name):
- name (required): Full name of the person
- email: Email address
- phone: Phone number
- company: Company or organization name
- title: Job title or position
- source: Where this contact came from (e.g., "iPhone", "Gmail", "business card")
- tags: Comma-separated tags if apparent from the data
- notes: Any additional information worth preserving that doesn't fit other fields

Rules:
1. Return ONLY a valid JSON array. No markdown fences, no explanation, no other text.
2. If the input is CSV, map columns intelligently even if they don't match standard names.
3. If the input is freeform text, extract any contact information you can identify.
4. Combine first name + last name fields into a single "name" field.
5. For phone numbers, preserve the original formatting.
6. Skip entries that have no identifiable information (no name, no email, no phone).
7. If "source" is not evident from the data, leave it empty."""


@dataclass
class SmartImportResult:
    contacts: list[dict] = field(default_factory=list)
    ai_used: bool = False
    warnings: list[str] = field(default_factory=list)


def parse_contacts(content: str, filename: str) -> SmartImportResult:
    """Parse contacts from any file format. Returns structured contacts for preview."""
    if not content.strip():
        return SmartImportResult(warnings=["File is empty"])

    if b"\x00" in content[:8192].encode("utf-8", errors="replace"):
        return SmartImportResult(warnings=["Binary files are not supported. Please export your contacts as CSV, vCard (.vcf), or text."])

    stripped = content.strip()

    if stripped.startswith("BEGIN:VCARD"):
        contacts = _parse_vcf(content)
        result = SmartImportResult(contacts=contacts, ai_used=False)
        if not contacts:
            result.warnings.append("No contacts found in vCard file")
        return result

    if filename.lower().endswith(".csv"):
        csv_result = _try_csv_deterministic(content)
        if csv_result is not None:
            result = SmartImportResult(contacts=csv_result, ai_used=False)
            if not csv_result:
                result.warnings.append("No contacts found in CSV file")
            return result

    return _parse_with_ai(content, filename)


# ── vCard parser ──────────────────────────────────────────────────────────────


def _unfold_lines(text: str) -> str:
    """RFC 6350: continuation lines start with a space or tab."""
    return re.sub(r"\r?\n[ \t]", "", text)


def _decode_value(value: str, params: str) -> str:
    """Decode quoted-printable or base64 encoded values."""
    param_upper = params.upper()
    if "ENCODING=QUOTED-PRINTABLE" in param_upper:
        try:
            return quopri.decodestring(value.encode("utf-8")).decode("utf-8", errors="replace")
        except Exception:
            return value
    return value


def _parse_vcf(content: str) -> list[dict]:
    """Parse vCard (.vcf) content into contact dicts."""
    content = _unfold_lines(content)
    contacts = []
    current: dict | None = None

    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        if line.upper() == "BEGIN:VCARD":
            current = {}
            continue

        if line.upper() == "END:VCARD":
            if current:
                contact = _vcf_entry_to_contact(current)
                if contact:
                    contacts.append(contact)
            current = None
            continue

        if current is None:
            continue

        if ":" not in line:
            continue

        key_part, value = line.split(":", 1)
        parts = key_part.split(";")
        prop = parts[0].upper()
        params = ";".join(parts[1:])
        value = _decode_value(value, params)

        if prop == "FN":
            current["fn"] = value.strip()
        elif prop == "N":
            current.setdefault("n", value.strip())
        elif prop == "EMAIL":
            current.setdefault("email", value.strip())
        elif prop == "TEL":
            current.setdefault("phone", value.strip())
        elif prop == "ORG":
            current["org"] = value.replace(";", " ").strip()
        elif prop == "TITLE":
            current["title"] = value.strip()
        elif prop == "NOTE":
            current["note"] = value.strip()

    return contacts


def _vcf_entry_to_contact(entry: dict) -> dict | None:
    """Convert a raw vCard entry dict to a normalized contact dict."""
    name = entry.get("fn", "")
    if not name:
        n_val = entry.get("n", "")
        if n_val:
            parts = n_val.split(";")
            last = parts[0].strip() if len(parts) > 0 else ""
            first = parts[1].strip() if len(parts) > 1 else ""
            name = f"{first} {last}".strip()

    if not name and not entry.get("email") and not entry.get("phone"):
        return None

    return {
        "name": name,
        "email": entry.get("email", ""),
        "phone": entry.get("phone", ""),
        "company": entry.get("org", ""),
        "title": entry.get("title", ""),
        "source": "vCard",
        "tags": "",
        "notes": entry.get("note", ""),
    }


# ── CSV deterministic parser ─────────────────────────────────────────────────


def _try_csv_deterministic(content: str) -> list[dict] | None:
    """Try to parse CSV with standard column matching. Returns None if headers don't match."""
    try:
        reader = csv.DictReader(io.StringIO(content))
        if not reader.fieldnames:
            return None
    except Exception:
        return None

    field_map = {f.strip().lower(): f for f in reader.fieldnames}

    def _resolve(target: str) -> str | None:
        for alias in COLUMN_ALIASES.get(target, []):
            if alias in field_map:
                return field_map[alias]
        return None

    name_col = _resolve("name")
    if not name_col:
        return None

    contacts = []
    for row in reader:
        name = (row.get(name_col) or "").strip()
        if not name:
            continue
        contacts.append({
            "name": name,
            "email": (row.get(_resolve("email") or "", "") or "").strip(),
            "phone": (row.get(_resolve("phone") or "", "") or "").strip(),
            "company": (row.get(_resolve("company") or "", "") or "").strip(),
            "title": (row.get(_resolve("title") or "", "") or "").strip(),
            "source": (row.get(_resolve("source") or "", "") or "").strip(),
            "tags": (row.get(_resolve("tags") or "", "") or "").strip(),
            "notes": (row.get(_resolve("notes") or "", "") or "").strip(),
        })

    return contacts


# ── AI-powered parser ─────────────────────────────────────────────────────────


def _parse_with_ai(content: str, filename: str) -> SmartImportResult:
    """Use the configured AI provider to parse contacts from arbitrary content."""
    provider = get_ai_provider()
    if not provider:
        return SmartImportResult(warnings=[
            "No AI provider configured. Only CSV and vCard (.vcf) formats are supported without AI. "
            "Set up an AI provider in Settings to import other formats."
        ])

    if len(content) > MAX_AI_CONTENT_BYTES:
        content = content[:MAX_AI_CONTENT_BYTES]
        truncated = True
    else:
        truncated = False

    user_message = f"Filename: {filename}\n\nFile content:\n{content}"
    messages = [{"role": "user", "content": user_message}]

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(asyncio.run, _call_ai(provider, messages))
            raw_text = future.result(timeout=60)
    else:
        raw_text = asyncio.run(_call_ai(provider, messages))

    contacts, parse_warnings = _extract_contacts_from_ai_response(raw_text)

    result = SmartImportResult(contacts=contacts, ai_used=True, warnings=parse_warnings)
    if truncated:
        result.warnings.insert(0, "File was truncated to 200KB for AI processing. Some contacts may be missing.")
    if not contacts:
        result.warnings.append("AI could not extract any contacts from this file.")
    return result


async def _call_ai(provider, messages: list[dict]) -> str:
    """Make a single AI call with no tools, collecting the text response."""
    text = ""
    async for event in provider.stream_turn(messages, [], _AI_SYSTEM_PROMPT):
        if event.get("type") == "text":
            text += event["text"]
        elif event.get("type") == "_turn_complete":
            break
    return text


def _extract_contacts_from_ai_response(raw: str) -> tuple[list[dict], list[str]]:
    """Parse JSON contacts from AI response text, handling common formatting issues."""
    warnings: list[str] = []

    text = raw.strip()
    fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence_match:
        text = fence_match.group(1).strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        bracket_match = re.search(r"\[[\s\S]*\]", text)
        if bracket_match:
            try:
                parsed = json.loads(bracket_match.group())
            except json.JSONDecodeError:
                return [], ["Failed to parse AI response as JSON. Please try a CSV or vCard file."]
        else:
            return [], ["Failed to parse AI response as JSON. Please try a CSV or vCard file."]

    if isinstance(parsed, dict) and len(parsed) == 1:
        val = next(iter(parsed.values()))
        if isinstance(val, list):
            parsed = val

    if not isinstance(parsed, list):
        return [], ["AI returned unexpected format. Please try a CSV or vCard file."]

    contacts = []
    skipped = 0
    for entry in parsed:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name", "") or "").strip()
        email = str(entry.get("email", "") or "").strip()
        phone = str(entry.get("phone", "") or "").strip()
        if not name and not email and not phone:
            skipped += 1
            continue
        contacts.append({
            field: str(entry.get(field, "") or "").strip()
            for field in CONTACT_FIELDS
        })

    if skipped:
        warnings.append(f"{skipped} entries skipped (no name, email, or phone)")

    return contacts, warnings
