"""Isolation Forest AIS anomaly detector (supporting ML model).

Detects unusual vessel behaviour (speed/course changes, route deviation,
stops, AIS transmission gaps) and produces an anomaly score.  Importantly,
an AIS gap is flagged as "requires verification" and is NOT automatically
treated as evidence of wrongdoing.
"""
from __future__ import annotations

import json
import logging
import pickle
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

from ...core.config import MODELS_DIR
from ...core.geo import angular_diff_deg, haversine_km
from ...core.logger import get_logger

logger = get_logger(__name__)

ANOMALY_FEATURES = [
    "mean_speed_change", "std_speed", "course_change_deg", "route_deviation",
    "stop_time_h", "turn_rate_deg_s", "max_gap_min", "gap_fraction",
]


def compute_anomaly_features(track: pd.DataFrame) -> dict:
    """Derive behaviour features per AIS track segment."""
    if len(track) < 3:
        return {f: 0.0 for f in ANOMALY_FEATURES}
    sog = track.sog.values
    t = track.timestamp.values
    lat = track.latitude.values
    lon = track.longitude.values

    dt = np.diff(t)
    dt = np.where(dt <= 0, 1.0, dt)
    dsog = np.abs(np.diff(sog))
    mean_speed_change = float(np.mean(dsog / dt * 3600.0))  # knots/hr

    cog = track.cog.values
    course_change = float(np.mean([angular_diff_deg(cog[i], cog[i + 1])
                                   for i in range(len(cog) - 1)]))

    # route deviation: cross-track from start->end line
    total_len = 0.0
    dev_sum = 0.0
    for i in range(len(lat) - 1):
        seg = haversine_km(lat[i], lon[i], lat[i + 1], lon[i + 1])
        total_len += seg
        if seg > 0:
            bearing_seg = _idx_bearing(lat[i], lon[i], lat[i + 1], lon[i + 1])
            dev_sum += abs(angular_diff_deg(cog[i], bearing_seg)) * seg
    route_deviation = float(dev_sum / (total_len + 1e-6) / 180.0) if total_len > 0 else 0.0

    # stops: points below 0.5 knots sustained
    stopped = sog < 0.5
    stop_time_h = float(stopped.sum() * np.median(dt) / 3600.0)

    # turn rate deg/s
    turn_rate = float(np.mean(np.abs(np.diff(cog)) / dt)) if len(dt) else 0.0

    # AIS gaps
    gaps = np.diff(t) / 60.0
    max_gap_min = float(gaps.max()) if len(gaps) else 0.0
    gap_fraction = float((gaps > 30.0).mean()) if len(gaps) else 0.0

    return {
        "mean_speed_change": mean_speed_change,
        "std_speed": float(np.std(sog)),
        "course_change_deg": course_change,
        "route_deviation": route_deviation,
        "stop_time_h": stop_time_h,
        "turn_rate_deg_s": turn_rate,
        "max_gap_min": max_gap_min,
        "gap_fraction": gap_fraction,
    }


def _idx_bearing(lat1, lon1, lat2, lon2):
    import math
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dl)
    return math.degrees(math.atan2(y, x)) % 360.0


class AISAnomalyDetector:
    """Isolation-Forest based detector with persistence."""

    def __init__(self, version: str = "v1", model: Optional[IsolationForest] = None):
        self.version = version
        self.model = model or IsolationForest(n_estimators=150, contamination=0.1,
                                              random_state=0)

    def fit(self, tracks: List[pd.DataFrame]) -> "AISAnomalyDetector":
        feats = [compute_anomaly_features(tr) for tr in tracks]
        X = pd.DataFrame(feats)[ANOMALY_FEATURES].fillna(0.0).values
        self.model.fit(X)
        return self

    def score(self, track: pd.DataFrame) -> Dict:
        feats = compute_anomaly_features(track)
        X = np.array([[feats[f] for f in ANOMALY_FEATURES]], dtype=float)
        # isolation forest: higher negative score = more anomalous
        raw = float(self.model.score_samples(X)[0])
        anomaly_score = float(1.0 / (1.0 + np.exp(-raw)))  # map to [0,1]
        gap_flag = feats["max_gap_min"] > 30.0
        return {
            "anomaly_score": anomaly_score,
            "features": feats,
            "ais_gap_detected": gap_flag,
            "interpretation": ("AIS coverage gap detected - requires verification"
                               if gap_flag else "No significant AIS gap"),
        }

    def save(self, model_dir: Optional[Path] = None) -> Path:
        model_dir = model_dir or MODELS_DIR / "ais_isolation_forest"
        model_dir.mkdir(parents=True, exist_ok=True)
        with open(model_dir / "ais_model.pkl", "wb") as f:
            pickle.dump(self.model, f)
        (model_dir / "config.json").write_text(
            json.dumps({"version": self.version, "features": ANOMALY_FEATURES}))
        return model_dir

    @classmethod
    def load(cls, model_dir: Optional[Path] = None) -> "AISAnomalyDetector":
        model_dir = model_dir or MODELS_DIR / "ais_isolation_forest"
        with open(model_dir / "ais_model.pkl", "rb") as f:
            model = pickle.load(f)
        return cls(model=model)
