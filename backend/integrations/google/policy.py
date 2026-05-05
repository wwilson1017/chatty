"""
Chatty — Google capability resolution (multi-account).

Each agent can have different Google accounts assigned per service
(Gmail, Calendar, Drive). Capabilities are resolved per-account.
"""

from __future__ import annotations


_GMAIL_READ_LEVELS = {"read", "send"}
_GMAIL_SEND_LEVELS = {"send"}
_CALENDAR_READ_LEVELS = {"read", "full"}
_CALENDAR_WRITE_LEVELS = {"full"}
_DRIVE_READ_LEVELS = {"file", "readonly", "full"}
_DRIVE_WRITE_LEVELS = {"file", "full"}

_ALL_DISABLED = {
    "gmail_read_enabled": False,
    "gmail_send_enabled": False,
    "calendar_read_enabled": False,
    "calendar_write_enabled": False,
    "drive_read_enabled": False,
    "drive_write_enabled": False,
}


def google_capabilities(account_id: str = "") -> dict[str, bool]:
    """Return capability flags for a specific Google account.

    If account_id is empty or the account doesn't exist, returns all-disabled.
    """
    if not account_id:
        return dict(_ALL_DISABLED)

    try:
        from integrations.registry import get_google_account
        acct = get_google_account(account_id)
        if not acct:
            return dict(_ALL_DISABLED)
        if acct.get("connection_status") == "broken":
            return dict(_ALL_DISABLED)
        grants = acct.get("scope_grants", {})
        if not grants:
            return dict(_ALL_DISABLED)
    except Exception:
        return dict(_ALL_DISABLED)

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
