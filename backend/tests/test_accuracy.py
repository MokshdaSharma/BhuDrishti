"""Unit and integration tests for accuracy assessment service (Phase 7)."""

import pytest
from shapely.geometry import Point, Polygon

from app.models.schemas import AccuracyReport
from app.services.accuracy import (
    compute_accuracy,
    compute_cadastral_topology_counts,
    compute_checkpoint_positional_error,
    compute_polygon_iou_and_f1,
)


def test_checkpoint_positional_error():
    """Verify RMSE and mean horizontal error computation against GNSS points."""
    # Parcel boundary along x=10 (from y=0 to y=10)
    p = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])

    # Checkpoint 1: at (10.3, 5) -> offset 0.3m
    # Checkpoint 2: at (10.4, 8) -> offset 0.4m
    # Checkpoint 3: at (5, 10.5) -> offset 0.5m
    pts = [Point(10.3, 5.0), Point(10.4, 8.0), Point(5.0, 10.5)]

    rmse, mean_err = compute_checkpoint_positional_error(pts, [p], max_search_dist_m=5.0)

    assert mean_err == pytest.approx(0.40, abs=1e-3)
    # sqrt((0.09 + 0.16 + 0.25)/3) = sqrt(0.50/3) = sqrt(0.1667) ~ 0.4082
    assert rmse == pytest.approx(0.4082, abs=1e-3)


def test_polygon_iou_and_f1():
    """Verify IoU, precision, recall, and F1 calculations for predicted vs GT polygons."""
    # Perfect match
    p1 = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
    gt1 = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])

    iou, f1 = compute_polygon_iou_and_f1([p1], [gt1])
    assert iou == pytest.approx(1.0)
    assert f1 == pytest.approx(1.0)

    # Disjoint
    p2 = Polygon([(0, 0), (5, 0), (5, 5), (0, 5)])
    gt2 = Polygon([(100, 100), (105, 100), (105, 105), (100, 105)])
    iou2, f12 = compute_polygon_iou_and_f1([p2], [gt2])
    assert iou2 == pytest.approx(0.0)
    assert f12 == pytest.approx(0.0)


def test_cadastral_topology_counts():
    """Verify correct, merged, and split parcel detection vs Ground Truth."""
    # 1. Correct (1-to-1 match)
    p_correct = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
    gt_correct = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])

    # 2. Merged (single AI parcel covering 2 GT parcels)
    p_merged = Polygon([(20, 0), (40, 0), (40, 10), (20, 10)])  # 200 m^2
    gt_left = Polygon([(20, 0), (30, 0), (30, 10), (20, 10)])   # 100 m^2
    gt_right = Polygon([(30, 0), (40, 0), (40, 10), (30, 10)])  # 100 m^2

    # 3. Split (single GT parcel split into 2 AI parcels)
    gt_split = Polygon([(50, 0), (70, 0), (70, 10), (50, 10)])   # 200 m^2
    p_split1 = Polygon([(50, 0), (60, 0), (60, 10), (50, 10)])  # 100 m^2
    p_split2 = Polygon([(60, 0), (70, 0), (70, 10), (60, 10)])  # 100 m^2

    ai_parcels = [p_correct, p_merged, p_split1, p_split2]
    gt_parcels = [gt_correct, gt_left, gt_right, gt_split]

    correct, merged, split = compute_cadastral_topology_counts(ai_parcels, gt_parcels)

    assert correct >= 1
    assert merged >= 1
    assert split >= 1


def test_compute_accuracy_end_to_end():
    """Verify end-to-end compute_accuracy output schema and disclaimer."""
    p = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
    bldg = Polygon([(2, 2), (6, 2), (6, 6), (2, 6)])
    pt = Point(10.1, 5.0)

    report = compute_accuracy(
        project_id=1,
        ai_parcels=[p],
        ai_buildings=[bldg],
        gt_points=[pt],
        gt_parcels=[p],
        gt_buildings=[bldg],
    )

    assert isinstance(report, AccuracyReport)
    assert report.project_id == 1
    assert report.rmse_horizontal_m is not None
    assert report.rmse_horizontal_m == pytest.approx(0.1, abs=1e-3)
    assert report.iou_parcels == pytest.approx(1.0)
    assert report.iou_buildings == pytest.approx(1.0)
    assert "Preliminary" in report.disclaimer
