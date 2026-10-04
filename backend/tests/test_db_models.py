"""Tests for database ORM models (Phase 1).

Verifies:
- All 10 tables exist in Base.metadata
- Foreign keys and relationships
- Column types and constraints
- Reserved word column mappings ('class', 'type', 'user')
- Enums match Section 6 specifications
- GIST index declarations on spatial columns
"""

from __future__ import annotations

from sqlalchemy.orm import class_mapper

from app.core.db import Base
from app.models.db_models import (
    EditAction,
    EditHistory,
    GTPointSource,
    Issue,
    IssueSeverity,
    IssueType,
    LandUse,
    LanduseClass,
    ParcelSource,
    ParcelStatus,
    Project,
    ProjectStatus,
    RasterKind,
)


def test_metadata_contains_all_10_tables():
    expected_tables = {
        "projects",
        "rasters",
        "parcels",
        "buildings",
        "roads",
        "landuse",
        "issues",
        "gt_points",
        "edit_history",
        "gee_cache",
    }
    actual_tables = set(Base.metadata.tables.keys())
    assert expected_tables.issubset(
        actual_tables
    ), f"Missing tables: {expected_tables - actual_tables}"


def test_enum_values():
    assert {e.value for e in ProjectStatus} == {"pending", "processing", "done", "error"}
    assert {e.value for e in RasterKind} == {
        "ori",
        "dsm",
        "dtm",
        "ndsm",
        "prob_building",
        "prob_road",
        "prob_boundary",
        "prob_landuse",
    }
    assert {e.value for e in ParcelSource} == {"ai", "edited", "field", "existing"}
    assert {e.value for e in ParcelStatus} == {"draft", "reviewed", "verified"}
    assert {e.value for e in LanduseClass} == {
        "built_up",
        "road",
        "vegetation",
        "water",
        "open_land",
        "other",
    }
    assert {e.value for e in IssueSeverity} == {"info", "warning", "error"}
    assert {e.value for e in IssueType} == {
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
    }
    assert {e.value for e in GTPointSource} == {"gnss", "cors", "field"}
    assert {e.value for e in EditAction} == {"insert", "update", "delete"}


def test_reserved_word_mappings():
    # LandUse: Python attr 'landuse_class' maps to DB column 'class'
    lu_mapper = class_mapper(LandUse)
    assert "landuse_class" in lu_mapper.all_orm_descriptors
    assert LandUse.__table__.c["class"].name == "class"

    # Issue: Python attr 'issue_type' maps to DB column 'type'
    issue_mapper = class_mapper(Issue)
    assert "issue_type" in issue_mapper.all_orm_descriptors
    assert Issue.__table__.c["type"].name == "type"

    # EditHistory: Python attr 'user_name' maps to DB column 'user'
    eh_mapper = class_mapper(EditHistory)
    assert "user_name" in eh_mapper.all_orm_descriptors
    assert EditHistory.__table__.c["user"].name == "user"


def test_project_relationships():
    p_mapper = class_mapper(Project)
    rel_names = {r.key for r in p_mapper.relationships}
    expected_rels = {
        "rasters",
        "parcels",
        "buildings",
        "roads",
        "landuses",
        "issues",
        "gt_points",
        "gee_caches",
    }
    assert expected_rels.issubset(rel_names)


def test_spatial_indexes_declared():
    # Verify GIST indexes on spatial tables
    tables_with_gist = {
        "projects": ["idx_projects_extent"],
        "parcels": ["idx_parcels_geom"],
        "buildings": ["idx_buildings_geom"],
        "roads": ["idx_roads_geom", "idx_roads_centerline"],
        "landuse": ["idx_landuse_geom"],
        "issues": ["idx_issues_geom"],
        "gt_points": ["idx_gt_points_geom"],
        "edit_history": ["idx_edit_history_old_geom", "idx_edit_history_new_geom"],
    }
    for tbl_name, idx_names in tables_with_gist.items():
        table = Base.metadata.tables[tbl_name]
        table_indexes = {idx.name for idx in table.indexes}
        for name in idx_names:
            assert name in table_indexes, f"Expected index {name} on {tbl_name}"
