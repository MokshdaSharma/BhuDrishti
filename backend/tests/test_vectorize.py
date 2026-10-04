"""Unit and integration tests for Vectorization pipeline (Phase 4).

Verifies:
- Building polygon extraction and geometric regularization
- Road network corridor extraction, skeletonization, spur pruning, centerline extraction, and width estimation
- Multi-class land-use polygon extraction and classification
- Full extract_features pipeline execution and FeatureSet output
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import LineString, MultiLineString, Polygon

from app.models.db_models import LanduseClass
from app.services.inference import ProbRasters
from app.services.vectorize import (
    BuildingFeature,
    FeatureSet,
    RoadFeature,
    extract_buildings,
    extract_features,
    extract_landuse,
    extract_roads,
)


@pytest.fixture
def synthetic_prob_rasters(tmp_path: Path) -> ProbRasters:
    """Create synthetic probability COGs for building, road, boundary, and landuse."""
    width, height = 300, 300
    transform = from_origin(500000.0, 3000000.0, 0.5, 0.5)
    crs = "EPSG:32643"

    # 1. Building probability: 2 rectangular buildings
    bldg_prob = np.zeros((height, width), dtype=np.float32)
    bldg_prob[50:120, 50:120] = 0.95  # 70x70 px = 35x35 m = 1225 m2
    bldg_prob[180:240, 180:250] = 0.90  # 60x70 px = 30x35 m = 1050 m2

    bldg_path = tmp_path / "prob_building.tif"
    with rasterio.open(
        bldg_path,
        "w",
        driver="GTiff",
        height=height,
        width=width,
        count=1,
        dtype="float32",
        crs=crs,
        transform=transform,
        tiled=True,
        blockxsize=256,
        blockysize=256,
    ) as dst:
        dst.write(bldg_prob, 1)

    # 2. Road probability: Horizontal road corridor of width 16px (8m)
    road_prob = np.zeros((height, width), dtype=np.float32)
    road_prob[140:156, :] = 0.85
    # Small spur to test pruning
    road_prob[156:162, 100:104] = 0.80

    road_path = tmp_path / "prob_road.tif"
    with rasterio.open(
        road_path,
        "w",
        driver="GTiff",
        height=height,
        width=width,
        count=1,
        dtype="float32",
        crs=crs,
        transform=transform,
        tiled=True,
        blockxsize=256,
        blockysize=256,
    ) as dst:
        dst.write(road_prob, 1)

    # 3. Boundary probability
    bound_prob = np.zeros((height, width), dtype=np.float32)
    bound_path = tmp_path / "prob_boundary.tif"
    with rasterio.open(
        bound_path,
        "w",
        driver="GTiff",
        height=height,
        width=width,
        count=1,
        dtype="float32",
        crs=crs,
        transform=transform,
        tiled=True,
        blockxsize=256,
        blockysize=256,
    ) as dst:
        dst.write(bound_prob, 1)

    # 4. Landuse probability (6 bands)
    lu_prob = np.full((6, height, width), 0.05, dtype=np.float32)
    # Band 0: built_up
    lu_prob[0, 50:120, 50:120] = 0.95
    # Band 1: road
    lu_prob[1, 140:156, :] = 0.90
    # Band 2: vegetation
    lu_prob[2, 0:50, :] = 0.85
    # Band 4: open_land everywhere else
    lu_prob[4, 200:300, 0:100] = 0.80

    lu_path = tmp_path / "prob_landuse.tif"
    with rasterio.open(
        lu_path,
        "w",
        driver="GTiff",
        height=height,
        width=width,
        count=6,
        dtype="float32",
        crs=crs,
        transform=transform,
        tiled=True,
        blockxsize=256,
        blockysize=256,
    ) as dst:
        for i in range(6):
            dst.write(lu_prob[i], i + 1)

    return ProbRasters(
        project_id=201,
        building_cog=str(bldg_path.resolve()),
        road_cog=str(road_path.resolve()),
        boundary_cog=str(bound_path.resolve()),
        landuse_cog=str(lu_path.resolve()),
    )


def test_extract_buildings(synthetic_prob_rasters: ProbRasters):
    buildings = extract_buildings(
        synthetic_prob_rasters.building_cog,
        threshold=0.5,
        min_area_m2=50.0,
        regularize=True,
    )

    assert len(buildings) == 2
    for b in buildings:
        assert isinstance(b, BuildingFeature)
        assert isinstance(b.geom, Polygon)
        assert b.confidence >= 0.8
        assert b.area_m2 > 500.0  # Synthetic buildings are > 1000 m2


def test_extract_roads(synthetic_prob_rasters: ProbRasters):
    roads = extract_roads(
        synthetic_prob_rasters.road_cog,
        threshold=0.4,
        min_area_m2=100.0,
        min_spur_length_px=4,
    )

    assert len(roads) >= 1
    main_road = roads[0]
    assert isinstance(main_road, RoadFeature)
    assert main_road.confidence >= 0.7
    assert main_road.centerline is not None
    assert isinstance(main_road.centerline, (LineString, MultiLineString))
    assert main_road.width_m > 4.0  # Approx ~8m road width


def test_extract_landuse(synthetic_prob_rasters: ProbRasters):
    landuse_features = extract_landuse(
        synthetic_prob_rasters.landuse_cog,
        min_area_m2=50.0,
    )

    assert len(landuse_features) >= 3
    classes_found = {lu.landuse_class for lu in landuse_features}
    assert LanduseClass.built_up in classes_found
    assert LanduseClass.road in classes_found
    assert LanduseClass.vegetation in classes_found


def test_extract_features_end_to_end(synthetic_prob_rasters: ProbRasters):
    feature_set = extract_features(
        project_id=201,
        probs=synthetic_prob_rasters,
        min_building_area=50.0,
        min_road_area=100.0,
        min_landuse_area=50.0,
    )

    assert isinstance(feature_set, FeatureSet)
    assert feature_set.project_id == 201
    assert len(feature_set.buildings) == 2
    assert len(feature_set.roads) >= 1
    assert len(feature_set.landuse) >= 3

    # Check JSON export capability
    f_dict = feature_set.to_dict()
    assert "buildings" in f_dict
    assert "roads" in f_dict
    assert "landuse" in f_dict
    assert "summary" in f_dict
    assert f_dict["summary"]["building_count"] == 2
