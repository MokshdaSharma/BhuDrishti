"""ParcelAI FastAPI application entry point.

Run with:
    uvicorn app.main:app --reload
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import (
    accuracy,
    compare,
    context,
    export,
    field,
    issues,
    jobs,
    parcels,
    projects,
    tiles,
    upload,
)
from app.core.config import get_settings
from app.core.errors import ParcelAIError, parcelai_exception_handler
from app.core.logging import configure_logging

# ── Logging ────────────────────────────────────────────────────────────────────
configure_logging()

# ── Settings ───────────────────────────────────────────────────────────────────
settings = get_settings()

# ── App ────────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="ParcelAI",
    description=(
        "AI-Based Automated Urban Parcel Mapping Platform. "
        "**Preliminary — subject to field verification.**"
    ),
    version="0.1.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

# ── CORS ───────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Error handlers ─────────────────────────────────────────────────────────────
app.add_exception_handler(ParcelAIError, parcelai_exception_handler)  # type: ignore[arg-type]

# ── Routers ────────────────────────────────────────────────────────────────────

app.include_router(projects.router, prefix="/api/v1")
app.include_router(upload.router, prefix="/api/v1")
app.include_router(jobs.router, prefix="/api/v1")
app.include_router(parcels.router, prefix="/api/v1")
app.include_router(issues.router, prefix="/api/v1")
app.include_router(compare.router, prefix="/api/v1")
app.include_router(accuracy.router, prefix="/api/v1")
app.include_router(export.router, prefix="/api/v1")
app.include_router(tiles.router, prefix="/api/v1")
app.include_router(context.router, prefix="/api/v1")
app.include_router(field.router, prefix="/api/v1")


# ── Health check ───────────────────────────────────────────────────────────────
@app.get("/api/v1/health", tags=["system"])
async def health() -> dict[str, Any]:
    """Liveness probe.

    Returns service status and current MOCK_MODEL flag.
    All downstream checks are non-blocking — a partial failure returns
    ``status: "degraded"`` rather than an HTTP error so monitoring
    does not alert on optional services (GEE, WebODM).
    """
    checks: dict[str, str] = {}
    overall = "ok"

    # Database ping (Phase 1+ will do a real query; for now just note config)
    checks["database"] = "configured" if settings.database_url else "missing"

    # Redis ping
    checks["redis"] = "configured" if settings.redis_url else "missing"

    # Model mode
    checks["mock_model"] = str(settings.mock_model).lower()

    # GEE
    checks["gee"] = "enabled" if settings.enable_gee else "disabled"

    return {
        "status": overall,
        "version": "0.1.0",
        "disclaimer": "Preliminary — subject to field verification",
        "checks": checks,
        "timestamp": int(time.time()),
    }
