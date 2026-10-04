"""GIS Export and PDF Report API router (Section 7.9)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models.db_models import Project
from app.services.accuracy import compute_accuracy
from app.services.export import export_dataset
from app.services.report import build_pdf_report

router = APIRouter(prefix="/projects", tags=["export"])


@router.get("/{project_id}/export")
def export_project_layers(
    project_id: int,
    format: str = Query("geojson", description="Export format: geojson, gpkg, shp, kml"),
    crs: str = Query("EPSG:4326", description="Target CRS (default EPSG:4326)"),
    db: Session = Depends(get_db),
) -> FileResponse:
    """Export all project vector layers in requested GIS format."""
    project = db.scalar(select(Project).where(Project.id == project_id))
    if not project:
        raise HTTPException(status_code=404, detail=f"Project #{project_id} not found")

    try:
        file_path = export_dataset(project_id=project_id, fmt=format, crs=crs, db=db)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    media_types = {
        "geojson": "application/geo+json",
        "gpkg": "application/geopackage+sqlite3",
        "shp": "application/zip",
        "kml": "application/vnd.google-earth.kml+xml",
    }

    return FileResponse(
        path=str(file_path),
        filename=file_path.name,
        media_type=media_types.get(format.lower(), "application/octet-stream"),
    )


@router.get("/{project_id}/report/pdf")
def get_project_pdf_report(
    project_id: int,
    db: Session = Depends(get_db),
) -> FileResponse:
    """Generate and download official PDF cadastral survey and validation report."""
    project = db.scalar(select(Project).where(Project.id == project_id))
    if not project:
        raise HTTPException(status_code=404, detail=f"Project #{project_id} not found")

    try:
        acc_report = compute_accuracy(project_id=project_id, db=db)
        pdf_path = build_pdf_report(project_id=project_id, db=db, accuracy_report=acc_report)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to generate PDF report: {exc}") from exc

    return FileResponse(
        path=str(pdf_path),
        filename=pdf_path.name,
        media_type="application/pdf",
    )
