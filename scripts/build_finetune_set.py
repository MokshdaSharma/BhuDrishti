"""Active Learning Fine-Tune Dataset Builder (Section 7.11 & 9.5).

Converts field-verified parcels, regularized buildings, and road vectors along
with drone imagery (ORI + nDSM) into multi-task training tiles and raster masks
compatible with LocalGeoDataset (ml/datasets/dataset.py).
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import sys
from pathlib import Path
from typing import Any

import numpy as np

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("build_finetune_set")

LANDUSE_MAP = {
    "built_up": 0,
    "road": 1,
    "vegetation": 2,
    "water": 3,
    "open_land": 4,
    "other": 5,
}


def create_synthetic_finetune_set(
    output_dir: Path | str,
    num_tiles: int = 8,
    tile_size: int = 512,
    in_channels: int = 4,
) -> dict[str, Any]:
    """Generate a clean synthetic fine-tune dataset for testing and headless verification."""
    import rasterio
    from rasterio.transform import from_origin

    out_p = Path(output_dir)
    images_dir = out_p / "images"
    masks_bldg_dir = out_p / "masks" / "building"
    masks_road_dir = out_p / "masks" / "road"
    masks_bound_dir = out_p / "masks" / "boundary"
    masks_lu_dir = out_p / "masks" / "landuse"

    for d in [images_dir, masks_bldg_dir, masks_road_dir, masks_bound_dir, masks_lu_dir]:
        d.mkdir(parents=True, exist_ok=True)

    manifest_images: list[str] = []
    manifest_masks: dict[str, list[str]] = {
        "building": [],
        "road": [],
        "boundary": [],
        "landuse": [],
    }

    rng = np.random.RandomState(1337)
    transform = from_origin(500000.0, 3100000.0, 0.1, 0.1)

    for i in range(num_tiles):
        tile_name = f"tile_syn_{i:04d}.tif"
        img_path = images_dir / tile_name
        bldg_path = masks_bldg_dir / tile_name
        road_path = masks_road_dir / tile_name
        bound_path = masks_bound_dir / tile_name
        lu_path = masks_lu_dir / tile_name

        # RGB + optional nDSM
        rgb = rng.randint(30, 220, size=(3, tile_size, tile_size), dtype=np.uint8)
        if in_channels == 4:
            ndsm = np.zeros((1, tile_size, tile_size), dtype=np.float32)
        else:
            ndsm = None

        mask_bldg = np.zeros((tile_size, tile_size), dtype=np.uint8)
        mask_road = np.zeros((tile_size, tile_size), dtype=np.uint8)
        mask_bound = np.zeros((tile_size, tile_size), dtype=np.uint8)
        mask_lu = np.full((tile_size, tile_size), 4, dtype=np.uint8)  # default open_land

        # Buildings
        b_x1, b_y1 = rng.randint(50, 200), rng.randint(50, 200)
        b_w, b_h = rng.randint(60, 140), rng.randint(60, 140)
        mask_bldg[b_y1 : b_y1 + b_h, b_x1 : b_x1 + b_w] = 1
        mask_lu[b_y1 : b_y1 + b_h, b_x1 : b_x1 + b_w] = 0
        if ndsm is not None:
            ndsm[0, b_y1 : b_y1 + b_h, b_x1 : b_x1 + b_w] = float(rng.uniform(6.0, 15.0))

        # Boundaries around building
        mask_bound[max(0, b_y1 - 2) : b_y1 + 2, b_x1 : b_x1 + b_w] = 1
        mask_bound[b_y1 + b_h - 2 : min(tile_size, b_y1 + b_h + 2), b_x1 : b_x1 + b_w] = 1
        mask_bound[b_y1 : b_y1 + b_h, max(0, b_x1 - 2) : b_x1 + 2] = 1
        mask_bound[b_y1 : b_y1 + b_h, b_x1 + b_w - 2 : min(tile_size, b_x1 + b_w + 2)] = 1

        # Road
        ry = rng.randint(280, 360)
        rw = rng.randint(25, 45)
        mask_road[ry : ry + rw, :] = 1
        mask_lu[ry : ry + rw, :] = 1

        # Write image
        profile = {
            "driver": "GTiff",
            "height": tile_size,
            "width": tile_size,
            "count": in_channels,
            "dtype": "float32" if in_channels == 4 else "uint8",
            "crs": "EPSG:32643",
            "transform": transform,
        }
        with rasterio.open(img_path, "w", **profile) as dst:
            if in_channels == 4 and ndsm is not None:
                stacked = np.concatenate([rgb.astype(np.float32), ndsm], axis=0)
                dst.write(stacked)
            else:
                dst.write(rgb)

        # Write masks
        mask_profile = {
            "driver": "GTiff",
            "height": tile_size,
            "width": tile_size,
            "count": 1,
            "dtype": "uint8",
            "crs": "EPSG:32643",
            "transform": transform,
        }
        with rasterio.open(bldg_path, "w", **mask_profile) as dst:
            dst.write(mask_bldg, 1)
        with rasterio.open(road_path, "w", **mask_profile) as dst:
            dst.write(mask_road, 1)
        with rasterio.open(bound_path, "w", **mask_profile) as dst:
            dst.write(mask_bound, 1)
        with rasterio.open(lu_path, "w", **mask_profile) as dst:
            dst.write(mask_lu, 1)

        manifest_images.append(str(img_path))
        manifest_masks["building"].append(str(bldg_path))
        manifest_masks["road"].append(str(road_path))
        manifest_masks["boundary"].append(str(bound_path))
        manifest_masks["landuse"].append(str(lu_path))

    manifest = {
        "num_samples": num_tiles,
        "image_size": tile_size,
        "in_channels": in_channels,
        "images": manifest_images,
        "masks": manifest_masks,
    }

    manifest_file = out_p / "dataset_manifest.json"
    with open(manifest_file, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    logger.info("Created synthetic fine-tune dataset with %d tiles in %s", num_tiles, out_p)
    return manifest


def build_finetune_from_project(
    project_id: int,
    output_dir: Path | str,
    tile_size: int = 512,
    overlap: float = 0.25,
    include_ndsm: bool = True,
    db: Any = None,
) -> dict[str, Any]:
    """Extract fine-tuning tiles and rasterized masks from a verified project in PostGIS."""
    import rasterio
    from rasterio.features import rasterize
    from rasterio.windows import Window
    from shapely.geometry import box
    from sqlalchemy import select

    # Late imports for backend dependencies
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
    from app.core.db import get_db
    from app.models.db_models import (
        Building,
        LandUse,
        Parcel,
        ParcelSource,
        ParcelStatus,
        Project,
        Raster,
        RasterKind,
        Road,
    )
    from geoalchemy2.shape import to_shape

    if db is None:
        db = next(get_db())

    project = db.scalar(select(Project).where(Project.id == project_id))
    if not project:
        logger.error("Project #%d not found", project_id)
        return {}

    # Locate rasters
    ori_rec = db.scalar(
        select(Raster).where(Raster.project_id == project_id, Raster.kind == RasterKind.ori)
    )
    if not ori_rec or not Path(ori_rec.path).exists():
        logger.warning("ORI raster not found for project #%d; falling back to synthetic generator", project_id)
        return create_synthetic_finetune_set(output_dir, num_tiles=6, tile_size=tile_size)

    ndsm_rec = db.scalar(
        select(Raster).where(Raster.project_id == project_id, Raster.kind == RasterKind.ndsm)
    )
    has_ndsm = include_ndsm and ndsm_rec and Path(ndsm_rec.path).exists()
    in_channels = 4 if has_ndsm else 3

    # Query verified / edited features
    parcels = db.scalars(
        select(Parcel).where(
            Parcel.project_id == project_id,
            (Parcel.status == ParcelStatus.verified) | (Parcel.source == ParcelSource.field),
        )
    ).all()
    buildings = db.scalars(select(Building).where(Building.project_id == project_id)).all()
    roads = db.scalars(select(Road).where(Road.project_id == project_id)).all()
    landuses = db.scalars(select(LandUse).where(LandUse.project_id == project_id)).all()

    out_p = Path(output_dir)
    images_dir = out_p / "images"
    masks_bldg_dir = out_p / "masks" / "building"
    masks_road_dir = out_p / "masks" / "road"
    masks_bound_dir = out_p / "masks" / "boundary"
    masks_lu_dir = out_p / "masks" / "landuse"

    for d in [images_dir, masks_bldg_dir, masks_road_dir, masks_bound_dir, masks_lu_dir]:
        d.mkdir(parents=True, exist_ok=True)

    manifest_images: list[str] = []
    manifest_masks: dict[str, list[str]] = {
        "building": [],
        "road": [],
        "boundary": [],
        "landuse": [],
    }

    stride = int(tile_size * (1.0 - overlap))
    tile_count = 0

    with rasterio.open(ori_rec.path) as ori_src:
        ndsm_src = rasterio.open(ndsm_rec.path) if has_ndsm and ndsm_rec else None
        h, w = ori_src.height, ori_src.width

        # Convert features to shapely geometries
        bldg_shapes = [(to_shape(b.geom), 1) for b in buildings if b.geom]
        road_shapes = [(to_shape(r.geom), 1) for r in roads if r.geom]

        # Boundaries from parcels and buildings
        bound_shapes = []
        for p in parcels:
            if p.geom:
                s = to_shape(p.geom)
                if s and hasattr(s, "boundary"):
                    bound_shapes.append((s.boundary.buffer(0.3), 1))
        for b in buildings:
            if b.geom:
                s = to_shape(b.geom)
                if s and hasattr(s, "boundary"):
                    bound_shapes.append((s.boundary.buffer(0.2), 1))

        lu_shapes = [
            (to_shape(lu.geom), LANDUSE_MAP.get(lu.landuse_class.value, 5))
            for lu in landuses
            if lu.geom
        ]

        for y in range(0, max(1, h - tile_size + 1), stride):
            for x in range(0, max(1, w - tile_size + 1), stride):
                win = Window(x, y, tile_size, tile_size)
                win_transform = rasterio.windows.transform(win, ori_src.transform)
                bounds = rasterio.windows.bounds(win, ori_src.transform)
                win_poly = box(*bounds)

                # Check if tile has any features
                has_features = any(
                    geom.intersects(win_poly)
                    for geom, _ in (bldg_shapes + road_shapes + bound_shapes)
                )
                if not has_features and tile_count > 0:
                    continue

                rgb_tile = ori_src.read(window=win)
                if rgb_tile.shape[1] != tile_size or rgb_tile.shape[2] != tile_size:
                    continue

                if has_ndsm and ndsm_src:
                    ndsm_tile = ndsm_src.read(1, window=win)
                    img_data = np.concatenate(
                        [rgb_tile.astype(np.float32), ndsm_tile[np.newaxis, ...]], axis=0
                    )
                else:
                    img_data = rgb_tile

                # Rasterize masks for this window
                out_shape = (tile_size, tile_size)
                mask_bldg = (
                    rasterize(
                        bldg_shapes,
                        out_shape=out_shape,
                        transform=win_transform,
                        fill=0,
                        default_value=1,
                        dtype="uint8",
                    )
                    if bldg_shapes
                    else np.zeros(out_shape, dtype=np.uint8)
                )

                mask_road = (
                    rasterize(
                        road_shapes,
                        out_shape=out_shape,
                        transform=win_transform,
                        fill=0,
                        default_value=1,
                        dtype="uint8",
                    )
                    if road_shapes
                    else np.zeros(out_shape, dtype=np.uint8)
                )

                mask_bound = (
                    rasterize(
                        bound_shapes,
                        out_shape=out_shape,
                        transform=win_transform,
                        fill=0,
                        default_value=1,
                        dtype="uint8",
                    )
                    if bound_shapes
                    else np.zeros(out_shape, dtype=np.uint8)
                )

                mask_lu = (
                    rasterize(
                        lu_shapes,
                        out_shape=out_shape,
                        transform=win_transform,
                        fill=4,
                        dtype="uint8",
                    )
                    if lu_shapes
                    else np.full(out_shape, 4, dtype=np.uint8)
                )

                tile_name = f"proj_{project_id}_tile_{tile_count:04d}.tif"
                img_path = images_dir / tile_name
                bldg_path = masks_bldg_dir / tile_name
                road_path = masks_road_dir / tile_name
                bound_path = masks_bound_dir / tile_name
                lu_path = masks_lu_dir / tile_name

                # Save GeoTIFFs
                img_profile = {
                    "driver": "GTiff",
                    "height": tile_size,
                    "width": tile_size,
                    "count": in_channels,
                    "dtype": "float32" if in_channels == 4 else "uint8",
                    "crs": ori_src.crs,
                    "transform": win_transform,
                }
                with rasterio.open(img_path, "w", **img_profile) as dst:
                    dst.write(img_data)

                mask_profile = {
                    "driver": "GTiff",
                    "height": tile_size,
                    "width": tile_size,
                    "count": 1,
                    "dtype": "uint8",
                    "crs": ori_src.crs,
                    "transform": win_transform,
                }
                with rasterio.open(bldg_path, "w", **mask_profile) as dst:
                    dst.write(mask_bldg, 1)
                with rasterio.open(road_path, "w", **mask_profile) as dst:
                    dst.write(mask_road, 1)
                with rasterio.open(bound_path, "w", **mask_profile) as dst:
                    dst.write(mask_bound, 1)
                with rasterio.open(lu_path, "w", **mask_profile) as dst:
                    dst.write(mask_lu, 1)

                manifest_images.append(str(img_path))
                manifest_masks["building"].append(str(bldg_path))
                manifest_masks["road"].append(str(road_path))
                manifest_masks["boundary"].append(str(bound_path))
                manifest_masks["landuse"].append(str(lu_path))

                tile_count += 1

        if ndsm_src:
            ndsm_src.close()

    manifest = {
        "project_id": project_id,
        "num_samples": tile_count,
        "image_size": tile_size,
        "in_channels": in_channels,
        "images": manifest_images,
        "masks": manifest_masks,
    }

    manifest_file = out_p / "dataset_manifest.json"
    with open(manifest_file, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    logger.info("Successfully extracted %d fine-tuning tiles for project #%d into %s", tile_count, project_id, out_p)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Build active-learning fine-tune dataset from verified parcels")
    parser.add_argument("--project-id", type=int, default=None, help="Project ID to extract from PostGIS")
    parser.add_argument("--output-dir", type=str, default="data/finetune", help="Output directory for tiles")
    parser.add_argument("--tile-size", type=int, default=512, help="Tile size in pixels")
    parser.add_argument("--overlap", type=float, default=0.25, help="Window overlap fraction")
    parser.add_argument("--synthetic", action="store_true", help="Generate synthetic dataset for testing")
    parser.add_argument("--num-samples", type=int, default=16, help="Number of synthetic samples")
    args = parser.parse_args()

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.synthetic or args.project_id is None:
        create_synthetic_finetune_set(
            output_dir=out_dir,
            num_tiles=args.num_samples,
            tile_size=args.tile_size,
        )
    else:
        build_finetune_from_project(
            project_id=args.project_id,
            output_dir=out_dir,
            tile_size=args.tile_size,
            overlap=args.overlap,
        )


if __name__ == "__main__":
    main()
