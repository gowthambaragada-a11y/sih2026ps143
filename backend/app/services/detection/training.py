"""Dataset, loss functions, metrics and training loop for segmentation."""
from __future__ import annotations

import logging
from typing import List, Optional, Sequence, Tuple

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import Dataset

from ...core.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Losses
# ---------------------------------------------------------------------------
class DiceBCE(nn.Module):
    """Dice loss + (binary/categorical) cross entropy, configurable."""

    def __init__(self, n_classes: int = 5, binary: bool = False, weight_bce: float = 0.5):
        super().__init__()
        self.n_classes = n_classes
        self.binary = binary
        self.weight_bce = weight_bce

    def forward(self, logits: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
        if self.binary:
            prob = torch.sigmoid(logits)
            target_1h = target.float()
            bce = F.binary_cross_entropy(prob, target_1h)
            dice = self._dice(prob, target_1h)
        else:
            prob = torch.softmax(logits, dim=1)
            target_1h = F.one_hot(target.long(), self.n_classes).permute(0, 3, 1, 2).float()
            bce = F.cross_entropy(logits, target.long())
            dice = self._dice(prob, target_1h)
        return self.weight_bce * bce + (1.0 - self.weight_bce) * (1.0 - dice)

    @staticmethod
    def _dice(prob, target_1h):
        smooth = 1.0
        inter = (prob * target_1h).sum(dim=(2, 3))
        denom = prob.sum(dim=(2, 3)) + target_1h.sum(dim=(2, 3)) + smooth
        return ((2.0 * inter + smooth) / denom).mean()


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------
def dice_score(pred: np.ndarray, target: np.ndarray, cls: int = 1) -> float:
    p = (pred == cls).astype(np.uint8)
    t = (target == cls).astype(np.uint8)
    inter = np.logical_and(p, t).sum()
    denom = p.sum() + t.sum()
    return float(2 * inter / (denom + 1e-6)) if denom > 0 else 0.0


def iou_score(pred: np.ndarray, target: np.ndarray, cls: int = 1) -> float:
    p = (pred == cls).astype(np.uint8)
    t = (target == cls).astype(np.uint8)
    inter = np.logical_and(p, t).sum()
    union = np.logical_or(p, t).sum()
    return float(inter / (union + 1e-6)) if union > 0 else 0.0


def pixel_metrics(pred: np.ndarray, target: np.ndarray, cls: int = 1) -> dict:
    p = (pred == cls).astype(np.uint8)
    t = (target == cls).astype(np.uint8)
    tp = np.logical_and(p, t).sum()
    fp = np.logical_and(p, ~t.astype(bool)).sum()
    fn = np.logical_and(~p.astype(bool), t).sum()
    prec = tp / (tp + fp + 1e-6)
    rec = tp / (tp + fn + 1e-6)
    f1 = 2 * prec * rec / (prec + rec + 1e-6)
    # false-positive rate = FP / total negative pixels
    neg = (~t.astype(bool)).sum()
    fpr = fp / (neg + 1e-6)
    return {"precision": float(prec), "recall": float(rec), "f1": float(f1),
            "false_positive_rate": float(fpr)}


def evaluate_segmentation(pred: np.ndarray, target: np.ndarray, n_classes: int) -> dict:
    """Aggregate per-class IoU/Dice over a batch of stacked predictions."""
    metrics = {}
    for c in range(n_classes):
        metrics[f"iou_class{c}"] = iou_score(pred, target, cls=c)
        metrics[f"dice_class{c}"] = dice_score(pred, target, cls=c)
    # oil (class 1) precision/recall/F1/fpr
    metrics.update(pixel_metrics(pred, target, cls=1))
    metrics["mean_iou"] = float(np.mean([iou_score(pred, target, c) for c in range(n_classes)]))
    return metrics


# ---------------------------------------------------------------------------
# Dataset
# ---------------------------------------------------------------------------
class SyntheticSegDataset(Dataset):
    """Dataset over synthetic (or pre-tiled) SAR scenes with multi-class labels.

    scenes: list of SyntheticScene objects.
    augment: whether to apply random flips/rotations.
    """

    def __init__(self, scenes, n_classes: int = 5, augment: bool = True, binary: bool = False):
        self.scenes = scenes
        self.n_classes = 1 if binary else n_classes
        self.augment = augment
        self.binary = binary

    def __len__(self):
        return len(self.scenes)

    def __getitem__(self, idx):
        scene = self.scenes[idx]
        chs = scene.channels()
        x = np.stack(chs, axis=0).astype(np.float32)
        lab = scene.label_rgb()
        if self.binary:
            y = (lab == 1).astype(np.float32)
        else:
            y = lab.astype(np.int64)

        if self.augment:
            as_int16 = y.astype(np.int64)
            # random flips
            if np.random.rand() < 0.5:
                x = x[:, :, ::-1]
                as_int16 = as_int16[:, ::-1]
            if np.random.rand() < 0.5:
                x = x[:, ::-1, :]
                as_int16 = as_int16[::-1, :]
            # random rotation
            k = np.random.randint(0, 4)
            x = np.rot90(x, k, axes=(1, 2))
            as_int16 = np.rot90(as_int16, k)
            y = as_int16
        return torch.from_numpy(x.copy()), torch.from_numpy(y.copy()).long()


# ---------------------------------------------------------------------------
# Trainer
# ---------------------------------------------------------------------------
def train_segmentation(
    model: nn.Module,
    train_scenes,
    val_scenes,
    n_classes: int = 5,
    binary: bool = False,
    epochs: int = 12,
    lr: float = 1e-3,
    batch_size: int = 8,
    device: str = "auto",
) -> dict:
    if device == "auto":
        device = "cuda" if torch.cuda.is_available() else "cpu"
    device = torch.device(device)
    model = model.to(device)

    train_ds = SyntheticSegDataset(train_scenes, n_classes=n_classes, augment=True, binary=binary)
    val_ds = SyntheticSegDataset(val_scenes, n_classes=n_classes, augment=False, binary=binary)
    train_loader = torch.utils.data.DataLoader(train_ds, batch_size=batch_size, shuffle=True)
    val_loader = torch.utils.data.DataLoader(val_ds, batch_size=batch_size, shuffle=False)

    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=epochs)
    criterion = DiceBCE(n_classes=n_classes, binary=binary)

    history = {"train_loss": [], "val_loss": [], "val_dice": []}
    best_dice = -1.0
    best_state = None

    for epoch in range(epochs):
        model.train()
        tl = 0.0
        nbat = 0
        for xb, yb in train_loader:
            xb, yb = xb.to(device), yb.to(device)
            if binary:
                yb = yb.float()
            opt.zero_grad()
            out = model(xb)
            loss = criterion(out, yb)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            tl += loss.item()
            nbat += 1
        sched.step()

        # validation
        model.eval()
        vdice = 0.0
        with torch.no_grad():
            for xb, yb in val_loader:
                xb, yb = xb.to(device), yb.to(device)
                out = model(xb)
                if binary:
                    pred = (torch.sigmoid(out) > 0.5).long()
                else:
                    pred = out.argmax(dim=1)
                pd = pred.cpu().numpy().reshape(-1)
                td = yb.cpu().numpy().reshape(-1)
                vdice += dice_score(pd, td, cls=1)
        vdice /= max(len(val_loader), 1)

        history["train_loss"].append(tl / nbat)
        history["val_dice"].append(vdice)
        if vdice > best_dice:
            best_dice = vdice
            best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
        logger.info("epoch %d/%d loss=%.4f val_dice=%.4f", epoch + 1, epochs,
                    tl / nbat, vdice)

    history["best_val_dice"] = best_dice
    history["best_state_dict"] = best_state
    return history


def inference_segmentation(model: nn.Module, x: np.ndarray, binary: bool = False,
                           device="auto") -> np.ndarray:
    """Run a (C,H,W) array through the model and return argmax class map."""
    if device == "auto":
        device = "cuda" if torch.cuda.is_available() else "cpu"
    model.eval()
    xt = torch.from_numpy(np.asarray(x, np.float32)).unsqueeze(0)
    with torch.no_grad():
        out = model(xt.to(device))
        if binary:
            pred = (torch.sigmoid(out) > 0.5).long()
        else:
            pred = out.argmax(dim=1)
    return pred[0].cpu().numpy()
