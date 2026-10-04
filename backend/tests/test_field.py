"""Unit and integration tests for field verification, QField sync, and active learning (Phase 11)."""

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import geopandas as gpd
import pytest
from fastapi.testclient import TestClient
from geoalchemy2.shape import from_shape
from shapely.geometry import Point, Polygon

from app.core.db import get_db
from app.main import app

from app.models.db_models import (
    Building,
    EditHistory,
    GtPoint,
    GTPointSource,
    Issue,
    IssueSeverity,
    IssueType,
    Parcel,
    ParcelSource,
    ParcelStatus,
    Project,
    ProjectStatus,
    Road,
)
from app.services.field_sync import _list_gpkg_layers, generate_field_package, sync_field_package
from ml.datasets.dataset import LocalGeoDataset
from scripts.build_finetune_set import create_synthetic_finetune_set



class MockFieldDbSession:
    """In-memory mock database session for field package generation and sync tests."""

    def __init__(self):
        self.projects: dict[int, Project] = {}
        self.parcels: dict[int, Parcel] = {}
        self.buildings: dict[int, Building] = {}
        self.roads: dict[int, Road] = {}
        self.issues: dict[int, Issue] = {}
        self.gt_points: dict[int, GtPoint] = {}
        self.edit_history: list[EditHistory] = []
        self._next_id = 1

    def add(self, obj):
        if not hasattr(obj, "id") or obj.id is None:
            obj.id = self._next_id
            self._next_id += 1
        if isinstance(obj, Project):
            self.projects[obj.id] = obj
        elif isinstance(obj, Parcel):
            self.parcels[obj.id] = obj
        elif isinstance(obj, Building):
            self.buildings[obj.id] = obj
        elif isinstance(obj, Road):
            self.roads[obj.id] = obj
        elif isinstance(obj, Issue):
            self.issues[obj.id] = obj
        elif isinstance(obj, GtPoint):
            self.gt_points[obj.id] = obj
        elif isinstance(obj, EditHistory):
            self.edit_history.append(obj)

    def scalar(self, statement):
        sql = str(statement).lower()
        if "from projects" in sql:
            for p in self.projects.values():
                return p
        elif "from parcels" in sql:
            for p in self.parcels.values():
                return p
        return None

    def scalars(self, statement):
        mock_result = MagicMock()
        sql = str(statement).lower()
        if "from parcels" in sql:
            mock_result.all.return_value = list(self.parcels.values())
        elif "from buildings" in sql:
            mock_result.all.return_value = list(self.buildings.values())
        elif "from roads" in sql:
            mock_result.all.return_value = list(self.roads.values())
        elif "from gt_points" in sql or "gt_point" in sql:
            if "gt_points.id" in sql or "gtpoint.id" in sql:
                mock_result.all.return_value = list(self.gt_points.keys())
            else:
                mock_result.all.return_value = list(self.gt_points.values())
        elif "from issues" in sql:
            mock_result.all.return_value = list(self.issues.values())
        else:
            mock_result.all.return_value = []
        return mock_result

    def commit(self):
        pass

    def flush(self):
        pass


@pytest.fixture
def populated_db():
    """Populate mock database with project and feature records."""
    db = MockFieldDbSession()

    proj = Project(
        id=1,
        name="Field Survey Demo Area",
        crs="EPSG:32643",
        status=ProjectStatus.done,
        created_at=datetime.now(timezone.utc),
    )
    db.add(proj)

    p1_geom = Polygon([(500000, 3000000), (500050, 3000000), (500050, 3000050), (500000, 3000050)])
    parcel1 = Parcel(
        id=101,
        project_id=1,
        geom=from_shape(p1_geom, srid=32643),
        confidence=0.82,
        source=ParcelSource.ai,
        status=ParcelStatus.draft,
        area_m2=2500.0,
        ladm_attrs={"surveyor": "", "notes": ""},
        updated_at=datetime.now(timezone.utc),
    )
    db.add(parcel1)

    b1_geom = Polygon([(500010, 3000010), (500030, 3000010), (500030, 3000030), (500010, 3000030)])
    bldg1 = Building(
        id=201,
        project_id=1,
        geom=from_shape(b1_geom, srid=32643),
        confidence=0.95,
        parcel_id=101,
    )
    db.add(bldg1)

    r1_geom = Polygon([(499980, 3000000), (499990, 3000000), (499990, 3000100), (499980, 3000100)])
    road1 = Road(
        id=301,
        project_id=1,
        geom=from_shape(r1_geom, srid=32643),
        width_m=6.0,
    )
    db.add(road1)

    pt1_geom = Point(500000, 3000000)
    pt1 = GtPoint(
        id=401,
        project_id=1,
        geom=from_shape(pt1_geom, srid=32643),
        source=GTPointSource.gnss,
        accuracy_m=0.02,
        note="Base station benchmark",
    )
    db.add(pt1)

    iss1 = Issue(
        id=501,
        project_id=1,
        issue_type=IssueType.sliver,
        severity=IssueSeverity.warning,
        geom=from_shape(Point(500050, 3000050), srid=32643),
        suggested_fix="Verify on ground",
        resolved=False,
    )
    db.add(iss1)

    return db


def test_generate_field_package(populated_db, tmp_path: Path):
    """Verify QField multi-layer GeoPackage creation with all required layers and schema."""
    pkg_file = tmp_path / "survey_package.gpkg"
    out_path = generate_field_package(project_id=1, output_path=pkg_file, db=populated_db)

    assert out_path.exists()
    assert out_path.name == "survey_package.gpkg"

    layers = _list_gpkg_layers(str(out_path))
    assert "parcels" in layers
    assert "gt_points" in layers

    assert "buildings" in layers
    assert "roads" in layers
    assert "issues" in layers

    gdf_p = gpd.read_file(str(out_path), layer="parcels")
    assert len(gdf_p) == 1
    assert "verified" in gdf_p.columns
    assert "surveyor" in gdf_p.columns
    assert "survey_note" in gdf_p.columns
    assert "photo_url" in gdf_p.columns
    assert gdf_p.iloc[0]["id"] == 101


def test_sync_field_package(populated_db, tmp_path: Path):
    """Test round-trip sync: modify QField attributes, edit geometry, add GNSS point, and verify DB updates."""
    # 1. Generate package
    pkg_file = tmp_path / "sync_test.gpkg"
    generate_field_package(project_id=1, output_path=pkg_file, db=populated_db)

    # 2. Simulate QField surveyor edits
    gdf_parcels = gpd.read_file(str(pkg_file), layer="parcels")
    # Mark verified
    gdf_parcels.loc[0, "verified"] = 1
    gdf_parcels.loc[0, "surveyor"] = "Er. Vikramjit Singh"
    gdf_parcels.loc[0, "survey_note"] = "Confirmed boundary stone at SW corner"
    gdf_parcels.loc[0, "photo_url"] = "photos/sw_corner.jpg"

    # Slightly adjust geometry in field
    original_poly = gdf_parcels.geometry.iloc[0]
    edited_poly = Polygon([(500000, 3000000), (500052, 3000000), (500052, 3000050), (500000, 3000050)])
    gdf_parcels.geometry.iloc[0] = edited_poly
    gdf_parcels.to_file(str(pkg_file), layer="parcels", driver="GPKG")

    # Add a new GNSS checkpoint to gt_points
    gdf_pts = gpd.read_file(str(pkg_file), layer="gt_points")
    new_pt_row = {
        "id": None,
        "project_id": 1,
        "source": "field",
        "accuracy_m": 0.015,
        "photo_url": "photos/monument_ne.jpg",
        "note": "RTK GNSS boundary corner",
        "geometry": Point(500052, 3000050),
    }
    gdf_pts = gpd.GeoDataFrame(list(gdf_pts.to_dict("records")) + [new_pt_row], crs=gdf_pts.crs)
    gdf_pts.to_file(str(pkg_file), layer="gt_points", driver="GPKG")

    # 3. Ingest back into ParcelAI
    res = sync_field_package(project_id=1, gpkg_path=pkg_file, db=populated_db)

    assert res["status"] == "synced"
    assert res["verified_parcels"] == 1
    assert res["updated_geometries"] == 1
    assert res["imported_checkpoints"] == 1
    assert len(res["errors"]) == 0

    # 4. Check DB mutations
    parcel = populated_db.parcels[101]
    assert parcel.status == ParcelStatus.verified
    assert parcel.source == ParcelSource.field
    assert parcel.ladm_attrs["surveyor"] == "Er. Vikramjit Singh"
    assert parcel.ladm_attrs["survey_notes"] == "Confirmed boundary stone at SW corner"
    assert len(populated_db.edit_history) >= 2


def test_build_synthetic_finetune_dataset(tmp_path: Path):
    """Test generating active learning dataset and loading with LocalGeoDataset."""
    out_dir = tmp_path / "finetune"
    manifest = create_synthetic_finetune_set(output_dir=out_dir, num_tiles=4, tile_size=256, in_channels=4)

    assert manifest["num_samples"] == 4
    assert len(manifest["images"]) == 4
    assert len(manifest["masks"]["building"]) == 4
    assert len(manifest["masks"]["road"]) == 4
    assert len(manifest["masks"]["boundary"]) == 4
    assert len(manifest["masks"]["landuse"]) == 4

    # Test loading dataset into PyTorch loader
    dataset = LocalGeoDataset(
        image_paths=manifest["images"],
        mask_paths=manifest["masks"],
        in_channels=4,
    )

    assert len(dataset) == 4
    item = dataset[0]
    assert "image" in item
    assert item["image"].shape == (4, 256, 256)
    assert item["building"].shape == (1, 256, 256)
    assert item["road"].shape == (1, 256, 256)
    assert item["boundary"].shape == (1, 256, 256)
    assert item["landuse"].shape == (256, 256)


def test_field_api_routes(populated_db, tmp_path: Path):
    """Test /field-package and /field-sync REST API endpoints."""
    app.dependency_overrides[get_db] = lambda: populated_db
    client = TestClient(app)

    # 1. GET /field-package
    resp = client.get("/api/v1/projects/1/field-package")
    assert resp.status_code == 200
    assert "geopackage" in resp.headers.get("content-type", "")

    # Save received package
    pkg_path = tmp_path / "api_download.gpkg"
    with open(pkg_path, "wb") as f:
        f.write(resp.content)
    assert pkg_path.exists()

    # 2. POST /field-sync
    with open(pkg_path, "rb") as f:
        sync_resp = client.post(
            "/api/v1/projects/1/field-sync",
            files={"file": ("survey_pkg.gpkg", f, "application/geopackage+sqlite3")},
        )
    assert sync_resp.status_code == 200
    sync_data = sync_resp.json()
    assert sync_data["status"] == "synced"
    assert sync_data["project_id"] == 1
    assert "Preliminary" in sync_data["disclaimer"]

    app.dependency_overrides.clear()
