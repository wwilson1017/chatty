"""
Chatty — Google capability resolution.

When Google is connected globally, ALL agents automatically get the
granted capabilities. No per-agent opt-in required — if the user
connected Gmail with send access, every agent can send email.

Per-agent flags (gmail_enabled, drive_enabled, etc.) act as opt-OUT
overrides: set them to False to restrict a specific agent. By default
they're treated as "use whatever the global connection grants."
"""

from __future__ import annotations


_GMAIL_READ_LEVELS = {"read", "send"}
_GMAIL_SEND_LEVELS = {"send"}
_CALENDAR_READ_LEVELS = {"read", "full"}
_CALENDAR_WRITE_LEVELS = {"full"}
_DRIVE_READ_LEVELS = {"file", "readonly", "full"}
_DRIVE_WRITE_LEVELS = {"file", "full"}


def _load_grants() -> dict[str, str]:
    """Load scope_grants from data/integrations/google.json."""
    try:
        from integrations.registry import get_credentials
        creds = get_credentials("google")
        if not creds or not creds.get("enabled"):
            return {}
        return creds.get("scope_grants", {}) or {}
    except Exception:
        return {}


def google_capabilities() -> dict[str, bool]:
    """Return capability flags based on global Google connection grants.

    If Google is connected, agents get all granted capabilities automatically.
    No per-agent toggle required — the global scope grants are the source of truth.
    """
    grants = _load_grants()
    if not grants:
        return {
            "gmail_read_enabled": False,
            "gmail_send_enabled": False,
            "calendar_read_enabled": False,
            "calendar_write_enabled": False,
            "drive_read_enabled": False,
            "drive_write_enabled": False,
        }

    gmail = grants.get("gmail", "none")
    calendar = grants.get("calendar", "none")
    drive = grants.get("drive", "none")

    return {
        "gmail_read_enabled": gmail in _GMAIL_READ_LEVELS,
        "gmail_send_enabled": gmail in _GMAIL_SEND_LEVELS,
        "calendar_read_enabled": calendar in _CALENDAR_READ_LEVELS,
        "calendar_write_enabled": calendar in _CALENDAR_WRITE_LEVELS,
        "drive_read_enabled": drive in _DRIVE_READ_LEVELS,
        "drive_write_enabled": drive in _DRIVE_WRITE_LEVELS,
    }
