"""Unit and integration tests for topology validation and auto-repair (Phase 6)."""

import pytest
from shapely.geometry import Polygon

from app.models.db_models import IssueSeverity, IssueType
from app.services.topology import (
    autofix_parcels,
    check_building_crosses_parcel,
    check_building_on_road,
    check_gaps,
    check_invalid_geometries,
    check_landlocked_parcels,
    check_low_confidence,
    check_overlaps,
    check_slivers,
    validate_topology_standalone,
)


def test_check_invalid_geometries():
    """Detect self-intersecting / invalid geometries."""
    # Self-intersecting bow-tie polygon
    bowtie = Polygon([(0, 0), (10, 10), (0, 10), (10, 0), (0, 0)])
    valid_p = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])

    findings = check_invalid_geometries([bowtie, valid_p], parcel_ids=[101, 102])
    assert len(findings) == 1
    assert findings[0].issue_type == IssueType.invalid_geometry
    assert findings[0].feature_id == 101
    assert findings[0].severity == IssueSeverity.error


def test_check_overlaps():
    """Detect overlapping parcel regions above area threshold."""
    p1 = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
    p2 = Polygon([(8, 0), (18, 0), (18, 10), (8, 10)])  # Overlap 2x10 = 20 m^2
    p3 = Polygon([(30, 0), (40, 0), (40, 10), (30, 10)])  # Disjoint

    findings = check_overlaps([p1, p2, p3], parcel_ids=[1, 2, 3], min_overlap_area_m2=1.0)
    assert len(findings) == 1
    assert findings[0].issue_type == IssueType.overlap
    assert findings[0].details["overlap_area_m2"] == pytest.approx(20.0)


def test_check_gaps():
    """Detect interior holes within parcel clusters."""
    # 4 surrounding parcels leaving a 2x2 hole in the center: (4,4) to (6,6)
    p1 = Polygon([(0, 0), (10, 0), (10, 4), (0, 4)])      # bottom
    p2 = Polygon([(0, 6), (10, 6), (10, 10), (0, 10)])    # top
    p3 = Polygon([(0, 4), (4, 4), (4, 6), (0, 6)])        # left
    p4 = Polygon([(6, 4), (10, 4), (10, 6), (6, 6)])      # right

    findings = check_gaps([p1, p2, p3, p4], max_gap_area_m2=50.0)
    assert len(findings) == 1
    assert findings[0].issue_type == IssueType.gap
    assert findings[0].details["gap_area_m2"] == pytest.approx(4.0)


def test_check_slivers():
    """Detect slivers (micro-polygons or abnormally thin shapes)."""
    normal_p = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])  # 100 m^2
    tiny_sliver = Polygon([(0, 0), (1, 0), (1, 5), (0, 5)])   # 5 m^2 (< 20 min_area)
    thin_sliver = Polygon([(0, 0), (100, 0), (100, 0.5), (0, 0.5)])  # 50 m^2, thinness << 0.15

    findings = check_slivers([normal_p, tiny_sliver, thin_sliver], min_area_m2=20.0, thinness_threshold=0.15)
    assert len(findings) >= 2
    types = [f.issue_type for f in findings]
    assert all(t == IssueType.sliver for t in types)


def test_check_building_crosses_parcel():
    """Detect buildings split across multiple parcel boundaries."""
    p1 = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
    p2 = Polygon([(10, 0), (20, 0), (20, 10), (10, 10)])

    # Building crossing the boundary x=10: (8, 2) to (12, 8)
    bldg_crossing = Polygon([(8, 2), (12, 2), (12, 8), (8, 8)])
    # Building cleanly contained inside p1: (2, 2) to (4, 4)
    bldg_inside = Polygon([(2, 2), (4, 2), (4, 4), (2, 4)])

    findings = check_building_crosses_parcel([p1, p2], [bldg_crossing, bldg_inside], parcel_ids=[1, 2])
    assert len(findings) == 1
    assert findings[0].issue_type == IssueType.building_crosses_parcel
    assert findings[0].severity == IssueSeverity.error


def test_check_building_on_road():
    """Detect building encroachment on road network."""
    road = Polygon([(0, 10), (50, 10), (50, 15), (0, 15)])
    bldg_on_road = Polygon([(5, 8), (15, 8), (15, 12), (5, 12)])  # 2m encroaching
    bldg_safe = Polygon([(5, 0), (15, 0), (15, 5), (5, 5)])

    findings = check_building_on_road([bldg_on_road, bldg_safe], [road], min_encroach_area_m2=1.0)
    assert len(findings) == 1
    assert findings[0].issue_type == IssueType.building_on_road
    assert findings[0].severity == IssueSeverity.error


def test_check_landlocked_parcels():
    """Detect parcels without road access."""
    road = Polygon([(0, 0), (50, 0), (50, 4), (0, 4)])
    p_frontage = Polygon([(0, 4), (10, 4), (10, 14), (0, 14)])  # Touches road
    p_landlocked = Polygon([(0, 30), (10, 30), (10, 40), (0, 40)])  # 26m from road

    findings = check_landlocked_parcels([p_frontage, p_landlocked], [road], parcel_ids=[10, 20], max_road_dist_m=2.0)
    assert len(findings) == 1
    assert findings[0].issue_type == IssueType.landlocked_parcel
    assert findings[0].feature_id == 20


def test_check_low_confidence():
    """Flag low confidence parcels."""
    p1 = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
    p2 = Polygon([(10, 0), (20, 0), (20, 10), (10, 10)])

    findings = check_low_confidence([p1, p2], confidences=[0.85, 0.25], parcel_ids=[1, 2], threshold=0.40)
    assert len(findings) == 1
    assert findings[0].issue_type == IssueType.low_confidence
    assert findings[0].feature_id == 2


def test_autofix_parcels():
    """Verify automatic geometry repair and sliver merging."""
    bowtie = Polygon([(0, 0), (10, 10), (0, 10), (10, 0), (0, 0)])
    main_p = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
    sliver = Polygon([(10, 0), (10.5, 0), (10.5, 10), (10, 10)])  # 5 m^2

    fixed, count = autofix_parcels([bowtie, main_p, sliver], min_area_m2=20.0)
    assert count >= 1
    assert all(p.is_valid for p in fixed)


def test_validate_topology_standalone():
    """Verify end-to-end standalone topology validation summary."""
    p1 = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
    p2 = Polygon([(9, 0), (19, 0), (19, 10), (9, 10)])  # Overlap
    road = Polygon([(0, 0), (20, 0), (20, 2), (0, 2)])

    summary, findings, fixed = validate_topology_standalone(
        project_id=1,
        parcels=[p1, p2],
        roads=[road],
        autofix=False,
    )

    assert summary.project_id == 1
    assert summary.total_parcels == 2
    assert summary.issues_found > 0
    assert "overlap" in summary.issues_by_type
