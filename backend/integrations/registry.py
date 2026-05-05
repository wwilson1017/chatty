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
import threading
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
        "description": "Todoist — tasks, projects, labels, and productivity tracking",
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
        if name == "google":
            return bool(data.get("accounts", {}))
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


# ── Google multi-account helpers ─────────────────────────────────────────────

_GOOGLE_FILE_LOCK = threading.RLock()


def _read_google_creds() -> dict:
    """Read google.json (caller must hold _GOOGLE_FILE_LOCK)."""
    return get_credentials("google")


def _write_google_creds(data: dict) -> None:
    """Write google.json (caller must hold _GOOGLE_FILE_LOCK)."""
    ensure_dir()
    encrypted = encrypt_dict(data)
    atomic_write_json(_creds_path("google"), encrypted)


def get_google_account(account_id: str) -> dict:
    """Load a specific Google account's credentials by account_id."""
    creds = get_credentials("google")
    return creds.get("accounts", {}).get(account_id, {})


def save_google_account(account_id: str, data: dict, create: bool = False) -> None:
    """Save/update a single Google account within google.json.

    When create=False (default, used by token refresh), refuses to save if
    the account doesn't exist — prevents disconnect-vs-refresh races.
    When create=True (used by onboarding), allows creating new entries.
    """
    with _GOOGLE_FILE_LOCK:
        creds = _read_google_creds()
        if "accounts" not in creds:
            creds["accounts"] = {}
        if not create and account_id not in creds["accounts"]:
            logger.warning("Refusing to save non-existent account %s (deleted?)", account_id)
            return
        creds["accounts"][account_id] = data
        _write_google_creds(creds)


def delete_google_account(account_id: str) -> dict | None:
    """Remove a Google account. Returns the removed account data or None."""
    with _GOOGLE_FILE_LOCK:
        creds = _read_google_creds()
        accounts = creds.get("accounts", {})
        removed = accounts.pop(account_id, None)
        if removed is not None:
            creds["accounts"] = accounts
            _write_google_creds(creds)
    if removed is not None:
        try:
            from integrations.google.client import _LOCKS_LOCK, _ACCOUNT_LOCKS
            with _LOCKS_LOCK:
                _ACCOUNT_LOCKS.pop(account_id, None)
        except Exception:
            pass
    return removed


def list_google_accounts() -> dict[str, dict]:
    """Return all Google accounts {id: data}."""
    creds = get_credentials("google")
    return creds.get("accounts", {})


def save_google_app_credentials(app_data: dict) -> None:
    """Save Google OAuth app credentials (locked)."""
    with _GOOGLE_FILE_LOCK:
        creds = _read_google_creds()
        creds["app"] = app_data
        _write_google_creds(creds)


def migrate_google_json() -> None:
    """Migrate old flat google.json to multi-account format."""
    import uuid

    creds = get_credentials("google")
    if not creds:
        return
    if "accounts" in creds:
        return
    if not creds.get("access_token"):
        return

    account_id = uuid.uuid4().hex[:8]
    scope_grants = creds.get("scope_grants", {})

    account_data = {
        "email": creds.pop("email", ""),
        "access_token": creds.pop("access_token", ""),
        "refresh_token": creds.pop("refresh_token", ""),
        "token_expires_at": creds.pop("token_expires_at", 0),
        "scope_grants": creds.pop("scope_grants", {}),
        "calendar_timezone": creds.pop("calendar_timezone", "UTC"),
        "connection_status": creds.pop("connection_status", "ok"),
    }

    creds.pop("enabled", None)

    creds["accounts"] = {account_id: account_data}
    save_credentials("google", creds)

    try:
        from agents.db import list_agents, update_agent
        ga = {}
        if scope_grants.get("gmail", "none") != "none":
            ga["gmail"] = account_id
        if scope_grants.get("calendar", "none") != "none":
            ga["calendar"] = account_id
        if scope_grants.get("drive", "none") != "none":
            ga["drive"] = account_id

        if ga:
            import json as _json
            ga_str = _json.dumps(ga)
            for agent in list_agents():
                update_agent(agent["id"], google_accounts=ga_str)

        logger.info("Migrated google.json to multi-account format (account_id=%s)", account_id)
    except Exception as e:
        logger.warning("Google migration: credential format updated but agent assignment failed: %s", e)


def list_integrations() -> list[dict]:
    """Return all integrations with their status."""
    result = []
    for key, meta in AVAILABLE_INTEGRATIONS.items():
        creds = get_credentials(key)
        always_on = meta.get("always_on", False)

        if key == "google":
            accounts = creds.get("accounts", {})
            is_configured = any(
                a.get("access_token") or a.get("refresh_token")
                for a in accounts.values()
            )
            is_enabled_val = bool(accounts)
        elif meta.get("auth_type") in ("oauth2", "oauth2_scoped"):
            is_configured = bool(creds.get("access_token") or creds.get("refresh_token"))
            is_enabled_val = bool(creds.get("enabled", False))
        else:
            is_configured = bool(creds)
            is_enabled_val = bool(creds.get("enabled", False))

        entry = {
            "id": key,
            **meta,
            "enabled": True if always_on else is_enabled_val,
            "configured": True if always_on else is_configured,
            "hidden": False,
            "connection_status": creds.get("connection_status", "ok") if creds else "ok",
            "tool_mode": creds.get("tool_mode", "normal"),
        }
        if key == "google" and creds:
            accounts = creds.get("accounts", {})
            entry["google_accounts"] = [
                {
                    "id": acct_id,
                    "email": acct.get("email", ""),
                    "scope_grants": acct.get("scope_grants", {}),
                    "connection_status": acct.get("connection_status", "ok"),
                }
                for acct_id, acct in accounts.items()
            ]
            if len(accounts) == 1:
                only = next(iter(accounts.values()))
                entry["email"] = only.get("email", "")
                entry["scope_grants"] = only.get("scope_grants", {})
            if any(a.get("connection_status") == "broken" for a in accounts.values()):
                entry["connection_status"] = "broken"
        if meta.get("auth_type") in ("oauth2", "oauth2_scoped"):
            from .app_credentials import has_app_credentials
            entry["has_app_credentials"] = has_app_credentials(key)
        result.append(entry)
    return result
