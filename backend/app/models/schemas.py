"""Pydantic v2 request / response schemas for the ParcelAI API.

Geometry is represented as GeoJSON-compatible dicts or WKT in responses.
Full serialisation is wired in Phase 7; these schemas define the shapes now
so all phases can import and use them consistently.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.db_models import (
    EditAction,
    GTPointSource,
    IssueSeverity,
    IssueType,
    LanduseClass,
    ParcelSource,
    ParcelStatus,
    ProjectStatus,
    RasterKind,
)

# ── Project ────────────────────────────────────────────────────────────────────


class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    crs: str = Field(default="EPSG:32643", max_length=64)


class ProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    crs: str
    extent: Any | None = None
    status: ProjectStatus
    created_at: datetime


# ── Raster ────────────────────────────────────────────────────────────────────


class RasterCreate(BaseModel):
    project_id: int
    kind: RasterKind
    path: str
    resolution: float | None = None
    crs: str | None = None


class RasterRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    kind: RasterKind
    path: str
    resolution: float | None = None
    crs: str | None = None


# ── Parcel ────────────────────────────────────────────────────────────────────


class ParcelCreate(BaseModel):
    project_id: int
    geom: Any  # WKT or GeoJSON dict
    confidence: float | None = None
    source: ParcelSource = ParcelSource.ai
    status: ParcelStatus = ParcelStatus.draft
    area_m2: float | None = None
    ladm_attrs: dict[str, Any] | None = None
    created_by: str | None = None


class ParcelUpdate(BaseModel):
    geom: Any | None = None
    confidence: float | None = None
    status: ParcelStatus | None = None
    ladm_attrs: dict[str, Any] | None = None


class ParcelRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    geom: Any
    confidence: float | None = None
    source: ParcelSource
    status: ParcelStatus
    area_m2: float | None = None
    ladm_attrs: dict[str, Any] | None = None
    created_by: str | None = None
    updated_at: datetime | None = None


class ParcelMergeRequest(BaseModel):
    parcel_ids: list[int] = Field(..., min_length=2)


class ParcelSplitRequest(BaseModel):
    line: Any  # GeoJSON LineString or WKT


# ── Building ──────────────────────────────────────────────────────────────────


class BuildingCreate(BaseModel):
    project_id: int
    geom: Any
    confidence: float | None = None
    parcel_id: int | None = None


class BuildingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    geom: Any
    confidence: float | None = None
    parcel_id: int | None = None


# ── Road ──────────────────────────────────────────────────────────────────────


class RoadCreate(BaseModel):
    project_id: int
    geom: Any
    centerline: Any | None = None
    width_m: float | None = None


class RoadRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    geom: Any
    centerline: Any | None = None
    width_m: float | None = None


# ── Land use ──────────────────────────────────────────────────────────────────


class LandUseCreate(BaseModel):
    project_id: int
    geom: Any
    landuse_class: LanduseClass = LanduseClass.other
    confidence: float | None = None


class LandUseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    geom: Any
    landuse_class: LanduseClass
    confidence: float | None = None


# ── Issue ─────────────────────────────────────────────────────────────────────


class IssueCreate(BaseModel):
    project_id: int
    issue_type: IssueType
    severity: IssueSeverity = IssueSeverity.warning
    geom: Any | None = None
    suggested_fix: str | None = None
    resolved: bool = False


class IssuePatch(BaseModel):
    resolved: bool | None = None
    suggested_fix: str | None = None


class IssueRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    issue_type: IssueType
    severity: IssueSeverity
    geom: Any | None = None
    suggested_fix: str | None = None
    resolved: bool
    created_at: datetime


IssueUpdate = IssuePatch  # Alias for backward compatibility


# ── GT Point ──────────────────────────────────────────────────────────────────


class GtPointCreate(BaseModel):
    project_id: int
    geom: Any
    source: GTPointSource
    accuracy_m: float | None = None
    photo_url: str | None = None
    note: str | None = None


class GtPointRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    geom: Any
    source: GTPointSource
    accuracy_m: float | None = None
    photo_url: str | None = None
    note: str | None = None


# ── Edit history ──────────────────────────────────────────────────────────────


class EditHistoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    feature_table: str
    feature_id: int
    action: EditAction
    old_geom: Any | None = None
    new_geom: Any | None = None
    user_name: str | None = None
    ts: datetime


# ── GEE cache ─────────────────────────────────────────────────────────────────


class GeeCacheRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    dataset: str
    params_hash: str
    result: Any | None = None
    created_at: datetime
    expires_at: datetime | None = None


# ── High-Level Summaries & Reports (Sections 7.5 - 7.8) ────────────────────────


class ValidationSummary(BaseModel):
    project_id: int
    total_parcels: int
    valid_parcels: int
    issues_found: int
    autofixed_count: int = 0
    issues_by_type: dict[str, int] = Field(default_factory=dict)


class CompareSummary(BaseModel):
    project_id: int
    matched_count: int = 0
    new_count: int = 0
    missing_count: int = 0
    changed_count: int = 0
    details: list[dict[str, Any]] = Field(default_factory=list)


class AccuracyReport(BaseModel):
    project_id: int
    rmse_horizontal_m: float | None = None
    mean_horizontal_error_m: float | None = None
    iou_buildings: float | None = None
    f1_buildings: float | None = None
    iou_parcels: float | None = None
    f1_parcels: float | None = None
    correct_parcels: int = 0
    merged_parcels: int = 0
    split_parcels: int = 0
    disclaimer: str = "Preliminary — subject to field verification"


class FieldSyncResult(BaseModel):
    project_id: int
    status: str = "synced"
    file_name: str | None = None
    verified_parcels: int = 0
    updated_geometries: int = 0
    imported_checkpoints: int = 0
    errors: list[str] = Field(default_factory=list)
    disclaimer: str = "Preliminary — subject to field verification"

