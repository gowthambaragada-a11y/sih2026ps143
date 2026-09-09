"""Attribution feature engineering (Model 3).

Builds the per-vessel feature vector combining spatial, temporal, trajectory,
vessel, AIS and physics compatibility features (per the PS143 spec) that feed
the XGBoost/LightGBM attribution model and the explainable scoring.
"""
from __future__ import annotations

import logging
from typing import List, Optional, Tuple

import numpy as np
import pandas as pd

from ...core.geo import angular_diff_deg, bearing_deg, haversine_km, haversine_km_vec, path_length_km
from ...core.logger import get_logger

logger = get_logger(__name__)

ATTRIBUTION_FEATURES = [
    # spatial
    "distance_to_origin_km", "min_distance_to_origin_km",
    "distance_to_slick_km", "trajectory_intersects_origin",
    "time_in_origin_region_h",
    # temporal
    "time_difference_h", "arrival_offset_h", "departure_offset_h",
    "duration_in_region_h",
    # trajectory
    "heading_difference", "trajectory_alignment", "trajectory_overlap",
    "route_deviation", "speed_profile", "turning_behaviour",
    # vessel
    "vessel_suitability", "vessel_draft", "vessel_length",
    # AIS
    "ais_gap_minutes", "ais_continuity", "transmission_frequency",
    "position_jump_count",
    # physics
    "drift_alignment", "vessel_to_origin_direction", "origin_to_slick_direction",
    "time_to_origin_h",
]

EVENT_META = ["mmsi", "mm_origin_lat", "mm_origin_lon", "mm_slick_lat", "mm_slick_lon",
              "mm_release_time", "mm_detection_time", "label"]


def compute_attribution_features(
    vessel: dict,
    origin: dict,
    slick: dict,
    track: Optional[pd.DataFrame] = None,
) -> dict:
    """Compute attribution features for a single candidate vessel.

    vessel: dict with mmsi, type, length, width, draft, cargo, speed profile...
    origin: dict with lat, lon, release_time (epoch s), drift_direction_deg
    slick:  dict with lat, lon, detection_time, area_km2
    track:  optional pandas DataFrame of that vessel's AIS positions
            (columns: latitude, longitude, timestamp, sog, cog, ...)
    """
    mmsi = vessel["mmsi"]
    o_lat, o_lon = origin["lat"], origin["lon"]
    s_lat, s_lon = slick["lat"], slick["lon"]

    d_origin = haversine_km(vessel.get("lat", o_lat), vessel.get("lon", o_lon), o_lat, o_lon)

    # Track-based features
    track_pts = None
    if track is not None and len(track) > 1:
        tr_lat = track.latitude.values
        tr_lon = track.longitude.values
        tr_t = track.timestamp.values
        # min distance to origin over the track
        min_do = min(haversine_km_vec(tr_lat, tr_lon, o_lat, o_lon))
        # distance to slick
        d_slick_track = min(haversine_km_vec(tr_lat, tr_lon, s_lat, s_lon))
        # time inside origin region: points within 15 km
        in_region = haversine_km_vec(tr_lat, tr_lon, o_lat, o_lon) <= 15.0
        n_in = int(in_region.sum())
        time_in_region_h = 0.0
        if n_in > 0 and n_in > 1:
            ts_in = tr_t[in_region]
            time_in_region_h = float((ts_in.max() - ts_in.min()) / 3600.0)
        # time difference: residue of track times vs release time
        rel_s = origin["release_time"]
        # times near release
        near = np.abs(tr_t - rel_s) / 3600.0
        min_tdiff_h = float(near.min()) if len(near) else np.nan
        # heading difference: vessel cog vs origin->... reconstructed drift
        drift_dir = origin.get("drift_direction_deg", np.nan)
        v_heading = float(track.cog.iloc[-1]) if "cog" in track.columns else np.nan
        heading_diff = angular_diff_deg(drift_dir, v_heading) if not np.isnan(drift_dir) and not np.isnan(v_heading) else np.nan

        # trajectory alignment: fraction of track within 15km of origin
        trajectory_alignment = float(n_in / max(len(tr_lat), 1))

        # AIS gaps
        gaps = np.diff(tr_t) / 60.0
        max_gap_min = float(gaps.max()) if len(gaps) else 0.0
        continuity = 1.0 - float((gaps > 30.0).mean()) if len(gaps) else 1.0
        tx_freq = float((1.0 / np.median(np.diff(tr_t) / 60.0))) if len(tr_t) > 2 else 0.0
        jump_count = int((gaps > 120.0).sum() + (haversine_km_vec(tr_lat[:-1], tr_lon[:-1], tr_lat[1:], tr_lon[1:]) > 50.0).sum())

        # vessel-to-origin direction vs drift direction (alignment of approach)
        vo_dir = bearing_deg(vessel.get("lat", tr_lat[-1]), vessel.get("lon", tr_lon[-1]), o_lat, o_lon)
        os_dir = bearing_deg(o_lat, o_lon, s_lat, s_lon)
        drift_alignment = 1.0 - angular_diff_deg(drift_dir, os_dir) / 180.0 if not np.isnan(drift_dir) else np.nan

        # speed profile closeness: vessel sog vs typical
        speed_profile = float(np.clip(1.0 - abs(np.nanmean(track.sog) - vessel.get("avg_speed", 12.0)) / 12.0, 0, 1)) if "sog" in track.columns else np.nan
        turning = float(np.std(np.diff(track.cog))) if "cog" in track.columns and len(track.cog) > 2 else 0.0

        route_dev = 0.3
        traj_overlap = trajectory_alignment
    else:
        min_do = d_origin
        d_slick_track = haversine_km(o_lat, o_lon, s_lat, s_lon)
        time_in_region_h = 0.0
        min_tdiff_h = np.nan
        heading_diff = np.nan
        trajectory_alignment = 0.0
        max_gap_min = 0.0; continuity = 1.0; tx_freq = 0.0; jump_count = 0
        vo_dir = np.nan; os_dir = bearing_deg(o_lat, o_lon, s_lat, s_lon)
        drift_dir = origin.get("drift_direction_deg", np.nan)
        drift_alignment = 1.0 - angular_diff_deg(drift_dir, os_dir) / 180.0 if not np.isnan(drift_dir) else np.nan
        speed_profile = np.nan; turning = 0.0
        route_dev = 0.0; traj_overlap = 0.0

    # vessel suitability (type/cargo-based supporting evidence only)
    suit = _vessel_suitability(vessel)

    # temporal
    rel_s = origin["release_time"]
    det_s = slick["detection_time"]
    time_diff_h = float((det_s - rel_s) / 3600.0)
    arrival_offset_h = min_tdiff_h
    departure_offset_h = min_tdiff_h
    duration_region = time_in_region_h

    return {
        "mmsi": str(mmsi),
        "distance_to_origin_km": float(d_origin),
        "min_distance_to_origin_km": float(min_do),
        "distance_to_slick_km": float(d_slick_track),
        "trajectory_intersects_origin": float(in_region.any()) if track is not None and len(track) > 1 else 0.0,
        "time_in_origin_region_h": float(time_in_region_h),
        "time_difference_h": float(time_diff_h),
        "arrival_offset_h": float(arrival_offset_h) if not np.isnan(arrival_offset_h) else float(time_diff_h),
        "departure_offset_h": float(departure_offset_h) if not np.isnan(departure_offset_h) else float(time_diff_h),
        "duration_in_region_h": float(duration_region),
        "heading_difference": float(heading_diff) if not np.isnan(heading_diff) else 90.0,
        "trajectory_alignment": float(trajectory_alignment),
        "trajectory_overlap": float(traj_overlap),
        "route_deviation": float(route_dev),
        "speed_profile": float(speed_profile) if not np.isnan(speed_profile) else 0.5,
        "turning_behaviour": float(turning),
        "vessel_suitability": float(suit),
        "vessel_draft": float(vessel.get("draft", np.nan)),
        "vessel_length": float(vessel.get("length", np.nan)),
        "ais_gap_minutes": float(max_gap_min),
        "ais_continuity": float(continuity),
        "transmission_frequency": float(tx_freq),
        "position_jump_count": float(jump_count),
        "drift_alignment": float(drift_alignment) if not np.isnan(drift_alignment) else 0.5,
        "vessel_to_origin_direction": float(vo_dir) if not np.isnan(vo_dir) else 0.0,
        "origin_to_slick_direction": float(os_dir),
        "time_to_origin_h": float(min_tdiff_h) if not np.isnan(min_tdiff_h) else float(time_diff_h),
    }


def _vessel_suitability(vessel: dict) -> float:
    """Supporting evidence from type/cargo; never conclusive on its own."""
    vtype = str(vessel.get("type", "")).lower()
    cargo = str(vessel.get("cargo", "")).lower()
    score = 0.4
    if any(t in vtype for t in ["tanker", "oil"]):
        score += 0.3
    if any(c in cargo for c in ["oil", "crude", "petroleum", "fuel"]):
        score += 0.3
    return float(np.clip(score, 0, 1))


def attribution_to_dataframe(records: List[dict]) -> pd.DataFrame:
    df = pd.DataFrame(records)
    for col in ATTRIBUTION_FEATURES + EVENT_META:
        if col not in df.columns:
            df[col] = np.nan
    return df
