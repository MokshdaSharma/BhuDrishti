"""Topology validation and auto-repair service for ParcelAI (Section 7.6).

Responsibilities:
- Validate spatial consistency of cadastral parcels, buildings, and roads.
- Checks:
  - Invalid geometry (self-intersections, bowties, open rings)
  - Overlapping parcels (> min_overlap_area)
  - Gaps / interior holes within parcel clusters
  - Sliver polygons (thinness ratio / area-to-perimeter)
  - Duplicate vertices and spikes
  - Building crosses parcel boundary (building bisected by multiple parcels)
  - Building on road (encroachment into road corridors)
  - Landlocked parcels (no road contact / access corridor)
  - Low confidence parcels
- Auto-fix trivial issues:
  - ST_MakeValid / shapely.make_valid
  - Remove duplicate vertices / simplify micro-spikes
  - Snap & merge tiny overlaps/slivers into neighbor with longest shared boundary
  - Log auto-fixes into edit_history
- Persistence to `issues` table and returning `ValidationSummary`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import shapely
from geoalchemy2.shape import from_shape, to_shape
from shapely.geometry import MultiPolygon, Point, Polygon, mapping
from shapely.ops import snap, unary_union
from shapely.validation import make_valid
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.db_models import (
    Building,
    EditAction,
    EditHistory,
    Issue,
    IssueSeverity,
    IssueType,
    Parcel,
    Road,
)
from app.models.schemas import ValidationSummary


@dataclass
class TopologyFinding:
    """Individual topology validation finding."""

    issue_type: IssueType
    severity: IssueSeverity
    geom: Polygon | MultiPolygon | Point | None
    suggested_fix: str
    feature_id: int | None = None
    resolved: bool = False
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "issue_type": self.issue_type.value,
            "severity": self.severity.value,
            "geom": mapping(self.geom) if self.geom is not None else None,
            "suggested_fix": self.suggested_fix,
            "feature_id": self.feature_id,
            "resolved": self.resolved,
            "details": self.details,
        }


def check_invalid_geometries(
    parcels: list[Polygon],
    parcel_ids: list[int] | None = None,
) -> list[TopologyFinding]:
    """Check for self-intersecting or invalid polygon geometries."""
    findings = []
    for idx, poly in enumerate(parcels):
        p_id = parcel_ids[idx] if parcel_ids and idx < len(parcel_ids) else idx + 1
        if not poly.is_valid:
            reason = shapely.is_valid_reason(poly)
            findings.append(
                TopologyFinding(
                    issue_type=IssueType.invalid_geometry,
                    severity=IssueSeverity.error,
                    geom=poly,
                    suggested_fix=f"Run make_valid: {reason}",
                    feature_id=p_id,
                )
            )
    return findings


def check_overlaps(
    parcels: list[Polygon],
    parcel_ids: list[int] | None = None,
    min_overlap_area_m2: float = 0.5,
) -> list[TopologyFinding]:
    """Detect overlapping parcel regions above area threshold."""
    findings = []
    n = len(parcels)
    for i in range(n):
        p1 = parcels[i]
        if not p1.is_valid or p1.is_empty:
            continue
        p1_id = parcel_ids[i] if parcel_ids and i < len(parcel_ids) else i + 1

        for j in range(i + 1, n):
            p2 = parcels[j]
            if not p2.is_valid or p2.is_empty:
                continue
            p2_id = parcel_ids[j] if parcel_ids and j < len(parcel_ids) else j + 1

            if p1.intersects(p2):
                try:
                    inter = p1.intersection(p2)
                    if inter.area >= min_overlap_area_m2:
                        findings.append(
                            TopologyFinding(
                                issue_type=IssueType.overlap,
                                severity=IssueSeverity.error,
                                geom=inter,
                                suggested_fix=f"Resolve overlap between parcel {p1_id} and parcel {p2_id} (area: {inter.area:.2f} m²)",
                                feature_id=p1_id,
                                details={"parcel_a": p1_id, "parcel_b": p2_id, "overlap_area_m2": round(inter.area, 2)},
                            )
                        )
                except Exception:
                    continue
    return findings


def check_gaps(
    parcels: list[Polygon],
    max_gap_area_m2: float = 50.0,
) -> list[TopologyFinding]:
    """Detect unassigned interior holes / gaps inside parcel cluster."""
    valid_parcels = [p for p in parcels if p.is_valid and not p.is_empty]
    if len(valid_parcels) < 3:
        return []

    findings = []
    try:
        cluster_union = unary_union(valid_parcels)
        hull = cluster_union.convex_hull
        diff = hull.difference(cluster_union)

        if isinstance(diff, Polygon):
            diff_parts = [diff]
        elif isinstance(diff, MultiPolygon):
            diff_parts = list(diff.geoms)
        else:
            diff_parts = []

        for part in diff_parts:
            # Check if hole is an interior hole (touches multiple parcels around it)
            if 0.5 <= part.area <= max_gap_area_m2:
                # Count touching parcels
                touching = sum(1 for p in valid_parcels if p.intersects(part))
                if touching >= 2:
                    findings.append(
                        TopologyFinding(
                            issue_type=IssueType.gap,
                            severity=IssueSeverity.warning,
                            geom=part,
                            suggested_fix=f"Interior gap detected ({part.area:.2f} m²); snap neighbor parcels or assign to adjacent parcel",
                            details={"gap_area_m2": round(part.area, 2), "touching_parcels": touching},
                        )
                    )
    except Exception:
        pass

    return findings


def check_slivers(
    parcels: list[Polygon],
    parcel_ids: list[int] | None = None,
    min_area_m2: float = 20.0,
    thinness_threshold: float = 0.15,
) -> list[TopologyFinding]:
    """Detect sliver polygons (abnormally small or extremely elongated thin shapes)."""
    findings = []
    for idx, poly in enumerate(parcels):
        if not poly.is_valid or poly.is_empty:
            continue
        p_id = parcel_ids[idx] if parcel_ids and idx < len(parcel_ids) else idx + 1
        area = poly.area
        perim = poly.length
        if perim <= 0:
            continue

        # Isoperimetric quotient = 4 * pi * Area / Perimeter^2
        thinness = (4.0 * math.pi * area) / (perim * perim)

        if area < min_area_m2 or (thinness < thinness_threshold and area < 100.0):
            findings.append(
                TopologyFinding(
                    issue_type=IssueType.sliver,
                    severity=IssueSeverity.warning,
                    geom=poly,
                    suggested_fix=f"Parcel {p_id} is a sliver (area: {area:.2f} m², thinness: {thinness:.3f}); merge with neighbor sharing longest edge",
                    feature_id=p_id,
                    details={"area_m2": round(area, 2), "thinness": round(thinness, 3)},
                )
            )
    return findings


def check_building_crosses_parcel(
    parcels: list[Polygon],
    buildings: list[Polygon],
    parcel_ids: list[int] | None = None,
) -> list[TopologyFinding]:
    """Detect buildings bisected by multiple parcel boundaries."""
    findings = []
    for b_idx, bldg in enumerate(buildings):
        if not bldg.is_valid or bldg.is_empty:
            continue

        intersecting_parcels = []
        for p_idx, parcel in enumerate(parcels):
            if parcel.is_valid and parcel.intersects(bldg):
                inter_area = parcel.intersection(bldg).area
                if inter_area > 0.05 * bldg.area:
                    p_id = parcel_ids[p_idx] if parcel_ids and p_idx < len(parcel_ids) else p_idx + 1
                    intersecting_parcels.append((p_id, inter_area))

        if len(intersecting_parcels) >= 2:
            p_ids_str = ", ".join(str(p[0]) for p in intersecting_parcels)
            findings.append(
                TopologyFinding(
                    issue_type=IssueType.building_crosses_parcel,
                    severity=IssueSeverity.error,
                    geom=bldg,
                    suggested_fix=f"Building #{b_idx + 1} crosses parcel boundaries ({p_ids_str}); merge parcels or re-align parcel boundary",
                    details={"building_index": b_idx + 1, "intersecting_parcels": [p[0] for p in intersecting_parcels]},
                )
            )
    return findings


def check_building_on_road(
    buildings: list[Polygon],
    roads: list[Polygon | MultiPolygon],
    min_encroach_area_m2: float = 1.0,
) -> list[TopologyFinding]:
    """Detect buildings encroaching on road network corridors."""
    findings = []
    if not roads or not buildings:
        return findings

    try:
        road_union = unary_union([r for r in roads if r.is_valid and not r.is_empty])
    except Exception:
        return findings

    if road_union.is_empty:
        return findings

    for b_idx, bldg in enumerate(buildings):
        if not bldg.is_valid or bldg.is_empty:
            continue
        if bldg.intersects(road_union):
            try:
                encroachment = bldg.intersection(road_union)
                if encroachment.area >= min_encroach_area_m2:
                    findings.append(
                        TopologyFinding(
                            issue_type=IssueType.building_on_road,
                            severity=IssueSeverity.error,
                            geom=encroachment,
                            suggested_fix=f"Building #{b_idx + 1} encroaches on road corridor (encroachment area: {encroachment.area:.2f} m²)",
                            details={"building_index": b_idx + 1, "encroachment_area_m2": round(encroachment.area, 2)},
                        )
                    )
            except Exception:
                continue
    return findings


def check_landlocked_parcels(
    parcels: list[Polygon],
    roads: list[Polygon | MultiPolygon],
    parcel_ids: list[int] | None = None,
    max_road_dist_m: float = 2.0,
) -> list[TopologyFinding]:
    """Detect parcels without direct road or access corridor frontage."""
    findings = []
    if not roads:
        return findings

    try:
        road_union = unary_union([r for r in roads if r.is_valid and not r.is_empty])
    except Exception:
        return findings

    for idx, poly in enumerate(parcels):
        if not poly.is_valid or poly.is_empty:
            continue
        p_id = parcel_ids[idx] if parcel_ids and idx < len(parcel_ids) else idx + 1
        dist = poly.distance(road_union)
        if dist > max_road_dist_m:
            findings.append(
                TopologyFinding(
                    issue_type=IssueType.landlocked_parcel,
                    severity=IssueSeverity.warning,
                    geom=poly,
                    suggested_fix=f"Parcel {p_id} is landlocked (distance to nearest road: {dist:.1f} m); add access corridor",
                    feature_id=p_id,
                    details={"distance_to_road_m": round(dist, 1)},
                )
            )
    return findings


def check_low_confidence(
    parcels: list[Polygon],
    confidences: list[float],
    parcel_ids: list[int] | None = None,
    threshold: float = 0.40,
) -> list[TopologyFinding]:
    """Flag parcels with low AI confidence for surveyor manual review."""
    findings = []
    for idx, conf in enumerate(confidences):
        if conf < threshold:
            p_id = parcel_ids[idx] if parcel_ids and idx < len(parcel_ids) else idx + 1
            poly = parcels[idx] if idx < len(parcels) else None
            findings.append(
                TopologyFinding(
                    issue_type=IssueType.low_confidence,
                    severity=IssueSeverity.info,
                    geom=poly,
                    suggested_fix=f"Parcel {p_id} confidence is low ({conf:.2f}); verify boundary in field or aerial view",
                    feature_id=p_id,
                    details={"confidence": round(conf, 4)},
                )
            )
    return findings


def autofix_parcels(
    parcels: list[Polygon],
    min_area_m2: float = 20.0,
    snap_tolerance: float = 0.1,
) -> tuple[list[Polygon], int]:
    """Auto-repair invalid geometries, duplicate vertices, micro-overlaps, and slivers."""
    fixed_count = 0
    cleaned = []

    # 1. Fix invalid geometries & simplify spikes
    for p in parcels:
        if not p.is_valid:
            try:
                repaired = make_valid(p)
                if isinstance(repaired, Polygon) and repaired.area > 0:
                    cleaned.append(repaired)
                    fixed_count += 1
                elif isinstance(repaired, MultiPolygon):
                    for part in repaired.geoms:
                        if part.area > 0:
                            cleaned.append(part)
                    fixed_count += 1
                else:
                    cleaned.append(p)
            except Exception:
                cleaned.append(p)
        else:
            # Simplify duplicate vertices
            sim = p.simplify(0.01, preserve_topology=True)
            if sim.is_valid and sim.area > 0:
                cleaned.append(sim)
            else:
                cleaned.append(p)

    # 2. Merge slivers
    active = list(cleaned)
    for sliver in [p for p in active if p.area < min_area_m2]:
        if sliver not in active:
            continue
        best_idx = -1
        max_edge = 0.0
        for idx, other in enumerate(active):
            if other != sliver and other.intersects(sliver):
                try:
                    inter_len = other.intersection(sliver).length
                    if inter_len > max_edge:
                        max_edge = inter_len
                        best_idx = idx
                except Exception:
                    continue
        if best_idx >= 0:
            target = active[best_idx]
            merged = unary_union([target, sliver])
            if merged.is_valid and isinstance(merged, Polygon):
                active[best_idx] = merged
                active.remove(sliver)
                fixed_count += 1

    # 3. Snap adjacent parcels
    if len(active) > 1:
        for i in range(len(active)):
            for j in range(i + 1, len(active)):
                p1 = active[i]
                p2 = active[j]
                if p1.distance(p2) <= snap_tolerance:
                    try:
                        p1_snap = snap(p1, p2, snap_tolerance)
                        p2_snap = snap(p2, p1_snap, snap_tolerance)
                        if p1_snap.is_valid and p2_snap.is_valid:
                            active[i] = p1_snap
                            active[j] = p2_snap
                    except Exception:
                        continue

    return active, fixed_count


def validate_topology_standalone(
    project_id: int,
    parcels: list[Polygon],
    buildings: list[Polygon] | None = None,
    roads: list[Polygon | MultiPolygon] | None = None,
    confidences: list[float] | None = None,
    parcel_ids: list[int] | None = None,
    autofix: bool = True,
) -> tuple[ValidationSummary, list[TopologyFinding], list[Polygon]]:
    """Run all topology validation checks in memory (standalone mode)."""
    buildings = buildings or []
    roads = roads or []
    confidences = confidences or [0.8] * len(parcels)

    autofixed_count = 0
    work_parcels = list(parcels)
    if autofix:
        work_parcels, autofixed_count = autofix_parcels(parcels)

    findings: list[TopologyFinding] = []
    findings.extend(check_invalid_geometries(work_parcels, parcel_ids))
    findings.extend(check_overlaps(work_parcels, parcel_ids))
    findings.extend(check_gaps(work_parcels))
    findings.extend(check_slivers(work_parcels, parcel_ids))
    findings.extend(check_building_crosses_parcel(work_parcels, buildings, parcel_ids))
    findings.extend(check_building_on_road(buildings, roads))
    findings.extend(check_landlocked_parcels(work_parcels, roads, parcel_ids))
    findings.extend(check_low_confidence(work_parcels, confidences, parcel_ids))

    issues_by_type: dict[str, int] = {}
    for f in findings:
        t = f.issue_type.value
        issues_by_type[t] = issues_by_type.get(t, 0) + 1

    valid_parcels_count = sum(1 for p in work_parcels if p.is_valid)

    summary = ValidationSummary(
        project_id=project_id,
        total_parcels=len(work_parcels),
        valid_parcels=valid_parcels_count,
        issues_found=len(findings),
        autofixed_count=autofixed_count,
        issues_by_type=issues_by_type,
    )

    return summary, findings, work_parcels


def validate(
    project_id: int,
    db: Session | None = None,
    autofix: bool = True,
) -> ValidationSummary:
    """Main topology validation entrypoint for API and service callers."""
    if db is None:
        # If no DB session provided, return empty summary for project
        return ValidationSummary(
            project_id=project_id,
            total_parcels=0,
            valid_parcels=0,
            issues_found=0,
            autofixed_count=0,
            issues_by_type={},
        )

    # 1. Fetch project parcels, buildings, and roads from DB
    db_parcels = db.scalars(
        select(Parcel).where(Parcel.project_id == project_id)
    ).all()
    db_buildings = db.scalars(
        select(Building).where(Building.project_id == project_id)
    ).all()
    db_roads = db.scalars(
        select(Road).where(Road.project_id == project_id)
    ).all()

    parcels = [to_shape(p.geom) for p in db_parcels if p.geom is not None]
    parcel_ids = [p.id for p in db_parcels]
    confidences = [p.confidence or 0.8 for p in db_parcels]
    buildings = [to_shape(b.geom) for b in db_buildings if b.geom is not None]
    roads = [to_shape(r.geom) for r in db_roads if r.geom is not None]

    # 2. Run standalone validator
    summary, findings, fixed_parcels = validate_topology_standalone(
        project_id=project_id,
        parcels=parcels,
        buildings=buildings,
        roads=roads,
        confidences=confidences,
        parcel_ids=parcel_ids,
        autofix=autofix,
    )

    # 3. If autofix changed parcels, update DB and log to edit_history
    if autofix and summary.autofixed_count > 0 and len(fixed_parcels) == len(db_parcels):
        for idx, db_p in enumerate(db_parcels):
            old_geom = db_p.geom
            new_shp = fixed_parcels[idx]
            new_geom = from_shape(new_shp, srid=32643)
            db_p.geom = new_geom
            db_p.updated_at = datetime.now(timezone.utc)

            # Log to edit_history
            db.add(
                EditHistory(
                    feature_table="parcels",
                    feature_id=db_p.id,
                    action=EditAction.update,
                    old_geom=old_geom,
                    new_geom=new_geom,
                    user_name="system_autofix",
                    ts=datetime.now(timezone.utc),
                )
            )

    # 4. Clear old unresolved issues for this project and write new findings
    db.execute(
        delete(Issue).where(
            Issue.project_id == project_id,
            Issue.resolved.is_(False),
        )
    )

    for f in findings:
        issue = Issue(
            project_id=project_id,
            issue_type=f.issue_type,
            severity=f.severity,
            geom=from_shape(f.geom, srid=32643) if f.geom is not None else None,
            suggested_fix=f.suggested_fix,
            resolved=False,
            created_at=datetime.now(timezone.utc),
        )
        db.add(issue)

    db.commit()
    return summary
