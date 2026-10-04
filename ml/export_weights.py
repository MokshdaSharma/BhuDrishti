"""Weight export script for ParcelAI (Section 7.2).

Exports:
- PyTorch state_dict (.pt file)
- metadata.json describing architecture, class names, normalization parameters, and model schema
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import torch

from ml.model import MultiTaskUnet


def export_model_package(
    checkpoint_path: str | Path,
    output_dir: str | Path,
    encoder_name: str = "resnet34",
    in_channels: int = 4,
    landuse_classes: int = 6,
) -> tuple[Path, Path]:
    """Load trained weights, validate forward pass, and export weights + metadata.json."""
    ckpt_p = Path(checkpoint_path)
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    model = MultiTaskUnet(
        encoder_name=encoder_name,
        encoder_weights=None,
        in_channels=in_channels,
        landuse_classes=landuse_classes,
    )

    if ckpt_p.exists():
        state = torch.load(ckpt_p, map_location="cpu", weights_only=True)
        if isinstance(state, dict) and "model_state_dict" in state:
            model.load_state_dict(state["model_state_dict"])
        elif isinstance(state, dict):
            model.load_state_dict(state)

    model.eval()

    # Verify dummy inference
    dummy = torch.randn(1, in_channels, 512, 512)
    with torch.no_grad():
        out = model.predict_probabilities(dummy)
        assert "building" in out and "road" in out and "boundary" in out and "landuse" in out

    weights_file = out_dir / "parcelai_v1.pt"
    torch.save(model.state_dict(), weights_file)

    meta_file = out_dir / "metadata.json"
    meta = {
        "model_name": "ParcelAI-MultiTask-v1",
        "architecture": "MultiTaskUnet",
        "encoder": encoder_name,
        "in_channels": in_channels,
        "input_channels": ["red", "green", "blue", "ndsm"] if in_channels == 4 else ["red", "green", "blue"],
        "tasks": {
            "building": {"type": "binary_segmentation", "channels": 1},
            "road": {"type": "binary_segmentation", "channels": 1},
            "boundary": {"type": "binary_edge_detection", "channels": 1},
            "landuse": {
                "type": "multiclass_segmentation",
                "classes": [
                    "built_up",
                    "road",
                    "vegetation",
                    "water",
                    "open_land",
                    "other",
                ],
            },
        },
        "normalization": {
            "mean": [0.485, 0.456, 0.406, 0.0],
            "std": [0.229, 0.224, 0.225, 1.0],
        },
        "tile_size": 512,
        "overlap": 0.25,
    }

    with open(meta_file, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

    return weights_file, meta_file


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Export ParcelAI model weights and metadata")
    parser.add_argument("--checkpoint", type=str, default="backend/models_store/best_model.pt", help="Input checkpoint")
    parser.add_argument("--output-dir", type=str, default="backend/models_store", help="Output directory")
    args = parser.parse_args()

    w, m = export_model_package(args.checkpoint, args.output_dir)
    print(f"Exported weights: {w}")
    print(f"Exported metadata: {m}")
