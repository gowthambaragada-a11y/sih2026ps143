"""AIS data layer.

An adapter layer normalises AIS from any provider (NOAA MarineCadastre,
AISStream, partner/satellite AIS) into one internal schema.  This keeps the
rest of the system provider-agnostic.  A synthetic AIS generator is provided
for offline development and the demo scenario.

Normalised fields (per the PS143 spec):
  mmsi, imo, timestamp, latitude, longitude, sog, cog, heading,
  navigation_status, vessel_type, vessel_length, vessel_width,
  draft, cargo
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np
import pandas as pd

from ...core.logger import get_logger

logger = get_logger(__name__)

NORMALISED_COLUMNS = [
    "mmsi", "imo", "timestamp", "latitude", "longitude", "sog", "cog",
    "heading", "navigation_status", "vessel_type", "vessel_length",
    "vessel_width", "draft", "cargo",
]


class AISAdapter:
    """Base adapter; subclasses map provider-specific columns to normalised schema."""

    def load(self, source) -> pd.DataFrame:
        raise NotImplementedError

    @staticmethod
    def normalise(df: pd.DataFrame) -> pd.DataFrame:
        out = pd.DataFrame()
        for col in NORMALISED_COLUMNS:
            out[col] = df[col] if col in df.columns else np.nan
        return out


class DataFrameAdapter(AISAdapter):
    """Accepts an already-normalised DataFrame (or a CSV path)."""

    def load(self, source) -> pd.DataFrame:
        if isinstance(source, (str,)) and source.lower().endswith(".csv"):
            df = pd.read_csv(source)
        elif isinstance(source, pd.DataFrame):
            df = source.copy()
        else:
            raise ValueError("Unsupported AIS source")
        return self.normalise(df)


def ais_from_csv(path) -> pd.DataFrame:
    return DataFrameAdapter().load(path)


# ---------------------------------------------------------------------------
# Synthetic AIS generator (offline demo + training data)
# ---------------------------------------------------------------------------
def generate_synthetic_ais(
    n_vessels: int = 12,
    t0: float = 0.0,
    dur_s: float = 172800.0,
    ship_lanes=None,
    seed: int = 0,
    truth_mmsi: Optional[str] = None,
) -> pd.DataFrame:
    """Generate a fleet of AIS vessels for a drift/attribution demo.

    ship_lanes: list of (start_lat,start_lon,end_lat,end_lon) corridors.
    Each vessel travels roughly a straight great-circle line with speed
    jitter and occasional AIS gaps.  The truth vessel (if given) is placed to
    intersect the origin region.
    """
    rng = np.random.default_rng(seed)
    rows = []
    n_samples = int(dur_s / 300.0)  # AIS every ~5 min
    times = t0 + np.arange(n_samples) * 300.0

    for vi in range(n_vessels):
        mmsi = 200000000 + vi
        if ship_lanes and vi < len(ship_lanes):
            (la0, lo0, la1, lo1) = ship_lanes[vi]
        else:
            la0, lo0 = rng.uniform(10, 30), rng.uniform(40, 60)
            la1, lo1 = rng.uniform(10, 30), rng.uniform(55, 75)
        speed = rng.uniform(8, 18)  # knots
        speed_ms = speed * 0.514444

        # interpolate positions
        frac = np.linspace(0, 1, n_samples)
        lats = la0 + (la1 - la0) * frac
        lons = lo0 + (lo1 - lo0) * frac

        # Make the bearing constant-ish: recompute linear interp is fine.
        # convert speed to actual lon/lat spacing
        dlat_step = speed_ms * 300.0 / 111320.0
        # ensure total distance roughly = speed*t (approx)
        # Re-derive so trajectory length matches speed
        total_dist_m = speed_ms * dur_s
        step_m = speed_ms * 300.0
        n = int(total_dist_m / step_m)
        n = min(n, int(dur_s / 300.0))
        if n < 2:
            n = 2
        times = t0 + np.arange(n) * 300.0
        b = np.arctan2((la1 - la0) * 111320.0, (lo1 - lo0) * 111320.0 * np.cos(np.deg2rad(la0)))
        lat = la0
        lon = lo0
        lats = []; lons = []
        dlat = np.sin(b) * step_m / 111320.0
        dlon = np.cos(b) * step_m / (111320.0 * np.cos(np.deg2rad(la0)))
        for _ in range(n):
            lats.append(lat); lons.append(lon)
            lat += dlat + rng.normal(0, 0.0004)
            lon += dlon + rng.normal(0, 0.0004)

        tij = np.arange(len(lats)) * 300.0 + t0
        # AIS gaps: drop some transmissions randomly
        keep = rng.random(len(lats)) > 0.12

        nav_status = rng.choice(["underway", "underway", "underway", "moored"], len(lats))
        is_truth = str(truth_mmsi) == str(mmsi)
        cargo = "crude_oil" if is_truth else np.nan
        for i in range(len(lats)):
            if not keep[i]:
                continue
            rows.append({
                "mmsi": str(mmsi), "imo": f"IMO{9000000 + vi}",
                "timestamp": float(tij[i]), "latitude": lats[i], "longitude": lons[i],
                "sog": speed + rng.normal(0, 0.5), "cog": np.rad2deg(b) % 360.0,
                "heading": np.rad2deg(b) % 360.0, "navigation_status": nav_status[i],
                "vessel_type": rng.choice(["tanker", "cargo", "fishing", "passenger"]),
                "vessel_length": rng.uniform(80, 300), "vessel_width": rng.uniform(12, 50),
                "draft": rng.uniform(5, 16), "cargo": cargo,
            })
    return pd.DataFrame(rows)
