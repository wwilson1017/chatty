"""
Chatty — Pending integration setup storage.

Stores onboarding selections (messaging + integrations) so the first
agent can pick them up and offer to help the user set them up.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from core.storage import atomic_write_json

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def save_pending(messaging: list[str], integrations: list[str]) -> dict:
    """Save onboarding selections to pending-setup.json."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    data = {
        "messaging": messaging,
        "integrations": integrations,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    atomic_write_json(DATA_DIR / "pending-setup.json", data)
    return data


def load_pending() -> dict | None:
    """Read pending setup selections. Returns None if no file exists."""
    path = DATA_DIR / "pending-setup.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def clear_pending() -> None:
    """Delete the pending setup file."""
    path = DATA_DIR / "pending-setup.json"
    if path.exists():
        path.unlink()
