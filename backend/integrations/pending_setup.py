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


def mark_integration_complete(context_dir: str | Path, integration_name: str) -> None:
    """Check off an integration in _pending-setup.md. Deletes the file when all done."""
    pending_path = Path(context_dir) / "_pending-setup.md"
    if not pending_path.exists():
        return
    try:
        content = pending_path.read_text(encoding="utf-8")
        updated = content.replace(f"- [ ] {integration_name}", f"- [x] {integration_name}")
        if updated != content:
            pending_path.write_text(updated, encoding="utf-8")
            if "- [ ]" not in updated:
                pending_path.unlink()
    except Exception:
        import logging
        logging.getLogger(__name__).debug(
            "Failed to update _pending-setup.md for %s", integration_name, exc_info=True
        )
