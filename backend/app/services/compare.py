"""Comparison service for ParcelAI (Section 7.6).

Responsibilities:
- Compare AI-extracted cadastral parcel layer against existing reference GIS parcel layers.
- Metrics:
  - Intersection over Union (IoU)
  - Relative Area Difference percentage
  - Hausdorff boundary distance
  - Centroid offset distance
- Classification:
  - matched (unchanged): high overlap (IoU >= 0.70) and area diff <= 15%
  - changed_parcel: partial overlap (0.20 <= IoU < 0.70) or significant area/boundary difference
  - new_parcel: AI parcel with no corresponding existing parcel (IoU < 0.20 with all existing)
  - missing_parcel: Existing parcel with no corresponding AI parcel (IoU < 0.20 with all AI)
- Issue logging:
  - Write new_parcel, missing_parcel, and changed_parcel records to PostGIS `issues` table.
- Return:
  - CompareSummary with counts and detailed per-parcel comparison metrics.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import geopandas as gpd
from geoalchemy2.shape import from_shape, to_shape
from shapely.geometry import MultiPolygon, Polygon, mapping
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ParcelAIError
from app.models.db_models import Issue, IssueSeverity, IssueType, Parcel
from app.models.schemas import CompareSummary


@dataclass
class ParcelComparisonItem:
    """Individual parcel comparison result."""

    status: str  # matched | changed | new | missing
    ai_parcel_id: int | None
    existing_parcel_id: int | None
    iou: float
    area_diff_pct: float
    hausdorff_distance_m: float
    centroid_distance_m: float
    ai_area_m2: float
    existing_area_m2: float
    geom: Polygon | MultiPolygon | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "ai_parcel_id": self.ai_parcel_id,
            "existing_parcel_id": self.existing_parcel_id,
            "iou": round(self.iou, 4),
            "area_diff_pct": round(self.area_diff_pct, 2),
            "hausdorff_distance_m": round(self.hausdorff_distance_m, 3),
            "centroid_distance_m": round(self.centroid_distance_m, 3),
            "ai_area_m2": round(self.ai_area_m2, 2),
            "existing_area_m2": round(self.existing_area_m2, 2),
            "geom": mapping(self.geom) if self.geom is not None else None,
        }


def load_vector_parcels(file_path: str | Path) -> list[Polygon]:
    """Load parcel polygons from GeoJSON, Shapefile, or GeoPackage."""
    p = Path(file_path)
    if not p.exists():
        raise ParcelAIError(f"Existing parcel layer file not found: {p}")

    gdf = gpd.read_file(p)
    polys: list[Polygon] = []
    for geom in gdf.geometry:
        if geom is None or geom.is_empty:
            continue
        if isinstance(geom, Polygon) and geom.is_valid:
            polys.append(geom)
        elif isinstance(geom, MultiPolygon):
            for part in geom.geoms:
                if part.is_valid and not part.is_empty:
                    polys.append(part)
        elif not geom.is_valid:
            valid = geom.buffer(0)
            if isinstance(valid, Polygon) and valid.is_valid:
                polys.append(valid)
            elif isinstance(valid, MultiPolygon):
                for part in valid.geoms:
                    if part.is_valid:
                        polys.append(part)

    return polys


def compare_parcel_lists(
    project_id: int,
    ai_parcels: list[Polygon],
    existing_parcels: list[Polygon],
    ai_ids: list[int] | None = None,
    existing_ids: list[int] | None = None,
    iou_match_threshold: float = 0.70,
    area_diff_threshold: float = 0.15,
) -> tuple[CompareSummary, list[ParcelComparisonItem]]:
    """Compare two lists of parcel polygons and return metrics and classification."""
    n_ai = len(ai_parcels)
    n_ext = len(existing_parcels)

    ai_ids = ai_ids or list(range(1, n_ai + 1))
    existing_ids = existing_ids or list(range(1, n_ext + 1))

    matched_existing_indices = set()
    matched_ai_indices = set()
    items: list[ParcelComparisonItem] = []

    # 1. Match AI parcels against existing parcels
    for i_ai, p_ai in enumerate(ai_parcels):
        if not p_ai.is_valid or p_ai.is_empty:
            continue
        ai_id = ai_ids[i_ai]

        best_iou = 0.0
        best_j = -1
        best_ext_poly = None

        for j_ext, p_ext in enumerate(existing_parcels):
            if not p_ext.is_valid or p_ext.is_empty:
                continue
            if p_ai.intersects(p_ext):
                inter_area = p_ai.intersection(p_ext).area
                union_area = p_ai.union(p_ext).area
                if union_area > 0:
                    iou = inter_area / union_area
                    if iou > best_iou:
                        best_iou = iou
                        best_j = j_ext
                        best_ext_poly = p_ext

        if best_j >= 0 and best_iou >= 0.20 and best_ext_poly is not None:
            # Candidate match found
            ext_id = existing_ids[best_j]
            matched_ai_indices.add(i_ai)
            matched_existing_indices.add(best_j)

            area_ai = p_ai.area
            area_ext = best_ext_poly.area
            area_diff = abs(area_ai - area_ext) / max(area_ext, 1e-6)

            try:
                h_dist = p_ai.hausdorff_distance(best_ext_poly)
            except Exception:
                h_dist = 0.0
            c_dist = p_ai.centroid.distance(best_ext_poly.centroid)

            if best_iou >= iou_match_threshold and area_diff <= area_diff_threshold:
                status = "matched"
            else:
                status = "changed"

            items.append(
                ParcelComparisonItem(
                    status=status,
                    ai_parcel_id=ai_id,
                    existing_parcel_id=ext_id,
                    iou=best_iou,
                    area_diff_pct=area_diff * 100.0,
                    hausdorff_distance_m=h_dist,
                    centroid_distance_m=c_dist,
                    ai_area_m2=area_ai,
                    existing_area_m2=area_ext,
                    geom=p_ai,
                )
            )
        else:
            # New parcel detected (present in AI but missing in existing GIS layer)
            items.append(
                ParcelComparisonItem(
                    status="new",
                    ai_parcel_id=ai_id,
                    existing_parcel_id=None,
                    iou=0.0,
                    area_diff_pct=100.0,
                    hausdorff_distance_m=0.0,
                    centroid_distance_m=0.0,
                    ai_area_m2=p_ai.area,
                    existing_area_m2=0.0,
                    geom=p_ai,
                )
            )

    # 2. Check for missing parcels (present in existing GIS layer but absent in AI)
    for j_ext, p_ext in enumerate(existing_parcels):
        if j_ext not in matched_existing_indices:
            ext_id = existing_ids[j_ext]
            items.append(
                ParcelComparisonItem(
                    status="missing",
                    ai_parcel_id=None,
                    existing_parcel_id=ext_id,
                    iou=0.0,
                    area_diff_pct=100.0,
                    hausdorff_distance_m=0.0,
                    centroid_distance_m=0.0,
                    ai_area_m2=0.0,
                    existing_area_m2=p_ext.area,
                    geom=p_ext,
                )
            )

    matched_count = sum(1 for item in items if item.status == "matched")
    changed_count = sum(1 for item in items if item.status == "changed")
    new_count = sum(1 for item in items if item.status == "new")
    missing_count = sum(1 for item in items if item.status == "missing")

    summary = CompareSummary(
        project_id=project_id,
        matched_count=matched_count,
        new_count=new_count,
        missing_count=missing_count,
        changed_count=changed_count,
        details=[item.to_dict() for item in items],
    )

    return summary, items


def compare_with_existing(
    project_id: int,
    existing_parcels_path: str | Path | None = None,
    db: Session | None = None,
    ai_parcels: list[Polygon] | None = None,
    existing_parcels: list[Polygon] | None = None,
    iou_match_threshold: float = 0.70,
    area_diff_threshold: float = 0.15,
) -> CompareSummary:
    """Main comparison service entrypoint."""
    # 1. Resolve AI parcels
    ai_ids = None
    if ai_parcels is None and db is not None:
        db_parcels = db.scalars(
            select(Parcel).where(Parcel.project_id == project_id)
        ).all()
        ai_parcels = [to_shape(p.geom) for p in db_parcels if p.geom is not None]
        ai_ids = [p.id for p in db_parcels]
    elif ai_parcels is None:
        ai_parcels = []

    # 2. Resolve existing parcels
    if existing_parcels is None and existing_parcels_path is not None:
        existing_parcels = load_vector_parcels(existing_parcels_path)
    elif existing_parcels is None:
        existing_parcels = []

    summary, items = compare_parcel_lists(
        project_id=project_id,
        ai_parcels=ai_parcels,
        existing_parcels=existing_parcels,
        ai_ids=ai_ids,
        iou_match_threshold=iou_match_threshold,
        area_diff_threshold=area_diff_threshold,
    )

    # 3. If DB session provided, log comparison findings as issues
    if db is not None:
        for item in items:
            issue_type = None
            suggested_fix = ""
            severity = IssueSeverity.info

            if item.status == "new":
                issue_type = IssueType.new_parcel
                suggested_fix = f"New parcel detected by AI (id: {item.ai_parcel_id}, area: {item.ai_area_m2:.2f} m²)"
                severity = IssueSeverity.info
            elif item.status == "missing":
                issue_type = IssueType.missing_parcel
                suggested_fix = f"Existing parcel #{item.existing_parcel_id} not detected by AI; check aerial coverage"
                severity = IssueSeverity.warning
            elif item.status == "changed":
                issue_type = IssueType.changed_parcel
                suggested_fix = (
                    f"Parcel changed vs existing layer (AI #{item.ai_parcel_id} vs Existing #{item.existing_parcel_id}, "
                    f"IoU: {item.iou:.2f}, area diff: {item.area_diff_pct:.1f}%)"
                )
                severity = IssueSeverity.warning

            if issue_type is not None and item.geom is not None:
                issue = Issue(
                    project_id=project_id,
                    issue_type=issue_type,
                    severity=severity,
                    geom=from_shape(item.geom, srid=32643),
                    suggested_fix=suggested_fix,
                    resolved=False,
                    created_at=datetime.now(timezone.utc),
                )
                db.add(issue)

        db.commit()

    return summary
