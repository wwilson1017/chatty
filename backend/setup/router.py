"""
Chatty — Setup wizard status endpoints.

Tracks whether the user has completed or skipped the first-login setup wizard.
"""

import json
import logging
from pathlib import Path

from fastapi import APIRouter, Depends

from core.auth import get_current_user
from core.admin_settings import (
    load_admin_settings,
    invalidate_cache,
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
async def get_admin_settings(user=Depends(get_current_user)):
    return load_admin_settings()


@router.put("/admin-settings")
async def update_admin_settings(body: dict, user=Depends(get_current_user)):
    settings = load_admin_settings()
    for key in ADMIN_DEFAULTS:
        if key in body:
            settings[key] = body[key]
    for _bool_key in ("always_power_mode", "write_budget_heartbeat_enabled",
                      "write_budget_interactive_enabled", "hourly_write_rate_limit_enabled",
                      "bot_reply_limit_enabled"):
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
                     "bot_reply_limit"):
        if not isinstance(settings.get(_int_key), int) or settings[_int_key] < 1:
            settings[_int_key] = ADMIN_DEFAULTS[_int_key]
    atomic_write_json(ADMIN_SETTINGS_FILE, settings)
    invalidate_cache()
    return settings
