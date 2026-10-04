"""Hybrid parcel builder service for ParcelAI (Section 7.5).

Algorithm:
1. Barrier raster from boundary probability + road polygons.
2. Watershed (skimage.segmentation.watershed) seeded by building clusters -> candidate regions.
3. Linework (predicted boundary edges, road edges) -> shapely.polygonize faces.
4. Reconcile: prefer polygonize faces containing exactly one building cluster; else watershed regions.
5. Rules:
   - A parcel must not cut through a building (merge regions bisecting buildings).
   - Merge tiny fragments into the neighbor with the longest shared edge.
   - Parcels should touch a road/access corridor where possible.
   - Configurable minimum area.
6. Snap edges (shapely.snap) and enforce shared vertices between neighbors.
7. Confidence = 0.5 * mean boundary prob along edges + 0.2 * shape regularity
                + 0.15 * building containment + 0.15 * IoU with existing layer (if present).
8. Return ParcelSet with final parcels and debug GeoJSON layers.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
import skimage.morphology
from rasterio import features
from scipy import ndimage
from shapely.geometry import MultiPolygon, Point, Polygon, mapping, shape
from shapely.ops import polygonize, snap, unary_union
from skimage.segmentation import watershed

from app.core.errors import ParcelAIError
from app.models.db_models import Parcel, ParcelSource, ParcelStatus
from app.services.inference import ProbRasters
from app.services.vectorize import FeatureSet


@dataclass
class ParcelFeature:
    """Extracted cadastral parcel feature with confidence and LADM attributes."""

    geom: Polygon
    confidence: float
    area_m2: float
    buildings_count: int = 0
    touches_road: bool = False
    ladm_attrs: dict[str, Any] = field(default_factory=dict)
    source: ParcelSource = ParcelSource.ai
    status: ParcelStatus = ParcelStatus.draft

    def to_dict(self) -> dict[str, Any]:
        return {
            "geom": mapping(self.geom),
            "confidence": round(self.confidence, 4),
            "area_m2": round(self.area_m2, 2),
            "buildings_count": self.buildings_count,
            "touches_road": self.touches_road,
            "ladm_attrs": self.ladm_attrs,
            "source": self.source.value,
            "status": self.status.value,
        }


@dataclass
class ParcelSet:
    """Collection of parcel features for a project with debug layers."""

    project_id: int
    parcels: list[ParcelFeature]
    debug_layers: dict[str, Any] = field(default_factory=dict)

    @property
    def count(self) -> int:
        return len(self.parcels)

    @property
    def total_area_m2(self) -> float:
        return sum(p.area_m2 for p in self.parcels)

    @property
    def mean_confidence(self) -> float:
        if not self.parcels:
            return 0.0
        return float(np.mean([p.confidence for p in self.parcels]))

    def to_geojson(self) -> dict[str, Any]:
        return {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "id": idx + 1,
                    "geometry": mapping(p.geom),
                    "properties": {
                        "parcel_id": idx + 1,
                        "confidence": round(p.confidence, 4),
                        "area_m2": round(p.area_m2, 2),
                        "buildings_count": p.buildings_count,
                        "touches_road": p.touches_road,
                        "source": p.source.value,
                        "status": p.status.value,
                        "ladm_attrs": p.ladm_attrs,
                    },
                }
                for idx, p in enumerate(self.parcels)
            ],
        }


def _create_barrier_raster(
    boundary_prob: np.ndarray,
    road_geoms: list[Polygon | MultiPolygon],
    transform: rasterio.Affine,
    shape_hw: tuple[int, int],
    boundary_threshold: float = 0.35,
) -> tuple[np.ndarray, np.ndarray]:
    """Create barrier surface from boundary probability and road corridors."""
    h, w = shape_hw
    road_mask = np.zeros((h, w), dtype=np.uint8)

    valid_roads = [r for r in road_geoms if r.is_valid and not r.is_empty]
    if valid_roads:
        shapes = [(geom, 1) for geom in valid_roads]
        road_mask = features.rasterize(
            shapes,
            out_shape=(h, w),
            transform=transform,
            fill=0,
            dtype=np.uint8,
        )

    # Barrier intensity: high boundary probability or road pixels
    barrier = np.clip(boundary_prob, 0.0, 1.0)
    barrier[road_mask == 1] = 1.0

    # Binary barrier for linework
    binary_barrier = ((boundary_prob >= boundary_threshold) | (road_mask == 1)).astype(np.uint8)

    return barrier, binary_barrier


def _create_watershed_markers(
    building_geoms: list[Polygon],
    barrier_raster: np.ndarray,
    transform: rasterio.Affine,
    shape_hw: tuple[int, int],
    min_open_dist_px: int = 40,
) -> tuple[np.ndarray, list[Point]]:
    """Generate seed markers for watershed from building footprints and open space minima."""
    h, w = shape_hw
    marker_raster = np.zeros((h, w), dtype=np.int32)
    seed_points: list[Point] = []
    marker_id = 1

    # 1. Building seeds
    for bldg in building_geoms:
        if not bldg.is_valid or bldg.is_empty:
            continue
        # Rasterize this building
        bldg_mask = features.rasterize(
            [(bldg, 1)],
            out_shape=(h, w),
            transform=transform,
            fill=0,
            dtype=np.uint8,
        )
        if np.any(bldg_mask):
            marker_raster[bldg_mask == 1] = marker_id
            centroid = bldg.centroid
            seed_points.append(centroid)
            marker_id += 1

    # 2. Open space seeds: areas with low barrier and far from existing markers
    if np.any(marker_raster > 0):
        dist_to_markers = ndimage.distance_transform_edt(marker_raster == 0)
    else:
        dist_to_markers = np.ones((h, w), dtype=np.float32) * min_open_dist_px

    open_candidate_mask = (dist_to_markers >= min_open_dist_px) & (barrier_raster < 0.3)
    labeled_open, num_open = ndimage.label(open_candidate_mask)

    for i in range(1, num_open + 1):
        ys, xs = np.where(labeled_open == i)
        if len(ys) > 50:  # Minimum pixel cluster for open space seed
            cy, cx = int(np.median(ys)), int(np.median(xs))
            marker_raster[cy, cx] = marker_id
            geo_x = transform.c + (cx + 0.5) * transform.a + (cy + 0.5) * transform.b
            geo_y = transform.f + (cx + 0.5) * transform.d + (cy + 0.5) * transform.e
            seed_points.append(Point(geo_x, geo_y))
            marker_id += 1

    # Fallback if no markers at all: grid of markers
    if marker_id == 1:
        step = max(h // 4, w // 4, 10)
        for r in range(step // 2, h, step):
            for c in range(step // 2, w, step):
                marker_raster[r, c] = marker_id
                geo_x = transform.c + (c + 0.5) * transform.a + (r + 0.5) * transform.b
                geo_y = transform.f + (c + 0.5) * transform.d + (r + 0.5) * transform.e
                seed_points.append(Point(geo_x, geo_y))
                marker_id += 1

    return marker_raster, seed_points


def _run_watershed_parcels(
    barrier_raster: np.ndarray,
    markers: np.ndarray,
    transform: rasterio.Affine,
    min_area_m2: float = 15.0,
) -> list[Polygon]:
    """Segment image into candidate parcels via marker-controlled watershed."""
    # Watershed on gradient/barrier surface
    ws_labels = watershed(barrier_raster, markers=markers, compactness=0.01)

    candidate_polys: list[Polygon] = []
    # Vectorize watershed regions
    for geom_dict, val in features.shapes(ws_labels.astype(np.int32), transform=transform):
        if val <= 0:
            continue
        poly = shape(geom_dict)
        if not poly.is_valid:
            poly = poly.buffer(0)
        if isinstance(poly, Polygon) and poly.area >= min_area_m2:
            candidate_polys.append(poly)
        elif isinstance(poly, MultiPolygon):
            for part in poly.geoms:
                if part.is_valid and part.area >= min_area_m2:
                    candidate_polys.append(part)

    return candidate_polys


def _extract_linework_faces(
    binary_barrier: np.ndarray,
    road_geoms: list[Polygon | MultiPolygon],
    transform: rasterio.Affine,
    bounds: tuple[float, float, float, float],
    min_area_m2: float = 15.0,
) -> list[Polygon]:
    """Polygonize thin boundary and road edges into planar topological faces."""
    minx, miny, maxx, maxy = bounds
    lines = []

    # 1. Boundary raster linework
    skel = skimage.morphology.skeletonize(binary_barrier > 0)
    for geom_dict, val in features.shapes(skel.astype(np.uint8), transform=transform):
        if val == 1:
            poly = shape(geom_dict)
            if poly.is_valid and not poly.is_empty:
                boundary = poly.boundary
                if not boundary.is_empty:
                    lines.append(boundary)

    # 2. Road boundaries
    for road in road_geoms:
        if road.is_valid and not road.is_empty:
            lines.append(road.boundary)

    # 3. Outer bounding box lines to close exterior faces
    bbox_poly = Polygon([(minx, miny), (maxx, miny), (maxx, maxy), (minx, maxy)])
    lines.append(bbox_poly.boundary)

    if not lines:
        return []

    try:
        merged_lines = unary_union(lines)
        faces = list(polygonize(merged_lines))
        valid_faces = [
            f
            for f in faces
            if f.is_valid and f.area >= min_area_m2 and bbox_poly.contains(f.centroid)
        ]
        return valid_faces
    except Exception:
        return []


def _reconcile_faces_and_watershed(
    watershed_polys: list[Polygon],
    linework_faces: list[Polygon],
    building_geoms: list[Polygon],
    road_union: Any,
    min_area_m2: float = 15.0,
) -> list[Polygon]:
    """Reconcile watershed regions and linework faces: prefer single-building faces, else watershed."""
    reconciled: list[Polygon] = []

    # Filter linework faces that contain exactly 1 building cluster
    good_faces: list[Polygon] = []
    for face in linework_faces:
        if not face.is_valid or face.area < min_area_m2:
            continue
        # Count buildings inside face
        contained_bldgs = sum(
            1 for b in building_geoms if face.contains(b.centroid) or face.intersection(b).area > 0.5 * b.area
        )
        if contained_bldgs == 1:
            good_faces.append(face)

    # If good linework faces cover significant area, use them; else fallback to watershed
    if good_faces:
        good_union = unary_union(good_faces)
        for face in good_faces:
            reconciled.append(face)

        # For remaining watershed areas not covered by good faces, add them
        for ws in watershed_polys:
            if not ws.is_valid or ws.area < min_area_m2:
                continue
            if not good_union.intersects(ws) or ws.difference(good_union).area > min_area_m2:
                diff = ws.difference(good_union)
                if isinstance(diff, Polygon) and diff.area >= min_area_m2:
                    reconciled.append(diff)
                elif isinstance(diff, MultiPolygon):
                    for part in diff.geoms:
                        if part.area >= min_area_m2:
                            reconciled.append(part)
    else:
        reconciled = [ws for ws in watershed_polys if ws.is_valid and ws.area >= min_area_m2]

    # Subtract road corridors from candidate parcels
    if road_union is not None and not road_union.is_empty:
        cleaned: list[Polygon] = []
        for poly in reconciled:
            try:
                sub = poly.difference(road_union)
                if isinstance(sub, Polygon) and sub.area >= min_area_m2:
                    cleaned.append(sub)
                elif isinstance(sub, MultiPolygon):
                    for part in sub.geoms:
                        if part.area >= min_area_m2:
                            cleaned.append(part)
            except Exception:
                cleaned.append(poly)
        reconciled = cleaned

    return reconciled


def _enforce_no_building_bisection(
    parcels: list[Polygon],
    building_geoms: list[Polygon],
) -> list[Polygon]:
    """Rule: A parcel must not cut through a building. Merge parcels sharing a bisected building."""
    if not parcels or not building_geoms:
        return parcels

    merged_parcels = list(parcels)

    for bldg in building_geoms:
        if not bldg.is_valid or bldg.is_empty:
            continue

        # Find all parcels that significantly intersect this building
        intersecting_indices = []
        for idx, p in enumerate(merged_parcels):
            if p.is_valid and p.intersects(bldg):
                inter_area = p.intersection(bldg).area
                if inter_area > 0.05 * bldg.area:
                    intersecting_indices.append(idx)

        if len(intersecting_indices) > 1:
            # Building is bisected by multiple parcels -> union them
            polys_to_merge = [merged_parcels[i] for i in intersecting_indices]
            merged_poly = unary_union(polys_to_merge)
            if not merged_poly.is_valid:
                merged_poly = merged_poly.buffer(0)

            # Keep merged poly and remove individual merged components
            remaining = [p for i, p in enumerate(merged_parcels) if i not in intersecting_indices]
            if isinstance(merged_poly, Polygon):
                remaining.append(merged_poly)
            elif isinstance(merged_poly, MultiPolygon):
                remaining.extend([part for part in merged_poly.geoms if part.is_valid])
            merged_parcels = remaining

    return merged_parcels


def _merge_sliver_fragments(
    parcels: list[Polygon],
    min_area_m2: float = 20.0,
) -> list[Polygon]:
    """Rule: Merge tiny fragments (< min_area_m2) into neighbor sharing longest edge."""
    if len(parcels) <= 1:
        return parcels

    active_parcels = [p for p in parcels if p.is_valid and p.area > 0]
    max_iterations = 10
    iteration = 0

    while iteration < max_iterations:
        iteration += 1
        slivers = [p for p in active_parcels if p.area < min_area_m2]
        if not slivers:
            break

        sliver = slivers[0]
        active_parcels.remove(sliver)

        best_neighbor_idx = -1
        max_shared_edge = -1.0

        for idx, neighbor in enumerate(active_parcels):
            if neighbor.intersects(sliver):
                try:
                    shared = neighbor.intersection(sliver)
                    shared_length = shared.length
                    if shared_length > max_shared_edge:
                        max_shared_edge = shared_length
                        best_neighbor_idx = idx
                except Exception:
                    continue

        if best_neighbor_idx >= 0:
            target = active_parcels[best_neighbor_idx]
            merged = unary_union([target, sliver])
            if not merged.is_valid:
                merged = merged.buffer(0)
            if isinstance(merged, Polygon):
                active_parcels[best_neighbor_idx] = merged
            elif isinstance(merged, MultiPolygon):
                active_parcels.pop(best_neighbor_idx)
                active_parcels.extend([p for p in merged.geoms if p.is_valid])
        else:
            # Isolated small parcel with no shared boundary -> re-insert if area > 0.5 * min_area
            if sliver.area >= min_area_m2 * 0.5:
                active_parcels.append(sliver)

    return [p for p in active_parcels if p.is_valid and p.area >= min_area_m2 * 0.5]


def _snap_parcel_neighbors(
    parcels: list[Polygon],
    tolerance: float = 0.1,
) -> list[Polygon]:
    """Snap adjacent parcel boundaries to enforce shared vertices and eliminate gaps/overlaps."""
    if len(parcels) <= 1:
        return parcels

    snapped = list(parcels)
    for i in range(len(snapped)):
        for j in range(i + 1, len(snapped)):
            p1 = snapped[i]
            p2 = snapped[j]
            if p1.distance(p2) <= tolerance:
                try:
                    p1_snapped = snap(p1, p2, tolerance)
                    p2_snapped = snap(p2, p1_snapped, tolerance)
                    if p1_snapped.is_valid and p1_snapped.area > 0:
                        snapped[i] = p1_snapped
                    if p2_snapped.is_valid and p2_snapped.area > 0:
                        snapped[j] = p2_snapped
                except Exception:
                    continue

    return [p for p in snapped if p.is_valid and p.area > 0]


def _compute_boundary_edge_confidence(
    geom: Polygon,
    boundary_prob: np.ndarray,
    transform: rasterio.Affine,
) -> float:
    """Sample boundary probability along parcel perimeter."""
    boundary = geom.boundary
    if boundary.is_empty:
        return 0.5

    h, w = boundary_prob.shape
    # Sample points along perimeter
    length = boundary.length
    num_samples = max(int(length / 2.0), 10)  # 1 sample every 2m
    distances = np.linspace(0, length, num_samples, endpoint=False)

    sampled_probs = []
    inv_transform = ~transform

    for dist in distances:
        pt = boundary.interpolate(dist)
        col = inv_transform.c + pt.x * inv_transform.a + pt.y * inv_transform.b
        row = inv_transform.f + pt.x * inv_transform.d + pt.y * inv_transform.e
        c, r = int(round(col)), int(round(row))
        if 0 <= r < h and 0 <= c < w:
            sampled_probs.append(float(boundary_prob[r, c]))

    if not sampled_probs:
        return 0.5
    return float(np.mean(sampled_probs))


def _compute_shape_regularity(geom: Polygon) -> float:
    """Calculate shape compactness / isoperimetric quotient = 4 * pi * Area / Perimeter^2."""
    area = geom.area
    perimeter = geom.length
    if perimeter <= 0 or area <= 0:
        return 0.0

    # Isoperimetric quotient (circle = 1.0, square = pi/4 ~ 0.785, elongated < 0.3)
    iq = (4.0 * math.pi * area) / (perimeter * perimeter)
    return float(np.clip(iq, 0.0, 1.0))


def _compute_building_containment_score(
    geom: Polygon,
    building_geoms: list[Polygon],
) -> tuple[float, int]:
    """Check building containment consistency: returns (score, contained_building_count)."""
    contained_count = 0
    bisected = False

    for b in building_geoms:
        if not b.is_valid or b.is_empty:
            continue
        if geom.contains(b):
            contained_count += 1
        elif geom.intersects(b):
            inter_area = geom.intersection(b).area
            if inter_area > 0.05 * b.area:
                if inter_area >= 0.90 * b.area:
                    contained_count += 1
                else:
                    bisected = True

    if bisected:
        score = 0.3
    elif contained_count >= 1:
        score = 1.0
    else:
        score = 0.75  # Clean open parcel with no buildings

    return score, contained_count


def _compute_existing_iou_score(
    geom: Polygon,
    existing_parcels: list[Polygon] | None,
) -> float:
    """Compute maximum IoU with any polygon in the existing reference GIS layer."""
    if not existing_parcels:
        return 0.0

    max_iou = 0.0
    for ext in existing_parcels:
        if not ext.is_valid or ext.is_empty:
            continue
        if geom.intersects(ext):
            inter = geom.intersection(ext).area
            union = geom.union(ext).area
            if union > 0:
                iou = inter / union
                if iou > max_iou:
                    max_iou = iou

    return float(np.clip(max_iou, 0.0, 1.0))


def _compute_parcel_confidence(
    geom: Polygon,
    boundary_prob: np.ndarray,
    transform: rasterio.Affine,
    building_geoms: list[Polygon],
    existing_parcels: list[Polygon] | None,
) -> tuple[float, int]:
    """Calculate multi-factor confidence score for a parcel."""
    c_boundary = _compute_boundary_edge_confidence(geom, boundary_prob, transform)
    c_regularity = _compute_shape_regularity(geom)
    c_containment, bldg_count = _compute_building_containment_score(geom, building_geoms)

    if existing_parcels:
        c_existing = _compute_existing_iou_score(geom, existing_parcels)
        conf = (
            0.50 * c_boundary
            + 0.20 * c_regularity
            + 0.15 * c_containment
            + 0.15 * c_existing
        )
    else:
        conf = (
            0.55 * c_boundary
            + 0.25 * c_regularity
            + 0.20 * c_containment
        )

    return float(np.clip(conf, 0.05, 0.99)), bldg_count


def build_parcels(
    project_id: int,
    probs: ProbRasters,
    features_set: FeatureSet,
    existing_parcels: list[Polygon] | None = None,
    min_parcel_area: float = 20.0,
    snap_tolerance: float = 0.1,
    boundary_threshold: float = 0.35,
    db_session: Any | None = None,
) -> ParcelSet:
    """Main entrypoint for hybrid parcel builder (Section 7.5)."""
    boundary_p = Path(probs.boundary_cog)
    if not boundary_p.exists():
        raise ParcelAIError(f"Boundary probability raster not found at {boundary_p}")

    with rasterio.open(boundary_p) as src:
        boundary_prob = src.read(1).astype(np.float32)
        transform = src.transform
        shape_hw = (src.height, src.width)
        bounds = (src.bounds.left, src.bounds.bottom, src.bounds.right, src.bounds.top)

    building_geoms = [b.geom for b in features_set.buildings if b.geom.is_valid]
    road_geoms = [r.geom for r in features_set.roads if r.geom.is_valid]
    road_union = unary_union(road_geoms) if road_geoms else None

    # Step 1: Barrier surface
    barrier_raster, binary_barrier = _create_barrier_raster(
        boundary_prob, road_geoms, transform, shape_hw, boundary_threshold
    )

    # Step 2: Watershed markers
    marker_raster, seed_points = _create_watershed_markers(
        building_geoms, barrier_raster, transform, shape_hw
    )

    # Step 3: Watershed segmentation
    ws_parcels = _run_watershed_parcels(barrier_raster, marker_raster, transform, min_parcel_area)

    # Step 4: Linework faces
    linework_faces = _extract_linework_faces(
        binary_barrier, road_geoms, transform, bounds, min_parcel_area
    )

    # Step 5: Reconcile
    reconciled = _reconcile_faces_and_watershed(
        ws_parcels, linework_faces, building_geoms, road_union, min_parcel_area
    )

    # Step 6: Cadastral rules (no building bisection & merge slivers)
    non_bisected = _enforce_no_building_bisection(reconciled, building_geoms)
    merged = _merge_sliver_fragments(non_bisected, min_area_m2=min_parcel_area)

    # Step 7: Topological snapping
    snapped = _snap_parcel_neighbors(merged, tolerance=snap_tolerance)

    # Step 8: Calculate confidence and compile features
    parcel_features: list[ParcelFeature] = []
    for poly in snapped:
        if not poly.is_valid or poly.area < min_parcel_area * 0.5:
            continue

        conf, bldg_count = _compute_parcel_confidence(
            poly, boundary_prob, transform, building_geoms, existing_parcels
        )

        touches_road = False
        if road_union is not None and not road_union.is_empty:
            touches_road = poly.distance(road_union) <= 1.5

        ladm_attrs = {
            "source": "ai_hybrid_watershed",
            "version": "1.0",
            "building_count": bldg_count,
            "touches_road": touches_road,
            "regularity": round(_compute_shape_regularity(poly), 3),
        }

        parcel_features.append(
            ParcelFeature(
                geom=poly,
                confidence=conf,
                area_m2=poly.area,
                buildings_count=bldg_count,
                touches_road=touches_road,
                ladm_attrs=ladm_attrs,
                source=ParcelSource.ai,
                status=ParcelStatus.draft,
            )
        )

    # Debug layers GeoJSON
    debug_layers = {
        "seeds": [mapping(p) for p in seed_points],
        "watershed_count": len(ws_parcels),
        "linework_faces_count": len(linework_faces),
        "reconciled_count": len(reconciled),
        "final_parcels_count": len(parcel_features),
    }

    # Step 9: Database persistence if session provided
    if db_session is not None:
        try:
            from geoalchemy2.shape import from_shape

            for pf in parcel_features:
                db_parcel = Parcel(
                    project_id=project_id,
                    geom=from_shape(pf.geom, srid=32643),
                    confidence=pf.confidence,
                    source=pf.source,
                    status=pf.status,
                    area_m2=pf.area_m2,
                    ladm_attrs=pf.ladm_attrs,
                )
                db_session.add(db_parcel)
            db_session.flush()
        except Exception:
            pass

    return ParcelSet(
        project_id=project_id,
        parcels=parcel_features,
        debug_layers=debug_layers,
    )
