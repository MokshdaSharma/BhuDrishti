"""Initial schema — all 10 ParcelAI tables with enums and GIST indexes.

Revision ID: 0001
Create Date: 2026-09-29
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from geoalchemy2 import Geometry
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── Enum types ────────────────────────────────────────────────────────────
    project_status = sa.Enum("pending", "processing", "done", "error", name="project_status")
    raster_kind = sa.Enum(
        "ori",
        "dsm",
        "dtm",
        "ndsm",
        "prob_building",
        "prob_road",
        "prob_boundary",
        "prob_landuse",
        name="raster_kind",
    )
    parcel_source = sa.Enum("ai", "edited", "field", "existing", name="parcel_source")
    parcel_status = sa.Enum("draft", "reviewed", "verified", name="parcel_status")
    landuse_class_enum = sa.Enum(
        "built_up",
        "road",
        "vegetation",
        "water",
        "open_land",
        "other",
        name="landuse_class_enum",
    )
    issue_type_enum = sa.Enum(
        "invalid_geometry",
        "overlap",
        "gap",
        "sliver",
        "spike",
        "building_crosses_parcel",
        "building_on_road",
        "landlocked_parcel",
        "new_parcel",
        "missing_parcel",
        "changed_parcel",
        "landuse_prior_mismatch",
        "low_confidence",
        name="issue_type_enum",
    )
    issue_severity = sa.Enum("info", "warning", "error", name="issue_severity")
    gt_point_source = sa.Enum("gnss", "cors", "field", name="gt_point_source")
    edit_action = sa.Enum("insert", "update", "delete", name="edit_action")

    for t in [
        project_status,
        raster_kind,
        parcel_source,
        parcel_status,
        landuse_class_enum,
        issue_type_enum,
        issue_severity,
        gt_point_source,
        edit_action,
    ]:
        t.create(op.get_bind(), checkfirst=True)

    # ── projects ──────────────────────────────────────────────────────────────
    op.create_table(
        "projects",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("crs", sa.String(64), nullable=False, server_default="EPSG:32643"),
        sa.Column("extent", Geometry("POLYGON", srid=4326, spatial_index=False), nullable=True),
        sa.Column("status", project_status, nullable=False, server_default="pending"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("idx_projects_extent", "projects", ["extent"], postgresql_using="gist")

    # ── rasters ───────────────────────────────────────────────────────────────
    op.create_table(
        "rasters",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "project_id",
            sa.Integer,
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", raster_kind, nullable=False),
        sa.Column("path", sa.Text, nullable=False),
        sa.Column("resolution", sa.Float, nullable=True),
        sa.Column("crs", sa.String(64), nullable=True),
    )
    op.create_index("idx_rasters_project_id", "rasters", ["project_id"])

    # ── parcels ───────────────────────────────────────────────────────────────
    op.create_table(
        "parcels",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "project_id",
            sa.Integer,
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("geom", Geometry("POLYGON", spatial_index=False), nullable=False),
        sa.Column("confidence", sa.Float, nullable=True),
        sa.Column("source", parcel_source, nullable=False, server_default="ai"),
        sa.Column("status", parcel_status, nullable=False, server_default="draft"),
        sa.Column("area_m2", sa.Float, nullable=True),
        sa.Column("ladm_attrs", JSONB, nullable=True),
        sa.Column("created_by", sa.String(255), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_parcels_project_id", "parcels", ["project_id"])
    op.create_index("idx_parcels_geom", "parcels", ["geom"], postgresql_using="gist")

    # ── buildings ─────────────────────────────────────────────────────────────
    op.create_table(
        "buildings",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "project_id",
            sa.Integer,
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("geom", Geometry("POLYGON", spatial_index=False), nullable=False),
        sa.Column("confidence", sa.Float, nullable=True),
        sa.Column(
            "parcel_id", sa.Integer, sa.ForeignKey("parcels.id", ondelete="SET NULL"), nullable=True
        ),
    )
    op.create_index("idx_buildings_project_id", "buildings", ["project_id"])
    op.create_index("idx_buildings_geom", "buildings", ["geom"], postgresql_using="gist")

    # ── roads ─────────────────────────────────────────────────────────────────
    op.create_table(
        "roads",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "project_id",
            sa.Integer,
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("geom", Geometry("POLYGON", spatial_index=False), nullable=False),
        sa.Column("centerline", Geometry("LINESTRING", spatial_index=False), nullable=True),
        sa.Column("width_m", sa.Float, nullable=True),
    )
    op.create_index("idx_roads_project_id", "roads", ["project_id"])
    op.create_index("idx_roads_geom", "roads", ["geom"], postgresql_using="gist")
    op.create_index("idx_roads_centerline", "roads", ["centerline"], postgresql_using="gist")

    # ── landuse ───────────────────────────────────────────────────────────────
    op.create_table(
        "landuse",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "project_id",
            sa.Integer,
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("geom", Geometry("POLYGON", spatial_index=False), nullable=False),
        sa.Column("class", landuse_class_enum, nullable=False, server_default="other"),
        sa.Column("confidence", sa.Float, nullable=True),
    )
    op.create_index("idx_landuse_project_id", "landuse", ["project_id"])
    op.create_index("idx_landuse_geom", "landuse", ["geom"], postgresql_using="gist")

    # ── issues ────────────────────────────────────────────────────────────────
    op.create_table(
        "issues",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "project_id",
            sa.Integer,
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("type", issue_type_enum, nullable=False),
        sa.Column("severity", issue_severity, nullable=False, server_default="warning"),
        sa.Column("geom", Geometry(spatial_index=False), nullable=True),
        sa.Column("suggested_fix", sa.Text, nullable=True),
        sa.Column("resolved", sa.Boolean, nullable=False, server_default="false"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("idx_issues_project_id", "issues", ["project_id"])
    op.create_index("idx_issues_geom", "issues", ["geom"], postgresql_using="gist")

    # ── gt_points ─────────────────────────────────────────────────────────────
    op.create_table(
        "gt_points",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "project_id",
            sa.Integer,
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("geom", Geometry("POINT", spatial_index=False), nullable=False),
        sa.Column("source", gt_point_source, nullable=False),
        sa.Column("accuracy_m", sa.Float, nullable=True),
        sa.Column("photo_url", sa.Text, nullable=True),
        sa.Column("note", sa.Text, nullable=True),
    )
    op.create_index("idx_gt_points_project_id", "gt_points", ["project_id"])
    op.create_index("idx_gt_points_geom", "gt_points", ["geom"], postgresql_using="gist")

    # ── edit_history ──────────────────────────────────────────────────────────
    op.create_table(
        "edit_history",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("feature_table", sa.String(64), nullable=False),
        sa.Column("feature_id", sa.Integer, nullable=False),
        sa.Column("action", edit_action, nullable=False),
        sa.Column("old_geom", Geometry(spatial_index=False), nullable=True),
        sa.Column("new_geom", Geometry(spatial_index=False), nullable=True),
        sa.Column("user", sa.String(255), nullable=True),
        sa.Column(
            "ts",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("idx_edit_history_feature_id", "edit_history", ["feature_id"])
    op.create_index(
        "idx_edit_history_old_geom", "edit_history", ["old_geom"], postgresql_using="gist"
    )
    op.create_index(
        "idx_edit_history_new_geom", "edit_history", ["new_geom"], postgresql_using="gist"
    )

    # ── gee_cache ─────────────────────────────────────────────────────────────
    op.create_table(
        "gee_cache",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "project_id",
            sa.Integer,
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("dataset", sa.String(255), nullable=False),
        sa.Column("params_hash", sa.String(64), nullable=False),
        sa.Column("result_path_or_json", JSONB, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_gee_cache_project_id", "gee_cache", ["project_id"])
    op.create_index("idx_gee_cache_params_hash", "gee_cache", ["params_hash"])


def downgrade() -> None:
    # Drop in reverse dependency order
    op.drop_table("gee_cache")
    op.drop_table("edit_history")
    op.drop_table("gt_points")
    op.drop_table("issues")
    op.drop_table("landuse")
    op.drop_table("roads")
    op.drop_table("buildings")
    op.drop_table("parcels")
    op.drop_table("rasters")
    op.drop_table("projects")

    # Drop enum types
    for name in [
        "edit_action",
        "gt_point_source",
        "issue_severity",
        "issue_type_enum",
        "landuse_class_enum",
        "parcel_status",
        "parcel_source",
        "raster_kind",
        "project_status",
    ]:
        sa.Enum(name=name).drop(op.get_bind(), checkfirst=True)
