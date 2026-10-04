"""Tiles API router providing TiTiler and Martin tile endpoints for frontend map viewers."""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models.db_models import Project, Raster

router = APIRouter(prefix="/projects", tags=["tiles"])


@router.get("/{project_id}/tiles")
def get_project_tile_urls(
    project_id: int,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Retrieve dynamic XYZ raster and vector tile URL templates for Mapbox/MapLibre."""
    project = db.scalar(select(Project).where(Project.id == project_id))
    if not project:
        raise HTTPException(status_code=404, detail=f"Project #{project_id} not found")

    titiler_base = os.getenv("TITILER_URL", "http://localhost:8000/titiler")
    martin_base = os.getenv("MARTIN_URL", "http://localhost:3000")

    rasters = db.scalars(select(Raster).where(Raster.project_id == project_id)).all()
    raster_tiles = {}
    for r in rasters:
        raster_tiles[r.kind.value] = f"{titiler_base}/cog/tiles/{{z}}/{{x}}/{{y}}.png?url={r.path}"

    vector_tiles = {
        "parcels": f"{martin_base}/parcels/{{z}}/{{x}}/{{y}}",
        "buildings": f"{martin_base}/buildings/{{z}}/{{x}}/{{y}}",
        "roads": f"{martin_base}/roads/{{z}}/{{x}}/{{y}}",
        "landuse": f"{martin_base}/landuse/{{z}}/{{x}}/{{y}}",
        "issues": f"{martin_base}/issues/{{z}}/{{x}}/{{y}}",
    }

    return {
        "project_id": project_id,
        "raster_tiles": raster_tiles,
        "vector_tiles": vector_tiles,
    }
