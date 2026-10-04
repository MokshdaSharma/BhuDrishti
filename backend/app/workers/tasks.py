"""Celery background tasks for ParcelAI pipeline (Section 7.9).

Orchestrates:
1. Ingest (CRS validation, reprojection, nDSM, COG tiling)
2. Inference (Probability COGs generation)
3. Vectorization (Buildings, roads, landuse feature extraction)
4. Hybrid Parcel Builder (Watershed, linework reconciliation, cadastral rules, confidence)
5. Topology Validation (Overlaps, gaps, slivers, encroachments, autofix)
6. GIS Comparison (IoU, area difference, new/missing/changed)
7. Accuracy Assessment (GNSS RMSE, horizontal error, F1)
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select

from app.core.db import get_session_factory
from app.models.db_models import Project, ProjectStatus
from app.services.accuracy import compute_accuracy
from app.services.compare import compare_with_existing
from app.services.inference import run_inference
from app.services.ingest import prepare_project
from app.services.parcels import build_parcels
from app.services.topology import validate
from app.services.vectorize import extract_features
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


def execute_pipeline_sync(project_id: int, progress_callback: Any | None = None) -> dict[str, Any]:
    """Synchronous pipeline execution (used directly in tests and as Celery task body)."""
    session_factory = get_session_factory()
    db = session_factory()

    def update_progress(pct: int, msg: str) -> None:
        logger.info(f"[Project {project_id}] {pct}% - {msg}")
        if progress_callback:
            progress_callback(pct, msg)

    try:
        # Fetch project
        project = db.scalar(select(Project).where(Project.id == project_id))
        if project:
            project.status = ProjectStatus.processing
            db.commit()

        # 1. Ingest (0% -> 20%)
        update_progress(10, "Ingesting and preparing project rasters")
        prepared = prepare_project(project_id)
        update_progress(25, "Project rasters ingested and tiled")

        # 2. Inference (25% -> 50%)
        update_progress(30, "Running AI multi-task segmentation inference")
        probs = run_inference(project_id, prepared.tiles)
        update_progress(50, "Probability COGs generated")

        # 3. Vectorize (50% -> 65%)
        update_progress(55, "Extracting regularized buildings, roads, and land-use")
        features_set = extract_features(project_id, probs)
        update_progress(65, "Base vector features extracted")

        # 4. Hybrid Parcels (65% -> 80%)
        update_progress(70, "Building cadastral parcels with watershed and linework reconciliation")
        parcel_set = build_parcels(project_id, probs, features_set, db_session=db)
        update_progress(80, f"Delineated {parcel_set.count} cadastral parcels")

        # 5. Topology Validation (80% -> 90%)
        update_progress(82, "Validating topology and applying auto-fixes")
        val_summary = validate(project_id, db=db, autofix=True)
        update_progress(90, f"Topology checked: {val_summary.issues_found} issues found, {val_summary.autofixed_count} autofixed")

        # 6. Compare with existing (90% -> 95%)
        update_progress(92, "Comparing with existing cadastral layers")
        comp_summary = compare_with_existing(project_id, db=db)
        update_progress(95, f"Compared: {comp_summary.matched_count} matched, {comp_summary.new_count} new, {comp_summary.changed_count} changed")

        # 7. Accuracy Assessment (95% -> 100%)
        update_progress(97, "Computing accuracy metrics against ground-truth and GNSS")
        acc_report = compute_accuracy(project_id, db=db)

        if project:
            project.status = ProjectStatus.done
            db.commit()

        update_progress(100, "Pipeline completed successfully")

        return {
            "status": "done",
            "project_id": project_id,
            "parcels_count": parcel_set.count,
            "total_area_m2": parcel_set.total_area_m2,
            "issues_count": val_summary.issues_found,
            "matched_count": comp_summary.matched_count,
            "rmse_horizontal_m": acc_report.rmse_horizontal_m,
        }

    except Exception as exc:
        logger.exception(f"Pipeline failed for project {project_id}: {exc}")
        if project:
            project.status = ProjectStatus.error
            db.commit()
        raise
    finally:
        db.close()


@celery_app.task(name="tasks.run_pipeline", bind=True)
def run_pipeline(self, project_id: int) -> dict[str, Any]:
    """Asynchronous Celery task for running the end-to-end pipeline."""
    def celery_progress(pct: int, msg: str) -> None:
        self.update_state(
            state="PROGRESS",
            meta={"current": pct, "total": 100, "status": msg},
        )

    return execute_pipeline_sync(project_id, progress_callback=celery_progress)
