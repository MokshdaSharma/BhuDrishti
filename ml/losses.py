"""Loss functions and evaluation metrics for multi-task parcel mapping (Section 7.2).

Includes:
- Binary Dice Loss and Multi-class Dice Loss
- Soft clDice (centerline Dice) for connected road topological continuity
- MultiTaskLoss with masked loss computation for partially labeled datasets
- Metrics: IoU, F1 score, Precision, Recall
"""

from __future__ import annotations

import torch
import torch.nn.functional as F
from torch import nn


class DiceLoss(nn.Module):
    """Binary Dice loss with numerical smoothing."""

    def __init__(self, smooth: float = 1.0):
        super().__init__()
        self.smooth = smooth

    def forward(self, logits: torch.Tensor, targets: torch.Tensor) -> torch.Tensor:
        probs = torch.sigmoid(logits)
        probs_flat = probs.view(-1)
        targets_flat = targets.view(-1).float()

        intersection = (probs_flat * targets_flat).sum()
        dice = (2.0 * intersection + self.smooth) / (probs_flat.sum() + targets_flat.sum() + self.smooth)
        return 1.0 - dice


class MulticlassDiceLoss(nn.Module):
    """Multi-class Dice loss computed per-class and averaged."""

    def __init__(self, num_classes: int = 6, smooth: float = 1.0):
        super().__init__()
        self.num_classes = num_classes
        self.smooth = smooth

    def forward(self, logits: torch.Tensor, targets: torch.Tensor) -> torch.Tensor:
        probs = torch.softmax(logits, dim=1)
        targets_one_hot = F.one_hot(targets.long(), num_classes=self.num_classes).permute(0, 3, 1, 2).float()

        dims = (0, 2, 3)
        intersection = (probs * targets_one_hot).sum(dim=dims)
        cardinality = (probs + targets_one_hot).sum(dim=dims)

        dice = (2.0 * intersection + self.smooth) / (cardinality + self.smooth)
        return 1.0 - dice.mean()


class SoftclDiceLoss(nn.Module):
    """Soft centerline Dice loss for topology and connectivity preservation (roads)."""

    def __init__(self, iter_: int = 3, smooth: float = 1.0):
        super().__init__()
        self.iter = iter_
        self.smooth = smooth

    def _soft_erode(self, img: torch.Tensor) -> torch.Tensor:
        p1 = -F.max_pool2d(-img, (3, 1), (1, 1), (1, 0))
        p2 = -F.max_pool2d(-img, (1, 3), (1, 1), (0, 1))
        return torch.min(p1, p2)

    def _soft_dilate(self, img: torch.Tensor) -> torch.Tensor:
        return F.max_pool2d(img, (3, 3), (1, 1), (1, 1))

    def _soft_open(self, img: torch.Tensor) -> torch.Tensor:
        return self._soft_dilate(self._soft_erode(img))

    def _soft_skel(self, img: torch.Tensor) -> torch.Tensor:
        img1 = self._soft_open(img)
        skel = F.relu(img - img1)
        for _ in range(self.iter):
            img = self._soft_erode(img)
            img1 = self._soft_open(img)
            delta = F.relu(img - img1)
            skel = skel + F.relu(delta - skel * delta)
        return skel

    def forward(self, logits: torch.Tensor, targets: torch.Tensor) -> torch.Tensor:
        probs = torch.sigmoid(logits)
        targets = targets.float()

        skel_pred = self._soft_skel(probs)
        skel_true = self._soft_skel(targets)

        tprec = (torch.sum(skel_pred * targets) + self.smooth) / (torch.sum(skel_pred) + self.smooth)
        tsens = (torch.sum(skel_true * probs) + self.smooth) / (torch.sum(skel_true) + self.smooth)
        cl_dice = 2.0 * (tprec * tsens) / (tprec + tsens)
        return 1.0 - cl_dice


class MultiTaskLoss(nn.Module):
    """Multi-task loss aggregating losses from all available heads with masked losses."""

    def __init__(
        self,
        weights: dict[str, float] | None = None,
        landuse_classes: int = 6,
    ):
        super().__init__()
        self.weights = weights or {
            "building": 1.0,
            "road": 1.0,
            "boundary": 1.0,
            "landuse": 1.0,
        }
        self.bce = nn.BCEWithLogitsLoss()
        self.dice = DiceLoss()
        self.cldice = SoftclDiceLoss(iter_=2)
        self.ce = nn.CrossEntropyLoss()
        self.mc_dice = MulticlassDiceLoss(num_classes=landuse_classes)

    def forward(
        self,
        predictions: dict[str, torch.Tensor],
        targets: dict[str, torch.Tensor | None],
    ) -> tuple[torch.Tensor, dict[str, float]]:
        """Compute aggregated loss, ignoring tasks where targets are None."""
        total_loss = torch.tensor(0.0, device=predictions["building"].device, requires_grad=True)
        loss_dict: dict[str, float] = {}

        # 1. Building head (BCE + Dice)
        if targets.get("building") is not None:
            t = targets["building"].float()
            p = predictions["building"]
            loss_bldg = self.bce(p, t) + self.dice(p, t)
            total_loss = total_loss + self.weights.get("building", 1.0) * loss_bldg
            loss_dict["loss_building"] = float(loss_bldg.item())

        # 2. Road head (BCE + Dice + soft clDice)
        if targets.get("road") is not None:
            t = targets["road"].float()
            p = predictions["road"]
            loss_road = self.bce(p, t) + 0.7 * self.dice(p, t) + 0.3 * self.cldice(p, t)
            total_loss = total_loss + self.weights.get("road", 1.0) * loss_road
            loss_dict["loss_road"] = float(loss_road.item())

        # 3. Boundary head (Weighted BCE)
        if targets.get("boundary") is not None:
            t = targets["boundary"].float()
            p = predictions["boundary"]
            loss_boundary = self.bce(p, t) + self.dice(p, t)
            total_loss = total_loss + self.weights.get("boundary", 1.0) * loss_boundary
            loss_dict["loss_boundary"] = float(loss_boundary.item())

        # 4. Land-use head (CrossEntropy + Multi-class Dice)
        if targets.get("landuse") is not None:
            t = targets["landuse"].long()
            p = predictions["landuse"]
            loss_landuse = self.ce(p, t) + self.mc_dice(p, t)
            total_loss = total_loss + self.weights.get("landuse", 1.0) * loss_landuse
            loss_dict["loss_landuse"] = float(loss_landuse.item())

        loss_dict["total_loss"] = float(total_loss.item())
        return total_loss, loss_dict


def compute_metrics(
    predictions: dict[str, torch.Tensor],
    targets: dict[str, torch.Tensor | None],
    threshold: float = 0.5,
) -> dict[str, float]:
    """Calculate IoU, F1, precision, and recall across multi-task heads."""
    metrics: dict[str, float] = {}

    for task in ["building", "road", "boundary"]:
        if targets.get(task) is not None:
            pred_bin = (torch.sigmoid(predictions[task]) > threshold).float().view(-1)
            true_bin = (targets[task] > 0.5).float().view(-1)

            tp = (pred_bin * true_bin).sum().item()
            fp = (pred_bin * (1.0 - true_bin)).sum().item()
            fn = ((1.0 - pred_bin) * true_bin).sum().item()

            iou = tp / (tp + fp + fn + 1e-6)
            prec = tp / (tp + fp + 1e-6)
            rec = tp / (tp + fn + 1e-6)
            f1 = 2.0 * prec * rec / (prec + rec + 1e-6)

            metrics[f"{task}_iou"] = float(iou)
            metrics[f"{task}_f1"] = float(f1)
            metrics[f"{task}_precision"] = float(prec)
            metrics[f"{task}_recall"] = float(rec)

    # Multi-class landuse accuracy & mean IoU
    if targets.get("landuse") is not None:
        pred_cls = torch.argmax(predictions["landuse"], dim=1).view(-1)
        true_cls = targets["landuse"].long().view(-1)
        acc = (pred_cls == true_cls).float().mean().item()
        metrics["landuse_acc"] = float(acc)

    return metrics
