"""Tests for Pydantic schemas (Phase 1).

Verifies request/response schema validation, defaults, and field serialisation.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.models.db_models import (
    ParcelSource,
    ParcelStatus,
    ProjectStatus,
)
from app.models.schemas import (
    AccuracyReport,
    CompareSummary,
    ParcelCreate,
    ParcelMergeRequest,
    ParcelSplitRequest,
    ProjectCreate,
    ProjectRead,
    ValidationSummary,
)


def test_project_schemas():
    p_create = ProjectCreate(name="Test Project", crs="EPSG:32643")
    assert p_create.name == "Test Project"
    assert p_create.crs == "EPSG:32643"

    now = datetime.now(timezone.utc)
    p_read = ProjectRead(
        id=1,
        name="Test Project",
        crs="EPSG:32643",
        extent=None,
        status=ProjectStatus.pending,
        created_at=now,
    )
    assert p_read.id == 1
    assert p_read.status == ProjectStatus.pending


def test_parcel_schemas():
    p_create = ParcelCreate(
        project_id=1,
        geom={"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]},
        confidence=0.95,
        source=ParcelSource.ai,
        status=ParcelStatus.draft,
        area_m2=100.0,
        ladm_attrs={"ba_unit_id": "P-001"},
    )
    assert p_create.confidence == 0.95
    assert p_create.source == ParcelSource.ai

    merge_req = ParcelMergeRequest(parcel_ids=[1, 2, 3])
    assert len(merge_req.parcel_ids) == 3

    with pytest.raises(ValidationError):
        # Must have at least 2 IDs
        ParcelMergeRequest(parcel_ids=[1])

    split_req = ParcelSplitRequest(line={"type": "LineString", "coordinates": [[0, 0.5], [1, 0.5]]})
    assert split_req.line["type"] == "LineString"


def test_validation_and_compare_summary_schemas():
    val_summary = ValidationSummary(
        project_id=1,
        total_parcels=100,
        valid_parcels=95,
        issues_found=5,
        autofixed_count=2,
    )
    assert val_summary.project_id == 1
    assert val_summary.valid_parcels == 95

    comp_summary = CompareSummary(
        project_id=1,
        matched_count=80,
        new_count=10,
        missing_count=5,
        changed_count=5,
    )
    assert comp_summary.matched_count == 80


def test_accuracy_report_schema():
    acc = AccuracyReport(
        project_id=1,
        rmse_horizontal_m=0.12,
        mean_horizontal_error_m=0.09,
        iou_buildings=0.88,
        f1_buildings=0.93,
        iou_parcels=0.85,
        f1_parcels=0.91,
        correct_parcels=90,
        merged_parcels=2,
        split_parcels=3,
    )
    assert acc.rmse_horizontal_m == 0.12
    assert acc.f1_buildings == 0.93
