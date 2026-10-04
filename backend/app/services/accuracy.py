"""Accuracy assessment service for ParcelAI (Section 7.7).

Responsibilities:
- Positional accuracy evaluation against GNSS/CORS/field survey checkpoints:
  - Root Mean Square Error (RMSE_horizontal)
  - Mean Horizontal Error (m)
- Area & Polygon overlap metrics against Ground-Truth (GT) layers:
  - Intersection over Union (IoU) for buildings and parcels
  - Precision, Recall, and F1 scores
- Cadastral count metrics:
  - correct_parcels (1-to-1 matches with GT, IoU >= 0.70)
  - merged_parcels (single AI parcel covering multiple GT parcels)
  - split_parcels (single GT parcel fragmented into multiple AI parcels)
- Disclaimer:
  - Always enforces "Preliminary — subject to field verification".
"""

from __future__ import annotations

import math
from pathlib import Path

import geopandas as gpd
import numpy as np
from geoalchemy2.shape import to_shape
from shapely.geometry import MultiPolygon, Point, Polygon
from shapely.ops import unary_union
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.db_models import Building, GtPoint, Parcel
from app.models.schemas import AccuracyReport


def load_point_features(file_path: str | Path) -> list[Point]:
    """Load survey checkpoint points from GeoJSON, Shapefile, or GeoPackage."""
    p = Path(file_path)
    if not p.exists():
        return []
    gdf = gpd.read_file(p)
    points: list[Point] = []
    for geom in gdf.geometry:
        if isinstance(geom, Point) and not geom.is_empty:
            points.append(geom)
    return points


def load_polygon_features(file_path: str | Path) -> list[Polygon]:
    """Load ground truth polygon features."""
    p = Path(file_path)
    if not p.exists():
        return []
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


def compute_checkpoint_positional_error(
    checkpoints: list[Point],
    reference_polygons: list[Polygon],
    max_search_dist_m: float = 15.0,
) -> tuple[float | None, float | None]:
    """Calculate RMSE and mean horizontal error from GNSS/CORS points to nearest boundary vertex/edge."""
    if not checkpoints or not reference_polygons:
        return None, None

    valid_polys = [p for p in reference_polygons if p.is_valid and not p.is_empty]
    if not valid_polys:
        return None, None

    try:
        boundaries_union = unary_union([p.boundary for p in valid_polys])
    except Exception:
        return None, None

    errors: list[float] = []
    for pt in checkpoints:
        if not pt.is_valid or pt.is_empty:
            continue
        dist = pt.distance(boundaries_union)
        if dist <= max_search_dist_m:
            errors.append(dist)

    if not errors:
        return None, None

    mean_err = float(np.mean(errors))
    rmse = float(math.sqrt(np.mean(np.square(errors))))
    return round(rmse, 4), round(mean_err, 4)


def compute_polygon_iou_and_f1(
    pred_polygons: list[Polygon],
    gt_polygons: list[Polygon],
    iou_match_threshold: float = 0.50,
) -> tuple[float | None, float | None]:
    """Compute overall IoU and F1 score between predicted and ground-truth polygon sets."""
    if not pred_polygons or not gt_polygons:
        return None, None

    valid_preds = [p for p in pred_polygons if p.is_valid and not p.is_empty]
    valid_gts = [p for p in gt_polygons if p.is_valid and not p.is_empty]

    if not valid_preds or not valid_gts:
        return None, None

    # Global spatial IoU
    try:
        pred_union = unary_union(valid_preds)
        gt_union = unary_union(valid_gts)
        inter_area = pred_union.intersection(gt_union).area
        union_area = pred_union.union(gt_union).area
        overall_iou = inter_area / max(union_area, 1e-6)
    except Exception:
        overall_iou = 0.0

    # Object-level precision, recall, F1
    matched_gt = set()
    matched_pred = set()

    for i, p in enumerate(valid_preds):
        best_iou = 0.0
        best_j = -1
        for j, g in enumerate(valid_gts):
            if p.intersects(g):
                inter = p.intersection(g).area
                un = p.union(g).area
                if un > 0:
                    iou = inter / un
                    if iou > best_iou:
                        best_iou = iou
                        best_j = j
        if best_j >= 0 and best_iou >= iou_match_threshold:
            matched_pred.add(i)
            matched_gt.add(best_j)

    tp = len(matched_gt)
    fp = len(valid_preds) - len(matched_pred)
    fn = len(valid_gts) - len(matched_gt)

    precision = tp / max(tp + fp, 1)
    recall = tp / max(tp + fn, 1)
    f1 = (2 * precision * recall) / max(precision + recall, 1e-6) if (precision + recall) > 0 else 0.0

    return round(float(overall_iou), 4), round(float(f1), 4)


def compute_cadastral_topology_counts(
    ai_parcels: list[Polygon],
    gt_parcels: list[Polygon],
    match_iou_threshold: float = 0.70,
    overlap_ratio_threshold: float = 0.20,
) -> tuple[int, int, int]:
    """Calculate correct, merged, and split parcel counts vs Ground-Truth."""
    if not ai_parcels or not gt_parcels:
        return 0, 0, 0

    valid_ai = [p for p in ai_parcels if p.is_valid and not p.is_empty]
    valid_gt = [p for p in gt_parcels if p.is_valid and not p.is_empty]

    correct_count = 0
    merged_count = 0
    split_count = 0

    # 1. Correct matches (1-to-1 with IoU >= threshold)
    for p_ai in valid_ai:
        for p_gt in valid_gt:
            if p_ai.intersects(p_gt):
                inter = p_ai.intersection(p_gt).area
                union = p_ai.union(p_gt).area
                if union > 0 and (inter / union) >= match_iou_threshold:
                    correct_count += 1
                    break

    # 2. Merged parcels: single AI parcel covers multiple GT parcels
    for p_ai in valid_ai:
        intersected_gt_count = 0
        for p_gt in valid_gt:
            if p_ai.intersects(p_gt):
                inter = p_ai.intersection(p_gt).area
                if inter >= overlap_ratio_threshold * p_gt.area:
                    intersected_gt_count += 1
        if intersected_gt_count >= 2:
            merged_count += 1

    # 3. Split parcels: single GT parcel is fragmented across multiple AI parcels
    for p_gt in valid_gt:
        intersected_ai_count = 0
        for p_ai in valid_ai:
            if p_gt.intersects(p_ai):
                inter = p_gt.intersection(p_ai).area
                if inter >= overlap_ratio_threshold * p_ai.area:
                    intersected_ai_count += 1
        if intersected_ai_count >= 2:
            split_count += 1

    return correct_count, merged_count, split_count


def compute_accuracy(
    project_id: int,
    db: Session | None = None,
    gt_points_path: str | Path | None = None,
    gt_parcels_path: str | Path | None = None,
    gt_buildings_path: str | Path | None = None,
    ai_parcels: list[Polygon] | None = None,
    ai_buildings: list[Polygon] | None = None,
    gt_points: list[Point] | None = None,
    gt_parcels: list[Polygon] | None = None,
    gt_buildings: list[Polygon] | None = None,
) -> AccuracyReport:
    """Main accuracy calculation entrypoint."""
    # 1. Resolve AI features
    if ai_parcels is None and db is not None:
        db_parcels = db.scalars(select(Parcel).where(Parcel.project_id == project_id)).all()
        ai_parcels = [to_shape(p.geom) for p in db_parcels if p.geom is not None]
    ai_parcels = ai_parcels or []

    if ai_buildings is None and db is not None:
        db_bldgs = db.scalars(select(Building).where(Building.project_id == project_id)).all()
        ai_buildings = [to_shape(b.geom) for b in db_bldgs if b.geom is not None]
    ai_buildings = ai_buildings or []

    # 2. Resolve GT points (GNSS / CORS)
    if gt_points is None and gt_points_path is not None:
        gt_points = load_point_features(gt_points_path)
    elif gt_points is None and db is not None:
        db_pts = db.scalars(select(GtPoint).where(GtPoint.project_id == project_id)).all()
        gt_points = [to_shape(pt.geom) for pt in db_pts if pt.geom is not None]
    gt_points = gt_points or []

    # 3. Resolve GT parcels
    if gt_parcels is None and gt_parcels_path is not None:
        gt_parcels = load_polygon_features(gt_parcels_path)
    gt_parcels = gt_parcels or []

    # 4. Resolve GT buildings
    if gt_buildings is None and gt_buildings_path is not None:
        gt_buildings = load_polygon_features(gt_buildings_path)
    gt_buildings = gt_buildings or []

    # 5. Compute metrics
    rmse, mean_err = compute_checkpoint_positional_error(gt_points, ai_parcels + ai_buildings)
    iou_bldgs, f1_bldgs = compute_polygon_iou_and_f1(ai_buildings, gt_buildings)
    iou_parcels, f1_parcels = compute_polygon_iou_and_f1(ai_parcels, gt_parcels)
    correct_p, merged_p, split_p = compute_cadastral_topology_counts(ai_parcels, gt_parcels)

    return AccuracyReport(
        project_id=project_id,
        rmse_horizontal_m=rmse,
        mean_horizontal_error_m=mean_err,
        iou_buildings=iou_bldgs,
        f1_buildings=f1_bldgs,
        iou_parcels=iou_parcels,
        f1_parcels=f1_parcels,
        correct_parcels=correct_p,
        merged_parcels=merged_p,
        split_parcels=split_p,
        disclaimer="Preliminary — subject to field verification",
    )
