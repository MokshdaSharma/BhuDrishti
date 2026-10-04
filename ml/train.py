"""Training script for ParcelAI multi-task model (Section 7.2).

Usage:
  python ml/train.py --smoke-test
  python ml/train.py --config ml/configs/default.yaml --epochs 25
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Any

import torch
import yaml
from torch.utils.data import DataLoader

from ml.datasets.dataset import SyntheticGeoDataset
from ml.losses import MultiTaskLoss, compute_metrics
from ml.model import MultiTaskUnet

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def train_one_epoch(
    model: MultiTaskUnet,
    loader: DataLoader,
    optimizer: torch.optim.Optimizer,
    criterion: MultiTaskLoss,
    device: torch.device,
    scaler: torch.amp.GradScaler | None = None,
    max_steps: int | None = None,
) -> dict[str, float]:
    """Train for one epoch or up to max_steps."""
    model.train()
    total_loss = 0.0
    num_batches = 0

    for step, batch in enumerate(loader):
        if max_steps is not None and step >= max_steps:
            break

        images = batch["image"].to(device)
        targets = {
            k: (v.to(device) if v is not None else None)
            for k, v in batch.items()
            if k != "image"
        }

        optimizer.zero_grad()

        if scaler is not None and device.type == "cuda":
            with torch.amp.autocast(device_type="cuda", dtype=torch.float16):
                outputs = model(images)
                loss, _ = criterion(outputs, targets)
            scaler.scale(loss).backward()
            scaler.step(optimizer)
            scaler.update()
        else:
            outputs = model(images)
            loss, _ = criterion(outputs, targets)
            loss.backward()
            optimizer.step()

        total_loss += float(loss.item())
        num_batches += 1

    return {"loss": total_loss / max(1, num_batches)}


def evaluate(
    model: MultiTaskUnet,
    loader: DataLoader,
    criterion: MultiTaskLoss,
    device: torch.device,
    max_steps: int | None = None,
) -> dict[str, float]:
    """Evaluate model on validation loader and compute metrics."""
    model.eval()
    total_loss = 0.0
    num_batches = 0
    all_metrics: list[dict[str, float]] = []

    with torch.no_grad():
        for step, batch in enumerate(loader):
            if max_steps is not None and step >= max_steps:
                break

            images = batch["image"].to(device)
            targets = {
                k: (v.to(device) if v is not None else None)
                for k, v in batch.items()
                if k != "image"
            }

            outputs = model(images)
            loss, _ = criterion(outputs, targets)
            metrics = compute_metrics(outputs, targets)

            total_loss += float(loss.item())
            all_metrics.append(metrics)
            num_batches += 1

    summary: dict[str, float] = {"val_loss": total_loss / max(1, num_batches)}
    if all_metrics:
        for k in all_metrics[0]:
            summary[f"val_{k}"] = sum(m.get(k, 0.0) for m in all_metrics) / len(all_metrics)

    return summary


def run_training(
    config: dict[str, Any],
    smoke_test: bool = False,
    output_dir: str = "backend/models_store",
) -> Path:
    """Main training orchestration function."""
    device = torch.device(config.get("device", "cuda" if torch.cuda.is_available() else "cpu"))
    logger.info(f"Using device: {device} (smoke_test={smoke_test})")

    out_p = Path(output_dir)
    out_p.mkdir(parents=True, exist_ok=True)

    # Initialize model
    model = MultiTaskUnet(
        encoder_name=config.get("encoder_name", "resnet34"),
        encoder_weights=None if smoke_test else config.get("encoder_weights", "imagenet"),
        in_channels=config.get("in_channels", 4),
        landuse_classes=config.get("landuse_classes", 6),
    ).to(device)

    criterion = MultiTaskLoss(landuse_classes=config.get("landuse_classes", 6))
    optimizer = torch.optim.AdamW(model.parameters(), lr=config.get("lr", 1e-4), weight_decay=1e-4)
    scaler = torch.amp.GradScaler("cuda") if device.type == "cuda" else None

    if smoke_test:
        logger.info("Executing smoke test with synthetic dataset (2 steps)...")
        train_dataset = SyntheticGeoDataset(num_samples=8, image_size=512, in_channels=config.get("in_channels", 4))
        val_dataset = SyntheticGeoDataset(num_samples=4, image_size=512, in_channels=config.get("in_channels", 4))

        train_loader = DataLoader(train_dataset, batch_size=2, shuffle=False)
        val_loader = DataLoader(val_dataset, batch_size=2, shuffle=False)

        train_res = train_one_epoch(model, train_loader, optimizer, criterion, device, scaler, max_steps=2)
        val_res = evaluate(model, val_loader, criterion, device, max_steps=1)

        logger.info(f"Smoke test complete! Train: {train_res}, Val: {val_res}")

        ckpt_path = out_p / "model_smoke_test.pt"
        torch.save({"model_state_dict": model.state_dict(), "config": config}, ckpt_path)
        return ckpt_path

    # Full training loop (when real data is provided)
    epochs = config.get("epochs", 10)
    batch_size = config.get("batch_size", 4)

    logger.info(f"Starting training for {epochs} epochs (batch_size={batch_size})...")
    # For full runs without external data, Synthetic dataset acts as placeholder
    train_dataset = SyntheticGeoDataset(num_samples=64, in_channels=config.get("in_channels", 4))
    val_dataset = SyntheticGeoDataset(num_samples=16, in_channels=config.get("in_channels", 4))

    train_loader = DataLoader(train_dataset, batch_size=batch_size, shuffle=True)
    val_loader = DataLoader(val_dataset, batch_size=batch_size, shuffle=False)

    best_loss = float("inf")
    best_ckpt = out_p / "best_model.pt"

    for epoch in range(1, epochs + 1):
        train_metrics = train_one_epoch(model, train_loader, optimizer, criterion, device, scaler)
        val_metrics = evaluate(model, val_loader, criterion, device)

        logger.info(f"Epoch {epoch:02d}/{epochs:02d} - Train Loss: {train_metrics['loss']:.4f} - Val Loss: {val_metrics['val_loss']:.4f}")

        if val_metrics["val_loss"] < best_loss:
            best_loss = val_metrics["val_loss"]
            torch.save(
                {
                    "epoch": epoch,
                    "model_state_dict": model.state_dict(),
                    "optimizer_state_dict": optimizer.state_dict(),
                    "config": config,
                    "val_metrics": val_metrics,
                },
                best_ckpt,
            )

    return best_ckpt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ParcelAI ML Training")
    parser.add_argument("--config", type=str, default=None, help="Path to YAML training config")
    parser.add_argument("--smoke-test", action="store_true", help="Run 2-step verification smoke test")
    parser.add_argument("--epochs", type=int, default=10, help="Number of epochs")
    parser.add_argument("--batch-size", type=int, default=4, help="Batch size")
    parser.add_argument("--lr", type=float, default=1e-4, help="Learning rate")
    parser.add_argument("--output-dir", type=str, default="backend/models_store", help="Checkpoint directory")
    parser.add_argument("--device", type=str, default=None, help="Device (cpu or cuda)")

    args = parser.parse_args()

    cfg: dict[str, Any] = {}
    if args.config and Path(args.config).exists():
        with open(args.config, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)

    if args.epochs:
        cfg["epochs"] = args.epochs
    if args.batch_size:
        cfg["batch_size"] = args.batch_size
    if args.lr:
        cfg["lr"] = args.lr
    if args.device:
        cfg["device"] = args.device

    ckpt = run_training(config=cfg, smoke_test=args.smoke_test, output_dir=args.output_dir)
    print(f"Checkpointed to: {ckpt}")
