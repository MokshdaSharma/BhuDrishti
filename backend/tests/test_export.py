"""Unit and integration tests for multi-format GIS export service (Phase 7)."""

import json
import zipfile
from pathlib import Path

import geopandas as gpd
import pytest
from shapely.geometry import Point, Polygon

from app.services.export import export_dataset


@pytest.fixture
def sample_feature_layers() -> dict[str, list[dict]]:
    """Create sample spatial features across layers for export tests."""
    p1 = Polygon([(500000, 3000000), (500020, 3000000), (500020, 3000020), (500000, 3000020)])
    b1 = Polygon([(500004, 3000004), (500012, 3000004), (500012, 3000012), (500004, 3000012)])
    r1 = Polygon([(499990, 3000000), (499995, 3000000), (499995, 3000050), (499990, 3000050)])
    iss1 = Point(500010, 3000010)

    return {
        "parcels": [{"id": 1, "geom": p1, "confidence": 0.92, "area_m2": 400.0, "source": "ai", "status": "draft"}],
        "buildings": [{"id": 1, "geom": b1, "confidence": 0.95, "parcel_id": 1}],
        "roads": [{"id": 1, "geom": r1, "width_m": 5.0}],
        "landuse": [{"id": 1, "geom": p1, "landuse_class": "built_up", "confidence": 0.88}],
        "issues": [{"id": 1, "geom": iss1, "issue_type": "sliver", "severity": "warning", "suggested_fix": "Merge"}],
    }


def test_export_geojson(sample_feature_layers: dict[str, list[dict]], tmp_path: Path):
    """Verify GeoJSON export structure and feature counts."""
    out_file = export_dataset(
        project_id=1,
        fmt="geojson",
        crs="EPSG:4326",
        output_dir=tmp_path,
        parcels=sample_feature_layers["parcels"],
        buildings=sample_feature_layers["buildings"],
        roads=sample_feature_layers["roads"],
        landuse=sample_feature_layers["landuse"],
        issues=sample_feature_layers["issues"],
    )

    assert out_file.exists()
    assert out_file.suffix == ".geojson"

    with open(out_file, encoding="utf-8") as f:
        data = json.load(f)

    assert data["type"] == "FeatureCollection"
    assert len(data["features"]) == 5
    layers = {feat["properties"]["layer"] for feat in data["features"]}
    assert "parcels" in layers
    assert "buildings" in layers


def test_export_gpkg(sample_feature_layers: dict[str, list[dict]], tmp_path: Path):
    """Verify GeoPackage (.gpkg) export with multi-layer tables."""
    out_file = export_dataset(
        project_id=1,
        fmt="gpkg",
        crs="EPSG:4326",
        output_dir=tmp_path,
        parcels=sample_feature_layers["parcels"],
        buildings=sample_feature_layers["buildings"],
        roads=sample_feature_layers["roads"],
        landuse=sample_feature_layers["landuse"],
        issues=sample_feature_layers["issues"],
    )

    assert out_file.exists()
    assert out_file.suffix == ".gpkg"

    # Read back layer using geopandas
    gdf_parcels = gpd.read_file(out_file, layer="parcels")
    assert len(gdf_parcels) == 1
    assert "confidence" in gdf_parcels.columns


def test_export_shapefile_zip(sample_feature_layers: dict[str, list[dict]], tmp_path: Path):
    """Verify Shapefile zipped archive export containing .shp, .shx, .dbf, .prj files."""
    out_file = export_dataset(
        project_id=1,
        fmt="shp",
        crs="EPSG:4326",
        output_dir=tmp_path,
        parcels=sample_feature_layers["parcels"],
        buildings=sample_feature_layers["buildings"],
        roads=sample_feature_layers["roads"],
    )

    assert out_file.exists()
    assert out_file.suffix == ".zip"

    with zipfile.ZipFile(out_file) as zf:
        names = zf.namelist()
        assert any("parcels/parcels.shp" in n or "parcels.shp" in n for n in names)
        assert any("buildings/buildings.shp" in n or "buildings.shp" in n for n in names)


def test_export_kml(sample_feature_layers: dict[str, list[dict]], tmp_path: Path):
    """Verify Google Earth KML XML export format."""
    out_file = export_dataset(
        project_id=1,
        fmt="kml",
        crs="EPSG:4326",
        output_dir=tmp_path,
        parcels=sample_feature_layers["parcels"],
        buildings=sample_feature_layers["buildings"],
    )

    assert out_file.exists()
    assert out_file.suffix == ".kml"

    with open(out_file, encoding="utf-8") as f:
        content = f.read()

    assert "<kml" in content
    assert "<Folder><name>Parcels</name>" in content
    assert "<Polygon>" in content
