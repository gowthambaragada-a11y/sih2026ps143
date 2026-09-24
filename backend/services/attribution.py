"""AIS vessel attribution (cross-matching against an origin fix).

Loads the AIS trajectory CSV (optionally zstd-compressed) located in
``backend/data/ais/`` and ranks nearby vessels by proximity, temporal match
and vessel type (tankers first).
"""
from __future__ import annotations

import logging
import math
import os
import time
from datetime import datetime
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

BACKEND_DIR = Path(__file__).resolve().parent.parent
AIS_DIR = BACKEND_DIR / "data" / "ais"
RADIUS_KM = float(os.getenv("OIL_ATTRIB_RADIUS_KM", "10"))
TOP_K = int(os.getenv("OIL_ATTRIB_TOP_K", "3"))
TIME_WINDOW_H = float(os.getenv("OIL_ATTRIB_TIME_WINDOW_H", "2"))

USECOLS = [
    "mmsi",
    "base_date_time",
    "longitude",
    "latitude",
    "sog",
    "vessel_name",
    "imo",
    "vessel_type",
]


def resolve_ais_csv() -> Path | None:
    override = os.getenv("OIL_AIS_CSV")
    cands = (
        [Path(override)]
        if override
        else list(AIS_DIR.glob("*.csv")) + list(AIS_DIR.glob("*.csv.zst"))
    )
    for p in cands:
        if p.is_file():
            return p
    return None


def _load_ais() -> pd.DataFrame | None:
    csv_path = resolve_ais_csv()
    if csv_path is None:
        return None
    df = pd.read_csv(csv_path, usecols=USECOLS, low_memory=False)
    df["base_date_time"] = pd.to_datetime(df["base_date_time"], errors="coerce")
    df = df.dropna(subset=["base_date_time", "latitude", "longitude"])
    df = df[(df["latitude"] != 0) & (df["longitude"] != 0)]
    return df


@lru_cache(maxsize=1)
def _get_ais() -> pd.DataFrame | None:
    try:
        st = time.time()
        df = _load_ais()
        if df is not None:
            logger.info("AIS loaded: %d rows in %.1fs", len(df), time.time() - st)
        return df
    except Exception as exc:  # pragma: no cover
        logger.warning("AIS load failed: %s", exc)
        return None


def _haversine_vec(lat0: float, lon0: float, lat_arr, lon_arr) -> np.ndarray:
    R = 6371.0
    p1 = math.radians(lat0)
    dp = np.radians(lat_arr - lat0)
    dl = np.radians(lon_arr - lon0)
    h = np.sin(dp / 2) ** 2 + math.cos(p1) * np.cos(np.radians(lat_arr)) * np.sin(dl / 2) ** 2
    return 2 * R * np.arcsin(np.sqrt(h))


def vessel_type_label(code) -> str:
    code = int(code) if not pd.isna(code) else None
    if code is None:
        return "Unknown"
    if 80 <= code <= 89:
        return "Tanker"
    if 70 <= code <= 79:
        return "Cargo"
    if 60 <= code <= 69:
        return "Passenger"
    if code == 30:
        return "Fishing"
    if code == 52 or code == 31:
        return "Tug/Towing"
    if code == 97:
        return "High-speed craft"
    if code in (0, None):
        return "Not available"
    return f"AIS-{code}"


def _type_score(code) -> float:
    code = int(code) if not pd.isna(code) else None
    if code is None:
        return 0.3
    if 80 <= code <= 87:
        return 1.0  # tanker
    if 88 <= code <= 89:
        return 0.9
    if 70 <= code <= 79:
        return 0.6
    if 60 <= code <= 69:
        return 0.5
    return 0.3


def correlate_vessel(
    origin_lat: float, origin_lon: float, time_str
) -> dict:
    """Rank vessels within RADIUS_KM of the spill origin.

    Returns ``{"top": [...], "count_total": n, "warnings": [...]}``.
    """
    warnings: list[str] = []
    t0 = time_str if isinstance(time_str, datetime) else pd.to_datetime(time_str)
    if pd.isna(t0):
        return {"top": [], "count_total": 0, "warnings": ["Invalid origin time."]}

    df = _get_ais()
    if df is None:
        return {
            "top": [],
            "count_total": 0,
            "warnings": [
                "AIS dataset unavailable (expected backend/data/ais/*.csv)."
            ],
        }

    # Fast regional pre-filter: origin bbox expanded by radius + margin.
    deg_guard = max(RADIUS_KM / 111.0, 0.1) + 0.05
    reg = df[
        (df["latitude"].between(origin_lat - deg_guard, origin_lat + deg_guard))
        & (df["longitude"].between(origin_lon - deg_guard, origin_lon + deg_guard))
    ].copy()

    if reg.empty:
        return {
            "top": [],
            "count_total": 0,
            "warnings": ["No AIS traffic within the search area at this time."],
        }

    reg["dist_km"] = _haversine_vec(
        origin_lat, origin_lon, reg["latitude"].to_numpy(), reg["longitude"].to_numpy()
    )
    reg["td_h"] = (reg["base_date_time"] - t0).dt.total_seconds() / 3600.0
    near = reg[(reg["dist_km"] <= RADIUS_KM) & (reg["td_h"].abs() <= TIME_WINDOW_H)]

    if near.empty:
        return {
            "top": [],
            "count_total": 0,
            "warnings": [
                f"No AIS vessel within {RADIUS_KM:.0f} km and "
                f"{TIME_WINDOW_H:.0f} h of the origin."
            ],
        }

    candidates: list[dict] = []
    for mmsi, g in near.groupby("mmsi"):
        g = g.sort_values("base_date_time")
        name = g["vessel_name"].dropna().iloc[-1] if len(g) else None
        vtype = g["vessel_type"].dropna().iloc[-1] if len(g) else None
        dmin = float(g["dist_km"].min())
        tmin = float(g["td_h"].abs().min())
        sog = float(g["sog"].fillna(0).median())
        prox = 1.0 / (1.0 + dmin)
        temp = 1.0 / (1.0 + tmin)
        score = 0.50 * prox + 0.30 * _type_score(vtype) + 0.20 * temp
        if sog is not None and sog < 0.5:
            score *= 1.05  # stopped/slow vessels are unusual & suspicious
        score = round(min(score, 0.999), 4)

        flags = ["within_search_radius"]
        if _type_score(vtype) >= 0.9:
            flags.append("tanker")
        if sog is not None and sog < 0.5:
            flags.append("slow_or_stopped")
        if tmin < 0.5:
            flags.append("present_at_origin_time")

        lat0 = float(g["latitude"].iloc[0])
        lon0 = float(g["longitude"].iloc[0])
        track = {
            "lat": g["latitude"].tolist(),
            "lon": g["longitude"].tolist(),
            "t": g["base_date_time"].dt.strftime("%Y-%m-%dT%H:%M:%S").tolist(),
            "sog": g["sog"].fillna(0).tolist(),
        }
        candidates.append(
            {
                "mmsi": str(int(mmsi)),
                "name": str(name) if name else None,
                "imo": str(g["imo"].dropna().iloc[-1]) if len(g) and not g["imo"].dropna().empty else None,
                "vessel_type": vessel_type_label(vtype),
                "vessel_type_code": int(vtype) if not pd.isna(vtype) else None,
                "score": score,
                "distance_to_origin_km": round(dmin, 3),
                "time_difference_hours": round(tmin, 3),
                "sog_knots": round(sog, 2) if sog is not None else None,
                "evidence_flags": flags,
                "lat": round(lat0, 6),
                "lon": round(lon0, 6),
                "track": track,
            }
        )

    candidates.sort(key=lambda v: (-v["score"], v["distance_to_origin_km"]))
    return {
        "top": candidates[:TOP_K],
        "count_total": len(candidates),
        "warnings": [],
    }