"""
Chatty — Setup wizard status endpoints.

Tracks whether the user has completed or skipped the first-login setup wizard.
"""

import json
import logging
import secrets
from pathlib import Path

from fastapi import APIRouter, Depends, Response

from core.auth import get_current_user
from core.admin_settings import (
    load_admin_settings,
    invalidate_cache,
    clamp_todo_settings,
    settings_write_lock,
    ADMIN_DEFAULTS,
    ADMIN_SETTINGS_FILE,
    VALID_TRIAGE_MODES,
    VALID_MODEL_TIERS,
    VALID_INJECTION_MODES,
)
from core.providers.credentials import CredentialStore
from core.storage import atomic_write_json
from branding.storage import load_config as load_branding, DEFAULT_CONFIG as BRANDING_DEFAULTS

logger = logging.getLogger(__name__)

router = APIRouter()

STATUS_FILE = Path(__file__).resolve().parent.parent / "data" / "setup-status.json"


def _load_status() -> dict:
    if STATUS_FILE.exists():
        try:
            return json.loads(STATUS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"skipped": False, "completed_at": None}


def _save_status(data: dict):
    atomic_write_json(STATUS_FILE, data)


@router.get("/status")
async def setup_status(user=Depends(get_current_user)):
    """Return setup wizard status — frontend uses this to decide whether to show the wizard."""
    status = _load_status()
    store = CredentialStore()
    providers_configured = store.is_configured()
    branding = load_branding()
    branding_customized = (
        branding.get("company_name", "") != BRANDING_DEFAULTS["company_name"]
        or branding.get("accent_color", "") != BRANDING_DEFAULTS["accent_color"]
        or branding.get("has_logo", False)
    )

    setup_complete = (
        status.get("skipped", False)
        or status.get("completed_at") is not None
        or providers_configured
    )

    return {
        "setup_complete": setup_complete,
        "skipped": status.get("skipped", False),
        "providers_configured": providers_configured,
        "branding_customized": branding_customized,
    }


@router.post("/skip")
async def skip_setup(user=Depends(get_current_user)):
    """Mark setup as skipped so the wizard won't show again."""
    status = _load_status()
    status["skipped"] = True
    _save_status(status)
    return {"ok": True}


@router.post("/complete")
async def complete_setup(user=Depends(get_current_user)):
    """Mark setup as fully completed."""
    import time
    status = _load_status()
    status["completed_at"] = int(time.time())
    _save_status(status)
    return {"ok": True}


@router.get("/admin-settings")
async def get_admin_settings(response: Response, user=Depends(get_current_user)):
    from core.todo.coaching import DEFAULT_GTD_COACHING

    # Body carries the todo secrets — a regenerated one must not outlive it in the browser cache.
    response.headers["Cache-Control"] = "no-store"
    # gtd_coaching_default is read-only metadata for the Settings "Reset to
    # default" button — the PUT handler's ADMIN_DEFAULTS key loop ignores it.
    return {**load_admin_settings(), "gtd_coaching_default": DEFAULT_GTD_COACHING}


@router.put("/admin-settings")
async def update_admin_settings(body: dict, response: Response, user=Depends(get_current_user)):
    # Body carries the todo secrets — a regenerated one must not outlive it in the browser cache.
    response.headers["Cache-Control"] = "no-store"
    # Lock the whole read-modify-write: a concurrent agent-tool write
    # (set_admin_setting) racing this PUT would otherwise be silently lost.
    with settings_write_lock:
        settings = load_admin_settings()
        was_web_enabled = settings.get("todo_web_enabled") is True
        for key in ADMIN_DEFAULTS:
            if key in body:
                settings[key] = body[key]
        # todo_web_enabled is deliberately absent: it opens a no-login
        # read/write surface, so clamp_todo_settings only accepts a real JSON
        # true — bool() here would let strings like "false" enable it.
        for _bool_key in ("always_power_mode", "write_budget_heartbeat_enabled",
                          "write_budget_interactive_enabled", "hourly_write_rate_limit_enabled",
                          "bot_reply_limit_enabled", "commitments_enabled"):
            if _bool_key in settings:
                settings[_bool_key] = bool(settings[_bool_key])
        if not isinstance(settings.get("triage_mode"), str) or settings["triage_mode"] not in VALID_TRIAGE_MODES:
            settings["triage_mode"] = ADMIN_DEFAULTS["triage_mode"]
        if not isinstance(settings.get("default_model_tier"), str) or settings["default_model_tier"] not in VALID_MODEL_TIERS:
            settings["default_model_tier"] = ADMIN_DEFAULTS["default_model_tier"]
        if settings.get("injection_scanning") not in VALID_INJECTION_MODES:
            settings["injection_scanning"] = ADMIN_DEFAULTS["injection_scanning"]
        for _int_key in ("write_budget_heartbeat", "write_budget_interactive",
                         "hourly_write_rate_limit", "event_log_retention_days",
                         "bot_reply_limit", "commitments_daily_cap"):
            if not isinstance(settings.get(_int_key), int) or settings[_int_key] < 1:
                settings[_int_key] = ADMIN_DEFAULTS[_int_key]
        # Cap bot_reply_limit so the loop-prevention guard can't be effectively disabled.
        settings["bot_reply_limit"] = min(settings["bot_reply_limit"], 100)
        # Cap the follow-up budget so a bad settings payload can't oversize prompts.
        settings["commitments_daily_cap"] = min(settings["commitments_daily_cap"], 20)
        clamp_todo_settings(settings)
        # Enable is a revocation boundary server-side, not just in the
        # Settings UI: turning the todo link on without submitting a token in
        # the same write mints a fresh secret, so a link leaked while the
        # feature was off can't be revived by a bare {"todo_web_enabled": true}.
        # Only an explicit *string* todo_web_token (even "", the deliberate
        # tokenless mode) skips the mint — a JSON null is not a supplied token.
        if (settings.get("todo_web_enabled") and not was_web_enabled
                and not isinstance(body.get("todo_web_token"), str)):
            settings["todo_web_token"] = secrets.token_hex(16)
        atomic_write_json(ADMIN_SETTINGS_FILE, settings)
        invalidate_cache()
    return settings
