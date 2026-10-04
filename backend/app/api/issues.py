"""Topology Issues API endpoints (Section 7.9)."""

from __future__ import annotations

import contextlib
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from geoalchemy2.shape import to_shape
from shapely.geometry import mapping
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models.db_models import Issue, IssueSeverity, Project
from app.models.schemas import IssuePatch, ValidationSummary
from app.services.topology import validate

router = APIRouter(tags=["issues"])


def _issue_to_feature(iss: Issue) -> dict[str, Any]:
    geom_dict = None
    if iss.geom is not None:
        try:
            geom_dict = mapping(to_shape(iss.geom))
        except Exception:
            geom_dict = None

    return {
        "type": "Feature",
        "id": iss.id,
        "geometry": geom_dict,
        "properties": {
            "id": iss.id,
            "project_id": iss.project_id,
            "issue_type": iss.issue_type.value,
            "severity": iss.severity.value,
            "suggested_fix": iss.suggested_fix,
            "resolved": iss.resolved,
            "created_at": iss.created_at.isoformat() if iss.created_at else None,
        },
    }


@router.post("/projects/{project_id}/validate", response_model=ValidationSummary)
def run_validation(
    project_id: int,
    autofix: bool = True,
    db: Session = Depends(get_db),
) -> ValidationSummary:
    """Run on-demand topology validation for a project with optional auto-fix."""
    project = db.scalar(select(Project).where(Project.id == project_id))
    if not project:
        raise HTTPException(status_code=404, detail=f"Project #{project_id} not found")

    return validate(project_id, db=db, autofix=autofix)


@router.get("/projects/{project_id}/issues")
def list_issues(
    project_id: int,
    severity: str | None = Query(None),
    resolved: bool | None = Query(None),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Retrieve validation issues for a project as a GeoJSON FeatureCollection."""
    query = select(Issue).where(Issue.project_id == project_id)
    if severity:
        with contextlib.suppress(ValueError):
            query = query.where(Issue.severity == IssueSeverity(severity))
    if resolved is not None:
        query = query.where(Issue.resolved == resolved)

    issues = db.scalars(query.order_by(Issue.id.asc())).all()

    return {
        "type": "FeatureCollection",
        "features": [_issue_to_feature(iss) for iss in issues],
    }


@router.patch("/issues/{issue_id}")
def update_issue(
    issue_id: int,
    payload: IssuePatch,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Mark an issue as resolved or update its suggested fix."""
    issue = db.scalar(select(Issue).where(Issue.id == issue_id))
    if not issue:
        raise HTTPException(status_code=404, detail=f"Issue #{issue_id} not found")

    if payload.resolved is not None:
        issue.resolved = payload.resolved
    if payload.suggested_fix is not None:
        issue.suggested_fix = payload.suggested_fix

    db.commit()
    db.refresh(issue)
    return _issue_to_feature(issue)
