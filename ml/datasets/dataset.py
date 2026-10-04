"""Dataset loaders for multi-task parcel mapping (Section 7.2).

Includes:
- LocalGeoDataset: Loads 4-channel (RGB + nDSM) or 3-channel (RGB) tiles with multi-task masks
- SyntheticGeoDataset: Generates synthetic on-the-fly tiles for smoke tests and unit testing
- Albumentations training and validation pipelines
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import albumentations as A
import numpy as np
import torch
from albumentations.pytorch import ToTensorV2
from torch.utils.data import Dataset


def get_train_transforms(image_size: int = 512) -> A.Compose:
    """Standard spatial and photometric data augmentations."""
    return A.Compose(
        [
            A.RandomCrop(image_size, image_size),
            A.HorizontalFlip(p=0.5),
            A.VerticalFlip(p=0.5),
            A.RandomRotate90(p=0.5),
            A.ColorJitter(brightness=0.2, contrast=0.2, saturation=0.2, p=0.4),
            A.Normalize(mean=(0.485, 0.456, 0.406, 0.0), std=(0.229, 0.224, 0.225, 1.0), max_pixel_value=255.0),
            ToTensorV2(),
        ],
        additional_targets={
            "mask_road": "mask",
            "mask_boundary": "mask",
            "mask_landuse": "mask",
        },
    )


def get_val_transforms(image_size: int = 512) -> A.Compose:
    """Validation deterministic preprocessing."""
    return A.Compose(
        [
            A.CenterCrop(image_size, image_size),
            A.Normalize(mean=(0.485, 0.456, 0.406, 0.0), std=(0.229, 0.224, 0.225, 1.0), max_pixel_value=255.0),
            ToTensorV2(),
        ],
        additional_targets={
            "mask_road": "mask",
            "mask_boundary": "mask",
            "mask_landuse": "mask",
        },
    )


class SyntheticGeoDataset(Dataset):
    """Generates synthetic 4-channel (RGB+nDSM) image tiles and multi-task masks on the fly."""

    def __init__(
        self,
        num_samples: int = 32,
        image_size: int = 512,
        in_channels: int = 4,
        seed: int = 42,
    ):
        super().__init__()
        self.num_samples = num_samples
        self.image_size = image_size
        self.in_channels = in_channels
        self.rng = np.random.RandomState(seed)

    def __len__(self) -> int:
        return self.num_samples

    def __getitem__(self, idx: int) -> dict[str, Any]:
        h, w = self.image_size, self.image_size

        # Synthetic RGB imagery (3 channels uint8)
        rgb = self.rng.randint(30, 220, size=(h, w, 3), dtype=np.uint8)

        # Synthetic nDSM (1 channel float32)
        ndsm = np.zeros((h, w, 1), dtype=np.float32)

        # Building mask (1 channel uint8)
        mask_building = np.zeros((h, w), dtype=np.uint8)
        # Road mask (1 channel uint8)
        mask_road = np.zeros((h, w), dtype=np.uint8)
        # Boundary mask (1 channel uint8)
        mask_boundary = np.zeros((h, w), dtype=np.uint8)
        # Landuse mask (1 channel uint8, values 0..5)
        mask_landuse = np.zeros((h, w), dtype=np.uint8)

        # Add 2 synthetic buildings
        mask_building[100:220, 100:220] = 1
        ndsm[100:220, 100:220, 0] = 8.5
        mask_landuse[100:220, 100:220] = 0  # built_up

        mask_building[300:400, 320:440] = 1
        ndsm[300:400, 320:440, 0] = 12.0
        mask_landuse[300:400, 320:440] = 0  # built_up

        # Add a road across the image
        mask_road[240:270, :] = 1
        mask_landuse[240:270, :] = 1  # road

        # Add boundary around buildings and road
        mask_boundary[98:102, 100:220] = 1
        mask_boundary[218:222, 100:220] = 1
        mask_boundary[100:220, 98:102] = 1
        mask_boundary[100:220, 218:222] = 1

        # Vegetation & open land in rest
        mask_landuse[0:100, :] = 2  # vegetation

        if self.in_channels == 4:
            # Stack RGB and nDSM -> (H, W, 4)
            image = np.concatenate([rgb.astype(np.float32), ndsm], axis=-1)
        else:
            image = rgb.astype(np.float32)

        # Convert to torch tensors
        # Image shape: (C, H, W)
        image_t = torch.from_numpy(image).permute(2, 0, 1).float()
        # Normalize RGB to [0, 1]
        image_t[:3] = image_t[:3] / 255.0

        return {
            "image": image_t,
            "building": torch.from_numpy(mask_building).unsqueeze(0).float(),
            "road": torch.from_numpy(mask_road).unsqueeze(0).float(),
            "boundary": torch.from_numpy(mask_boundary).unsqueeze(0).float(),
            "landuse": torch.from_numpy(mask_landuse).long(),
        }


class LocalGeoDataset(Dataset):
    """Dataset for tiled local aerial imagery and multi-task raster masks."""

    def __init__(
        self,
        image_paths: list[str | Path],
        mask_paths: dict[str, list[str | Path]] | None = None,
        transform: Callable | None = None,
        in_channels: int = 4,
    ):
        super().__init__()
        self.image_paths = [Path(p) for p in image_paths]
        self.mask_paths = mask_paths or {}
        self.transform = transform
        self.in_channels = in_channels

    def __len__(self) -> int:
        return len(self.image_paths)

    def __getitem__(self, idx: int) -> dict[str, Any]:
        import rasterio

        img_path = self.image_paths[idx]
        with rasterio.open(img_path) as src:
            img = src.read()  # (C, H, W)
            img = np.transpose(img, (1, 2, 0)).astype(np.float32)  # (H, W, C)

        targets: dict[str, torch.Tensor | None] = {}
        for task in ["building", "road", "boundary", "landuse"]:
            if task in self.mask_paths and idx < len(self.mask_paths[task]):
                mask_p = self.mask_paths[task][idx]
                with rasterio.open(mask_p) as msrc:
                    mask = msrc.read(1)
                    if task == "landuse":
                        targets[task] = torch.from_numpy(mask).long()
                    else:
                        targets[task] = torch.from_numpy(mask).unsqueeze(0).float()
            else:
                targets[task] = None

        img_t = torch.from_numpy(img).permute(2, 0, 1).float()
        if img_t.shape[0] >= 3:
            img_t[:3] = img_t[:3] / 255.0

        return {
            "image": img_t,
            **targets,
        }
