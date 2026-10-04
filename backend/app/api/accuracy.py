"""Accuracy assessment API router (Section 7.9)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models.db_models import Project
from app.models.schemas import AccuracyReport
from app.services.accuracy import compute_accuracy

router = APIRouter(prefix="/projects", tags=["accuracy"])


@router.get("/{project_id}/accuracy", response_model=AccuracyReport)
def get_project_accuracy(
    project_id: int,
    db: Session = Depends(get_db),
) -> AccuracyReport:
    """Retrieve accuracy metrics computed against GNSS checkpoints and ground truth."""
    project = db.scalar(select(Project).where(Project.id == project_id))
    if not project:
        raise HTTPException(status_code=404, detail=f"Project #{project_id} not found")

    return compute_accuracy(project_id=project_id, db=db)
