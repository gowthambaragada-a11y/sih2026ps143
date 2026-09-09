"""AIS cleaning, gridding/trajectory reconstruction, and candidate filtering."""
from __future__ import annotations

import logging
from typing import Iterable, List, Optional, Tuple

import numpy as np
import pandas as pd

from ...core.geo import haversine_km, haversine_km_vec, path_length_km
from ...core.logger import get_logger

logger = get_logger(__name__)


def clean_ais(df: pd.DataFrame) -> pd.DataFrame:
    """Remove implausible records and sort chronologically per MMSI."""
    out = df.copy()
    out = out.dropna(subset=["mmsi", "latitude", "longitude", "timestamp"])
    out = out[(out.latitude.between(-90, 90)) & (out.longitude.between(-180, 180))]
    out["mmsi"] = out["mmsi"].astype(str)
    out["timestamp"] = out["timestamp"].astype(float)
    out = out.sort_values(["mmsi", "timestamp"]).reset_index(drop=True)
    return out


def split_trajectories(dff: pd.DataFrame, max_gap_h: float = 3.0,
                       max_jump_km: float = 50.0) -> List[pd.DataFrame]:
    """Split a single vessel's AIS stream into discrete trajectory segments.

    A new segment starts on a large temporal gap or an implausible spatial jump
    (candidate AIS manipulation, or signal dropout).
    """
    if len(dff) < 2:
        return [dff]
    segments = []
    cur = [dff.iloc[0]]
    for i in range(1, len(dff)):
        prev = dff.iloc[i - 1]
        row = dff.iloc[i]
        dt_h = (row.timestamp - prev.timestamp) / 3600.0
        dk = haversine_km(prev.latitude, prev.longitude, row.latitude, row.longitude)
        if dt_h > max_gap_h or dk > max_jump_km:
            segments.append(pd.DataFrame(cur))
            cur = [row]
        else:
            cur.append(row)
    segments.append(pd.DataFrame(cur))
    return segments


def reconstruct_tracks(df: pd.DataFrame, max_gap_h: float = 3.0) -> pd.DataFrame:
    """Return a track_id-annotated DataFrame."""
    out_rows = []
    for mmsi, g in df.groupby("mmsi"):
        segs = split_trajectories(g, max_gap_h=max_gap_h)
        for si, seg in enumerate(segs):
            seg = seg.copy()
            seg["track_id"] = f"{mmsi}_{si}"
            out_rows.append(seg)
    return pd.concat(out_rows, ignore_index=True)


def trajectory_stats(track: pd.DataFrame) -> dict:
    """Summary features for one track segment."""
    if len(track) < 2:
        return {"n_points": len(track), "length_km": 0.0, "avg_sog": np.nan,
                "max_sog": np.nan, "start_time": None, "end_time": None}
    length = path_length_km(track.latitude.values, track.longitude.values)
    return {
        "n_points": len(track),
        "length_km": float(length),
        "avg_sog": float(track.sog.mean()),
        "max_sog": float(track.sog.max()),
        "start_time": float(track.timestamp.min()),
        "end_time": float(track.timestamp.max()),
        "min_dist_origin_km": np.nan,
        "time_in_origin_h": np.nan,
    }


def filter_candidates_by_region(tracks: pd.DataFrame,
                                origin_candidates: List[Tuple[float, float]],
                                buffer_km: float = 20.0) -> pd.DataFrame:
    """Keep only vessels whose tracks come within buffer_km of any origin
    candidate point (the probable origin region from the origin model)."""
    keep = []
    for _, g in tracks.groupby("track_id"):
        g = g.copy()
        min_d = float("inf")
        min_time = None
        for (oc_lat, oc_lon) in origin_candidates:
            d = haversine_km_vec(g.latitude.values, g.longitude.values,
                                 oc_lat, oc_lon).min()
            if d < min_d:
                min_d = d
        if min_d <= buffer_km:
            g["min_dist_origin_km"] = min_d
            keep.append(g)
    if keep:
        return pd.concat(keep, ignore_index=True)
    return pd.DataFrame(columns=tracks.columns)
