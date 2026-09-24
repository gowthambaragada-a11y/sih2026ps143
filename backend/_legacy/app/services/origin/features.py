"""Origin model feature engineering.

For a set of candidate origin hypotheses (each from a backtracked drift
trajectory), computes a feature vector that combines:
  * initial position (release point)
  * estimated release time / drift duration
  * environmental summary (wind speed/dir, current speed/dir)
  * trajectory-fit (distance from observed slick, overlap)
  * geometric similarity (shape/area)
  * uncertainty
These features feed the XGBoost Origin Probability Model (Model 2).
"""
from __future__ import annotations

import logging
from typing import List, Optional

import numpy as np
import pandas as pd

from ...core.geo import bearing_deg, haversine_km, path_length_km
from ...core.logger import get_logger
from ..drift.engine import DriftSimulator, EnsembleResult

logger = get_logger(__name__)

FEATURE_COLUMNS = [
    "release_lat", "release_lon",
    "drift_duration_h", "release_time_offset_h",
    "wind_speed", "wind_dir", "current_speed", "current_dir",
    "dist_to_slick_km", "trajectory_origin_distance_km",
    "path_length_km", "slick_endpoint_distance_km",
    "shape_similarity", "area_similarity",
    "uncertainty_km",
]


def compute_origin_features(
    candidates: List[dict],
    drift_result: EnsembleResult,
    slick_centroid: tuple,
    slick_area_km2: float,
) -> pd.DataFrame:
    """Build the origin feature DataFrame from a list of candidate hypotheses.

    Each candidate dict:
        {lat, lon, release_time (epoch s), probability_prior, ...}
    """
    rows = []
    slick_lat, slick_lon = slick_centroid
    for idx, cand in enumerate(candidates):
        rel_s = cand.get("release_time")
        drift_dur_h = cand.get("drift_duration_h", 0.0)
        dist_slick = haversine_km(cand["lat"], cand["lon"],
                                  slick_lat, slick_lon)

        # environmental context at release point via the drift fields
        wind_speed = cand.get("wind_speed", np.nan)
        wind_dir = cand.get("wind_dir", np.nan)
        cur_speed = cand.get("current_speed", np.nan)
        cur_dir = cand.get("current_dir", np.nan)

        # trajectory fit: distance from the mean backtrack endpoint to slick
        if drift_result.trajectories:
            ends = np.array([t[-1] for t in drift_result.trajectories])
            end_slick = np.array([haversine_km(e[0], e[1], slick_lat, slick_lon)
                                  for e in ends])
            slick_endpoint_km = float(np.median(end_slick))
            # pointwise mean trajectory across members (trim to min length)
            min_n = min(len(t) for t in drift_result.trajectories)
            stacked = np.stack([t[:min_n] for t in drift_result.trajectories])  # (M, N, 2)
            mean_traj = stacked.mean(axis=0)                                    # (N, 2)
            path_len = float(path_length_km(mean_traj[:, 0], mean_traj[:, 1]))
            path_shape = dist_slick / (path_len + 1e-6)
            # shape similarity: how close the asymptotic drift heading is to
            # the release->slick bearing
            bearing_rel = bearing_deg(cand["lat"], cand["lon"], slick_lat, slick_lon)
        else:
            slick_endpoint_km = dist_slick
            path_len = dist_slick
            path_shape = 1.0

        rows.append({
            "candidate_id": cand.get("candidate_id", f"C{idx}"),
            "release_lat": cand["lat"],
            "release_lon": cand["lon"],
            "drift_duration_h": drift_dur_h,
            "release_time_offset_h": cand.get("release_time_offset_h", drift_dur_h),
            "wind_speed": wind_speed,
            "wind_dir": wind_dir,
            "current_speed": cur_speed,
            "current_dir": cur_dir,
            "dist_to_slick_km": dist_slick,
            "trajectory_origin_distance_km": cand.get("trajectory_origin_distance_km", dist_slick),
            "path_length_km": path_len,
            "slick_endpoint_distance_km": slick_endpoint_km,
            "shape_similarity": cand.get("shape_similarity", 1.0),
            "area_similarity": cand.get("area_similarity", 1.0),
            "uncertainty_km": cand.get("uncertainty_km", np.nan),
        })
    df = pd.DataFrame(rows)
    for col in FEATURE_COLUMNS:
        if col not in df.columns:
            df[col] = np.nan
    df[FEATURE_COLUMNS] = df[FEATURE_COLUMNS].fillna(0.0)
    return df[FEATURE_COLUMNS].astype(float)
