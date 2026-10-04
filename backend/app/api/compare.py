"""Cadastral comparison API router (Section 7.9)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models.db_models import Project
from app.models.schemas import CompareSummary
from app.services.compare import compare_with_existing

router = APIRouter(prefix="/projects", tags=["compare"])


@router.get("/{project_id}/compare", response_model=CompareSummary)
def get_project_comparison(
    project_id: int,
    db: Session = Depends(get_db),
) -> CompareSummary:
    """Compare AI-delineated parcels against existing cadastral GIS layer."""
    project = db.scalar(select(Project).where(Project.id == project_id))
    if not project:
        raise HTTPException(status_code=404, detail=f"Project #{project_id} not found")

    return compare_with_existing(project_id=project_id, db=db)
