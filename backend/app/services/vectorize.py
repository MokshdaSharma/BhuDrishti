"""Vectorization service for ParcelAI (Section 7.4).

Responsibilities:
- Building Footprint Extraction:
  - Threshold probability raster -> rasterio.features.shapes -> minimum area filter
  - Geometry regularization: snap to dominant orientation / minimum rotated rectangle when rectangularity is high
  - Per-building confidence estimation
- Road Network Extraction:
  - Polygon corridor extraction -> skeletonization via skimage.morphology.skeletonize
  - Graph construction via networkx -> spur pruning (remove dead-end branches < threshold)
  - Centerline LineString extraction and road width estimation
- Land-Use Polygon Extraction:
  - Multi-class argmax across 6 probability bands -> polygonization -> area filtering
  - Per-polygon confidence estimation
- Output: FeatureSet containing buildings, roads, and land-use polygons.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import networkx as nx
import numpy as np
import rasterio
import shapely
import skimage.morphology
from rasterio import features
from scipy import ndimage
from shapely.geometry import LineString, MultiLineString, MultiPolygon, Polygon, mapping, shape
from shapely.ops import linemerge

from app.core.errors import ParcelAIError
from app.models.db_models import LanduseClass
from app.services.inference import ProbRasters


@dataclass
class BuildingFeature:
    """Extracted building polygon feature with confidence."""

    geom: Polygon
    confidence: float
    area_m2: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "geom": mapping(self.geom),
            "confidence": round(self.confidence, 4),
            "area_m2": round(self.area_m2, 2),
        }


@dataclass
class RoadFeature:
    """Extracted road corridor polygon with centerline and estimated width."""

    geom: Polygon | MultiPolygon
    centerline: LineString | MultiLineString | None
    width_m: float
    confidence: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "geom": mapping(self.geom),
            "centerline": mapping(self.centerline) if self.centerline else None,
            "width_m": round(self.width_m, 2),
            "confidence": round(self.confidence, 4),
        }


@dataclass
class LandUseFeature:
    """Extracted land-use polygon with classification."""

    geom: Polygon | MultiPolygon
    landuse_class: LanduseClass
    confidence: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "geom": mapping(self.geom),
            "landuse_class": self.landuse_class.value,
            "confidence": round(self.confidence, 4),
        }


@dataclass
class FeatureSet:
    """Complete set of vectorized features for a project."""

    project_id: int
    buildings: list[BuildingFeature]
    roads: list[RoadFeature]
    landuse: list[LandUseFeature]

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "buildings": [b.to_dict() for b in self.buildings],
            "roads": [r.to_dict() for r in self.roads],
            "landuse": [lu.to_dict() for lu in self.landuse],
            "summary": {
                "building_count": len(self.buildings),
                "road_count": len(self.roads),
                "landuse_count": len(self.landuse),
                "total_built_up_area_m2": sum(b.area_m2 for b in self.buildings),
            },
        }


def _compute_mean_confidence(
    poly: Polygon | MultiPolygon,
    prob_array: np.ndarray,
    transform: rasterio.Affine,
) -> float:
    """Calculate mean raster probability within a Shapely geometry."""
    try:
        mask = features.geometry_mask(
            [poly],
            out_shape=prob_array.shape,
            transform=transform,
            invert=True,
            all_touched=False,
        )
        if not np.any(mask):
            # Fallback to all_touched=True if polygon is small
            mask = features.geometry_mask(
                [poly],
                out_shape=prob_array.shape,
                transform=transform,
                invert=True,
                all_touched=True,
            )
        if np.any(mask):
            return float(np.mean(prob_array[mask]))
        return 0.5
    except Exception:
        return 0.5


def _regularize_building_geometry(poly: Polygon, rectangularity_thresh: float = 0.82) -> Polygon:
    """Regularize building footprint.

    If the polygon has high rectangularity (area / min_rotated_rect_area >= threshold),
    snap to its minimum rotated rectangle. Otherwise, apply topology-preserving simplification.
    """
    if not poly.is_valid:
        poly = shapely.make_valid(poly)
        if isinstance(poly, MultiPolygon):
            poly = max(poly.geoms, key=lambda p: p.area)
        elif not isinstance(poly, Polygon):
            return poly

    area = poly.area
    if area <= 0:
        return poly

    mrr = poly.minimum_rotated_rectangle
    mrr_area = mrr.area

    if mrr_area > 0:
        rectangularity = area / mrr_area
        if rectangularity >= rectangularity_thresh:
            return mrr

    # Douglas-Peucker simplification preserving right angles / shape
    simplified = poly.simplify(tolerance=0.25, preserve_topology=True)
    return simplified if simplified.is_valid and simplified.area > 0 else poly


def extract_buildings(
    prob_path: str | Path,
    threshold: float = 0.5,
    min_area_m2: float = 10.0,
    regularize: bool = True,
) -> list[BuildingFeature]:
    """Extract and regularize building footprint polygons from probability COG."""
    with rasterio.open(prob_path) as src:
        prob = src.read(1).astype(np.float32)
        transform = src.transform

    binary = (prob >= threshold).astype(np.uint8)
    # Morphological cleanup
    binary = ndimage.binary_opening(binary, structure=np.ones((3, 3))).astype(np.uint8)
    binary = ndimage.binary_closing(binary, structure=np.ones((3, 3))).astype(np.uint8)

    buildings: list[BuildingFeature] = []

    for geom_dict, val in features.shapes(binary, mask=(binary == 1), transform=transform):
        if val != 1:
            continue
        geom = shape(geom_dict)
        if not geom.is_valid:
            geom = shapely.make_valid(geom)

        polys: list[Polygon] = []
        if isinstance(geom, Polygon):
            polys = [geom]
        elif isinstance(geom, MultiPolygon):
            polys = list(geom.geoms)

        for p in polys:
            if p.area < min_area_m2:
                continue

            clean_p = _regularize_building_geometry(p) if regularize else p
            conf = _compute_mean_confidence(clean_p, prob, transform)

            buildings.append(
                BuildingFeature(
                    geom=clean_p,
                    confidence=conf,
                    area_m2=clean_p.area,
                )
            )

    return buildings


def _extract_centerline_from_skeleton(
    skeleton: np.ndarray,
    transform: rasterio.Affine,
    min_spur_length_px: int = 6,
) -> LineString | MultiLineString | None:
    """Convert a 2D binary skeleton into a networkx graph, prune dead-end spurs, and return LineStrings."""
    rows, cols = np.where(skeleton > 0)
    if len(rows) == 0:
        return None

    # Build 8-connected planar graph of skeleton pixels
    graph = nx.Graph()
    pixel_set = set(zip(rows, cols, strict=False))

    for r, c in pixel_set:
        graph.add_node((r, c))
        for dr in [-1, 0, 1]:
            for dc in [-1, 0, 1]:
                if dr == 0 and dc == 0:
                    continue
                neighbor = (r + dr, c + dc)
                if neighbor in pixel_set and not graph.has_edge((r, c), neighbor):
                    graph.add_edge((r, c), neighbor)

    # Spur pruning: prune short terminal branches of degree 1
    modified = True
    while modified:
        modified = False
        leaf_nodes = [node for node, deg in graph.degree() if deg == 1]
        for leaf in leaf_nodes:
            if leaf not in graph:
                continue
            # Traverse branch from leaf until degree != 2
            path = [leaf]
            curr = leaf
            prev = None
            while True:
                neighbors = [n for n in graph.neighbors(curr) if n != prev]
                if len(neighbors) != 1:
                    break
                prev = curr
                curr = neighbors[0]
                path.append(curr)
                if graph.degree(curr) != 2:
                    break

            if len(path) <= min_spur_length_px and graph.degree(path[-1]) > 2:
                # Remove spur pixels excluding junction
                graph.remove_nodes_from(path[:-1])
                modified = True

    if graph.number_of_nodes() < 2:
        return None

    # Extract continuous line paths
    lines: list[LineString] = []

    for comp in nx.connected_components(graph):
        sub = graph.subgraph(comp)
        # Find nodes with degree != 2 (endpoints or junctions)
        endpoints = [n for n, deg in sub.degree() if deg != 2]

        if not endpoints and sub.number_of_nodes() >= 3:
            # Simple cycle
            cycle_nodes = list(nx.dfs_preorder_nodes(sub))
            coords = [transform * (c + 0.5, r + 0.5) for r, c in cycle_nodes]
            coords.append(coords[0])
            if len(coords) >= 2:
                lines.append(LineString(coords))
            continue

        visited_edges = set()
        for ep in endpoints:
            for neighbor in sub.neighbors(ep):
                edge_key = tuple(sorted([ep, neighbor]))
                if edge_key in visited_edges:
                    continue

                # Trace path until next non-2-degree node or end
                path = [ep, neighbor]
                visited_edges.add(edge_key)
                curr = neighbor
                prev = ep

                while sub.degree(curr) == 2:
                    next_nodes = [n for n in sub.neighbors(curr) if n != prev]
                    if not next_nodes:
                        break
                    nxt = next_nodes[0]
                    visited_edges.add(tuple(sorted([curr, nxt])))
                    prev = curr
                    curr = nxt
                    path.append(curr)

                if len(path) >= 2:
                    geo_coords = [
                        (
                            transform.c + (c + 0.5) * transform.a + (r + 0.5) * transform.b,
                            transform.f + (c + 0.5) * transform.d + (r + 0.5) * transform.e,
                        )
                        for r, c in path
                    ]
                    lines.append(LineString(geo_coords))

    if not lines:
        return None

    merged = linemerge(lines) if len(lines) > 1 else lines[0]
    if isinstance(merged, (LineString, MultiLineString)):
        return merged
    return MultiLineString(lines)


def extract_roads(
    prob_path: str | Path,
    threshold: float = 0.4,
    min_area_m2: float = 20.0,
    min_spur_length_px: int = 8,
) -> list[RoadFeature]:
    """Extract road polygons and calculate pruned skeleton centerlines and widths."""
    with rasterio.open(prob_path) as src:
        prob = src.read(1).astype(np.float32)
        transform = src.transform

    binary = (prob >= threshold).astype(np.uint8)
    binary = ndimage.binary_opening(binary, structure=np.ones((3, 3))).astype(np.uint8)

    # Skeletonize road network
    skeleton = skimage.morphology.skeletonize(binary > 0).astype(np.uint8)

    roads: list[RoadFeature] = []

    for geom_dict, val in features.shapes(binary, mask=(binary == 1), transform=transform):
        if val != 1:
            continue
        geom = shape(geom_dict)
        if not geom.is_valid:
            geom = shapely.make_valid(geom)

        if geom.area < min_area_m2:
            continue

        # Extract local skeleton within this polygon
        try:
            poly_mask = features.geometry_mask(
                [geom],
                out_shape=skeleton.shape,
                transform=transform,
                invert=True,
                all_touched=True,
            )
            local_skel = np.where(poly_mask, skeleton, 0)
            centerline = _extract_centerline_from_skeleton(local_skel, transform, min_spur_length_px)
        except Exception:
            centerline = None

        # Estimate average road width: W = Area / Length
        if centerline and centerline.length > 0:
            width_m = float(geom.area / max(1.0, centerline.length))
        else:
            # Fallback estimation using equivalent rectangular corridor
            width_m = float(np.sqrt(max(1.0, geom.area)) * 0.4)

        conf = _compute_mean_confidence(geom, prob, transform)

        roads.append(
            RoadFeature(
                geom=geom,
                centerline=centerline,
                width_m=width_m,
                confidence=conf,
            )
        )

    return roads


def extract_landuse(
    prob_path: str | Path,
    min_area_m2: float = 25.0,
) -> list[LandUseFeature]:
    """Extract land-use polygons by multi-class argmax across 6 probability bands."""
    with rasterio.open(prob_path) as src:
        prob_stack = src.read().astype(np.float32)  # (6, H, W)
        transform = src.transform

    # Class index map (Section 6)
    class_map = {
        0: LanduseClass.built_up,
        1: LanduseClass.road,
        2: LanduseClass.vegetation,
        3: LanduseClass.water,
        4: LanduseClass.open_land,
        5: LanduseClass.other,
    }

    argmax_map = np.argmax(prob_stack, axis=0).astype(np.int16)
    landuse_features: list[LandUseFeature] = []

    for geom_dict, class_idx in features.shapes(argmax_map, transform=transform):
        class_idx = int(class_idx)
        lu_class = class_map.get(class_idx, LanduseClass.other)
        geom = shape(geom_dict)

        if not geom.is_valid:
            geom = shapely.make_valid(geom)

        if geom.area < min_area_m2:
            continue

        # Smooth polygon boundaries slightly
        smoothed = geom.simplify(tolerance=0.3, preserve_topology=True)
        if not smoothed.is_valid or smoothed.area <= 0:
            smoothed = geom

        conf = _compute_mean_confidence(smoothed, prob_stack[class_idx], transform)

        landuse_features.append(
            LandUseFeature(
                geom=smoothed,
                landuse_class=lu_class,
                confidence=conf,
            )
        )

    return landuse_features


def extract_features(
    project_id: int,
    probs: ProbRasters,
    min_building_area: float = 10.0,
    min_road_area: float = 20.0,
    min_landuse_area: float = 25.0,
) -> FeatureSet:
    """Main vectorization entrypoint: extracts buildings, roads, and land-use polygons."""
    bldg_p = Path(probs.building_cog)
    road_p = Path(probs.road_cog)
    lu_p = Path(probs.landuse_cog)

    if not bldg_p.exists() or not road_p.exists() or not lu_p.exists():
        raise ParcelAIError(f"One or more probability rasters not found for project {project_id}")

    buildings = extract_buildings(bldg_p, min_area_m2=min_building_area, regularize=True)
    roads = extract_roads(road_p, min_area_m2=min_road_area)
    landuse = extract_landuse(lu_p, min_area_m2=min_landuse_area)

    return FeatureSet(
        project_id=project_id,
        buildings=buildings,
        roads=roads,
        landuse=landuse,
    )
