"""
Chatty — Setup wizard status endpoints.

Tracks whether the user has completed or skipped the first-login setup wizard.
"""

import json
import logging
from pathlib import Path

from fastapi import APIRouter, Depends

from core.auth import get_current_user
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
