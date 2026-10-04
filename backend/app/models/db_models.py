"""SQLAlchemy 2.0 ORM models for all ParcelAI tables (Section 6).

Geometry columns use GeoAlchemy2. GIST indexes declared in __table_args__.
All feature tables carry a project_id FK to projects.
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Any

from geoalchemy2 import Geometry
from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


# Enums
class ProjectStatus(str, enum.Enum):
    pending = "pending"
    processing = "processing"
    done = "done"
    error = "error"


class RasterKind(str, enum.Enum):
    ori = "ori"
    dsm = "dsm"
    dtm = "dtm"
    ndsm = "ndsm"
    prob_building = "prob_building"
    prob_road = "prob_road"
    prob_boundary = "prob_boundary"
    prob_landuse = "prob_landuse"


class ParcelSource(str, enum.Enum):
    ai = "ai"
    edited = "edited"
    field = "field"
    existing = "existing"


class ParcelStatus(str, enum.Enum):
    draft = "draft"
    reviewed = "reviewed"
    verified = "verified"


class LanduseClass(str, enum.Enum):
    built_up = "built_up"
    road = "road"
    vegetation = "vegetation"
    water = "water"
    open_land = "open_land"
    other = "other"


class IssueSeverity(str, enum.Enum):
    info = "info"
    warning = "warning"
    error = "error"


class IssueType(str, enum.Enum):
    invalid_geometry = "invalid_geometry"
    overlap = "overlap"
    gap = "gap"
    sliver = "sliver"
    spike = "spike"
    building_crosses_parcel = "building_crosses_parcel"
    building_on_road = "building_on_road"
    landlocked_parcel = "landlocked_parcel"
    new_parcel = "new_parcel"
    missing_parcel = "missing_parcel"
    changed_parcel = "changed_parcel"
    landuse_prior_mismatch = "landuse_prior_mismatch"
    low_confidence = "low_confidence"


class GTPointSource(str, enum.Enum):
    gnss = "gnss"
    cors = "cors"
    field = "field"


class EditAction(str, enum.Enum):
    insert = "insert"
    update = "update"
    delete = "delete"


# Models


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (Index("idx_projects_extent", "extent", postgresql_using="gist"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    crs: Mapped[str] = mapped_column(String(64), nullable=False, default="EPSG:32643")
    extent: Mapped[Any | None] = mapped_column(Geometry("POLYGON", srid=4326), nullable=True)
    status: Mapped[ProjectStatus] = mapped_column(
        SAEnum(ProjectStatus, name="project_status", create_type=True),
        nullable=False,
        default=ProjectStatus.pending,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    rasters: Mapped[list[Raster]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    parcels: Mapped[list[Parcel]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    buildings: Mapped[list[Building]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    roads: Mapped[list[Road]] = relationship(back_populates="project", cascade="all, delete-orphan")
    landuses: Mapped[list[LandUse]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    issues: Mapped[list[Issue]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    gt_points: Mapped[list[GtPoint]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    gee_caches: Mapped[list[GeeCache]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )


class Raster(Base):
    __tablename__ = "rasters"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[RasterKind] = mapped_column(
        SAEnum(RasterKind, name="raster_kind", create_type=True), nullable=False
    )
    path: Mapped[str] = mapped_column(Text, nullable=False)
    resolution: Mapped[float | None] = mapped_column(Float, nullable=True)
    crs: Mapped[str | None] = mapped_column(String(64), nullable=True)
    project: Mapped[Project] = relationship(back_populates="rasters")


class Parcel(Base):
    __tablename__ = "parcels"
    __table_args__ = (Index("idx_parcels_geom", "geom", postgresql_using="gist"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    geom: Mapped[Any] = mapped_column(Geometry("POLYGON"), nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[ParcelSource] = mapped_column(
        SAEnum(ParcelSource, name="parcel_source", create_type=True),
        nullable=False,
        default=ParcelSource.ai,
    )
    status: Mapped[ParcelStatus] = mapped_column(
        SAEnum(ParcelStatus, name="parcel_status", create_type=True),
        nullable=False,
        default=ParcelStatus.draft,
    )
    area_m2: Mapped[float | None] = mapped_column(Float, nullable=True)
    ladm_attrs: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, onupdate=func.now()
    )
    project: Mapped[Project] = relationship(back_populates="parcels")
    buildings: Mapped[list[Building]] = relationship(back_populates="parcel")


class Building(Base):
    __tablename__ = "buildings"
    __table_args__ = (Index("idx_buildings_geom", "geom", postgresql_using="gist"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    geom: Mapped[Any] = mapped_column(Geometry("POLYGON"), nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    parcel_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("parcels.id", ondelete="SET NULL"), nullable=True, index=True
    )
    project: Mapped[Project] = relationship(back_populates="buildings")
    parcel: Mapped[Parcel | None] = relationship(back_populates="buildings")


class Road(Base):
    __tablename__ = "roads"
    __table_args__ = (
        Index("idx_roads_geom", "geom", postgresql_using="gist"),
        Index("idx_roads_centerline", "centerline", postgresql_using="gist"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    geom: Mapped[Any] = mapped_column(Geometry("POLYGON"), nullable=False)
    centerline: Mapped[Any | None] = mapped_column(Geometry("LINESTRING"), nullable=True)
    width_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    project: Mapped[Project] = relationship(back_populates="roads")


class LandUse(Base):
    """DB column 'class' mapped to Python attr 'landuse_class' (Decision A-LU1)."""

    __tablename__ = "landuse"
    __table_args__ = (Index("idx_landuse_geom", "geom", postgresql_using="gist"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    geom: Mapped[Any] = mapped_column(Geometry("POLYGON"), nullable=False)
    landuse_class: Mapped[LanduseClass] = mapped_column(
        "class",
        SAEnum(LanduseClass, name="landuse_class_enum", create_type=True),
        nullable=False,
        default=LanduseClass.other,
    )
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    project: Mapped[Project] = relationship(back_populates="landuses")


class Issue(Base):
    """DB column 'type' mapped to Python attr 'issue_type'."""

    __tablename__ = "issues"
    __table_args__ = (Index("idx_issues_geom", "geom", postgresql_using="gist"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    issue_type: Mapped[IssueType] = mapped_column(
        "type", SAEnum(IssueType, name="issue_type_enum", create_type=True), nullable=False
    )
    severity: Mapped[IssueSeverity] = mapped_column(
        SAEnum(IssueSeverity, name="issue_severity", create_type=True),
        nullable=False,
        default=IssueSeverity.warning,
    )
    geom: Mapped[Any | None] = mapped_column(Geometry(), nullable=True)
    suggested_fix: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    project: Mapped[Project] = relationship(back_populates="issues")


class GtPoint(Base):
    __tablename__ = "gt_points"
    __table_args__ = (Index("idx_gt_points_geom", "geom", postgresql_using="gist"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    geom: Mapped[Any] = mapped_column(Geometry("POINT"), nullable=False)
    source: Mapped[GTPointSource] = mapped_column(
        SAEnum(GTPointSource, name="gt_point_source", create_type=True), nullable=False
    )
    accuracy_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    photo_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    project: Mapped[Project] = relationship(back_populates="gt_points")


class EditHistory(Base):
    """DB column 'user' mapped to Python attr 'user_name'."""

    __tablename__ = "edit_history"
    __table_args__ = (
        Index("idx_edit_history_old_geom", "old_geom", postgresql_using="gist"),
        Index("idx_edit_history_new_geom", "new_geom", postgresql_using="gist"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    feature_table: Mapped[str] = mapped_column(String(64), nullable=False)
    feature_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    action: Mapped[EditAction] = mapped_column(
        SAEnum(EditAction, name="edit_action", create_type=True), nullable=False
    )
    old_geom: Mapped[Any | None] = mapped_column(Geometry(), nullable=True)
    new_geom: Mapped[Any | None] = mapped_column(Geometry(), nullable=True)
    user_name: Mapped[str | None] = mapped_column("user", String(255), nullable=True)
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class GeeCache(Base):
    __tablename__ = "gee_cache"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    dataset: Mapped[str] = mapped_column(String(255), nullable=False)
    params_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    result: Mapped[Any | None] = mapped_column("result_path_or_json", JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    project: Mapped[Project] = relationship(back_populates="gee_caches")
