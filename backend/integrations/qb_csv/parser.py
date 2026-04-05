"""
Chatty — QuickBooks CSV parser and entity auto-detection.

Detects QBO export entity types from column headers and filename hints,
normalizes rows, and parses dates for SQLite storage.
"""

import csv
import io
import json
import logging
import re
from datetime import datetime

logger = logging.getLogger(__name__)

# ── Filename hints (fast path) ────────────────────────────────────────────────

FILENAME_HINTS: dict[str, str] = {
    "account": "accounts",
    "chart": "accounts",
    "coa": "accounts",
    "customer": "customers",
    "client": "customers",
    "vendor": "vendors",
    "supplier": "vendors",
    "invoice": "invoices",
    "bill": "bills",
    "expense": "expenses",
    "purchase": "expenses",
    "payment": "payments",
    "product": "products",
    "service": "products",
    "item": "products",
    "journal": "journal_entries",
}

# ── Entity signatures (column-based detection) ───────────────────────────────

# Each entity type has required columns (all must match) and optional columns
# (boost the score). Column names are lowercase.
ENTITY_SIGNATURES: dict[str, dict] = {
    "accounts": {
        "required": [["name", "account name", "account"]],
        "required_any": [["type", "account type"]],
        "optional": ["detail type", "detail_type", "description", "balance", "currency"],
    },
    "customers": {
        "required": [["display name", "customer", "customer name", "client name"]],
        "optional": ["email", "phone", "balance", "billing address", "billing street",
                      "first name", "last name", "company", "notes"],
    },
    "vendors": {
        "required": [["display name", "vendor", "vendor name", "supplier name"]],
        "optional": ["email", "phone", "balance", "1099 vendor", "1099",
                      "address", "company", "notes"],
        "distinguishing": ["1099 vendor", "1099", "vendor name"],
    },
    "invoices": {
        "required": [["invoice no", "invoice #", "invoice number", "invoice", "num"]],
        "optional": ["customer", "date", "due date", "amount", "balance", "status",
                      "terms", "memo", "item", "quantity"],
    },
    "bills": {
        "required": [["vendor", "vendor name", "supplier"]],
        "required_any": [["due date", "due_date"]],
        "optional": ["date", "amount", "balance", "status", "bill no", "bill #",
                      "terms", "memo", "account"],
    },
    "expenses": {
        "required": [["date", "transaction date", "txn date"]],
        "required_any": [["amount", "total", "total amount"]],
        "optional": ["type", "payee", "category", "account", "memo",
                      "payment method", "ref no", "ref #"],
    },
    "payments": {
        "required": [["date", "payment date"]],
        "required_any": [["amount", "payment amount", "total"]],
        "optional": ["customer", "method", "payment method", "reference",
                      "deposit to", "memo", "invoice #"],
    },
    "journal_entries": {
        "required": [["date", "journal date"]],
        "optional": ["account", "debit", "credit", "description", "memo",
                      "journal no", "journal #", "name", "class"],
        "distinguishing": ["debit", "credit"],
    },
    "products": {
        "required": [["name", "product/service", "product", "item name"]],
        "optional": ["sku", "type", "description", "price", "sales price",
                      "cost", "purchase cost", "quantity on hand", "qty on hand",
                      "income account", "expense account"],
    },
}


def _normalize_headers(headers: list[str]) -> list[str]:
    """Lowercase and strip whitespace from headers."""
    return [h.strip().lower() for h in headers]


def _match_any(header_set: set[str], aliases: list[str]) -> bool:
    """Check if any alias matches a header."""
    return any(a in header_set for a in aliases)


def _filename_hint(filename: str) -> str | None:
    """Try to detect entity type from filename."""
    name = filename.lower().replace("_", " ").replace("-", " ")
    # Remove extension
    name = re.sub(r"\.\w+$", "", name)
    for keyword, entity_type in FILENAME_HINTS.items():
        if keyword in name:
            return entity_type
    return None


def detect_entity_type(headers: list[str], filename: str = "") -> str | None:
    """Detect the QBO entity type from CSV column headers and filename.

    Returns entity type string or None if unrecognized.
    """
    header_set = set(_normalize_headers(headers))

    # Score each entity type
    best_type = None
    best_score = 0
    filename_hint = _filename_hint(filename)

    for entity_type, sig in ENTITY_SIGNATURES.items():
        # Check required columns — all groups must have at least one match
        required = sig.get("required", [])
        all_required = True
        for group in required:
            if not _match_any(header_set, group):
                all_required = False
                break

        required_any = sig.get("required_any", [])
        for group in required_any:
            if not _match_any(header_set, group):
                all_required = False
                break

        if not all_required:
            continue

        # Score: required matches * 3 + optional matches
        score = len(required) * 3 + len(required_any) * 3
        for col in sig.get("optional", []):
            if col in header_set:
                score += 1

        # Boost from distinguishing columns
        for col in sig.get("distinguishing", []):
            if col in header_set:
                score += 2

        # Boost if filename hint matches
        if filename_hint == entity_type:
            score += 5

        if score > best_score:
            best_score = score
            best_type = entity_type

    # If we have a filename hint but no header match, trust the filename for
    # ambiguous cases (customers vs vendors)
    if best_type is None and filename_hint:
        return filename_hint

    return best_type


def is_qbo_csv(headers: list[str], filename: str = "") -> bool:
    """Quick check: does this CSV look like a QBO export?"""
    return detect_entity_type(headers, filename) is not None


# ── Date normalization ────────────────────────────────────────────────────────

_DATE_FORMATS = [
    "%m/%d/%Y",     # US QBO default: 01/15/2024
    "%m/%d/%y",     # Short year: 01/15/24
    "%Y-%m-%d",     # ISO: 2024-01-15
    "%d/%m/%Y",     # UK: 15/01/2024
    "%m-%d-%Y",     # Hyphen variant
    "%b %d, %Y",    # Jan 15, 2024
    "%B %d, %Y",    # January 15, 2024
]


def _normalize_date(value: str) -> str:
    """Parse a date string and return YYYY-MM-DD, or the original if unparseable."""
    value = value.strip()
    if not value:
        return ""
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return value  # Return as-is if no format matches


def _parse_number(value: str) -> float:
    """Parse a numeric string, handling currency symbols and commas."""
    if not value or not value.strip():
        return 0.0
    cleaned = re.sub(r"[,$\s]", "", value.strip())
    # Handle parentheses for negative: (123.45) -> -123.45
    match = re.match(r"^\((.+)\)$", cleaned)
    if match:
        cleaned = "-" + match.group(1)
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


# ── Row normalization per entity type ─────────────────────────────────────────

def _resolve_column(row: dict, aliases: list[str]) -> str:
    """Find the first matching column value from a list of aliases."""
    for alias in aliases:
        for key, val in row.items():
            if key.strip().lower() == alias:
                return (val or "").strip()
    return ""


def _normalize_account(row: dict, raw: str) -> dict:
    return {
        "name": _resolve_column(row, ["name", "account name", "account"]),
        "type": _resolve_column(row, ["type", "account type"]),
        "detail_type": _resolve_column(row, ["detail type", "detail_type"]),
        "description": _resolve_column(row, ["description"]),
        "balance": _parse_number(_resolve_column(row, ["balance"])),
        "currency": _resolve_column(row, ["currency"]) or "USD",
        "raw_data": raw,
    }


def _normalize_customer(row: dict, raw: str) -> dict:
    return {
        "display_name": _resolve_column(row, ["display name", "customer", "customer name", "client name"]),
        "email": _resolve_column(row, ["email", "email address", "e-mail"]),
        "phone": _resolve_column(row, ["phone", "phone number", "telephone"]),
        "address": _resolve_column(row, ["billing address", "billing street", "address"]),
        "balance": _parse_number(_resolve_column(row, ["balance"])),
        "raw_data": raw,
    }


def _normalize_vendor(row: dict, raw: str) -> dict:
    return {
        "display_name": _resolve_column(row, ["display name", "vendor", "vendor name", "supplier name"]),
        "email": _resolve_column(row, ["email", "email address", "e-mail"]),
        "phone": _resolve_column(row, ["phone", "phone number", "telephone"]),
        "address": _resolve_column(row, ["address", "street"]),
        "balance": _parse_number(_resolve_column(row, ["balance"])),
        "raw_data": raw,
    }


def _normalize_product(row: dict, raw: str) -> dict:
    return {
        "name": _resolve_column(row, ["name", "product/service", "product", "item name"]),
        "sku": _resolve_column(row, ["sku"]),
        "type": _resolve_column(row, ["type"]),
        "description": _resolve_column(row, ["description"]),
        "price": _parse_number(_resolve_column(row, ["price", "sales price", "rate"])),
        "cost": _parse_number(_resolve_column(row, ["cost", "purchase cost"])),
        "quantity_on_hand": _parse_number(_resolve_column(row, ["quantity on hand", "qty on hand", "qty"])),
        "raw_data": raw,
    }


def _normalize_invoice(row: dict, raw: str) -> dict:
    return {
        "txn_type": "invoice",
        "txn_number": _resolve_column(row, ["invoice no", "invoice #", "invoice number", "num"]),
        "txn_date": _normalize_date(_resolve_column(row, ["date", "invoice date", "txn date"])),
        "due_date": _normalize_date(_resolve_column(row, ["due date", "due_date"])),
        "entity_name": _resolve_column(row, ["customer", "customer name", "name"]),
        "entity_type": "customer",
        "account": _resolve_column(row, ["account"]),
        "category": _resolve_column(row, ["category", "class"]),
        "description": _resolve_column(row, ["memo", "description", "item"]),
        "amount": _parse_number(_resolve_column(row, ["amount", "total", "total amount"])),
        "balance": _parse_number(_resolve_column(row, ["balance", "balance due", "open balance"])),
        "status": _resolve_column(row, ["status"]),
        "payment_method": "",
        "raw_data": raw,
    }


def _normalize_bill(row: dict, raw: str) -> dict:
    return {
        "txn_type": "bill",
        "txn_number": _resolve_column(row, ["bill no", "bill #", "num"]),
        "txn_date": _normalize_date(_resolve_column(row, ["date", "bill date", "txn date"])),
        "due_date": _normalize_date(_resolve_column(row, ["due date", "due_date"])),
        "entity_name": _resolve_column(row, ["vendor", "vendor name", "supplier"]),
        "entity_type": "vendor",
        "account": _resolve_column(row, ["account", "ap account"]),
        "category": _resolve_column(row, ["category", "class"]),
        "description": _resolve_column(row, ["memo", "description"]),
        "amount": _parse_number(_resolve_column(row, ["amount", "total", "total amount"])),
        "balance": _parse_number(_resolve_column(row, ["balance", "open balance"])),
        "status": _resolve_column(row, ["status"]),
        "payment_method": "",
        "raw_data": raw,
    }


def _normalize_expense(row: dict, raw: str) -> dict:
    return {
        "txn_type": "expense",
        "txn_number": _resolve_column(row, ["ref no", "ref #", "num"]),
        "txn_date": _normalize_date(_resolve_column(row, ["date", "transaction date", "txn date"])),
        "due_date": "",
        "entity_name": _resolve_column(row, ["payee", "vendor", "name"]),
        "entity_type": _resolve_column(row, ["type"]).lower() if _resolve_column(row, ["type"]) else "",
        "account": _resolve_column(row, ["account", "bank account"]),
        "category": _resolve_column(row, ["category", "account", "expense account"]),
        "description": _resolve_column(row, ["memo", "description"]),
        "amount": _parse_number(_resolve_column(row, ["amount", "total", "total amount"])),
        "balance": 0.0,
        "status": _resolve_column(row, ["status"]),
        "payment_method": _resolve_column(row, ["payment method", "method"]),
        "raw_data": raw,
    }


def _normalize_payment(row: dict, raw: str) -> dict:
    return {
        "txn_type": "payment",
        "txn_number": _resolve_column(row, ["reference", "ref no", "ref #", "num"]),
        "txn_date": _normalize_date(_resolve_column(row, ["date", "payment date"])),
        "due_date": "",
        "entity_name": _resolve_column(row, ["customer", "customer name", "name"]),
        "entity_type": "customer",
        "account": _resolve_column(row, ["deposit to", "account"]),
        "category": "",
        "description": _resolve_column(row, ["memo", "description"]),
        "amount": _parse_number(_resolve_column(row, ["amount", "payment amount", "total"])),
        "balance": 0.0,
        "status": "",
        "payment_method": _resolve_column(row, ["method", "payment method"]),
        "raw_data": raw,
    }


def _normalize_journal_entry(row: dict, raw: str) -> dict:
    """Normalize a journal entry row. Returns a transaction record +
    the journal line data is embedded in raw_data for separate insertion."""
    return {
        "txn_type": "journal_entry",
        "txn_number": _resolve_column(row, ["journal no", "journal #", "num"]),
        "txn_date": _normalize_date(_resolve_column(row, ["date", "journal date"])),
        "due_date": "",
        "entity_name": _resolve_column(row, ["name"]),
        "entity_type": "",
        "account": _resolve_column(row, ["account"]),
        "category": _resolve_column(row, ["class"]),
        "description": _resolve_column(row, ["description", "memo"]),
        "amount": _parse_number(_resolve_column(row, ["debit"])) - _parse_number(_resolve_column(row, ["credit"])),
        "balance": 0.0,
        "status": "",
        "payment_method": "",
        "raw_data": raw,
        # Extra fields for journal_lines table
        "_debit": _parse_number(_resolve_column(row, ["debit"])),
        "_credit": _parse_number(_resolve_column(row, ["credit"])),
        "_journal_date": _normalize_date(_resolve_column(row, ["date", "journal date"])),
        "_account": _resolve_column(row, ["account"]),
        "_name": _resolve_column(row, ["name"]),
        "_description": _resolve_column(row, ["description", "memo"]),
    }


_NORMALIZERS = {
    "accounts": _normalize_account,
    "customers": _normalize_customer,
    "vendors": _normalize_vendor,
    "products": _normalize_product,
    "invoices": _normalize_invoice,
    "bills": _normalize_bill,
    "expenses": _normalize_expense,
    "payments": _normalize_payment,
    "journal_entries": _normalize_journal_entry,
}


# ── Main parse function ──────────────────────────────────────────────────────

def parse_csv_file(
    content: str,
    filename: str = "",
    entity_type: str | None = None,
) -> dict:
    """Parse a CSV string into structured records ready for DB insertion.

    Args:
        content: Raw CSV text content.
        filename: Original filename for detection hints.
        entity_type: Override auto-detection with explicit entity type.

    Returns:
        {
            "entity_type": str,
            "records": list[dict],
            "headers": list[str],
            "row_count": int,
            "warnings": list[str],
            "detected_by": str,  # "filename", "headers", "manual", or "override"
        }
    """
    warnings: list[str] = []

    reader = csv.DictReader(io.StringIO(content))
    if not reader.fieldnames:
        return {
            "entity_type": None,
            "records": [],
            "headers": [],
            "row_count": 0,
            "warnings": ["CSV has no headers"],
            "detected_by": "none",
        }

    headers = list(reader.fieldnames)
    norm_headers = _normalize_headers(headers)

    # Detect entity type
    detected_by = "headers"
    if entity_type:
        detected_by = "override"
    else:
        entity_type = detect_entity_type(norm_headers, filename)
        if entity_type is None:
            return {
                "entity_type": None,
                "records": [],
                "headers": headers,
                "row_count": 0,
                "warnings": ["Could not detect QBO entity type from headers"],
                "detected_by": "none",
            }
        # Check if filename was the deciding factor
        if _filename_hint(filename) == entity_type:
            detected_by = "filename"

    normalizer = _NORMALIZERS.get(entity_type)
    if not normalizer:
        return {
            "entity_type": entity_type,
            "records": [],
            "headers": headers,
            "row_count": 0,
            "warnings": [f"No normalizer for entity type: {entity_type}"],
            "detected_by": detected_by,
        }

    records = []
    for i, row in enumerate(reader, start=2):
        try:
            raw = json.dumps({k: v for k, v in row.items() if v}, ensure_ascii=False)
            record = normalizer(row, raw)
            records.append(record)
        except Exception as e:
            warnings.append(f"Row {i}: {e}")
            if len(warnings) > 50:
                warnings.append("Too many warnings, stopping")
                break

    return {
        "entity_type": entity_type,
        "records": records,
        "headers": headers,
        "row_count": len(records),
        "warnings": warnings,
        "detected_by": detected_by,
    }
