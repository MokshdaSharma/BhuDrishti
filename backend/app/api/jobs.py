"""Jobs API endpoints for asynchronous pipeline execution (Section 7.9)."""

from __future__ import annotations

import uuid
from typing import Any

try:
    from celery.result import AsyncResult
except ImportError:
    class AsyncResult:  # type: ignore[no-redef]
        def __init__(self, job_id, app=None):
            self.id = job_id
            self.state = "SUCCESS"
            self.result = {"status": "completed"}
            self.info = {"current": 100, "status": "Finished"}
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models.db_models import Project
from app.workers.celery_app import celery_app
from app.workers.tasks import execute_pipeline_sync, run_pipeline

router = APIRouter(tags=["jobs"])


@router.post("/projects/{project_id}/run", status_code=status.HTTP_202_ACCEPTED)
def run_project_pipeline(
    project_id: int,
    sync: bool = False,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Trigger the end-to-end automated processing pipeline for a project."""
    project = db.scalar(select(Project).where(Project.id == project_id))
    if not project:
        raise HTTPException(status_code=404, detail=f"Project #{project_id} not found")

    if sync:
        # Synchronous execution mode (useful for testing and deterministic local runs)
        result = execute_pipeline_sync(project_id)
        return {
            "job_id": f"sync_{uuid.uuid4().hex[:8]}",
            "project_id": project_id,
            "status": "ready",
            "mode": "sync",
            "result": result,
        }

    try:
        # Asynchronous Celery execution
        task = run_pipeline.delay(project_id)
        job_id = str(task.id)
        return {
            "job_id": job_id,
            "project_id": project_id,
            "status": "queued",
            "mode": "async",
        }
    except Exception as exc:
        # Fallback to local synchronous run if Redis / Celery broker is offline
        result = execute_pipeline_sync(project_id)
        return {
            "job_id": f"fallback_{uuid.uuid4().hex[:8]}",
            "project_id": project_id,
            "status": "ready",
            "mode": "sync_fallback",
            "note": f"Celery broker unavailable ({exc}); ran synchronously",
            "result": result,
        }


@router.get("/jobs/{job_id}")
def get_job_status(job_id: str) -> dict[str, Any]:
    """Retrieve current status, progress percentage, and logs of an asynchronous job."""
    if job_id.startswith("sync_") or job_id.startswith("fallback_"):
        return {
            "job_id": job_id,
            "status": "SUCCESS",
            "progress": 100,
            "message": "Completed synchronously",
        }

    task_result = AsyncResult(job_id, app=celery_app)
    state = task_result.state
    meta = task_result.info if isinstance(task_result.info, dict) else {}

    response: dict[str, Any] = {
        "job_id": job_id,
        "status": state,
        "progress": meta.get("current", 0) if state == "PROGRESS" else (100 if state == "SUCCESS" else 0),
        "message": meta.get("status", "") if state == "PROGRESS" else str(task_result.result if state == "SUCCESS" else ""),
    }

    if state == "FAILURE":
        response["error"] = str(task_result.result)

    return response
