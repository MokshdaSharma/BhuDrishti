"""Projects API endpoints (Section 7.9)."""

from fastapi import APIRouter, Depends, HTTPException, Response, status
from geoalchemy2.shape import to_shape
from shapely.geometry import mapping
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models.db_models import Project, ProjectStatus
from app.models.schemas import ProjectCreate, ProjectRead

router = APIRouter(prefix="/projects", tags=["projects"])


def _project_to_schema(p: Project) -> ProjectRead:
    extent_dict = None
    if p.extent is not None:
        try:
            extent_dict = mapping(to_shape(p.extent))
        except Exception:
            extent_dict = None

    return ProjectRead(
        id=p.id,
        name=p.name,
        crs=p.crs,
        extent=extent_dict,
        status=p.status,
        created_at=p.created_at,
    )


@router.post("", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
def create_project(payload: ProjectCreate, db: Session = Depends(get_db)) -> ProjectRead:
    """Create a new mapping project."""
    project = Project(
        name=payload.name,
        crs=payload.crs,
        status=ProjectStatus.pending,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return _project_to_schema(project)


@router.get("", response_model=list[ProjectRead])
def list_projects(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)) -> list[ProjectRead]:
    """List all projects with pagination."""
    projects = db.scalars(select(Project).offset(skip).limit(limit).order_by(Project.id.desc())).all()
    return [_project_to_schema(p) for p in projects]


@router.get("/{project_id}", response_model=ProjectRead)
def get_project(project_id: int, db: Session = Depends(get_db)) -> ProjectRead:
    """Retrieve details of a specific project."""
    project = db.scalar(select(Project).where(Project.id == project_id))
    if not project:
        raise HTTPException(status_code=404, detail=f"Project #{project_id} not found")
    return _project_to_schema(project)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def delete_project(project_id: int, db: Session = Depends(get_db)) -> Response:
    """Delete a project and all associated cascading records."""
    project = db.scalar(select(Project).where(Project.id == project_id))
    if not project:
        raise HTTPException(status_code=404, detail=f"Project #{project_id} not found")
    db.delete(project)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
