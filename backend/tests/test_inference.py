"""Unit and integration tests for the Inference pipeline (Phase 3).

Verifies:
- Classical CV inference (mock_model=True)
- Deep Learning batched inference (mock_model=False) with Hann blending
- Output COG format and value bounds [0.0, 1.0]
- ProbRasters integrity
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest
import rasterio
import torch
from ml.model import MultiTaskUnet

from app.services.inference import ProbRasters, run_inference
from app.services.ingest import prepare_project


@pytest.fixture
def prepared_demo_project(tmp_path: Path) -> tuple[int, Any, Path]:
    """Create a synthetic prepared project with ORI, DSM, DTM, nDSM, and COGs."""
    from rasterio.transform import from_origin

    width, height = 400, 400
    transform = from_origin(500000.0, 3000000.0, 0.2, 0.2)
    crs = "EPSG:32643"

    ori_p = tmp_path / "raw_ori.tif"
    dsm_p = tmp_path / "raw_dsm.tif"
    dtm_p = tmp_path / "raw_dtm.tif"

    # Synthetic RGB image
    rgb_data = np.full((3, height, width), 120, dtype=np.uint8)
    # Green park area
    rgb_data[1, 0:150, 0:150] = 220
    # Blue water body
    rgb_data[2, 250:350, 250:350] = 230
    with rasterio.open(ori_p, "w", driver="GTiff", height=height, width=width, count=3, dtype="uint8", crs=crs, transform=transform) as dst:
        for i in range(3):
            dst.write(rgb_data[i], i + 1)

    # Synthetic DTM (ground 50m)
    dtm_data = np.full((height, width), 50.0, dtype=np.float32)
    with rasterio.open(dtm_p, "w", driver="GTiff", height=height, width=width, count=1, dtype="float32", crs=crs, transform=transform) as dst:
        dst.write(dtm_data, 1)

    # Synthetic DSM (ground 50m + building of 8m height at [150:250, 150:250])
    dsm_data = dtm_data.copy()
    dsm_data[150:250, 150:250] += 8.0
    with rasterio.open(dsm_p, "w", driver="GTiff", height=height, width=width, count=1, dtype="float32", crs=crs, transform=transform) as dst:
        dst.write(dsm_data, 1)

    proc_dir = tmp_path / "processed"
    prep = prepare_project(
        project_id=101,
        ori_path=ori_p,
        dsm_path=dsm_p,
        dtm_path=dtm_p,
        project_crs=crs,
        output_dir=proc_dir,
        tile_size=256,
        overlap=0.25,
    )

    return 101, prep, proc_dir


def test_classical_cv_inference(prepared_demo_project: tuple[int, Any, Path], tmp_path: Path):
    proj_id, prep, proc_dir = prepared_demo_project

    prob_rasters = run_inference(
        project_id=proj_id,
        prepared_data=prep,
        mock_model=True,
        output_dir=proc_dir,
    )

    assert isinstance(prob_rasters, ProbRasters)
    assert Path(prob_rasters.building_cog).exists()
    assert Path(prob_rasters.road_cog).exists()
    assert Path(prob_rasters.boundary_cog).exists()
    assert Path(prob_rasters.landuse_cog).exists()

    # Check building probability raster values
    with rasterio.open(prob_rasters.building_cog) as src:
        bldg_prob = src.read(1)
        assert src.is_tiled
        assert bldg_prob.min() >= 0.0 and bldg_prob.max() <= 1.0
        # Elevated building center should have high building probability
        assert np.mean(bldg_prob[170:230, 170:230]) > 0.5
        # Ground should have low building probability
        assert np.mean(bldg_prob[0:50, 0:50]) < 0.2

    # Check landuse probability raster (6 channels)
    with rasterio.open(prob_rasters.landuse_cog) as src:
        assert src.count == 6
        lu_prob = src.read()
        assert lu_prob.min() >= 0.0 and lu_prob.max() <= 1.0


def test_deep_learning_inference_with_weights(prepared_demo_project: tuple[int, Any, Path], tmp_path: Path):
    proj_id, prep, proc_dir = prepared_demo_project

    # Create dummy model weights checkpoint
    model = MultiTaskUnet(encoder_name="resnet34", encoder_weights=None, in_channels=4, landuse_classes=6)
    ckpt_path = tmp_path / "model_weights.pt"
    torch.save(model.state_dict(), ckpt_path)

    prob_rasters = run_inference(
        project_id=proj_id,
        prepared_data=prep,
        model_path=ckpt_path,
        mock_model=False,
        output_dir=proc_dir,
        device="cpu",
        batch_size=2,
    )

    assert isinstance(prob_rasters, ProbRasters)
    assert Path(prob_rasters.building_cog).exists()
    assert Path(prob_rasters.road_cog).exists()
    assert Path(prob_rasters.boundary_cog).exists()
    assert Path(prob_rasters.landuse_cog).exists()

    with rasterio.open(prob_rasters.building_cog) as src:
        assert src.is_tiled
        prob = src.read(1)
        assert prob.min() >= 0.0 and prob.max() <= 1.0
