"""Multi-task neural network architecture for ParcelAI (Section 7.2).

Architecture:
- Shared encoder (ResNet34 by default) extracting multi-scale feature maps.
- Four multi-task segmentation decoder heads:
  1. Building footprint head: (B, 1, H, W) binary logits
  2. Road network head: (B, 1, H, W) binary logits
  3. Parcel boundary / edge head: (B, 1, H, W) binary logits
  4. Land-use classification head: (B, 6, H, W) multi-class logits
"""

from __future__ import annotations

from typing import Any

import segmentation_models_pytorch as smp
import torch
from torch import nn


class MultiTaskHead(nn.Module):
    """Segmentation output head with Conv3x3 -> ReLU -> Conv1x1."""

    def __init__(self, in_channels: int, out_channels: int):
        super().__init__()
        self.block = nn.Sequential(
            nn.Conv2d(in_channels, in_channels // 2, kernel_size=3, padding=1, bias=False),
            nn.BatchNorm2d(in_channels // 2),
            nn.ReLU(inplace=True),
            nn.Conv2d(in_channels // 2, out_channels, kernel_size=1),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.block(x)


class MultiTaskUnet(nn.Module):
    """Multi-task UNet with shared encoder and four specialized decoder heads."""

    def __init__(
        self,
        encoder_name: str = "resnet34",
        encoder_weights: str | None = "imagenet",
        in_channels: int = 4,
        landuse_classes: int = 6,
        decoder_channels: tuple[int, ...] = (256, 128, 64, 32, 16),
    ):
        super().__init__()
        self.encoder_name = encoder_name
        self.in_channels = in_channels
        self.landuse_classes = landuse_classes

        # Base UNet from segmentation_models_pytorch
        base_unet = smp.Unet(
            encoder_name=encoder_name,
            encoder_weights=encoder_weights,
            in_channels=in_channels,
            classes=decoder_channels[-1],
            decoder_channels=decoder_channels,
        )

        self.encoder = base_unet.encoder
        self.decoder = base_unet.decoder

        feature_dim = decoder_channels[-1]

        # 4 Multi-Task Heads
        self.building_head = MultiTaskHead(feature_dim, 1)
        self.road_head = MultiTaskHead(feature_dim, 1)
        self.boundary_head = MultiTaskHead(feature_dim, 1)
        self.landuse_head = MultiTaskHead(feature_dim, landuse_classes)

    def forward(self, x: torch.Tensor) -> dict[str, torch.Tensor]:
        """Forward pass returning logits for all four heads."""
        features = self.encoder(x)
        decoder_output = self.decoder(features)

        return {
            "building": self.building_head(decoder_output),
            "road": self.road_head(decoder_output),
            "boundary": self.boundary_head(decoder_output),
            "landuse": self.landuse_head(decoder_output),
        }

    def predict_probabilities(self, x: torch.Tensor) -> dict[str, torch.Tensor]:
        """Forward pass with sigmoid and softmax applied."""
        logits = self.forward(x)
        return {
            "building": torch.sigmoid(logits["building"]),
            "road": torch.sigmoid(logits["road"]),
            "boundary": torch.sigmoid(logits["boundary"]),
            "landuse": torch.softmax(logits["landuse"], dim=1),
        }


def build_model(config: dict[str, Any] | None = None) -> MultiTaskUnet:
    """Factory helper to build model from config dictionary."""
    cfg = config or {}
    return MultiTaskUnet(
        encoder_name=cfg.get("encoder_name", "resnet34"),
        encoder_weights=cfg.get("encoder_weights", "imagenet"),
        in_channels=cfg.get("in_channels", 4),
        landuse_classes=cfg.get("landuse_classes", 6),
    )
