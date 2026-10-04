"""Unit and integration tests for hybrid parcel builder service (Phase 5)."""

from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import Polygon

from app.models.db_models import LanduseClass
from app.services.inference import ProbRasters
from app.services.parcels import (
    ParcelSet,
    _compute_building_containment_score,
    _compute_parcel_confidence,
    _create_barrier_raster,
    _create_watershed_markers,
    _enforce_no_building_bisection,
    _merge_sliver_fragments,
    _snap_parcel_neighbors,
    build_parcels,
)
from app.services.vectorize import (
    BuildingFeature,
    FeatureSet,
    LandUseFeature,
    RoadFeature,
)


@pytest.fixture
def synthetic_prob_rasters(tmp_path: Path) -> ProbRasters:
    """Create a set of synthetic probability COGs for parcel testing."""
    transform = from_origin(500000.0, 3000000.0, 0.5, 0.5)
    shape = (100, 100)

    # 1. Building raster: 2 square buildings
    bldg_arr = np.zeros(shape, dtype=np.float32)
    bldg_arr[20:40, 20:40] = 0.95
    bldg_arr[60:80, 60:80] = 0.90
    bldg_p = tmp_path / "prob_bldg.tif"
    with rasterio.open(
        bldg_p, "w", driver="GTiff", height=100, width=100, count=1, dtype="float32",
        crs="EPSG:32643", transform=transform
    ) as dst:
        dst.write(bldg_arr, 1)

    # 2. Road raster: vertical corridor
    road_arr = np.zeros(shape, dtype=np.float32)
    road_arr[:, 48:53] = 0.95
    road_p = tmp_path / "prob_road.tif"
    with rasterio.open(
        road_p, "w", driver="GTiff", height=100, width=100, count=1, dtype="float32",
        crs="EPSG:32643", transform=transform
    ) as dst:
        dst.write(road_arr, 1)

    # 3. Boundary raster: grid lines dividing parcels + roads
    boundary_arr = np.zeros(shape, dtype=np.float32)
    boundary_arr[0, :] = 0.9
    boundary_arr[-1, :] = 0.9
    boundary_arr[:, 0] = 0.9
    boundary_arr[:, -1] = 0.9
    boundary_arr[50, :] = 0.9  # Horizontal partition
    boundary_arr[:, 48:53] = 0.9  # Road edges
    bound_p = tmp_path / "prob_boundary.tif"
    with rasterio.open(
        bound_p, "w", driver="GTiff", height=100, width=100, count=1, dtype="float32",
        crs="EPSG:32643", transform=transform
    ) as dst:
        dst.write(boundary_arr, 1)

    # 4. Landuse raster: 6 bands
    lu_arr = np.zeros((6, 100, 100), dtype=np.float32)
    lu_arr[0, :, :] = 0.7  # built_up
    lu_p = tmp_path / "prob_landuse.tif"
    with rasterio.open(
        lu_p, "w", driver="GTiff", height=100, width=100, count=6, dtype="float32",
        crs="EPSG:32643", transform=transform
    ) as dst:
        dst.write(lu_arr)

    return ProbRasters(
        project_id=1,
        building_cog=str(bldg_p),
        road_cog=str(road_p),
        boundary_cog=str(bound_p),
        landuse_cog=str(lu_p),
    )


@pytest.fixture
def synthetic_features() -> FeatureSet:
    """Create sample vectorized features matching the synthetic grid."""
    # Building 1: (500010, 2999980) to (500020, 2999990)
    b1 = Polygon([(500010, 2999980), (500020, 2999980), (500020, 2999990), (500010, 2999990)])
    # Building 2: (500030, 2999960) to (500040, 2999960)
    b2 = Polygon([(500030, 2999960), (500040, 2999960), (500040, 2999970), (500030, 2999970)])

    # Road corridor: vertical line
    r1 = Polygon([(500024, 2999950), (500026.5, 2999950), (500026.5, 3000000), (500024, 3000000)])

    buildings = [
        BuildingFeature(geom=b1, confidence=0.92, area_m2=b1.area),
        BuildingFeature(geom=b2, confidence=0.88, area_m2=b2.area),
    ]
    roads = [
        RoadFeature(geom=r1, centerline=None, width_m=2.5, confidence=0.95),
    ]
    landuse = [
        LandUseFeature(geom=Polygon([(500000, 2999950), (500050, 2999950), (500050, 3000000), (500000, 3000000)]),
                       landuse_class=LanduseClass.built_up, confidence=0.85),
    ]

    return FeatureSet(project_id=1, buildings=buildings, roads=roads, landuse=landuse)


def test_create_barrier_raster():
    """Verify barrier raster blends boundary probabilities and road polygons."""
    transform = from_origin(500000.0, 3000000.0, 1.0, 1.0)
    boundary_prob = np.zeros((50, 50), dtype=np.float32)
    boundary_prob[25, :] = 0.8

    road = Polygon([(10, 0), (15, 0), (15, 50), (10, 50)])
    barrier, binary = _create_barrier_raster(boundary_prob, [road], transform, (50, 50), 0.35)

    assert barrier.shape == (50, 50)
    assert binary.shape == (50, 50)
    assert np.all(barrier[25, :] >= 0.8)


def test_watershed_markers_and_containment():
    """Verify marker creation for building centroids and building containment checks."""
    transform = from_origin(0.0, 100.0, 1.0, 1.0)
    bldg1 = Polygon([(10, 10), (20, 10), (20, 20), (10, 20)])
    bldg2 = Polygon([(60, 60), (70, 60), (70, 70), (60, 70)])
    barrier = np.zeros((100, 100), dtype=np.float32)

    markers, seeds = _create_watershed_markers([bldg1, bldg2], barrier, transform, (100, 100))
    assert len(seeds) >= 2
    assert np.max(markers) >= 2

    # Check containment score
    parcel = Polygon([(5, 5), (25, 5), (25, 25), (5, 25)])
    score, count = _compute_building_containment_score(parcel, [bldg1, bldg2])
    assert score == 1.0
    assert count == 1


def test_cadastral_rules_no_building_bisection():
    """Verify that candidate parcels bisecting a building are merged together."""
    bldg = Polygon([(15, 15), (25, 15), (25, 25), (15, 25)])

    # Two parcels splitting the building in half along x=20
    p1 = Polygon([(0, 0), (20, 0), (20, 30), (0, 30)])
    p2 = Polygon([(20, 0), (40, 0), (40, 30), (20, 30)])

    merged = _enforce_no_building_bisection([p1, p2], [bldg])
    assert len(merged) == 1
    assert merged[0].contains(bldg)


def test_merge_sliver_fragments():
    """Verify that slivers (< min_area) are merged into neighbors with longest shared edge."""
    # Main parcel: 100 m^2
    main_p = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
    # Sliver along right edge: 5 m^2 (width 0.5, height 10)
    sliver = Polygon([(10, 0), (10.5, 0), (10.5, 10), (10, 10)])

    merged = _merge_sliver_fragments([main_p, sliver], min_area_m2=20.0)
    assert len(merged) == 1
    assert merged[0].area == pytest.approx(105.0)


def test_snap_parcel_neighbors():
    """Verify topological snapping aligns neighboring vertices."""
    # Two touching parcels with a slight vertex offset (< tolerance)
    p1 = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
    p2 = Polygon([(10.05, 0), (20, 0), (20, 10), (10.05, 10)])

    snapped = _snap_parcel_neighbors([p1, p2], tolerance=0.1)
    assert len(snapped) == 2


def test_parcel_confidence_scoring():
    """Verify multi-factor confidence computation."""
    transform = from_origin(0.0, 100.0, 1.0, 1.0)
    boundary_prob = np.full((100, 100), 0.85, dtype=np.float32)

    bldg = Polygon([(10, 10), (20, 10), (20, 20), (10, 20)])
    parcel = Polygon([(5, 5), (25, 5), (25, 25), (5, 25)])

    # 1. Without reference layer
    conf1, bldg_count1 = _compute_parcel_confidence(parcel, boundary_prob, transform, [bldg], None)
    assert 0.05 <= conf1 <= 0.99
    assert bldg_count1 == 1

    # 2. With reference layer
    ref_parcel = Polygon([(4, 4), (26, 4), (26, 26), (4, 26)])
    conf2, _ = _compute_parcel_confidence(parcel, boundary_prob, transform, [bldg], [ref_parcel])
    assert 0.05 <= conf2 <= 0.99


def test_build_parcels_end_to_end(synthetic_prob_rasters: ProbRasters, synthetic_features: FeatureSet):
    """Verify full build_parcels pipeline execution, GeoJSON export, and LADM attributes."""
    parcel_set = build_parcels(
        project_id=1,
        probs=synthetic_prob_rasters,
        features_set=synthetic_features,
        min_parcel_area=15.0,
        boundary_threshold=0.35,
    )

    assert isinstance(parcel_set, ParcelSet)
    assert parcel_set.count > 0
    assert parcel_set.total_area_m2 > 0
    assert 0.0 < parcel_set.mean_confidence <= 1.0

    geojson = parcel_set.to_geojson()
    assert geojson["type"] == "FeatureCollection"
    assert len(geojson["features"]) == parcel_set.count

    first_feat = geojson["features"][0]
    props = first_feat["properties"]
    assert "confidence" in props
    assert "area_m2" in props
    assert "ladm_attrs" in props
    assert props["status"] == "draft"
    assert props["source"] == "ai"

    assert "seeds" in parcel_set.debug_layers
    assert "final_parcels_count" in parcel_set.debug_layers
