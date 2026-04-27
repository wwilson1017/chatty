"""
Chatty — Integration registry.

Tracks which integrations are available and whether they're enabled.
Credentials are stored in data/integrations/{name}.json.

Available integrations:
  odoo        — Odoo ERP (XML-RPC)
  quickbooks  — QuickBooks Online (OAuth2)
  bamboohr    — BambooHR HR system
  crm_lite    — Built-in lightweight CRM
  whatsapp    — WhatsApp (stub)
"""

import json
import logging
from pathlib import Path

from core.encryption import decrypt_dict, encrypt_dict, needs_migration
from core.storage import atomic_write_json

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "integrations"

AVAILABLE_INTEGRATIONS = {
    "odoo": {
        "name": "Odoo",
        "description": "Odoo ERP — inventory, sales, purchases, accounting",
        "icon": "🏢",
        "auth_type": "credentials",
    },
    "google": {
        "name": "Google (Gmail + Calendar + Drive)",
        "description": "Connect Google — email, calendar, and Drive access, with per-scope permissions",
        "icon": "📧",
        "auth_type": "oauth2_scoped",
    },
    "quickbooks": {
        "name": "QuickBooks",
        "description": "QuickBooks Online — invoices, bills, P&L, customers",
        "icon": "📊",
        "auth_type": "oauth2",
    },
    "bamboohr": {
        "name": "BambooHR",
        "description": "BambooHR — employee directory, time tracking, HR data",
        "icon": "👥",
        "auth_type": "api_key",
    },
    "qb_csv": {
        "name": "QuickBooks CSV",
        "description": "Import & analyze QuickBooks CSV exports — no login required",
        "icon": "📒",
        "auth_type": "none",
    },
    "crm_lite": {
        "name": "CRM",
        "description": "Built-in CRM — always available.",
        "icon": "📋",
        "auth_type": "none",
        "always_on": True,
    },
    "telegram": {
        "name": "Telegram",
        "description": "Telegram Bot — connect your agent to a Telegram bot",
        "icon": "✈️",
        "auth_type": "per_agent",
    },
    "whatsapp": {
        "name": "WhatsApp",
        "description": "WhatsApp — connect agents to WhatsApp via QR code scan",
        "icon": "💬",
        "auth_type": "qr_session",
    },
    "paperclip": {
        "name": "Paperclip",
        "description": "AI company orchestration — org chart, tasks, budgets, governance",
        "icon": "📎",
        "auth_type": "api_key",
    },
    "todoist": {
        "name": "Todoist",
        "description": "Task management and productivity",
        "icon": "✅",
        "auth_type": "api_key",
    },
}


def ensure_dir():
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _creds_path(name: str) -> Path:
    return DATA_DIR / f"{name}.json"


def is_enabled(name: str) -> bool:
    """Check if an integration is configured and enabled."""
    path = _creds_path(name)
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return bool(data.get("enabled", False))
    except Exception:
        return False


def get_credentials(name: str) -> dict:
    """Load integration credentials. Returns empty dict if not configured."""
    path = _creds_path(name)
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        decrypted = decrypt_dict(raw)
        # Auto-migrate plaintext credentials to encrypted on disk
        if needs_migration(raw):
            logger.info("Migrating %s.json to encrypted storage", name)
            save_credentials(name, decrypted)
        return decrypted
    except Exception:
        return {}


def save_credentials(name: str, data: dict) -> None:
    """Save integration credentials (sensitive fields encrypted at rest)."""
    ensure_dir()
    encrypted = encrypt_dict(data)
    atomic_write_json(_creds_path(name), encrypted)


def enable(name: str) -> None:
    """Mark integration as enabled."""
    creds = get_credentials(name)
    creds["enabled"] = True
    save_credentials(name, creds)


def disable(name: str) -> None:
    """Mark integration as disabled (credentials preserved)."""
    creds = get_credentials(name)
    creds["enabled"] = False
    save_credentials(name, creds)


def ensure_crm_active() -> None:
    """Ensure CRM Lite is always configured and enabled on startup."""
    creds = get_credentials("crm_lite")
    if not creds or not creds.get("enabled"):
        save_credentials("crm_lite", {**creds, "enabled": True})


def get_tool_mode(name: str) -> str:
    """Get the tool_mode ceiling for an integration. Default: 'normal' (approval)."""
    creds = get_credentials(name)
    return creds.get("tool_mode", "normal")


def set_tool_mode(name: str, mode: str) -> None:
    """Set the tool_mode ceiling for an integration."""
    if mode not in ("read-only", "normal", "power"):
        raise ValueError(f"Invalid tool_mode: {mode}")
    creds = get_credentials(name)
    creds["tool_mode"] = mode
    save_credentials(name, creds)


def list_integrations() -> list[dict]:
    """Return all integrations with their status."""
    result = []
    for key, meta in AVAILABLE_INTEGRATIONS.items():
        creds = get_credentials(key)
        always_on = meta.get("always_on", False)
        # For OAuth integrations, "configured" means tokens exist (not just app creds)
        if meta.get("auth_type") in ("oauth2", "oauth2_scoped"):
            is_configured = bool(creds.get("access_token") or creds.get("refresh_token"))
        else:
            is_configured = bool(creds)

        entry = {
            "id": key,
            **meta,
            "enabled": True if always_on else bool(creds.get("enabled", False)),
            "configured": True if always_on else is_configured,
            "hidden": False,
            "connection_status": creds.get("connection_status", "ok") if creds else "ok",
            "tool_mode": creds.get("tool_mode", "normal"),
        }
        if key == "google" and creds:
            entry["email"] = creds.get("email", "")
            entry["scope_grants"] = creds.get("scope_grants", {})
        if meta.get("auth_type") in ("oauth2", "oauth2_scoped"):
            from .app_credentials import has_app_credentials
            entry["has_app_credentials"] = has_app_credentials(key)
        result.append(entry)
    return result
