"""XGBoost Origin Probability Model (Model 2).

Takes the engineered origin features for each candidate hypothesis and outputs
a probability distribution over origins.  Compares XGBoost against Random
Forest during training and records the chosen model + version for
reproducibility.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split

from ...core.logger import get_logger
from ...core.config import MODELS_DIR
from .features import FEATURE_COLUMNS

logger = get_logger(__name__)

try:
    from xgboost import XGBClassifier
except Exception:  # pragma: no cover
    XGBClassifier = None


class OriginModel:
    """Wrapper around the origin classifier with persistence + calibration."""

    def __init__(self, kind: str = "origin_xgboost", model: object = None,
                 version: str = "v1"):
        import pickle
        self.kind = kind
        self.model = model
        self.version = version
        self.feature_columns = FEATURE_COLUMNS

    # ---- persistence ----
    def save(self, model_dir: Optional[Path] = None) -> Path:
        import pickle
        model_dir = model_dir or MODELS_DIR / self.kind
        model_dir.mkdir(parents=True, exist_ok=True)
        with open(model_dir / "origin_model.pkl", "wb") as f:
            pickle.dump(self.model, f)
        with open(model_dir / "config.json", "w") as f:
            json.dump({"version": self.version, "kind": self.kind,
                       "features": self.feature_columns}, f, indent=2)
        return model_dir

    @classmethod
    def load(cls, model_dir: Optional[Path] = None, kind: str = "origin_xgboost") -> "OriginModel":
        import pickle
        model_dir = model_dir or MODELS_DIR / kind
        with open(model_dir / "origin_model.pkl", "rb") as f:
            model = pickle.load(f)
        cfg = json.loads((model_dir / "config.json").read_text())
        return cls(kind=kind, model=model, version=cfg["version"])

    # ---- predict ----
    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        X = X[self.feature_columns]
        if hasattr(self.model, "predict_proba"):
            proba = self.model.predict_proba(X)
            # sklearn binary classifier: proba[:,1] is positive class
            if proba.ndim == 2 and proba.shape[1] == 2:
                return proba[:, 1]
            return proba.ravel()
        return np.asarray(self.model.predict(X)).ravel()


def _synthesize_origin_training_data(n: int = 1200, seed: int = 0) -> pd.DataFrame:
    """Generate labelled synthetic training data for origin estimation.

    Label 1 = a plausible origin (low distance/short drift, aligned trajectory);
    label 0 = distractor (far, mismatched).  This gold standard is used to
    calibrate the model and is clearly marked synthetic.
    """
    rng = np.random.default_rng(seed)
    rows = []
    for _ in range(n):
        dist = rng.uniform(0.5, 60.0)
        dur = rng.uniform(2.0, 48.0)
        wind_speed = rng.uniform(2.0, 15.0)
        cur_speed = rng.uniform(0.05, 0.8)
        endpoint = rng.uniform(1.0, 40.0)
        shape = rng.uniform(0.2, 1.0)
        area = rng.uniform(0.3, 1.0)
        unc = rng.uniform(1.0, 12.0)
        # label: plausible if the displacement/time is consistent AND within a
        # credible detection horizon.  Very young slicks are compact and far
        # harder to detect by SAR, so very short drift durations are downweighted
        # until the slick matures (age prior, hump-shaped around ~22 h).
        dur_prior = np.clip(1.0 - np.abs(dur - 22.0) / 24.0, 0.0, 1.0)
        score = (1.0 - dist / 60.0) * 0.30 + dur_prior * 0.40 + shape * 0.15 - unc / 30.0
        noise = rng.normal(0, 0.12)
        label = 1 if score + noise > 0.5 else 0
        rows.append({
            "release_lat": rng.uniform(-10, 30),
            "release_lon": rng.uniform(40, 90),
            "drift_duration_h": dur,
            "release_time_offset_h": dur,
            "wind_speed": wind_speed, "wind_dir": rng.uniform(0, 360),
            "current_speed": cur_speed, "current_dir": rng.uniform(0, 360),
            "dist_to_slick_km": dist,
            "trajectory_origin_distance_km": dist,
            "path_length_km": dist + rng.uniform(0, 20),
            "slick_endpoint_distance_km": endpoint,
            "shape_similarity": shape, "area_similarity": area,
            "uncertainty_km": unc,
            "label": label,
        })
    return pd.DataFrame(rows)


def train_origin_model(model_dir: Optional[Path] = None, version: str = "v1",
                       n_samples: int = 1200, seed: int = 0,
                       compare_rf: bool = True) -> Dict:
    """Train XGBoost (and optionally Random Forest) origin model, comparing
    them and persisting the better one.  Returns evaluation dict."""
    if XGBClassifier is None:
        raise RuntimeError("xgboost not installed; install to train origin model")

    df = _synthesize_origin_training_data(n=n_samples, seed=seed)
    X = df[FEATURE_COLUMNS]
    y = df["label"].values
    Xtr, Xte, ytr, yte = train_test_split(
        X, y, test_size=0.25, stratify=y, random_state=seed)

    xgb = XGBClassifier(n_estimators=150, max_depth=4, learning_rate=0.1,
                        subsample=0.8, colsample_bytree=0.8, eval_metric="auc",
                        random_state=seed, use_label_encoder=False)
    xgb.fit(Xtr, ytr)
    from sklearn.metrics import roc_auc_score, accuracy_score
    xgb_auc = roc_auc_score(yte, xgb.predict_proba(Xte)[:, 1])
    xgb_acc = accuracy_score(yte, xgb.predict(Xte))

    results = {"xgb_auc": float(xgb_auc), "xgb_acc": float(xgb_acc),
               "chosen": "xgb"}

    if compare_rf:
        rf = RandomForestClassifier(n_estimators=200, max_depth=8, random_state=seed)
        rf.fit(Xtr, ytr)
        rf_auc = roc_auc_score(yte, rf.predict_proba(Xte)[:, 1])
        rf_acc = accuracy_score(yte, rf.predict(Xte))
        results.update({"rf_auc": float(rf_auc), "rf_acc": float(rf_acc)})
        if rf_auc > xgb_auc:
            results["chosen"] = "rf"
            model = rf
        else:
            model = xgb
    else:
        model = xgb

    om = OriginModel(kind="origin_xgboost", model=model, version=version)
    om.save(model_dir)
    results["version"] = version
    results["features"] = FEATURE_COLUMNS
    logger.info("Origin model trained: %s", results)
    return results
