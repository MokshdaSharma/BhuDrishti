"""Integration tests for ParcelAI REST API endpoints (Phase 8)."""

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.db import get_db
from app.main import app
from app.models.db_models import (
    Building,
    Issue,
    Parcel,
    Project,
    ProjectStatus,
    Raster,
    Road,
)


class MockDbSession:
    """In-memory mock database session for fast API route testing."""

    def __init__(self):
        self.projects: dict[int, Project] = {}
        self.parcels: dict[int, Parcel] = {}
        self.buildings: dict[int, Building] = {}
        self.roads: dict[int, Road] = {}
        self.issues: dict[int, Issue] = {}
        self.rasters: dict[int, Raster] = {}
        self.gt_points: dict[int, Any] = {}
        self._next_id = 1

    def _get_store(self, statement):
        sql = str(statement).lower()
        if "from gt_points" in sql or "gtpoint" in sql:
            return self.gt_points
        elif "from parcels" in sql or "parcel" in sql:
            return self.parcels
        elif "from buildings" in sql or "building" in sql:
            return self.buildings
        elif "from roads" in sql or "road" in sql:
            return self.roads
        elif "from issues" in sql or "issue" in sql:
            return self.issues
        elif "from rasters" in sql or "raster" in sql:
            return self.rasters
        elif "from projects" in sql or "project" in sql:
            return self.projects
        return self.projects

    def add(self, obj):
        if not hasattr(obj, "id") or obj.id is None:
            obj.id = self._next_id
            self._next_id += 1

        if hasattr(obj, "created_at") and getattr(obj, "created_at", None) is None:
            obj.created_at = datetime.now(timezone.utc)

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
        elif isinstance(obj, Raster):
            self.rasters[obj.id] = obj

    def delete(self, obj):
        if isinstance(obj, Project):
            self.projects.pop(obj.id, None)
        elif isinstance(obj, Parcel):
            self.parcels.pop(obj.id, None)
        elif isinstance(obj, Issue):
            self.issues.pop(obj.id, None)

    def commit(self):
        pass

    def rollback(self):
        pass

    def flush(self):
        pass

    def refresh(self, obj):
        if hasattr(obj, "created_at") and getattr(obj, "created_at", None) is None:
            obj.created_at = datetime.now(timezone.utc)

    def scalar(self, statement):
        store = self._get_store(statement)
        for item in store.values():
            return item
        return None

    def scalars(self, statement):
        store = self._get_store(statement)
        res = MagicMock()
        res.all.return_value = list(store.values())
        return res

    def execute(self, statement):
        pass


@pytest.fixture
def mock_db():
    return MockDbSession()


@pytest.fixture
def client(mock_db):
    def override_get_db():
        try:
            yield mock_db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_create_and_list_projects(client: TestClient, mock_db: MockDbSession):
    """POST /api/v1/projects and GET /api/v1/projects."""
    # 1. Create project
    res = client.post("/api/v1/projects", json={"name": "Test Mohali", "crs": "EPSG:32643"})
    assert res.status_code == 201
    data = res.json()
    assert data["name"] == "Test Mohali"
    assert data["crs"] == "EPSG:32643"
    assert data["status"] == "pending"
    p_id = data["id"]

    # 2. List projects
    mock_db.projects[p_id] = Project(
        id=p_id,
        name="Test Mohali",
        crs="EPSG:32643",
        status=ProjectStatus.pending,
        created_at=datetime.now(timezone.utc),
    )
    res_list = client.get("/api/v1/projects")
    assert res_list.status_code == 200
    assert len(res_list.json()) >= 1


def test_get_project_tiles(client: TestClient, mock_db: MockDbSession):
    """GET /api/v1/projects/{id}/tiles."""
    mock_db.projects[1] = Project(
        id=1, name="Tiles Test", crs="EPSG:32643", status=ProjectStatus.done, created_at=datetime.now(timezone.utc)
    )
    res = client.get("/api/v1/projects/1/tiles")
    assert res.status_code == 200
    data = res.json()
    assert "raster_tiles" in data
    assert "vector_tiles" in data
    assert "parcels" in data["vector_tiles"]


def test_get_context_status(client: TestClient, mock_db: MockDbSession):
    """GET /api/v1/projects/{id}/context/status."""
    mock_db.projects[1] = Project(
        id=1, name="GEE Test", crs="EPSG:32643", status=ProjectStatus.done, created_at=datetime.now(timezone.utc)
    )
    res = client.get("/api/v1/projects/1/context/status")
    assert res.status_code == 200
    data = res.json()
    assert "gee_enabled" in data
    assert "available_layers" in data


def test_jobs_status_and_run(client: TestClient, mock_db: MockDbSession):
    """POST /api/v1/projects/{id}/run and GET /api/v1/jobs/{id}."""
    mock_db.projects[1] = Project(
        id=1, name="Run Test", crs="EPSG:32643", status=ProjectStatus.pending, created_at=datetime.now(timezone.utc)
    )

    with patch("app.workers.tasks.run_pipeline.delay") as mock_delay:
        mock_task = MagicMock()
        mock_task.id = "test-job-uuid-1234"
        mock_delay.return_value = mock_task

        res = client.post("/api/v1/projects/1/run")
        assert res.status_code == 202
        data = res.json()
        assert data["job_id"] == "test-job-uuid-1234"
        assert data["status"] == "queued"

    # Check job status for sync job
    res_job = client.get("/api/v1/jobs/sync_12345678")
    assert res_job.status_code == 200
    assert res_job.json()["status"] == "SUCCESS"
    assert res_job.json()["progress"] == 100


def test_compare_and_accuracy_routes(client: TestClient, mock_db: MockDbSession):
    """GET /api/v1/projects/{id}/compare and GET /api/v1/projects/{id}/accuracy."""
    mock_db.projects[1] = Project(
        id=1, name="Metrics Test", crs="EPSG:32643", status=ProjectStatus.done, created_at=datetime.now(timezone.utc)
    )

    # Compare route
    res_comp = client.get("/api/v1/projects/1/compare")
    assert res_comp.status_code == 200
    assert "matched_count" in res_comp.json()

    # Accuracy route
    res_acc = client.get("/api/v1/projects/1/accuracy")
    assert res_acc.status_code == 200
    assert "Preliminary" in res_acc.json()["disclaimer"]


def test_export_and_report_routes(client: TestClient, mock_db: MockDbSession, tmp_path: Path):
    """GET /api/v1/projects/{id}/export and GET /api/v1/projects/{id}/report/pdf."""
    mock_db.projects[1] = Project(
        id=1, name="Export Test", crs="EPSG:32643", status=ProjectStatus.done, created_at=datetime.now(timezone.utc)
    )

    dummy_geojson = tmp_path / "export_test.geojson"
    dummy_geojson.write_text('{"type": "FeatureCollection", "features": []}', encoding="utf-8")

    dummy_pdf = tmp_path / "report_test.pdf"
    dummy_pdf.write_bytes(b"%PDF-1.4 mock pdf content")

    with patch("app.api.export.export_dataset", return_value=dummy_geojson):
        # Export GeoJSON
        res_exp = client.get("/api/v1/projects/1/export?format=geojson")
        assert res_exp.status_code == 200
        assert "application/geo+json" in res_exp.headers["content-type"]

    with patch("app.api.export.build_pdf_report", return_value=dummy_pdf):
        # Download PDF report
        res_pdf = client.get("/api/v1/projects/1/report/pdf")
        assert res_pdf.status_code == 200
        assert res_pdf.headers["content-type"] == "application/pdf"
