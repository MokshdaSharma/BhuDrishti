"""Ingest service for ParcelAI (Section 7.1).

Responsibilities:
- Validate uploaded GeoTIFFs (ORI, DSM, DTM) and vector formats (GPKG, SHP, GeoJSON).
- Validate CRS, resolution, extent.
- Reproject to project CRS (default EPSG:32643).
- Resample DSM and DTM to align exactly with the ORI grid.
- Calculate nDSM = clip(DSM - DTM, 0, None) as float32.
- Derive approximate ground surface (DTM) via morphological opening if DTM is missing.
- Convert rasters to Cloud-Optimized GeoTIFFs (COG) with pyramids and tiling.
- Generate 512x512 windows with 25% overlap for model inference.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from rasterio import Affine
from rasterio.enums import Resampling
from rasterio.warp import (
    Resampling as WarpResampling,
)
from rasterio.warp import (
    calculate_default_transform,
    reproject,
)
from scipy import ndimage

from app.core.config import get_settings
from app.core.errors import IngestError


@dataclass
class TileWindow:
    """Window specification for model tiling (512x512 with 25% overlap)."""

    window_id: int
    col_off: int
    row_off: int
    width: int
    height: int
    transform: list[float]  # 6-element affine transform [a, b, c, d, e, f]
    bounds: tuple[float, float, float, float]  # minx, miny, maxx, maxy

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PreparedData:
    """Output artifact of prepare_project containing paths to COGs and tiling specs."""

    project_id: int
    crs: str
    ori_cog: str
    dsm_cog: str | None
    dtm_cog: str | None
    ndsm_cog: str | None
    tiles: list[TileWindow]
    width: int
    height: int
    resolution: float
    bounds: tuple[float, float, float, float]
    is_approximate_dtm: bool = False
    fallback_dem_used: bool = False

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["tiles"] = [t.to_dict() if isinstance(t, TileWindow) else t for t in self.tiles]
        return data


def validate_raster(file_path: str | Path) -> dict[str, Any]:
    """Validate raster integrity and verify existence of CRS, transform, and bands."""
    p = Path(file_path)
    if not p.exists():
        raise IngestError(f"Raster file not found: {p}")

    try:
        with rasterio.open(p) as src:
            if src.crs is None:
                raise IngestError(
                    f"Raster {p.name} has no defined Coordinate Reference System (CRS). "
                    "Please assign a valid CRS prior to ingest."
                )
            if src.width <= 0 or src.height <= 0 or src.count <= 0:
                raise IngestError(f"Raster {p.name} has invalid dimensions: {src.width}x{src.height}, bands={src.count}")

            res_x, res_y = abs(src.res[0]), abs(src.res[1])
            return {
                "name": p.name,
                "path": str(p.resolve()),
                "crs": src.crs.to_string(),
                "width": src.width,
                "height": src.height,
                "count": src.count,
                "dtypes": src.dtypes,
                "bounds": tuple(src.bounds),
                "transform": list(src.transform)[:6],
                "resolution": (res_x + res_y) / 2.0,
                "nodata": src.nodata,
            }
    except Exception as exc:
        if isinstance(exc, IngestError):
            raise
        raise IngestError(f"Failed to open or validate raster {p.name}: {exc}") from exc


def reproject_raster(
    src_path: str | Path,
    dst_path: str | Path,
    target_crs: str = "EPSG:32643",
    resampling: Resampling = Resampling.bilinear,
) -> str:
    """Reproject a raster to the target CRS."""
    src_p = Path(src_path)
    dst_p = Path(dst_path)
    dst_p.parent.mkdir(parents=True, exist_ok=True)

    with rasterio.open(src_p) as src:
        src_crs = src.crs
        if src_crs and src_crs.to_string() == target_crs:
            # Already in target CRS: copy/save with target profile
            profile = src.profile.copy()
            with rasterio.open(dst_p, "w", **profile) as dst:
                for band_idx in range(1, src.count + 1):
                    dst.write(src.read(band_idx), band_idx)
            return str(dst_p.resolve())

        transform, width, height = calculate_default_transform(
            src_crs, target_crs, src.width, src.height, *src.bounds
        )
        profile = src.profile.copy()
        profile.update(
            {
                "crs": target_crs,
                "transform": transform,
                "width": width,
                "height": height,
            }
        )

        with rasterio.open(dst_p, "w", **profile) as dst:
            for i in range(1, src.count + 1):
                reproject(
                    source=rasterio.band(src, i),
                    destination=rasterio.band(dst, i),
                    src_transform=src.transform,
                    src_crs=src.crs,
                    dst_transform=transform,
                    dst_crs=target_crs,
                    resampling=WarpResampling(resampling.value),
                )

    return str(dst_p.resolve())


def resample_to_grid(
    src_path: str | Path,
    dst_path: str | Path,
    target_crs: str,
    target_transform: Affine | list[float],
    target_width: int,
    target_height: int,
    resampling: Resampling = Resampling.bilinear,
    nodata: float | None = None,
) -> str:
    """Resample a raster to match an exact reference grid (same CRS, transform, dimensions)."""
    src_p = Path(src_path)
    dst_p = Path(dst_path)
    dst_p.parent.mkdir(parents=True, exist_ok=True)

    if isinstance(target_transform, list):
        target_aff = Affine(*target_transform[:6])
    else:
        target_aff = target_transform

    with rasterio.open(src_p) as src:
        profile = src.profile.copy()
        dst_nodata = nodata if nodata is not None else src.nodata
        profile.update(
            {
                "crs": target_crs,
                "transform": target_aff,
                "width": target_width,
                "height": target_height,
                "nodata": dst_nodata,
            }
        )

        with rasterio.open(dst_p, "w", **profile) as dst:
            for i in range(1, src.count + 1):
                reproject(
                    source=rasterio.band(src, i),
                    destination=rasterio.band(dst, i),
                    src_transform=src.transform,
                    src_crs=src.crs,
                    dst_transform=target_aff,
                    dst_crs=target_crs,
                    src_nodata=src.nodata,
                    dst_nodata=dst_nodata,
                    resampling=WarpResampling(resampling.value),
                )

    return str(dst_p.resolve())


def derive_approximate_dtm(
    dsm_path: str | Path,
    dst_dtm_path: str | Path,
    filter_radius_px: int = 35,
) -> str:
    """Derive approximate DTM from DSM using morphological grey opening (filter structures/trees)."""
    dsm_p = Path(dsm_path)
    dst_p = Path(dst_dtm_path)
    dst_p.parent.mkdir(parents=True, exist_ok=True)

    with rasterio.open(dsm_p) as src:
        dsm_data = src.read(1).astype(np.float32)
        profile = src.profile.copy()
        nodata = src.nodata

    valid_mask = np.isfinite(dsm_data)
    if nodata is not None:
        valid_mask = valid_mask & (dsm_data != nodata)

    # Fill invalid entries temporarily with min elevation
    min_elev = np.min(dsm_data[valid_mask]) if np.any(valid_mask) else 0.0
    filled_dsm = np.where(valid_mask, dsm_data, min_elev)

    # Create disk footprint for morphological opening
    y, x = np.ogrid[-filter_radius_px : filter_radius_px + 1, -filter_radius_px : filter_radius_px + 1]
    footprint = (x * x + y * y) <= (filter_radius_px * filter_radius_px)

    # Grey opening: erosion followed by dilation removes bright elevated structures
    approx_dtm = ndimage.grey_opening(filled_dsm, footprint=footprint)

    # Restore nodata mask
    if nodata is not None:
        approx_dtm = np.where(valid_mask, approx_dtm, nodata)

    profile.update({"dtype": "float32", "count": 1})
    with rasterio.open(dst_p, "w", **profile) as dst:
        dst.write(approx_dtm.astype(np.float32), 1)

    return str(dst_p.resolve())


def compute_ndsm(
    dsm_path: str | Path,
    dtm_path: str | Path,
    dst_ndsm_path: str | Path,
    clip_min: float = 0.0,
    clip_max: float | None = 150.0,
) -> str:
    """Compute normalized Digital Surface Model: nDSM = clip(DSM - DTM, 0, None) float32."""
    dsm_p = Path(dsm_path)
    dtm_p = Path(dtm_path)
    dst_p = Path(dst_ndsm_path)
    dst_p.parent.mkdir(parents=True, exist_ok=True)

    with rasterio.open(dsm_p) as dsm_src, rasterio.open(dtm_p) as dtm_src:
        if (dsm_src.width != dtm_src.width) or (dsm_src.height != dtm_src.height):
            raise IngestError(
                f"DSM ({dsm_src.width}x{dsm_src.height}) and DTM ({dtm_src.width}x{dtm_src.height}) "
                "dimensions do not match. Resample to common grid first."
            )

        dsm = dsm_src.read(1).astype(np.float32)
        dtm = dtm_src.read(1).astype(np.float32)

        # Handle nodata
        dsm_valid = np.isfinite(dsm)
        if dsm_src.nodata is not None:
            dsm_valid = dsm_valid & (dsm != dsm_src.nodata)

        dtm_valid = np.isfinite(dtm)
        if dtm_src.nodata is not None:
            dtm_valid = dtm_valid & (dtm != dtm_src.nodata)

        both_valid = dsm_valid & dtm_valid

        # nDSM = clip(DSM - DTM, 0, max)
        diff = dsm - dtm
        ndsm = np.where(both_valid, np.clip(diff, clip_min, clip_max), 0.0).astype(np.float32)

        profile = dsm_src.profile.copy()
        profile.update(
            {
                "dtype": "float32",
                "count": 1,
                "nodata": -9999.0,
            }
        )
        ndsm = np.where(both_valid, ndsm, -9999.0).astype(np.float32)

        with rasterio.open(dst_p, "w", **profile) as dst:
            dst.write(ndsm, 1)

    return str(dst_p.resolve())


def convert_to_cog(
    src_path: str | Path,
    dst_cog_path: str | Path,
    blocksize: int = 256,
    overview_levels: list[int] | None = None,
) -> str:
    """Convert any GeoTIFF to a Cloud-Optimized GeoTIFF (COG) with internal tiling and overviews."""
    src_p = Path(src_path)
    dst_p = Path(dst_cog_path)
    dst_p.parent.mkdir(parents=True, exist_ok=True)

    if overview_levels is None:
        overview_levels = [2, 4, 8, 16]

    with rasterio.open(src_p) as src:
        profile = src.profile.copy()
        profile.update(
            {
                "driver": "GTiff",
                "tiled": True,
                "blockxsize": blocksize,
                "blockysize": blocksize,
                "compress": "DEFLATE",
                "interleave": "pixel" if src.count > 1 else "band",
            }
        )

        with rasterio.open(dst_p, "w", **profile) as dst:
            for band_idx in range(1, src.count + 1):
                dst.write(src.read(band_idx), band_idx)

            # Build internal overviews for fast pyramid tile serving (TiTiler)
            if max(src.width, src.height) > blocksize:
                dst.build_overviews(overview_levels, Resampling.nearest)
                dst.update_tags(ns="rio_overview", resampling="nearest")

    return str(dst_p.resolve())


def generate_tiles(
    width: int,
    height: int,
    tile_size: int = 512,
    overlap: float = 0.25,
    transform: Affine | list[float] | None = None,
) -> list[TileWindow]:
    """Generate regular overlapping 512x512 windows covering the raster extent."""
    if width <= 0 or height <= 0:
        return []

    step = max(1, int(tile_size * (1.0 - overlap)))
    aff = (
        Affine(*transform[:6])
        if isinstance(transform, list)
        else (transform if transform is not None else Affine.identity())
    )

    col_offsets = list(range(0, max(1, width - tile_size + 1), step))
    if not col_offsets or col_offsets[-1] + tile_size < width:
        col_offsets.append(max(0, width - tile_size))
    col_offsets = sorted(set(col_offsets))

    row_offsets = list(range(0, max(1, height - tile_size + 1), step))
    if not row_offsets or row_offsets[-1] + tile_size < height:
        row_offsets.append(max(0, height - tile_size))
    row_offsets = sorted(set(row_offsets))

    tiles: list[TileWindow] = []
    window_id = 0

    for r in row_offsets:
        for c in col_offsets:
            w = min(tile_size, width - c)
            h = min(tile_size, height - r)

            # Calculate window geographic affine transform and bounds
            win_transform = aff @ Affine.translation(c, r)
            minx = win_transform.c
            maxy = win_transform.f
            maxx = minx + w * win_transform.a
            miny = maxy + h * win_transform.e  # note: win_transform.e is negative for north-up

            # Ensure min < max in bounds tuple
            bounds = (
                min(minx, maxx),
                min(miny, maxy),
                max(minx, maxx),
                max(miny, maxy),
            )

            tiles.append(
                TileWindow(
                    window_id=window_id,
                    col_off=c,
                    row_off=r,
                    width=w,
                    height=h,
                    transform=list(win_transform)[:6],
                    bounds=bounds,
                )
            )
            window_id += 1

    return tiles


def prepare_project(
    project_id: int,
    ori_path: str | Path,
    dsm_path: str | Path | None = None,
    dtm_path: str | Path | None = None,
    project_crs: str | None = None,
    output_dir: str | Path | None = None,
    tile_size: int = 512,
    overlap: float = 0.25,
) -> PreparedData:
    """Main pipeline entrypoint: validates, reprojects, aligns, calculates nDSM, creates COGs and tiles.

    Returns a PreparedData object ready for inference (Phase 3).
    """
    settings = get_settings()
    target_crs = project_crs or settings.default_crs

    # Output directory setup
    base_out = Path(output_dir or f"{settings.data_dir}/projects/{project_id}/processed")
    cog_out = base_out / "cogs"
    tmp_out = base_out / "intermediate"
    cog_out.mkdir(parents=True, exist_ok=True)
    tmp_out.mkdir(parents=True, exist_ok=True)

    # 1. Validate ORI (mandatory primary raster)
    validate_raster(ori_path)

    # 2. Reproject ORI to target CRS
    ori_reproj_path = tmp_out / f"ori_{project_id}_reproj.tif"
    reproject_raster(ori_path, ori_reproj_path, target_crs=target_crs)
    ori_reproj_meta = validate_raster(ori_reproj_path)

    # 3. Convert ORI to COG
    ori_cog_path = cog_out / f"ori_{project_id}.tif"
    convert_to_cog(ori_reproj_path, ori_cog_path)

    ref_transform = Affine(*ori_reproj_meta["transform"])
    ref_width = ori_reproj_meta["width"]
    ref_height = ori_reproj_meta["height"]

    dsm_cog_path: str | None = None
    dtm_cog_path: str | None = None
    ndsm_cog_path: str | None = None
    is_approximate_dtm = False

    # 4. Handle DSM if present
    if dsm_path and Path(dsm_path).exists():
        validate_raster(dsm_path)
        dsm_aligned_path = tmp_out / f"dsm_{project_id}_aligned.tif"
        resample_to_grid(
            src_path=dsm_path,
            dst_path=dsm_aligned_path,
            target_crs=target_crs,
            target_transform=ref_transform,
            target_width=ref_width,
            target_height=ref_height,
            resampling=Resampling.bilinear,
        )
        dsm_cog_file = cog_out / f"dsm_{project_id}.tif"
        convert_to_cog(dsm_aligned_path, dsm_cog_file)
        dsm_cog_path = str(dsm_cog_file.resolve())

        # 5. Handle DTM or morphological fallback
        if dtm_path and Path(dtm_path).exists():
            validate_raster(dtm_path)
            dtm_aligned_path = tmp_out / f"dtm_{project_id}_aligned.tif"
            resample_to_grid(
                src_path=dtm_path,
                dst_path=dtm_aligned_path,
                target_crs=target_crs,
                target_transform=ref_transform,
                target_width=ref_width,
                target_height=ref_height,
                resampling=Resampling.bilinear,
            )
            is_approximate_dtm = False
        else:
            # Section 7.1: Derive rough ground surface by morphological opening of DSM
            dtm_aligned_path = tmp_out / f"dtm_{project_id}_approx.tif"
            derive_approximate_dtm(dsm_aligned_path, dtm_aligned_path)
            is_approximate_dtm = True

        dtm_cog_file = cog_out / f"dtm_{project_id}.tif"
        convert_to_cog(dtm_aligned_path, dtm_cog_file)
        dtm_cog_path = str(dtm_cog_file.resolve())

        # 6. Calculate nDSM = clip(DSM - DTM, 0, None)
        ndsm_raw_path = tmp_out / f"ndsm_{project_id}_raw.tif"
        compute_ndsm(dsm_aligned_path, dtm_aligned_path, ndsm_raw_path)
        ndsm_cog_file = cog_out / f"ndsm_{project_id}.tif"
        convert_to_cog(ndsm_raw_path, ndsm_cog_file)
        ndsm_cog_path = str(ndsm_cog_file.resolve())

    # 7. Generate 512x512 tile windows
    tiles = generate_tiles(
        width=ref_width,
        height=ref_height,
        tile_size=tile_size,
        overlap=overlap,
        transform=ref_transform,
    )

    return PreparedData(
        project_id=project_id,
        crs=target_crs,
        ori_cog=str(ori_cog_path.resolve()),
        dsm_cog=dsm_cog_path,
        dtm_cog=dtm_cog_path,
        ndsm_cog=ndsm_cog_path,
        tiles=tiles,
        width=ref_width,
        height=ref_height,
        resolution=ori_reproj_meta["resolution"],
        bounds=ori_reproj_meta["bounds"],
        is_approximate_dtm=is_approximate_dtm,
        fallback_dem_used=False,
    )
