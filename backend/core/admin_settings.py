"""Admin settings loader with mtime-based cache.

Extracted from setup/router.py so that core modules can read admin
settings without importing the HTTP router layer.
"""

import json
import logging
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

ADMIN_SETTINGS_FILE = Path(__file__).resolve().parent.parent / "data" / "admin-settings.json"

ADMIN_DEFAULTS = {
    "always_power_mode": False,
    "triage_mode": "always_cheap",
    "default_model_tier": "auto",
    "notifications_web_push": True,
    "notifications_telegram": True,
    "notifications_whatsapp": True,
    "injection_scanning": "flag",
    "write_budget_heartbeat_enabled": True,
    "write_budget_heartbeat": 10,
    "write_budget_interactive_enabled": True,
    "write_budget_interactive": 50,
    "hourly_write_rate_limit_enabled": False,
    "hourly_write_rate_limit": 100,
    "event_log_retention_days": 90,
    "bot_reply_limit_enabled": True,
    "bot_reply_limit": 5,
    "commitments_enabled": True,
    "commitments_daily_cap": 3,
}

VALID_TRIAGE_MODES = {"standard", "cheap", "always_cheap"}
VALID_MODEL_TIERS = {"auto", "top", "mid", "light"}
VALID_INJECTION_MODES = {"off", "flag", "block"}

_cache_lock = threading.Lock()
_cached_settings: dict | None = None
_cached_mtime: float = 0.0


def load_admin_settings() -> dict:
    global _cached_settings, _cached_mtime

    try:
        mtime = ADMIN_SETTINGS_FILE.stat().st_mtime
    except OSError:
        return dict(ADMIN_DEFAULTS)

    with _cache_lock:
        if _cached_settings is not None and mtime == _cached_mtime:
            return dict(_cached_settings)

    try:
        result = {**ADMIN_DEFAULTS, **json.loads(ADMIN_SETTINGS_FILE.read_text(encoding="utf-8"))}
    except Exception:
        return dict(ADMIN_DEFAULTS)

    if not isinstance(result.get("triage_mode"), str) or result["triage_mode"] not in VALID_TRIAGE_MODES:
        result["triage_mode"] = ADMIN_DEFAULTS["triage_mode"]
    if not isinstance(result.get("default_model_tier"), str) or result["default_model_tier"] not in VALID_MODEL_TIERS:
        result["default_model_tier"] = ADMIN_DEFAULTS["default_model_tier"]
    if result.get("injection_scanning") not in VALID_INJECTION_MODES:
        result["injection_scanning"] = ADMIN_DEFAULTS["injection_scanning"]
    for _int_key in ("write_budget_heartbeat", "write_budget_interactive",
                     "hourly_write_rate_limit", "event_log_retention_days",
                     "bot_reply_limit", "commitments_daily_cap"):
        if not isinstance(result.get(_int_key), int) or result[_int_key] < 1:
            result[_int_key] = ADMIN_DEFAULTS[_int_key]
    # Cap bot_reply_limit so the loop-prevention guard can't be effectively disabled.
    result["bot_reply_limit"] = min(result["bot_reply_limit"], 100)
    # Cap the follow-up budget so a bad settings payload can't oversize prompts.
    result["commitments_daily_cap"] = min(result["commitments_daily_cap"], 20)
    if not isinstance(result.get("bot_reply_limit_enabled"), bool):
        result["bot_reply_limit_enabled"] = ADMIN_DEFAULTS["bot_reply_limit_enabled"]
    if not isinstance(result.get("commitments_enabled"), bool):
        result["commitments_enabled"] = ADMIN_DEFAULTS["commitments_enabled"]

    with _cache_lock:
        _cached_settings = result
        _cached_mtime = mtime

    return dict(result)


def invalidate_cache() -> None:
    global _cached_settings, _cached_mtime
    with _cache_lock:
        _cached_settings = None
        _cached_mtime = 0.0
