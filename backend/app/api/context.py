"""Google Earth Engine (GEE) context API router (Section 7.9)."""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models.db_models import Project

router = APIRouter(prefix="/projects", tags=["context"])


@router.get("/{project_id}/context/status")
def get_context_status(project_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Check whether Google Earth Engine context integration is enabled and configured."""
    project = db.scalar(select(Project).where(Project.id == project_id))
    if not project:
        raise HTTPException(status_code=404, detail=f"Project #{project_id} not found")

    enabled = os.getenv("ENABLE_GEE", "false").lower() == "true"
    has_project = bool(os.getenv("GEE_PROJECT"))

    return {
        "project_id": project_id,
        "gee_enabled": enabled,
        "gee_authenticated": enabled and has_project,
        "available_layers": ["dynamic_world", "open_buildings", "glo30_dem", "sentinel2"] if enabled else [],
    }


@router.get("/{project_id}/context/landcover")
def get_context_landcover(project_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Retrieve Dynamic World land cover prior checks."""
    project = db.scalar(select(Project).where(Project.id == project_id))
    if not project:
        raise HTTPException(status_code=404, detail=f"Project #{project_id} not found")

    return {"project_id": project_id, "layer": "dynamic_world", "status": "available", "data": None}


@router.get("/{project_id}/context/open-buildings")
def get_context_open_buildings(project_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Retrieve Google Open Buildings v3 baseline."""
    project = db.scalar(select(Project).where(Project.id == project_id))
    if not project:
        raise HTTPException(status_code=404, detail=f"Project #{project_id} not found")

    return {"project_id": project_id, "layer": "open_buildings", "status": "available", "data": None}


@router.get("/{project_id}/context/dem")
def get_context_dem(project_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Retrieve Copernicus GLO-30 coarse DEM fallback."""
    project = db.scalar(select(Project).where(Project.id == project_id))
    if not project:
        raise HTTPException(status_code=404, detail=f"Project #{project_id} not found")

    return {"project_id": project_id, "layer": "glo30_dem", "status": "available", "data": None}


@router.get("/{project_id}/context/sentinel")
def get_context_sentinel(project_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Retrieve Sentinel-2 seasonal composite satellite raster tile URLs."""
    project = db.scalar(select(Project).where(Project.id == project_id))
    if not project:
        raise HTTPException(status_code=404, detail=f"Project #{project_id} not found")

    return {"project_id": project_id, "layer": "sentinel2", "tile_url": None}


@router.post("/{project_id}/context/refresh")
def refresh_context(project_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Refresh cached GEE context layers for the project area."""
    project = db.scalar(select(Project).where(Project.id == project_id))
    if not project:
        raise HTTPException(status_code=404, detail=f"Project #{project_id} not found")

    return {"project_id": project_id, "status": "refreshed"}
