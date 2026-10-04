"""Inference service for ParcelAI (Section 7.3).

Generates probability COGs for:
1. Buildings: probability of building footprint [0.0, 1.0]
2. Roads: probability of road / pathway network [0.0, 1.0]
3. Boundaries: probability of parcel boundary linework [0.0, 1.0]
4. Land-use: multi-class probabilities (6 channels: built_up, road, vegetation, water, open_land, other)

Supports:
- Deep Learning mode (MOCK_MODEL=false): MultiTaskUnet inference with smooth Hann window blending
- Classical CV mode (MOCK_MODEL=true): Deterministic classical computer vision using nDSM thresholds,
  color indices (NDVI/greenness), and Sobel/Canny edge filtering for CPU execution without pretrained weights.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
import torch
from ml.model import MultiTaskUnet
from scipy import ndimage

from app.core.config import get_settings
from app.core.errors import InferenceError
from app.services.ingest import PreparedData, convert_to_cog


@dataclass
class ProbRasters:
    """Paths to the generated probability Cloud-Optimized GeoTIFFs."""

    project_id: int
    building_cog: str
    road_cog: str
    boundary_cog: str
    landuse_cog: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _hann_window_2d(h: int, w: int) -> np.ndarray:
    """Generate 2D Hann blending window to eliminate tile boundary seams."""
    win_y = np.hanning(h)
    win_x = np.hanning(w)
    win_2d = np.outer(win_y, win_x)
    return np.maximum(win_2d, 1e-4).astype(np.float32)


def _run_classical_cv_inference(
    ori_path: str | Path,
    ndsm_path: str | Path | None,
    width: int,
    height: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Deterministic Classical Computer Vision inference (MOCK_MODEL=true).

    Uses nDSM elevation, spectral indices (greenness/saturation), and edge filters.
    """
    # 1. Read ORI (RGB)
    with rasterio.open(ori_path) as src:
        ori = src.read()[:3].astype(np.float32)  # (3, H, W)
        r, g, b = ori[0], ori[1], ori[2]

    # Grayscale image for edge detection
    gray = (0.299 * r + 0.587 * g + 0.114 * b) / 255.0

    # 2. Read nDSM (or simulate 0.0)
    if ndsm_path and Path(ndsm_path).exists():
        with rasterio.open(ndsm_path) as src:
            ndsm = src.read(1).astype(np.float32)
            ndsm = np.where(np.isfinite(ndsm), np.maximum(ndsm, 0.0), 0.0)
    else:
        ndsm = np.zeros((height, width), dtype=np.float32)

    # ── Task 1: Buildings (nDSM > 2.5m + height thresholding) ───────────────────
    # Height threshold: structures above 2.5m elevation
    bldg_prob = np.clip((ndsm - 2.0) / 4.0, 0.0, 1.0)
    # Morphological cleanup on building structures
    bldg_binary = bldg_prob > 0.4
    bldg_cleaned = ndimage.binary_opening(bldg_binary, structure=np.ones((5, 5)))
    bldg_cleaned = ndimage.binary_closing(bldg_cleaned, structure=np.ones((7, 7)))
    prob_building = np.where(bldg_cleaned, np.maximum(bldg_prob, 0.75), bldg_prob * 0.2).astype(np.float32)

    # ── Task 2: Roads (Low nDSM < 0.8m + low color saturation) ───────────────────
    max_c = np.maximum(np.maximum(r, g), b)
    min_c = np.minimum(np.minimum(r, g), b)
    saturation = np.where(max_c > 0, (max_c - min_c) / (max_c + 1e-5), 0.0)

    # Low height + low saturation (asphalt, concrete, packed gravel)
    is_ground = ndsm < 1.0
    is_neutral_color = saturation < 0.25
    road_candidate = is_ground & is_neutral_color & (prob_building < 0.2)

    # Smooth road corridors
    road_smoothed = ndimage.gaussian_filter(road_candidate.astype(np.float32), sigma=1.5)
    prob_road = np.clip(road_smoothed * 1.2, 0.0, 1.0).astype(np.float32)

    # ── Task 3: Boundaries (Sobel edges + building and road linework) ────────────
    sobel_x = ndimage.sobel(gray, axis=1)
    sobel_y = ndimage.sobel(gray, axis=0)
    edge_mag = np.hypot(sobel_x, sobel_y)
    edge_norm = np.clip(edge_mag / (np.percentile(edge_mag, 98) + 1e-5), 0.0, 1.0)

    # Combine visual edges with structural building perimeter edges
    bldg_edges = ndimage.morphological_gradient(prob_building, size=(3, 3))
    road_edges = ndimage.morphological_gradient(prob_road, size=(3, 3))

    prob_boundary = np.clip(0.4 * edge_norm + 0.4 * bldg_edges + 0.2 * road_edges, 0.0, 1.0).astype(np.float32)

    # ── Task 4: Land-use classification (6 classes) ──────────────────────────────
    # 0: built_up, 1: road, 2: vegetation, 3: water, 4: open_land, 5: other
    prob_landuse = np.zeros((6, height, width), dtype=np.float32)

    # Greenness index for vegetation: (G - R) / (G + R)
    greenness = (g - r) / (g + r + 1e-5)
    is_vegetation = (greenness > 0.08) & (ndsm < 15.0)

    # Water index: (B - R) / (B + R) with dark brightness
    is_water = ((b - r) / (b + r + 1e-5) > 0.15) & (gray < 0.35) & is_ground

    prob_landuse[0] = prob_building  # built_up
    prob_landuse[1] = prob_road      # road
    prob_landuse[2] = np.where(is_vegetation & (prob_building < 0.3), 0.9, 0.05)  # vegetation
    prob_landuse[3] = np.where(is_water, 0.95, 0.02)                              # water
    prob_landuse[4] = np.where(is_ground & ~is_vegetation & (prob_road < 0.3) & (prob_building < 0.3), 0.85, 0.05)  # open_land
    prob_landuse[5] = 0.05  # other

    # Normalize softmax across 6 classes
    exp_lu = np.exp(prob_landuse * 3.0)
    prob_landuse = (exp_lu / np.sum(exp_lu, axis=0, keepdims=True)).astype(np.float32)

    return prob_building, prob_road, prob_boundary, prob_landuse


def _run_deep_learning_inference(
    model_path: str | Path,
    ori_path: str | Path,
    ndsm_path: str | Path | None,
    prepared_data: PreparedData,
    device: str = "cpu",
    batch_size: int = 4,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Batched neural network inference over 512x512 tile windows with Hann blending."""
    model_p = Path(model_path)
    if not model_p.exists():
        raise InferenceError(f"Model checkpoint not found at {model_p}")

    width, height = prepared_data.width, prepared_data.height
    dev = torch.device(device)

    # Load model
    model = MultiTaskUnet(encoder_name="resnet34", encoder_weights=None, in_channels=4, landuse_classes=6)
    checkpoint = torch.load(model_p, map_location=dev, weights_only=True)
    if isinstance(checkpoint, dict) and "model_state_dict" in checkpoint:
        model.load_state_dict(checkpoint["model_state_dict"])
    elif isinstance(checkpoint, dict):
        model.load_state_dict(checkpoint)

    model.to(dev)
    model.eval()

    # Pre-allocate full probability accumulators and weight matrices for blending
    acc_building = np.zeros((height, width), dtype=np.float32)
    acc_road = np.zeros((height, width), dtype=np.float32)
    acc_boundary = np.zeros((height, width), dtype=np.float32)
    acc_landuse = np.zeros((6, height, width), dtype=np.float32)
    weight_map = np.zeros((height, width), dtype=np.float32)

    with rasterio.open(ori_path) as ori_src:
        ori_full = ori_src.read()[:3].astype(np.float32) / 255.0

    if ndsm_path and Path(ndsm_path).exists():
        with rasterio.open(ndsm_path) as ndsm_src:
            ndsm_full = ndsm_src.read(1).astype(np.float32)
            ndsm_full = np.where(np.isfinite(ndsm_full), np.maximum(ndsm_full, 0.0), 0.0)
    else:
        ndsm_full = np.zeros((height, width), dtype=np.float32)

    # Tile batch inference loop
    tiles = prepared_data.tiles
    for batch_start in range(0, len(tiles), batch_size):
        batch_tiles = tiles[batch_start : batch_start + batch_size]
        batch_tensors = []

        for tile in batch_tiles:
            c, r, w, h = tile.col_off, tile.row_off, tile.width, tile.height
            # Extract 512x512 tile window (pad if edge window)
            tile_rgb = np.zeros((3, 512, 512), dtype=np.float32)
            tile_ndsm = np.zeros((1, 512, 512), dtype=np.float32)

            tile_rgb[:, :h, :w] = ori_full[:, r : r + h, c : c + w]
            tile_ndsm[0, :h, :w] = ndsm_full[r : r + h, c : c + w]

            # 4-channel input: (4, 512, 512)
            tile_input = np.concatenate([tile_rgb, tile_ndsm], axis=0)
            batch_tensors.append(torch.from_numpy(tile_input))

        batch_torch = torch.stack(batch_tensors).to(dev)

        with torch.no_grad():
            preds = model.predict_probabilities(batch_torch)
            p_bldg = preds["building"].cpu().numpy()[:, 0]
            p_road = preds["road"].cpu().numpy()[:, 0]
            p_bound = preds["boundary"].cpu().numpy()[:, 0]
            p_lu = preds["landuse"].cpu().numpy()

        # Blend predictions into canvas using Hann weights
        for idx, tile in enumerate(batch_tiles):
            c, r, w, h = tile.col_off, tile.row_off, tile.width, tile.height
            hann = _hann_window_2d(h, w)

            acc_building[r : r + h, c : c + w] += p_bldg[idx, :h, :w] * hann
            acc_road[r : r + h, c : c + w] += p_road[idx, :h, :w] * hann
            acc_boundary[r : r + h, c : c + w] += p_bound[idx, :h, :w] * hann
            for cls_idx in range(6):
                acc_landuse[cls_idx, r : r + h, c : c + w] += p_lu[idx, cls_idx, :h, :w] * hann

            weight_map[r : r + h, c : c + w] += hann

    # Normalize by accumulated weights
    valid_weights = np.maximum(weight_map, 1e-4)
    prob_building = np.clip(acc_building / valid_weights, 0.0, 1.0)
    prob_road = np.clip(acc_road / valid_weights, 0.0, 1.0)
    prob_boundary = np.clip(acc_boundary / valid_weights, 0.0, 1.0)
    prob_landuse = np.clip(acc_landuse / valid_weights[np.newaxis, :, :], 0.0, 1.0)

    return prob_building, prob_road, prob_boundary, prob_landuse


def run_inference(
    project_id: int,
    prepared_data: PreparedData,
    model_path: str | Path | None = None,
    mock_model: bool | None = None,
    output_dir: str | Path | None = None,
    device: str = "cpu",
    batch_size: int = 4,
) -> ProbRasters:
    """Run model inference or classical CV mock inference and write probability COGs."""
    settings = get_settings()
    use_mock = mock_model if mock_model is not None else settings.mock_model
    target_model_path = Path(model_path or settings.model_path)

    # If mock_model=False but checkpoint is missing, fallback safely to classical CV
    if not use_mock and not target_model_path.exists():
        use_mock = True

    base_out = Path(output_dir or f"{settings.data_dir}/projects/{project_id}/processed")
    cog_out = base_out / "cogs"
    tmp_out = base_out / "intermediate"
    cog_out.mkdir(parents=True, exist_ok=True)
    tmp_out.mkdir(parents=True, exist_ok=True)

    width, height = prepared_data.width, prepared_data.height

    if use_mock:
        prob_bldg, prob_road, prob_bound, prob_lu = _run_classical_cv_inference(
            ori_path=prepared_data.ori_cog,
            ndsm_path=prepared_data.ndsm_cog,
            width=width,
            height=height,
        )
    else:
        prob_bldg, prob_road, prob_bound, prob_lu = _run_deep_learning_inference(
            model_path=target_model_path,
            ori_path=prepared_data.ori_cog,
            ndsm_path=prepared_data.ndsm_cog,
            prepared_data=prepared_data,
            device=device,
            batch_size=batch_size,
        )

    # Write probability rasters to intermediate GeoTIFFs then convert to COG
    with rasterio.open(prepared_data.ori_cog) as ref_src:
        profile_single = ref_src.profile.copy()
        profile_single.update({"count": 1, "dtype": "float32", "nodata": None})

        profile_multi = ref_src.profile.copy()
        profile_multi.update({"count": 6, "dtype": "float32", "nodata": None})

    # 1. Building COG
    tmp_bldg = tmp_out / f"prob_building_{project_id}_raw.tif"
    cog_bldg = cog_out / f"prob_building_{project_id}.tif"
    with rasterio.open(tmp_bldg, "w", **profile_single) as dst:
        dst.write(prob_bldg.astype(np.float32), 1)
    convert_to_cog(tmp_bldg, cog_bldg)

    # 2. Road COG
    tmp_road = tmp_out / f"prob_road_{project_id}_raw.tif"
    cog_road = cog_out / f"prob_road_{project_id}.tif"
    with rasterio.open(tmp_road, "w", **profile_single) as dst:
        dst.write(prob_road.astype(np.float32), 1)
    convert_to_cog(tmp_road, cog_road)

    # 3. Boundary COG
    tmp_bound = tmp_out / f"prob_boundary_{project_id}_raw.tif"
    cog_bound = cog_out / f"prob_boundary_{project_id}.tif"
    with rasterio.open(tmp_bound, "w", **profile_single) as dst:
        dst.write(prob_bound.astype(np.float32), 1)
    convert_to_cog(tmp_bound, cog_bound)

    # 4. Land-use COG
    tmp_lu = tmp_out / f"prob_landuse_{project_id}_raw.tif"
    cog_lu = cog_out / f"prob_landuse_{project_id}.tif"
    with rasterio.open(tmp_lu, "w", **profile_multi) as dst:
        for i in range(6):
            dst.write(prob_lu[i].astype(np.float32), i + 1)
    convert_to_cog(tmp_lu, cog_lu)

    return ProbRasters(
        project_id=project_id,
        building_cog=str(cog_bldg.resolve()),
        road_cog=str(cog_road.resolve()),
        boundary_cog=str(cog_bound.resolve()),
        landuse_cog=str(cog_lu.resolve()),
    )
