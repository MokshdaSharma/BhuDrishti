"""Tests to verify SQL script contents and topology rules (Phase 1).

Verifies:
- db/init.sql creates PostGIS extensions
- backend/alembic/versions/0001_initial_schema.py creates all 10 tables, enums, and GIST indexes
- db/topology_rules.sql creates validation functions, triggers, and auto-fix procedures
"""

from __future__ import annotations

from pathlib import Path


def test_init_sql_completeness():
    init_sql_path = Path(__file__).resolve().parents[2] / "db" / "init.sql"
    assert init_sql_path.exists(), f"db/init.sql not found at {init_sql_path}"

    content = init_sql_path.read_text(encoding="utf-8").lower()

    # Extensions required for PostGIS & spatial processing
    assert "postgis" in content
    assert "postgis_raster" in content
    assert "postgis_topology" in content


def test_migration_schema_completeness():
    migration_path = (
        Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0001_initial_schema.py"
    )
    assert migration_path.exists(), f"0001_initial_schema.py not found at {migration_path}"

    content = migration_path.read_text(encoding="utf-8")

    # All 10 tables declared in Section 6
    expected_tables = [
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
    ]
    for tbl in expected_tables:
        assert f'op.create_table(\n        "{tbl}"' in content or f'"{tbl}"' in content

    # Spatial GIST Indexes
    expected_indexes = [
        "idx_projects_extent",
        "idx_parcels_geom",
        "idx_buildings_geom",
        "idx_roads_geom",
        "idx_roads_centerline",
        "idx_landuse_geom",
        "idx_issues_geom",
        "idx_gt_points_geom",
        "idx_edit_history_old_geom",
        "idx_edit_history_new_geom",
    ]
    for idx in expected_indexes:
        assert idx in content, f"Expected index {idx} in migration 0001"


def test_topology_rules_sql_completeness():
    topo_sql_path = Path(__file__).resolve().parents[2] / "db" / "topology_rules.sql"
    assert topo_sql_path.exists(), f"db/topology_rules.sql not found at {topo_sql_path}"

    content = topo_sql_path.read_text(encoding="utf-8").lower()

    # Functions & Rules defined in Section 6 & 7.6
    expected_elements = [
        "validate_project_topology",
        "invalid_geometry",
        "overlap",
        "gap",
        "sliver",
        "building_crosses_parcel",
        "building_on_road",
        "landlocked_parcel",
        "autofix_project_topology",
        "log_parcel_edit_history",
        "trg_parcels_edit_history",
    ]
    for el in expected_elements:
        assert el in content, f"Expected topology element '{el}' in db/topology_rules.sql"
