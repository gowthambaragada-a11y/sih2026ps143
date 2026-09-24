"""Train all OILTRACE-AI models on synthetic demo + generated data.

This script is what a reviewer runs to reproduce the model artifacts:
    python -m app.services.training --all

It trains:
    * oil segmentation U-Net (and optionally SegFormer) on synthetic scenes
    * origin XGBoost model
    * vessel attribution XGBoost (vs LightGBM) model
    * AIS Isolation Forest
Each is saved under models/ with a config + version for reproducibility.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from ..core.config import MODELS_DIR
from ..core.logger import get_logger

logger = get_logger(__name__)


def train_segmentation(kind: str = "unet", epochs: int = 12, n_scenes: int = 60,
                       n_classes: int = 5, version: str = "v1") -> dict:
    from ..services.sar.synthetic import render_synthetic_scene
    from ..services.detection import networks, training
    import numpy as np

    scenes = [render_synthetic_scene(size=256, wind_speed=float(3 + (i % 10)), seed=i)
              for i in range(n_scenes)]
    # split at event level (each scene is an independent event/fingerprint)
    n_val = max(int(n_scenes * 0.2), 2)
    train_scenes = scenes[:n_scenes - n_val]
    val_scenes = scenes[n_scenes - n_val:]

    model = networks.build_segmentation_model(kind, n_channels=2, n_classes=n_classes)
    hist = training.train_segmentation(
        model, train_scenes, val_scenes, n_classes=n_classes,
        epochs=epochs, lr=1e-3, batch_size=8, device="auto")

    # save best state
    import torch
    out = MODELS_DIR / "oil_segmentation"
    out.mkdir(parents=True, exist_ok=True)
    torch.save(hist["best_state_dict"], out / "oil_segmentation.pt")
    (out / "config.json").write_text(
        f'{{"kind":"{kind}","n_classes":{n_classes},"binary":false,"epochs":{epochs},"version":"{version}","val_dice":{hist["best_val_dice"]:.4f}}}')
    logger.info("Segmentation net saved (val_dice=%.3f)", hist["best_val_dice"])
    return {"kind": kind, "best_val_dice": hist["best_val_dice"]}


def train_origin(version="v1", n=1200):
    from ..services.origin.model import train_origin_model
    return train_origin_model(version=version, n_samples=n)


def train_attribution(version="v1", n=900):
    from ..services.attribution.model import train_attribution_model
    return train_attribution_model(version=version, n_samples=n)


def train_anomaly(version="v1"):
    from ..services.ais.loader import generate_synthetic_ais
    from ..services.ais.anomaly import AISAnomalyDetector, compute_anomaly_features
    from ..services.ais.trajectories import clean_ais, reconstruct_tracks
    import pandas as pd

    ais = generate_synthetic_ais(n_vessels=40, seed=123, dur_s=172800.0)
    tracks = reconstruct_tracks(clean_ais(ais))
    track_list = [g for _, g in tracks.groupby("track_id")]
    det = AISAnomalyDetector(version=version).fit(track_list)
    det.save()
    logger.info("Isolation Forest anomaly detector saved")
    return {"version": version, "n_tracks": len(track_list)}


def main():
    parser = argparse.ArgumentParser(description="Train OILTRACE-AI models")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--seg", action="store_true")
    parser.add_argument("--segformer", action="store_true")
    parser.add_argument("--origin", action="store_true")
    parser.add_argument("--attribution", action="store_true")
    parser.add_argument("--anomaly", action="store_true")
    parser.add_argument("--epochs", type=int, default=12)
    parser.add_argument("--n-scenes", type=int, default=60)
    parser.add_argument("--version", default="v1")
    args = parser.parse_args()

    from ..core.logger import configure_logging
    configure_logging()

    if args.all or args.seg:
        train_segmentation("unet", epochs=args.epochs, n_scenes=args.n_scenes,
                           version=args.version)
    if args.all or args.segformer:
        train_segmentation("segformer", epochs=args.epochs, n_scenes=args.n_scenes,
                           version=args.version)
    if args.all or args.origin:
        train_origin(version=args.version)
    if args.all or args.attribution:
        train_attribution(version=args.version)
    if args.all or args.anomaly:
        train_anomaly(version=args.version)
    if not (args.all or args.seg or args.segformer or args.origin or args.attribution or args.anomaly):
        parser.print_help()


if __name__ == "__main__":
    main()
