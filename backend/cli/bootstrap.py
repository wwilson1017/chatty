"""Chatty CLI — Lightweight backend bootstrap (no web server)."""

import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

_BACKEND_DIR = Path(__file__).resolve().parent.parent


def _safe_init(name: str, init_fn, critical: bool = False):
    try:
        init_fn()
    except Exception as e:
        if critical:
            raise
        logger.warning("Non-critical DB init failed (%s): %s", name, e)


def bootstrap():
    """Initialize Chatty backend for CLI use."""
    from dotenv import load_dotenv
    load_dotenv(_BACKEND_DIR / ".env")

    from core.encryption import EncryptionKeyManager
    EncryptionKeyManager.get_key()

    data_root = _BACKEND_DIR / "data"
    for subdir in ("agents", "shared", "reminders", "integrations"):
        (data_root / subdir).mkdir(parents=True, exist_ok=True)

    from agents.db import init_db as init_agents_db
    _safe_init("agents", init_agents_db, critical=True)

    from integrations.registry import is_enabled as integration_enabled
    if integration_enabled("crm_lite"):
        from integrations.crm_lite.db import init_db as init_crm_db
        _safe_init("crm_lite", init_crm_db)

    from core.agents.reminders.db import init_db as init_reminders_db
    _safe_init("reminders", init_reminders_db)

    from core.agents.shared_context.db import init_db as init_shared_context_db
    _safe_init("shared_context", init_shared_context_db)

    from core.agents.tool_config_db import init_db as init_tool_config_db
    _safe_init("tool_configs", init_tool_config_db)

    from core.events.db import init_db as init_events_db
    _safe_init("events", init_events_db)

    from core.agents.shared_context.db import DATA_DIR as shared_dir
    seed_dir = _BACKEND_DIR / "seed" / "shared"
    if seed_dir.exists():
        shared_dir.mkdir(parents=True, exist_ok=True)
        for sf in seed_dir.glob("*.md"):
            target = shared_dir / sf.name
            if not target.exists():
                shutil.copy2(sf, target)
