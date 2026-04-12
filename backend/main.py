"""
Chatty — FastAPI entry point.

Mounts all routers, initializes databases, sets up CORS and APScheduler.
"""

import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from core.config import settings
from core.auth import router as auth_router
from core.providers.router import router as providers_router
from agents.router import router as agents_router
from branding.router import router as branding_router
from integrations.router import router as integrations_router
from integrations.crm_lite.router import router as crm_router
from integrations.qb_csv.router import router as qb_csv_router
from integrations.whatsapp.router import router as whatsapp_router
from webby.router import router as webby_router
from core.agents.scheduled_actions.router import router as scheduled_actions_router
from setup.router import router as setup_router
from backup.router import router as backup_router
from integrations.telegram.router import router as telegram_router

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# APScheduler instance (started in lifespan)
_scheduler = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize required directories and databases on startup."""
    global _scheduler

    # Ensure data directories exist
    data_root = Path(__file__).resolve().parent / "data"
    for subdir in ("agents", "branding", "integrations", "reminders", "telegram", "whatsapp"):
        (data_root / subdir).mkdir(parents=True, exist_ok=True)

    # Initialize agent registry DB
    from agents.db import init_db as init_agents_db
    init_agents_db()

    # Initialize CRM Lite DB if enabled
    from integrations.registry import is_enabled as integration_enabled
    if integration_enabled("crm_lite"):
        from integrations.crm_lite.db import init_db as init_crm_db
        init_crm_db()

    # Initialize QB CSV Analysis DB if enabled
    if integration_enabled("qb_csv"):
        from integrations.qb_csv.db import init_db as init_qb_csv_db
        init_qb_csv_db()

    # Initialize Telegram state DB + register webhooks
    from integrations.telegram.state import init_db as init_telegram_db
    init_telegram_db()

    from integrations.telegram.lifecycle import register_all_webhooks
    register_all_webhooks()

    # Initialize WhatsApp state DB if bridge is configured
    if settings.whatsapp.is_configured:
        from integrations.whatsapp.state import init_db as init_whatsapp_db
        init_whatsapp_db()
        logger.info("WhatsApp bridge configured at %s", settings.whatsapp.bridge_url)

    # Initialize reminders + scheduled actions DB (also creates dreaming tables)
    from core.agents.reminders.db import init_db as init_reminders_db
    init_reminders_db()

    # Initialize shared context DB
    from core.agents.shared_context.db import init_db as init_shared_context_db
    init_shared_context_db()

    # Initialize tool toggle config DB
    from core.agents.tool_config_db import init_db as init_tool_config_db
    init_tool_config_db()

    # Start APScheduler for reminders and scheduled actions
    from apscheduler.schedulers.background import BackgroundScheduler
    _scheduler = BackgroundScheduler()

    from core.agents.reminders.heartbeat import process_due_reminders
    from core.agents.scheduled_actions.processor import process_due_actions

    _scheduler.add_job(process_due_reminders, "interval", seconds=60, id="reminder_heartbeat")
    _scheduler.add_job(process_due_actions, "interval", seconds=60, id="scheduled_actions_processor")

    # Nightly memory/dreaming jobs (run per-agent)
    from core.agents.scheduled_actions.nightly import run_nightly_jobs
    _scheduler.add_job(run_nightly_jobs, "cron", hour=23, minute=0, id="nightly_memory_jobs",
                       timezone="America/Chicago")

    _scheduler.start()
    logger.info("APScheduler started (reminder heartbeat + scheduled actions + nightly jobs)")

    # Log WhatsApp session status on startup
    if settings.whatsapp.is_configured:
        try:
            from integrations.whatsapp.lifecycle import reconnect_all_sessions
            reconnect_all_sessions()
        except Exception as e:
            logger.warning("WhatsApp session reconnect check failed: %s", e)

    # ── Railway environment logging ─────────────────────────────────────────
    if settings.is_railway:
        from core.config import RAILWAY_PUBLIC_URL
        logger.info("Running on Railway: %s", RAILWAY_PUBLIC_URL)
    else:
        logger.info("Running locally (no RAILWAY_PUBLIC_DOMAIN detected)")

    if settings.jwt_secret_is_auto:
        logger.warning(
            "JWT_SECRET not set — using auto-generated secret. "
            "Sessions will reset on redeploy. Set JWT_SECRET env var for persistent sessions."
        )

    if not os.environ.get("ENCRYPTION_KEY"):
        logger.info(
            "ENCRYPTION_KEY not set — will auto-generate and store in %s",
            data_root / ".encryption-key",
        )

    # ── Volume health check ──────────────────────────────────────────────
    volume_marker = data_root / ".volume-marker"
    if volume_marker.exists():
        logger.info("Persistent volume verified (marker file present)")
    else:
        volume_marker.write_text(f"chatty:{datetime.now(timezone.utc).isoformat()}")
        if settings.is_railway:
            logger.info(
                "First boot — wrote volume marker to %s. "
                "If this message appears on every deploy, your persistent volume may not be configured. "
                "Mount a volume at /app/backend/data in Railway settings.",
                volume_marker,
            )

    logger.info("Chatty backend started. Data dir: %s", data_root)
    yield

    # Shutdown scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
    logger.info("Chatty backend shutting down.")


app = FastAPI(
    title="Chatty",
    description="Personal AI agent platform",
    version="0.1.0",
    lifespan=lifespan,
)

# ── CORS ──────────────────────────────────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routes ────────────────────────────────────────────────────────────────────

app.include_router(auth_router, prefix="/api")
app.include_router(providers_router, prefix="/api/providers", tags=["providers"])
app.include_router(agents_router, prefix="/api/agents", tags=["agents"])
app.include_router(branding_router, prefix="/api/branding", tags=["branding"])
app.include_router(integrations_router, prefix="/api/integrations", tags=["integrations"])
app.include_router(whatsapp_router, prefix="/api/messaging", tags=["messaging"])
app.include_router(crm_router, prefix="/api/crm", tags=["crm"])
app.include_router(qb_csv_router, prefix="/api/qb-csv", tags=["qb-csv"])
app.include_router(webby_router, tags=["webby"])
app.include_router(scheduled_actions_router, prefix="/api/scheduled-actions", tags=["scheduled-actions"])
app.include_router(setup_router, prefix="/api/setup", tags=["setup"])
app.include_router(backup_router, prefix="/api/backup", tags=["backup"])
app.include_router(telegram_router, prefix="/api/telegram", tags=["telegram"])

from core.agents.shared_context.router import router as shared_context_router
app.include_router(shared_context_router, tags=["shared-context"])


@app.get("/api/health")
async def health():
    return {"status": "ok", "version": "0.1.0"}


# ── Static files (production frontend build) ──────────────────────────────────

_frontend_dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if _frontend_dist.exists():
    app.mount("/", StaticFiles(directory=str(_frontend_dist), html=True), name="frontend")
