"""Unit and integration tests for cadastral survey PDF reporting service (Phase 7)."""

from pathlib import Path

from shapely.geometry import Point, Polygon

from app.models.schemas import AccuracyReport
from app.services.report import build_pdf_report


def test_build_pdf_report(tmp_path: Path):
    """Verify PDF report generation, file integrity, and element rendering."""
    p1 = Polygon([(500000, 3000000), (500020, 3000000), (500020, 3000020), (500000, 3000020)])
    p2 = Polygon([(500020, 3000000), (500040, 3000000), (500040, 3000020), (500020, 3000020)])
    b1 = Polygon([(500004, 3000004), (500014, 3000004), (500014, 3000014), (500004, 3000014)])
    r1 = Polygon([(499990, 3000000), (499995, 3000000), (499995, 3000050), (499990, 3000050)])
    iss1 = Point(500020, 3000010)

    parcels = [
        {"id": 1, "geom": p1, "confidence": 0.95, "area_m2": 400.0},
        {"id": 2, "geom": p2, "confidence": 0.88, "area_m2": 400.0},
    ]
    buildings = [{"id": 1, "geom": b1, "confidence": 0.96}]
    roads = [{"id": 1, "geom": r1, "width_m": 5.0}]
    issues = [{"id": 1, "geom": iss1, "issue_type": "sliver", "severity": "warning", "suggested_fix": "Snap neighbor boundaries"}]

    acc_report = AccuracyReport(
        project_id=1,
        rmse_horizontal_m=0.124,
        mean_horizontal_error_m=0.098,
        iou_buildings=0.912,
        f1_buildings=0.954,
        iou_parcels=0.885,
        f1_parcels=0.939,
        correct_parcels=2,
        merged_parcels=0,
        split_parcels=0,
    )

    pdf_path = build_pdf_report(
        project_id=1,
        output_dir=tmp_path,
        parcels=parcels,
        buildings=buildings,
        roads=roads,
        issues=issues,
        accuracy_report=acc_report,
    )

    assert pdf_path.exists()
    assert pdf_path.suffix == ".pdf"
    # PDF should have substantive content including map snapshot image
    assert pdf_path.stat().st_size > 15000  # > 15 KB
