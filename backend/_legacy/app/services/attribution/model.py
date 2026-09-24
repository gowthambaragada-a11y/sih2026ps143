"""Vessel attribution model (Model 3) + explainable scoring.

A gradient-boosted model (XGBoost, compared against LightGBM) ranks candidate
vessels, and a deterministic, transparent evidence-scoring component produces
per-vessel component scores and interpretable evidence flags.  The final
ranking is evidence-backed: we never claim absolute guilt, only a probability
ranking given the available evidence.
"""
from __future__ import annotations

import json
import logging
import pickle
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from ...core.config import MODELS_DIR
from ...core.logger import get_logger
from .features import ATTRIBUTION_FEATURES

logger = get_logger(__name__)

try:
    from xgboost import XGBClassifier
except Exception:  # pragma: no cover
    XGBClassifier = None

try:
    from lightgbm import LGBMClassifier
except Exception:  # pragma: no cover
    LGBMClassifier = None


# ---------------------------------------------------------------------------
# Evidence scoring: transparent, explainable component scores
# ---------------------------------------------------------------------------
def evidence_scores(fx: dict) -> Dict[str, float]:
    """Compute 6 explainable component scores (0..1) from attribution features.

    Weights are domain-informed and made explicit; they are optimised against
    validation data in production (see score tuning notebook).
    """
    comp = {}

    # Spatial compatibility
    d_origin_km = fx.get("distance_to_origin_km", 50.0)
    min_do = fx.get("min_distance_to_origin_km", d_origin_km)
    comp["spatial"] = float(np.clip(1.0 - min_do / 50.0, 0, 1.0) *
                            (0.5 + 0.5 * fx.get("trajectory_intersects_origin", 0.0)))

    # Temporal compatibility (vessel-specific: when it was actually near origin)
    t_resid = fx.get("time_to_origin_h", fx.get("arrival_offset_h", 24.0))
    t_resid = abs(float(t_resid)) if t_resid == t_resid else 24.0   # NaN guard
    comp["temporal"] = float(np.clip(1.0 - t_resid / 12.0, 0.0, 1.0))

    # Trajectory compatibility
    comp["trajectory"] = float(np.clip(
        0.5 * fx.get("trajectory_alignment", 0.0) +
        0.25 * fx.get("trajectory_overlap", 0.0) +
        0.25 * (1.0 - fx.get("heading_difference", 90.0) / 180.0), 0, 1.0))

    # Vessel suitability (supporting only)
    comp["vessel_suitability"] = float(np.clip(fx.get("vessel_suitability", 0.4), 0, 1.0))

    # Behavioural anomaly (higher anomaly = more suspicious but must be verified)
    anomaly = fx.get("anomaly_score", 0.0)
    comp["behaviour"] = float(np.clip(anomaly, 0, 1.0))

    # AIS evidence (gap presence reduces reliability, so cap score)
    ais_gap = fx.get("ais_gap_minutes", 0.0)
    cont = fx.get("ais_continuity", 1.0)
    comp["ais_evidence"] = float(np.clip(cont * 0.7 + fx.get("transmission_frequency", 0.0) * 0.3
                                         - (ais_gap > 30.0) * 0.25, 0, 1.0))

    return comp


FINAL_WEIGHTS = {
    "spatial": 0.28,
    "temporal": 0.30,
    "trajectory": 0.20,
    "vessel_suitability": 0.08,
    "behaviour": 0.09,
    "ais_evidence": 0.05,
}


def final_score(comp: Dict[str, float]) -> float:
    return float(sum(FINAL_WEIGHTS[k] * comp[k] for k in FINAL_WEIGHTS))


# ---------------------------------------------------------------------------
# Evidence flags (explainable output)
# ---------------------------------------------------------------------------
def build_evidence_flags(fx: dict, comp: Dict[str, float]) -> List[dict]:
    flags = []

    def _add(label, ok, warn=False, detail=""):
        flags.append({"label": label, "flag": "positive" if ok and not warn else ("warning" if warn else "negative"),
                      "detail": detail})

    _add("Entered probable origin region",
         fx.get("min_distance_to_origin_km", 1e9) < 20.0,
         detail=f"min distance {fx.get('min_distance_to_origin_km', 0):.1f} km")
    _add("Present during estimated spill window",
         abs(fx.get("time_difference_h", 1e9)) < 24.0,
         detail=f"time difference {fx.get('time_difference_h', 0):.1f} h")
    _add("Trajectory intersects origin probability zone",
         fx.get("trajectory_intersects_origin", 0.0) > 0.5)
    _add("Heading compatible with reconstructed movement",
         fx.get("heading_difference", 90.0) < 60.0,
         detail=f"heading diff {fx.get('heading_difference', 0):.0f} deg")
    if fx.get("ais_gap_minutes", 0.0) > 30.0:
        _add("AIS coverage gap detected - requires verification", False, warn=True,
             detail=f"max gap {fx.get('ais_gap_minutes', 0):.0f} min")
    if fx.get("anomaly_score", 0.0) > 0.7:
        _add("Unusual behavioural pattern detected (needs verification)", False, warn=True)
    # Confidence caps so we never over-claim
    if comp["behaviour"] > 0.7 and comp["ais_evidence"] < 0.3:
        _add("Evidence confidence reduced by AIS gaps", False, warn=True)
    return flags


# ---------------------------------------------------------------------------
# Model wrapper
# ---------------------------------------------------------------------------
class AttributionModel:
    def __init__(self, model=None, version: str = "v1"):
        self.model = model
        self.version = version
        self.feature_columns = ATTRIBUTION_FEATURES

    def save(self, model_dir: Optional[Path] = None) -> Path:
        model_dir = model_dir or MODELS_DIR / "vessel_xgboost"
        model_dir.mkdir(parents=True, exist_ok=True)
        with open(model_dir / "vessel_model.pkl", "wb") as f:
            pickle.dump(self.model, f)
        (model_dir / "config.json").write_text(
            json.dumps({"version": self.version, "features": self.feature_columns}))
        return model_dir

    @classmethod
    def load(cls, model_dir: Optional[Path] = None) -> "AttributionModel":
        model_dir = model_dir or MODELS_DIR / "vessel_xgboost"
        with open(model_dir / "vessel_model.pkl", "rb") as f:
            model = pickle.load(f)
        cfg = json.loads((model_dir / "config.json").read_text())
        return cls(model=model, version=cfg["version"])

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        X = X[self.feature_columns]
        X = X.apply(pd.to_numeric, errors="coerce").fillna(0.0).values
        if self.model is None:
            return np.zeros(len(X))
        if hasattr(self.model, "predict_proba"):
            p = self.model.predict_proba(X)
            return p[:, 1] if p.ndim == 2 and p.shape[1] == 2 else p.ravel()
        return np.asarray(self.model.predict(X)).ravel()


def _synthesize_attribution_training(n: int = 900, seed: int = 0) -> pd.DataFrame:
    """Synthetic attribution training data (see Section 15).

    Each record simulates one scenario fleet: a single guilty vessel crosses
    the probable origin region ~exactly at the estimated release time with a
    trajectory that closely matches the backward drift, while distractor
    vessels pass the region at the wrong time / distance / direction.  The
    label marks the guilty vessel.  This grounds the model in the physical
    scenario structure (spatial + temporal + trajectory consistency) instead
    of arbitrary label noise.
    """
    rng = np.random.default_rng(seed)
    rows = []

    def _feat_row(v, guilty, rel_s, o_lat, o_lon, s_lat, s_lon):
        crossing_t = v["crossing_t"]
        # spatial
        min_do = v["min_do"]
        intersects = 1.0 if min_do < 15.0 else 0.0
        # temporal: how close to the (uncertain) release estimate
        resid_h = min(abs(float((crossing_t - rel_s)) / 3600.0), rng.uniform(0, 8))
        time_to_origin_h = resid_h if guilty else abs(rng.normal(0, 1)) + rng.uniform(6, 24)
        # trajectory
        alignment = v["alignment"]
        heading_diff = rng.uniform(0, 35) if guilty else rng.uniform(15, 150)
        overlap = alignment + rng.uniform(0, 0.1)
        return {
            "distance_to_origin_km": rng.uniform(0.5, 30),
            "min_distance_to_origin_km": min_do,
            "distance_to_slick_km": rng.uniform(0.5, 45),
            "trajectory_intersects_origin": intersects,
            "time_in_origin_region_h": (rng.uniform(0.5, 4.0) if guilty else rng.uniform(0, 1.5)),
            "time_difference_h": float(rel_s / 3600.0 - crossing_t / 3600.0),
            "arrival_offset_h": time_to_origin_h,
            "departure_offset_h": time_to_origin_h + rng.uniform(0, 1.5),
            "duration_in_region_h": (rng.uniform(0.5, 4.0) if guilty else rng.uniform(0, 1.0)),
            "heading_difference": heading_diff,
            "trajectory_alignment": alignment,
            "trajectory_overlap": overlap,
            "route_deviation": (rng.uniform(0, 0.2) if guilty else rng.uniform(0.1, 1.0)),
            "speed_profile": (rng.uniform(0.6, 1.0) if guilty else rng.uniform(0.2, 0.9)),
            "turning_behaviour": (rng.uniform(0, 8) if guilty else rng.uniform(2, 30)),
            "vessel_suitability": rng.uniform(0.4, 1.0),
            "vessel_draft": rng.uniform(8, 15),
            "vessel_length": rng.uniform(150, 300),
            "ais_gap_minutes": (rng.uniform(0, 25) if guilty else rng.uniform(0, 120)),
            "ais_continuity": (rng.uniform(0.7, 1.0) if guilty else rng.uniform(0.3, 1.0)),
            "transmission_frequency": rng.uniform(0.3, 1.0),
            "position_jump_count": (rng.uniform(0, 2) if guilty else rng.uniform(0, 4)),
            "drift_alignment": (rng.uniform(0.7, 1.0) if guilty else rng.uniform(0, 0.7)),
            "vessel_to_origin_direction": rng.uniform(0, 360),
            "origin_to_slick_direction": 118.0 + rng.normal(0, 6),
            "time_to_origin_h": time_to_origin_h,
        }

    for _ in range(n):
        rel_s = rng.uniform(8, 40) * 3600.0
        o_lat, o_lon = 20.0, 60.0
        s_lat, s_lon = 20.2, 60.25
        n_vessels = int(rng.integers(3, 8))
        for i in range(n_vessels):
            guilty = i == 0
            crossing_t = rel_s if guilty else rel_s + rng.choice([-1, 1]) * rng.uniform(8, 30) * 3600.0
            v = {
                "crossing_t": crossing_t,
                "min_do": (rng.uniform(0.3, 6) if guilty else rng.uniform(4, 60)),
                "alignment": (rng.uniform(0.15, 0.45) if guilty else rng.uniform(0.0, 0.12)),
            }
            fx = _feat_row(v, guilty, rel_s, o_lat, o_lon, s_lat, s_lon)
            for k in ATTRIBUTION_FEATURES:
                fx.setdefault(k, 0.0)
            rows.append({**fx, "mmsi": str(100000000 + i),
                         "mm_origin_lat": o_lat, "mm_origin_lon": o_lon,
                         "mm_slick_lat": s_lat, "mm_slick_lon": s_lon,
                         "mm_release_time": rel_s, "mm_detection_time": rel_s + 12 * 3600.0,
                         "label": 1 if guilty else 0})
    return pd.DataFrame(rows)


def train_attribution_model(model_dir: Optional[Path] = None, version: str = "v1",
                            n_samples: int = 900, seed: int = 0,
                            compare_lgbm: bool = True) -> Dict:
    """Train XGBoost attribution model (compare vs LightGBM)."""
    if XGBClassifier is None:
        raise RuntimeError("xgboost not installed")
    df = _synthesize_attribution_training(n=n_samples, seed=seed)
    X = df[ATTRIBUTION_FEATURES].apply(pd.to_numeric, errors="coerce").fillna(0.0)
    y = df["label"].values
    from sklearn.model_selection import train_test_split
    from sklearn.metrics import roc_auc_score, top_k_accuracy_score
    Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=0.25, stratify=y, random_state=seed)

    xgb = XGBClassifier(n_estimators=200, max_depth=4, learning_rate=0.08,
                        subsample=0.8, colsample_bytree=0.8, eval_metric="auc",
                        use_label_encoder=False, random_state=seed)
    xgb.fit(Xtr, ytr)
    xgb_auc = roc_auc_score(yte, xgb.predict_proba(Xte)[:, 1])

    results = {"xgb_auc": float(xgb_auc), "chosen": "xgb"}

    if compare_lgbm and LGBMClassifier is not None:
        lgb = LGBMClassifier(n_estimators=200, max_depth=4, learning_rate=0.08,
                             subsample=0.8, colsample_bytree=0.8, random_state=seed,
                             verbose=-1)
        lgb.fit(Xtr, ytr)
        lgb_auc = roc_auc_score(yte, lgb.predict_proba(Xte)[:, 1])
        results["lgbm_auc"] = float(lgb_auc)
        if lgb_auc > xgb_auc:
            results["chosen"] = "lgbm"
            model = lgb
        else:
            model = xgb
    else:
        model = xgb

    am = AttributionModel(model=model, version=version)
    am.save(model_dir)
    results["version"] = version
    results["features"] = ATTRIBUTION_FEATURES
    logger.info("Attribution model trained: %s", results)
    return results
