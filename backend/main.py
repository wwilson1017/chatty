"""
Chatty — FastAPI entry point.

Mounts all routers, initializes databases, sets up CORS.
"""

import logging
from contextlib import asynccontextmanager
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
from webby.router import router as webby_router

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize required directories and databases on startup."""
    # Ensure data directories exist
    data_root = Path(__file__).resolve().parent / "data"
    for subdir in ("agents", "branding", "integrations"):
        (data_root / subdir).mkdir(parents=True, exist_ok=True)

    # Initialize agent registry DB
    from agents.db import init_db as init_agents_db
    init_agents_db()

    # Initialize CRM Lite DB if enabled
    from integrations.registry import is_enabled as integration_enabled
    if integration_enabled("crm_lite"):
        from integrations.crm_lite.db import init_db as init_crm_db
        init_crm_db()

    logger.info("Chatty backend started. Data dir: %s", data_root)
    yield
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
app.include_router(webby_router, tags=["webby"])


@app.get("/api/health")
async def health():
    return {"status": "ok", "version": "0.1.0"}


# ── Static files (production frontend build) ──────────────────────────────────

_frontend_dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if _frontend_dist.exists():
    app.mount("/", StaticFiles(directory=str(_frontend_dist), html=True), name="frontend")
