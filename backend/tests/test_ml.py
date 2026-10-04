"""Unit tests for ML model architecture, loss functions, datasets, and export (Phase 3)."""

from __future__ import annotations

import json
from pathlib import Path

import torch
from ml.datasets.dataset import SyntheticGeoDataset
from ml.export_weights import export_model_package
from ml.losses import MultiTaskLoss
from ml.model import MultiTaskUnet
from ml.train import run_training


def test_multitask_unet_shapes():
    model = MultiTaskUnet(
        encoder_name="resnet34",
        encoder_weights=None,
        in_channels=4,
        landuse_classes=6,
    )
    model.eval()

    # Input: batch of 2 images with 4 channels (RGB + nDSM) of size 256x256
    x = torch.randn(2, 4, 256, 256)
    with torch.no_grad():
        out = model(x)
        probs = model.predict_probabilities(x)

    # 1. Building head
    assert out["building"].shape == (2, 1, 256, 256)
    assert probs["building"].min() >= 0.0 and probs["building"].max() <= 1.0

    # 2. Road head
    assert out["road"].shape == (2, 1, 256, 256)
    assert probs["road"].min() >= 0.0 and probs["road"].max() <= 1.0

    # 3. Boundary head
    assert out["boundary"].shape == (2, 1, 256, 256)
    assert probs["boundary"].min() >= 0.0 and probs["boundary"].max() <= 1.0

    # 4. Land-use head
    assert out["landuse"].shape == (2, 6, 256, 256)
    assert probs["landuse"].shape == (2, 6, 256, 256)
    # Check softmax sum across 6 classes equals 1.0
    sum_probs = probs["landuse"].sum(dim=1)
    assert torch.allclose(sum_probs, torch.ones_like(sum_probs), atol=1e-4)


def test_multitask_loss_with_full_and_partial_targets():
    criterion = MultiTaskLoss(landuse_classes=6)

    preds = {
        "building": torch.randn(2, 1, 64, 64),
        "road": torch.randn(2, 1, 64, 64),
        "boundary": torch.randn(2, 1, 64, 64),
        "landuse": torch.randn(2, 6, 64, 64),
    }

    full_targets = {
        "building": torch.randint(0, 2, (2, 1, 64, 64)).float(),
        "road": torch.randint(0, 2, (2, 1, 64, 64)).float(),
        "boundary": torch.randint(0, 2, (2, 1, 64, 64)).float(),
        "landuse": torch.randint(0, 6, (2, 64, 64)).long(),
    }

    loss, loss_dict = criterion(preds, full_targets)
    assert loss.item() > 0.0
    assert "loss_building" in loss_dict
    assert "loss_road" in loss_dict
    assert "loss_boundary" in loss_dict
    assert "loss_landuse" in loss_dict

    # Partial / Masked targets test (only building & road labeled)
    partial_targets = {
        "building": full_targets["building"],
        "road": full_targets["road"],
        "boundary": None,
        "landuse": None,
    }
    partial_loss, partial_loss_dict = criterion(preds, partial_targets)
    assert partial_loss.item() > 0.0
    assert "loss_building" in partial_loss_dict
    assert "loss_road" in partial_loss_dict
    assert "loss_boundary" not in partial_loss_dict
    assert "loss_landuse" not in partial_loss_dict


def test_synthetic_geo_dataset():
    ds = SyntheticGeoDataset(num_samples=4, image_size=256, in_channels=4)
    assert len(ds) == 4

    sample = ds[0]
    assert sample["image"].shape == (4, 256, 256)
    assert sample["building"].shape == (1, 256, 256)
    assert sample["road"].shape == (1, 256, 256)
    assert sample["boundary"].shape == (1, 256, 256)
    assert sample["landuse"].shape == (256, 256)


def test_train_smoke_test(tmp_path: Path):
    config = {
        "encoder_name": "resnet34",
        "in_channels": 4,
        "landuse_classes": 6,
        "lr": 1e-3,
        "device": "cpu",
    }
    ckpt = run_training(config=config, smoke_test=True, output_dir=str(tmp_path))
    assert ckpt.exists()


def test_export_model_package(tmp_path: Path):
    # Train dummy model
    model = MultiTaskUnet(encoder_name="resnet34", encoder_weights=None, in_channels=4)
    dummy_ckpt = tmp_path / "test_ckpt.pt"
    torch.save({"model_state_dict": model.state_dict()}, dummy_ckpt)

    out_dir = tmp_path / "exported"
    w_path, meta_path = export_model_package(
        checkpoint_path=dummy_ckpt,
        output_dir=out_dir,
        in_channels=4,
    )

    assert w_path.exists()
    assert meta_path.exists()

    with open(meta_path, encoding="utf-8") as f:
        meta = json.load(f)
    assert meta["architecture"] == "MultiTaskUnet"
    assert "building" in meta["tasks"]
    assert "road" in meta["tasks"]
    assert "boundary" in meta["tasks"]
    assert "landuse" in meta["tasks"]
