"""
Chatty — FastAPI entry point.

Mounts all routers, initializes databases, sets up CORS and APScheduler.
"""

import contextvars
import logging
import os
import shutil
import uuid as _uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from core.config import settings
from core.auth import router as auth_router
from core.auth_2fa import router as auth_2fa_router
from core.providers.router import router as providers_router
from core.providers.oauth_callback_router import router as oauth_callback_router
from agents.router import router as agents_router
from agents.import_router import router as import_router
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

# Request-ID context variable for log tracing
request_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default="",
)


# ---------------------------------------------------------------------------
# Per-DB safe initialization
# ---------------------------------------------------------------------------

db_statuses: dict[str, str] = {}


def _safe_init(name: str, fn, *, critical: bool = False) -> None:
    """Initialize a database with error isolation and status tracking."""
    try:
        result = fn()
        status = result.get("status", "ok") if isinstance(result, dict) else "ok"
        db_statuses[name] = status
        if status not in ("ok", "fresh"):
            logger.warning("DB %s initialized with status: %s", name, status)
    except Exception:
        logger.exception("DB init failed: %s", name)
        db_statuses[name] = "error"
        if critical:
            raise
        return

    if critical and db_statuses[name] not in ("ok", "fresh"):
        raise RuntimeError(f"Critical DB {name} init returned: {db_statuses[name]}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize required directories and databases on startup."""
    global _scheduler

    # Ensure data directories exist
    data_root = Path(__file__).resolve().parent / "data"
    for subdir in ("agents", "branding", "integrations", "reminders", "telegram", "whatsapp"):
        (data_root / subdir).mkdir(parents=True, exist_ok=True)

    # ── Database initialization (per-DB error isolation) ───────────────────
    from agents.db import init_db as init_agents_db
    _safe_init("agents", init_agents_db, critical=True)

    from integrations.crm_lite.db import init_db as init_crm_db
    _safe_init("crm_lite", init_crm_db)

    from integrations.registry import is_enabled as integration_enabled, ensure_crm_active
    ensure_crm_active()

    if integration_enabled("qb_csv"):
        from integrations.qb_csv.db import init_db as init_qb_csv_db
        _safe_init("qb_csv", init_qb_csv_db)

    from integrations.telegram.state import init_db as init_telegram_db
    _safe_init("telegram", init_telegram_db)

    from integrations.telegram.lifecycle import register_all_webhooks
    register_all_webhooks()

    if settings.whatsapp.is_configured:
        from integrations.whatsapp.state import init_db as init_whatsapp_db
        _safe_init("whatsapp", init_whatsapp_db)
        logger.info("WhatsApp bridge configured at %s", settings.whatsapp.bridge_url)

    from core.auth_2fa import init_db as init_auth_2fa_db
    _safe_init("auth_2fa", init_auth_2fa_db, critical=True)

    from core.agents.reminders.db import init_db as init_reminders_db
    _safe_init("reminders", init_reminders_db)

    from core.agents.shared_context.db import init_db as init_shared_context_db
    _safe_init("shared_context", init_shared_context_db)

    from core.agents.shared_context.db import DATA_DIR as _shared_dir
    _seed_dir = Path(__file__).parent / "seed" / "shared"
    if _seed_dir.exists():
        _shared_dir.mkdir(parents=True, exist_ok=True)
        for _sf in _seed_dir.glob("*.md"):
            _target = _shared_dir / _sf.name
            if not _target.exists():
                shutil.copy2(_sf, _target)
                logger.info("Seeded shared context: %s", _sf.name)

    from core.agents.tool_config_db import init_db as init_tool_config_db
    _safe_init("tool_configs", init_tool_config_db)

    # Store statuses on app.state for health endpoint
    app.state.db_statuses = db_statuses

    # ── APScheduler ────────────────────────────────────────────────────────
    from apscheduler.schedulers.background import BackgroundScheduler
    _scheduler = BackgroundScheduler()

    from core.agents.reminders.heartbeat import process_due_reminders
    from core.agents.scheduled_actions.processor import process_due_actions

    _scheduler.add_job(process_due_reminders, "interval", seconds=60, id="reminder_heartbeat")
    _scheduler.add_job(process_due_actions, "interval", seconds=60, id="scheduled_actions_processor")

    from core.agents.scheduled_actions.nightly import run_nightly_jobs
    _scheduler.add_job(run_nightly_jobs, "cron", hour=23, minute=0, id="nightly_memory_jobs",
                       timezone="America/Chicago")

    from core.auth_2fa import cleanup_expired_devices
    _scheduler.add_job(cleanup_expired_devices, "interval", hours=24, id="2fa_device_cleanup")

    from agents.import_service.sessions import sweep_expired as _sweep_import_sessions
    _scheduler.add_job(_sweep_import_sessions, "interval", seconds=600, id="import_session_sweep")

    from core.agents.scheduled_actions.sweeper import sweep as _scheduled_sweep
    _scheduler.add_job(_scheduled_sweep, "interval", seconds=300, id="scheduled_actions_sweeper")

    _scheduler.start()
    logger.info("APScheduler started (reminder heartbeat + scheduled actions + sweeper + nightly jobs)")

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
        volume_marker.write_text(f"chatty:{datetime.now(timezone.utc).isoformat()}", encoding="utf-8")
        if settings.is_railway:
            logger.info(
                "First boot — wrote volume marker to %s. "
                "If this message appears on every deploy, your persistent volume may not be configured. "
                "Mount a volume at /app/backend/data in Railway settings.",
                volume_marker,
            )

    logger.info("Chatty backend started. Data dir: %s", data_root)
    yield

    # Shutdown scheduler + executor
    if _scheduler:
        _scheduler.shutdown(wait=False)
    try:
        from core.agents.scheduled_actions.processor import shutdown_executor
        shutdown_executor()
    except Exception:
        pass
    logger.info("Chatty backend shutting down.")


app = FastAPI(
    title="Chatty",
    description="Personal AI agent platform",
    version="1.0.0",
    lifespan=lifespan,
)


# ── Request-ID middleware ────────────────────────────────────────────────────

@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    rid = _uuid.uuid4().hex[:12]
    request_id_ctx.set(rid)
    response = await call_next(request)
    response.headers["X-Request-ID"] = rid
    return response


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
app.include_router(auth_2fa_router, prefix="/api", tags=["auth-2fa"])
app.include_router(providers_router, prefix="/api/providers", tags=["providers"])
app.include_router(oauth_callback_router, prefix="/api/oauth", tags=["oauth"])
app.include_router(agents_router, prefix="/api/agents", tags=["agents"])
app.include_router(import_router, tags=["import"])
app.include_router(branding_router, prefix="/api/branding", tags=["branding"])
app.include_router(integrations_router, prefix="/api/integrations", tags=["integrations"])
app.include_router(whatsapp_router, prefix="/api/messaging", tags=["messaging"])
app.include_router(crm_router, prefix="/api/crm", tags=["crm"])
app.include_router(qb_csv_router, prefix="/api/qb-csv", tags=["qb-csv"])
app.include_router(webby_router, tags=["webby"])
app.include_router(scheduled_actions_router, prefix="/api/scheduled-actions", tags=["scheduled-actions"])

from core.agents.alerts.router import router as alerts_router
app.include_router(alerts_router, prefix="/api/alerts", tags=["alerts"])
app.include_router(setup_router, prefix="/api/setup", tags=["setup"])
app.include_router(backup_router, prefix="/api/backup", tags=["backup"])
app.include_router(telegram_router, prefix="/api/telegram", tags=["telegram"])

from core.agents.shared_context.router import router as shared_context_router
app.include_router(shared_context_router, tags=["shared-context"])


# ── Health endpoints ──────────────────────────────────────────────────────────

@app.get("/api/health")
async def health(request: Request):
    statuses = getattr(request.app.state, "db_statuses", {})
    degraded = any(v not in ("ok", "fresh") for v in statuses.values())
    return {"status": "degraded" if degraded else "ok", "version": "0.1.0", "databases": statuses}


@app.get("/api/health/live")
async def health_live():
    return {"status": "ok"}


# ── Static files (production frontend build) ──────────────────────────────────

_frontend_dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if _frontend_dist.exists():
    app.mount("/", StaticFiles(directory=str(_frontend_dist), html=True), name="frontend")
