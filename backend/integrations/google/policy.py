"""
Chatty — Google capability resolution (multi-account).

Each agent can have different Google accounts assigned per service
(Gmail, Calendar, Drive, Workspace). Capabilities are resolved per-account.

`GOOGLE_SERVICES` is the single source of truth for the list of assignable
Google services. Iterate it instead of hardcoding ("gmail", "calendar",
"drive", ...) tuples so adding a service stays a one-line change.
"""

from __future__ import annotations

# Single source of truth for the assignable Google services. Order matters only
# for stable iteration; "workspace" bundles Docs + Sheets + Slides.
GOOGLE_SERVICES = ("gmail", "calendar", "drive", "workspace")

_GMAIL_READ_LEVELS = {"read", "send"}
_GMAIL_SEND_LEVELS = {"send"}
_CALENDAR_READ_LEVELS = {"read", "full"}
_CALENDAR_WRITE_LEVELS = {"full"}
_DRIVE_READ_LEVELS = {"file", "readonly", "full"}
_DRIVE_WRITE_LEVELS = {"file", "full"}
_WORKSPACE_READ_LEVELS = {"read", "edit"}
_WORKSPACE_WRITE_LEVELS = {"edit"}

_ALL_DISABLED = {
    "gmail_read_enabled": False,
    "gmail_send_enabled": False,
    "calendar_read_enabled": False,
    "calendar_write_enabled": False,
    "drive_read_enabled": False,
    "drive_write_enabled": False,
    "workspace_read_enabled": False,
    "workspace_write_enabled": False,
}

# Per-service capability flag keys, used to scope flags to the right service
# when flattening per-service account assignments into tool-definition kwargs.
_SERVICE_FLAG_KEYS = {
    "gmail": ("gmail_read_enabled", "gmail_send_enabled"),
    "calendar": ("calendar_read_enabled", "calendar_write_enabled"),
    "drive": ("drive_read_enabled", "drive_write_enabled"),
    "workspace": ("workspace_read_enabled", "workspace_write_enabled"),
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
    workspace = grants.get("workspace", "none")

    return {
        "gmail_read_enabled": gmail in _GMAIL_READ_LEVELS,
        "gmail_send_enabled": gmail in _GMAIL_SEND_LEVELS,
        "calendar_read_enabled": calendar in _CALENDAR_READ_LEVELS,
        "calendar_write_enabled": calendar in _CALENDAR_WRITE_LEVELS,
        "drive_read_enabled": drive in _DRIVE_READ_LEVELS,
        "drive_write_enabled": drive in _DRIVE_WRITE_LEVELS,
        "workspace_read_enabled": workspace in _WORKSPACE_READ_LEVELS,
        "workspace_write_enabled": workspace in _WORKSPACE_WRITE_LEVELS,
    }


def google_capabilities_union(account_ids: list[str]) -> dict[str, bool]:
    """Return capability flags as the union across multiple accounts.

    Internal helper for google_tool_flags(). New tool-building call sites should
    use google_tool_flags() instead, which scopes flags per service and emits
    the multi_* flags ready to spread into get_tool_definitions().
    """
    if not account_ids:
        return dict(_ALL_DISABLED)
    result = dict(_ALL_DISABLED)
    for aid in account_ids:
        caps = google_capabilities(aid)
        for key, val in caps.items():
            if val:
                result[key] = True
    return result


def google_tool_flags(ids_by_service: dict[str, list[str]]) -> dict[str, bool]:
    """Flatten per-service account assignments into get_tool_definitions() kwargs.

    For each service in GOOGLE_SERVICES, unions that service's assigned accounts
    and keeps only that service's own capability flags (so an account assigned to
    Drive does not enable Gmail tools just because it also granted Gmail). Also
    emits a `multi_<service>` flag (True when >1 account is assigned) so the
    multi-account `account` param is injected into that service's tools.

    The returned dict is spreadable directly: get_tool_definitions(**flags, ...).
    """
    flags: dict[str, bool] = {}
    for svc in GOOGLE_SERVICES:
        ids = ids_by_service.get(svc, []) or []
        caps = google_capabilities_union(ids)
        # Tolerate partial capability dicts (e.g. older stubs): a missing flag
        # simply means that capability is disabled.
        for key in _SERVICE_FLAG_KEYS[svc]:
            flags[key] = caps.get(key, False)
        flags[f"multi_{svc}"] = len(ids) > 1
    return flags
