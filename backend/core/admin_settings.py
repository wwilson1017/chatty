"""Admin settings loader with mtime-based cache.

Extracted from setup/router.py so that core modules can read admin
settings without importing the HTTP router layer.
"""

import json
import logging
import re
import threading
from pathlib import Path

from core.todo.coaching import DEFAULT_GTD_COACHING, MAX_COACHING_CHARS

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
    "todo_capture_token": "",
    "gtd_coaching_text": DEFAULT_GTD_COACHING,
}

_CAPTURE_TOKEN_STRIP_RE = re.compile(r"[^A-Za-z0-9_-]")


def clamp_todo_settings(settings: dict) -> None:
    """In-place validation for the todo-gtd string settings.

    Capture token must stay URL-safe (it is a path segment); coaching text is
    capped so a bad payload can't oversize every agent's system prompt.
    """
    token = settings.get("todo_capture_token")
    if not isinstance(token, str):
        token = ""
    settings["todo_capture_token"] = _CAPTURE_TOKEN_STRIP_RE.sub("", token)[:128]
    coaching = settings.get("gtd_coaching_text")
    if not isinstance(coaching, str):
        coaching = ADMIN_DEFAULTS["gtd_coaching_text"]
    settings["gtd_coaching_text"] = coaching[:MAX_COACHING_CHARS]


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
    clamp_todo_settings(result)

    with _cache_lock:
        _cached_settings = result
        _cached_mtime = mtime

    return dict(result)


def invalidate_cache() -> None:
    global _cached_settings, _cached_mtime
    with _cache_lock:
        _cached_settings = None
        _cached_mtime = 0.0


def set_admin_setting(key: str, value) -> dict:
    """Persist one admin setting outside the HTTP layer (e.g. from an agent tool).

    Values are clamped by load_admin_settings on the way back out.
    """
    from core.storage import atomic_write_json

    settings = load_admin_settings()
    settings[key] = value
    clamp_todo_settings(settings)
    atomic_write_json(ADMIN_SETTINGS_FILE, settings)
    invalidate_cache()
    return load_admin_settings()
