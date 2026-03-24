"""
Chatty — Branding storage.

Saves/loads branding config (name, accent color) and logo from data/branding/.
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

BRANDING_DIR = Path(__file__).resolve().parent.parent / "data" / "branding"
CONFIG_FILE = BRANDING_DIR / "config.json"
LOGO_FILE = BRANDING_DIR / "logo.png"

DEFAULT_CONFIG = {
    "company_name": "Chatty",
    "accent_color": "#6366f1",  # indigo-500
    "has_logo": False,
}


def ensure_dir():
    BRANDING_DIR.mkdir(parents=True, exist_ok=True)


def load_config() -> dict:
    """Load branding config. Returns defaults if file doesn't exist."""
    ensure_dir()
    if not CONFIG_FILE.exists():
        return dict(DEFAULT_CONFIG)
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        return {**DEFAULT_CONFIG, **data, "has_logo": LOGO_FILE.exists()}
    except Exception as e:
        logger.warning("Failed to load branding config: %s", e)
        return dict(DEFAULT_CONFIG)


def save_config(company_name: str | None = None, accent_color: str | None = None) -> dict:
    """Update branding config fields. Returns the updated config."""
    ensure_dir()
    current = load_config()
    if company_name is not None:
        current["company_name"] = company_name
    if accent_color is not None:
        current["accent_color"] = accent_color
    current.pop("has_logo", None)  # derived field, don't persist
    CONFIG_FILE.write_text(json.dumps(current, indent=2), encoding="utf-8")
    return load_config()


def save_logo(data: bytes) -> bool:
    """Save logo PNG bytes. Returns True on success."""
    ensure_dir()
    try:
        LOGO_FILE.write_bytes(data)
        return True
    except Exception as e:
        logger.error("Failed to save logo: %s", e)
        return False


def delete_logo() -> bool:
    """Delete the logo file. Returns True if it existed."""
    if LOGO_FILE.exists():
        LOGO_FILE.unlink()
        return True
    return False


def get_logo_path() -> Path | None:
    """Return the logo file path if it exists, else None."""
    return LOGO_FILE if LOGO_FILE.exists() else None
