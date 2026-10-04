"""Unit and integration tests for existing parcel layer comparison service (Phase 6)."""

from pathlib import Path

import geopandas as gpd
from shapely.geometry import Polygon

from app.models.schemas import CompareSummary
from app.services.compare import (
    compare_parcel_lists,
    compare_with_existing,
    load_vector_parcels,
)


def test_compare_parcel_lists_matched():
    """Verify matched/unchanged parcel detection (high IoU >= 0.70)."""
    p_ai = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
    p_ext = Polygon([(0.2, 0.2), (10.1, 0.2), (10.1, 10.1), (0.2, 10.1)])  # >90% IoU

    summary, items = compare_parcel_lists(
        project_id=1,
        ai_parcels=[p_ai],
        existing_parcels=[p_ext],
    )

    assert isinstance(summary, CompareSummary)
    assert summary.matched_count == 1
    assert summary.changed_count == 0
    assert summary.new_count == 0
    assert summary.missing_count == 0
    assert items[0].status == "matched"
    assert items[0].iou > 0.85


def test_compare_parcel_lists_changed():
    """Verify changed parcel detection (partial IoU or significant area diff)."""
    p_ai = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])  # 100 m^2
    # Existing parcel is twice as wide: (0, 0) to (20, 10) (200 m^2) -> 50% IoU
    p_ext = Polygon([(0, 0), (20, 0), (20, 10), (0, 10)])

    summary, items = compare_parcel_lists(
        project_id=1,
        ai_parcels=[p_ai],
        existing_parcels=[p_ext],
    )

    assert summary.changed_count == 1
    assert summary.matched_count == 0
    assert items[0].status == "changed"
    assert items[0].area_diff_pct > 40.0


def test_compare_parcel_lists_new_and_missing():
    """Verify detection of new AI parcels and missing existing parcels."""
    # AI has parcel at (0, 0)
    p_ai = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
    # Existing has parcel at (100, 100)
    p_ext = Polygon([(100, 100), (110, 100), (110, 110), (100, 110)])

    summary, items = compare_parcel_lists(
        project_id=1,
        ai_parcels=[p_ai],
        existing_parcels=[p_ext],
    )

    assert summary.new_count == 1
    assert summary.missing_count == 1
    assert summary.matched_count == 0
    statuses = [item.status for item in items]
    assert "new" in statuses
    assert "missing" in statuses


def test_compare_with_existing_file(tmp_path: Path):
    """Verify loading from GeoJSON file and running compare_with_existing."""
    ext_poly = Polygon([(0, 0), (15, 0), (15, 15), (0, 15)])
    gdf = gpd.GeoDataFrame([{"id": 1, "geometry": ext_poly}], crs="EPSG:32643")
    geojson_path = tmp_path / "existing_parcels.geojson"
    gdf.to_file(geojson_path, driver="GeoJSON")

    loaded = load_vector_parcels(geojson_path)
    assert len(loaded) == 1
    assert loaded[0].equals(ext_poly)

    # Compare with AI parcel
    ai_poly = Polygon([(0, 0), (15, 0), (15, 15), (0, 15)])
    summary = compare_with_existing(
        project_id=1,
        existing_parcels_path=geojson_path,
        ai_parcels=[ai_poly],
    )

    assert summary.matched_count == 1
    assert summary.project_id == 1
    assert len(summary.details) == 1
