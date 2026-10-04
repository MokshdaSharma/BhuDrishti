"""Unit and integration tests for the Ingest pipeline (Phase 2).

Verifies:
- Raster validation and CRS checking
- Reprojection to project CRS
- Resampling and grid alignment
- Morphological DTM derivation fallback
- nDSM computation: nDSM = clip(DSM - DTM, 0, None)
- Cloud-Optimized GeoTIFF (COG) generation
- 512x512 tile window generation with overlap
- End-to-end prepare_project execution
"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from app.core.errors import IngestError
from app.services.ingest import (
    PreparedData,
    TileWindow,
    compute_ndsm,
    convert_to_cog,
    derive_approximate_dtm,
    generate_tiles,
    prepare_project,
    validate_raster,
)


@pytest.fixture
def sample_rasters_dir(tmp_path: Path) -> Generator[Path, None, None]:
    """Create a temporary directory containing synthetic ORI, DSM, and DTM GeoTIFFs."""
    # Synthetic small region: 600x600 pixels at 0.1m resolution in EPSG:32643 (UTM 43N)
    width, height = 600, 600
    transform = from_origin(500000.0, 3000000.0, 0.1, 0.1)
    crs = "EPSG:32643"

    # 1. Synthetic 3-band RGB Orthomosaic (ORI)
    ori_path = tmp_path / "sample_ori.tif"
    ori_data = np.random.randint(50, 200, size=(3, height, width), dtype=np.uint8)
    with rasterio.open(
        ori_path,
        "w",
        driver="GTiff",
        height=height,
        width=width,
        count=3,
        dtype="uint8",
        crs=crs,
        transform=transform,
    ) as dst:
        for i in range(3):
            dst.write(ori_data[i], i + 1)

    # 2. Synthetic DTM (smooth ground slope ~100m to 105m)
    dtm_path = tmp_path / "sample_dtm.tif"
    x = np.linspace(0, 5, width)
    y = np.linspace(0, 5, height)
    xx, yy = np.meshgrid(x, y)
    dtm_data = (100.0 + 0.5 * xx + 0.3 * yy).astype(np.float32)
    with rasterio.open(
        dtm_path,
        "w",
        driver="GTiff",
        height=height,
        width=width,
        count=1,
        dtype="float32",
        crs=crs,
        transform=transform,
        nodata=-9999.0,
    ) as dst:
        dst.write(dtm_data, 1)

    # 3. Synthetic DSM (Ground + elevated building structures of height +8m and +12m)
    dsm_path = tmp_path / "sample_dsm.tif"
    dsm_data = dtm_data.copy()
    # Add building 1 (100x100 px, +8m height)
    dsm_data[100:200, 100:200] += 8.0
    # Add building 2 (120x80 px, +12m height)
    dsm_data[300:420, 350:430] += 12.0

    with rasterio.open(
        dsm_path,
        "w",
        driver="GTiff",
        height=height,
        width=width,
        count=1,
        dtype="float32",
        crs=crs,
        transform=transform,
        nodata=-9999.0,
    ) as dst:
        dst.write(dsm_data, 1)

    yield tmp_path


def test_validate_raster_success(sample_rasters_dir: Path):
    ori_path = sample_rasters_dir / "sample_ori.tif"
    meta = validate_raster(ori_path)
    assert meta["width"] == 600
    assert meta["height"] == 600
    assert meta["count"] == 3
    assert "32643" in meta["crs"]
    assert meta["resolution"] == pytest.approx(0.1, abs=1e-3)


def test_validate_raster_missing_file():
    with pytest.raises(IngestError, match="not found"):
        validate_raster("non_existent_file.tif")


def test_validate_raster_missing_crs(tmp_path: Path):
    # Create GeoTIFF without CRS
    no_crs_path = tmp_path / "no_crs.tif"
    with rasterio.open(
        no_crs_path,
        "w",
        driver="GTiff",
        height=50,
        width=50,
        count=1,
        dtype="uint8",
    ) as dst:
        dst.write(np.zeros((50, 50), dtype=np.uint8), 1)

    with pytest.raises(IngestError, match="no defined Coordinate Reference System"):
        validate_raster(no_crs_path)


def test_compute_ndsm(sample_rasters_dir: Path, tmp_path: Path):
    dsm_path = sample_rasters_dir / "sample_dsm.tif"
    dtm_path = sample_rasters_dir / "sample_dtm.tif"
    ndsm_out = tmp_path / "ndsm.tif"

    compute_ndsm(dsm_path, dtm_path, ndsm_out)
    assert ndsm_out.exists()

    with rasterio.open(ndsm_out) as src:
        ndsm = src.read(1)
        # Ground should have nDSM ~ 0
        assert np.all(ndsm[0:50, 0:50] == pytest.approx(0.0, abs=1e-3))
        # Building 1 should have nDSM ~ 8.0
        assert np.all(ndsm[110:190, 110:190] == pytest.approx(8.0, abs=1e-3))
        # Building 2 should have nDSM ~ 12.0
        assert np.all(ndsm[310:410, 360:420] == pytest.approx(12.0, abs=1e-3))


def test_derive_approximate_dtm(sample_rasters_dir: Path, tmp_path: Path):
    dsm_path = sample_rasters_dir / "sample_dsm.tif"
    approx_dtm_out = tmp_path / "approx_dtm.tif"

    derive_approximate_dtm(dsm_path, approx_dtm_out, filter_radius_px=55)
    assert approx_dtm_out.exists()

    with rasterio.open(approx_dtm_out) as src:
        approx_dtm = src.read(1)
        # Morphological opening should have filtered out elevated structures
        # The estimated ground under building 1 should be close to ground level (~100-105m)
        assert np.mean(approx_dtm[100:200, 100:200]) < 105.0


def test_convert_to_cog(sample_rasters_dir: Path, tmp_path: Path):
    ori_path = sample_rasters_dir / "sample_ori.tif"
    cog_out = tmp_path / "ori_cog.tif"

    convert_to_cog(ori_path, cog_out, blocksize=256)
    assert cog_out.exists()

    with rasterio.open(cog_out) as src:
        assert src.is_tiled
        assert src.block_shapes[0] == (256, 256)
        assert len(src.overviews(1)) > 0


def test_generate_tiles():
    width, height = 1000, 800
    tile_size = 512
    overlap = 0.25

    tiles = generate_tiles(width=width, height=height, tile_size=tile_size, overlap=overlap)
    assert len(tiles) > 0

    # Ensure all tiles are valid TileWindow objects
    for t in tiles:
        assert isinstance(t, TileWindow)
        assert t.width <= tile_size
        assert t.height <= tile_size
        assert t.col_off + t.width <= width
        assert t.row_off + t.height <= height
        assert len(t.transform) == 6
        assert len(t.bounds) == 4
        assert t.bounds[0] <= t.bounds[2]  # minx <= maxx
        assert t.bounds[1] <= t.bounds[3]  # miny <= maxy


def test_prepare_project_full(sample_rasters_dir: Path, tmp_path: Path):
    ori_path = sample_rasters_dir / "sample_ori.tif"
    dsm_path = sample_rasters_dir / "sample_dsm.tif"
    dtm_path = sample_rasters_dir / "sample_dtm.tif"
    out_dir = tmp_path / "proc_out"

    prep = prepare_project(
        project_id=42,
        ori_path=ori_path,
        dsm_path=dsm_path,
        dtm_path=dtm_path,
        project_crs="EPSG:32643",
        output_dir=out_dir,
    )

    assert isinstance(prep, PreparedData)
    assert prep.project_id == 42
    assert prep.crs == "EPSG:32643"
    assert Path(prep.ori_cog).exists()
    assert prep.dsm_cog is not None and Path(prep.dsm_cog).exists()
    assert prep.dtm_cog is not None and Path(prep.dtm_cog).exists()
    assert prep.ndsm_cog is not None and Path(prep.ndsm_cog).exists()
    assert not prep.is_approximate_dtm
    assert len(prep.tiles) > 0


def test_prepare_project_without_dtm_fallback(sample_rasters_dir: Path, tmp_path: Path):
    ori_path = sample_rasters_dir / "sample_ori.tif"
    dsm_path = sample_rasters_dir / "sample_dsm.tif"
    out_dir = tmp_path / "proc_out_no_dtm"

    # Ingest with DSM only (missing DTM) -> triggers morphological ground estimation
    prep = prepare_project(
        project_id=43,
        ori_path=ori_path,
        dsm_path=dsm_path,
        dtm_path=None,
        project_crs="EPSG:32643",
        output_dir=out_dir,
    )

    assert prep.is_approximate_dtm is True
    assert prep.dtm_cog is not None and Path(prep.dtm_cog).exists()
    assert prep.ndsm_cog is not None and Path(prep.ndsm_cog).exists()
