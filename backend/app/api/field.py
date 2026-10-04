"""Field verification and QField package API router (Section 7.9 & 7.11)."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models.db_models import Project
from app.models.schemas import FieldSyncResult
from app.services.field_sync import generate_field_package, sync_field_package

router = APIRouter(prefix="/projects", tags=["field"])


@router.get("/{project_id}/field-package")
def get_field_package(project_id: int, db: Session = Depends(get_db)) -> FileResponse:
    """Export lightweight GeoPackage configured for QField mobile field verification."""
    project = db.scalar(select(Project).where(Project.id == project_id))
    if not project:
        raise HTTPException(status_code=404, detail=f"Project #{project_id} not found")

    try:
        gpkg_path = generate_field_package(project_id=project_id, db=db)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to generate field package: {exc}") from exc

    return FileResponse(
        path=str(gpkg_path),
        filename=f"project_{project_id}_qfield.gpkg",
        media_type="application/geopackage+sqlite3",
    )


@router.post("/{project_id}/field-sync", response_model=FieldSyncResult)
async def sync_field_package_endpoint(
    project_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> FieldSyncResult:
    """Ingest surveyed GeoPackage from QField, updating verified parcel statuses and ground-truth points."""
    project = db.scalar(select(Project).where(Project.id == project_id))
    if not project:
        raise HTTPException(status_code=404, detail=f"Project #{project_id} not found")

    temp_file = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".gpkg", delete=False) as tmp:
            shutil.copyfileobj(file.file, tmp)
            temp_file = Path(tmp.name)

        result = sync_field_package(
            project_id=project_id,
            gpkg_path=temp_file,
            db=db,
            file_name=file.filename,
        )
        return FieldSyncResult(**result)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Field sync failed: {exc}") from exc
    finally:
        if temp_file and temp_file.exists():
            import contextlib
            with contextlib.suppress(Exception):
                temp_file.unlink()

