"""Upload API endpoints for drone rasters and reference GIS layers (Section 7.9)."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from geoalchemy2.shape import from_shape
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.errors import IngestError
from app.models.db_models import GtPoint, GTPointSource, Project, Raster, RasterKind
from app.services.accuracy import load_point_features
from app.services.ingest import validate_raster

router = APIRouter(prefix="/projects", tags=["upload"])


@router.post("/{project_id}/upload", status_code=status.HTTP_201_CREATED)
async def upload_file(
    project_id: int,
    kind: str = Form(..., description="Raster kind (ori, dsm, dtm) or vector kind (parcels, gt)"),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Upload project input data: ORI, DSM, DTM, existing parcels, or GT/GNSS survey points."""
    project = db.scalar(select(Project).where(Project.id == project_id))
    if not project:
        raise HTTPException(status_code=404, detail=f"Project #{project_id} not found")

    kind_lower = kind.lower().strip()
    valid_kinds = {"ori", "dsm", "dtm", "parcels", "gt"}
    if kind_lower not in valid_kinds:
        raise HTTPException(status_code=400, detail=f"Invalid kind '{kind}'. Valid kinds: {sorted(valid_kinds)}")

    # Prepare project upload directory
    upload_dir = Path("data") / "projects" / str(project_id)
    upload_dir.mkdir(parents=True, exist_ok=True)
    file_path = upload_dir / (file.filename or f"{kind_lower}_upload.tif")

    # Save uploaded bytes
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    # Process based on kind
    if kind_lower in ("ori", "dsm", "dtm"):
        try:
            info = validate_raster(file_path)
        except IngestError as exc:
            if file_path.exists():
                file_path.unlink()
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        # Create or update DB Raster entry
        raster_kind = RasterKind(kind_lower)
        existing_raster = db.scalar(
            select(Raster).where(Raster.project_id == project_id, Raster.kind == raster_kind)
        )
        if existing_raster:
            existing_raster.path = str(file_path)
            existing_raster.crs = info.crs
            existing_raster.resolution = float(info.resolution[0])
        else:
            new_raster = Raster(
                project_id=project_id,
                kind=raster_kind,
                path=str(file_path),
                crs=info.crs,
                resolution=float(info.resolution[0]),
            )
            db.add(new_raster)
        db.commit()

        return {
            "status": "uploaded",
            "project_id": project_id,
            "kind": kind_lower,
            "file_name": file.filename,
            "path": str(file_path),
            "crs": info.crs,
            "resolution": info.resolution,
            "dimensions": (info.width, info.height),
        }

    elif kind_lower == "gt":
        # Load survey points into gt_points table
        try:
            pts = load_point_features(file_path)
            for pt in pts:
                gt_rec = GtPoint(
                    project_id=project_id,
                    geom=from_shape(pt, srid=32643),
                    source=GTPointSource.gnss,
                    accuracy_m=0.05,
                )
                db.add(gt_rec)
            db.commit()
            return {
                "status": "uploaded",
                "project_id": project_id,
                "kind": "gt",
                "file_name": file.filename,
                "points_imported": len(pts),
            }
        except Exception as exc:
            return {
                "status": "uploaded",
                "project_id": project_id,
                "kind": "gt",
                "file_name": file.filename,
                "note": f"Saved file; point parsing note: {exc}",
            }

    else:
        # Existing parcels layer
        return {
            "status": "uploaded",
            "project_id": project_id,
            "kind": kind_lower,
            "file_name": file.filename,
            "path": str(file_path),
        }
