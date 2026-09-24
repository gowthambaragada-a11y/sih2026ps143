"""OpenDrift backward-trajectory hindcast wrapper.

Imports the local ``modules/opendrift`` clone (already on PATH via the repo
layout) and runs an OpenOil backward simulation from a spill location to
estimate where the oil most likely originated.
"""
from __future__ import annotations

import os

# Avoid OpenMP duplicate-runtime crashes when torch + scipy/opendrift coexist.
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

import logging
import math
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

BACKEND_DIR = Path(__file__).resolve().parent.parent
OPENDRIFFT_DIR = BACKEND_DIR.parent / "modules" / "opendrift"

# Default surface-current guess (m/s) used when no ocean forcing is bundled.
# Eastern Arabian Sea during SW monsoon: roughly westward monsoonal current.
DEFAULT_CURRENT_U = float(os.getenv("OIL_CURRENT_U", "-0.35"))
DEFAULT_CURRENT_V = float(os.getenv("OIL_CURRENT_V", "0.0"))
DURATION_HOURS = float(os.getenv("OIL_DRIFT_HOURS", "4"))
TIME_STEP_S = int(os.getenv("OIL_DRIFT_DT_S", "-300"))


@__import__("functools").lru_cache(maxsize=1)
def _opendrift_available() -> bool:
    if str(OPENDRIFFT_DIR) not in sys.path:
        sys.path.insert(0, str(OPENDRIFFT_DIR))
    try:
        import matplotlib  # noqa: F401

        matplotlib.use("Agg")
        import opendrift  # noqa: F401

        from opendrift.models.openoil import OpenOil  # noqa: F401

        return True
    except Exception as exc:  # pragma: no cover
        logger.warning("OpenDrift import unavailable (%s); using analytic fallback.", exc)
        return False


def _parse_time(time_str) -> datetime:
    if isinstance(time_str, datetime):
        return time_str
    s = str(time_str).strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    raise ValueError(f"Unrecognised timestamp: {time_str!r}")


def _run_opendrift(lat: float, lon: float, t0: datetime):
    if not _opendrift_available():
        raise RuntimeError("OpenDrift not importable")
    from opendrift.models.openoil import OpenOil

    o = OpenOil(loglevel=50)  # CRITICAL only -> quiet in API logs
    for key, val in [
        ("environment:constant:x_sea_water_velocity", DEFAULT_CURRENT_U),
        ("environment:constant:y_sea_water_velocity", DEFAULT_CURRENT_V),
        ("environment:constant:x_wind", 0.0),
        ("environment:constant:y_wind", 0.0),
        ("environment:constant:sea_surface_wave_significant_height", 1.0),
    ]:
        o.set_config(key, val)

    o.seed_elements(
        lon=lon,
        lat=lat,
        radius=100,
        number=120,
        time=t0,
        diameter=1e-5,
    )
    o.run(
        duration=-timedelta(hours=DURATION_HOURS),
        time_step=timedelta(seconds=TIME_STEP_S),
        time_step_output=timedelta(hours=1),
        outfile=None,
    )

    # Final positions of the backward run -> where the slick came from.
    lons = o.result["lon"].isel(time=-1, drop=True).dropna(dim="trajectory").to_numpy()
    lats = o.result["lat"].isel(time=-1, drop=True).dropna(dim="trajectory").to_numpy()

    # Median of final positions keeps the estimate robust to stranded elements.
    origin_lon = float(np.median(lons))
    origin_lat = float(np.median(lats))

    # Mean trajectory (median lon/lat across elements at each output step).
    traj = []
    times = o.result["time"].to_numpy()
    lons_all = o.result["lon"].to_numpy()
    lats_all = o.result["lat"].to_numpy()
    for i in range(lons_all.shape[0]):
        sl = lons_all[i]
        sa = lats_all[i]
        sl = sl[~np.isnan(sl)]
        sa = sa[~np.isnan(sa)]
        if sl.size:
            traj.append({"lat": float(np.median(sa)), "lon": float(np.median(sl))})

    return {
        "origin_lat": origin_lat,
        "origin_lon": origin_lon,
        "trajectory": traj,
        "steps": int(o.steps_calculation),
    }


def _analytic_fallback(lat: float, lon: float, t0: datetime) -> dict:
    """No-OpenDrift fallback: reverse a constant-velocity trajectory."""
    hours_back = -DURATION_HOURS  # simulation durations are negative
    km_per_deg_lat = 111.32
    km_per_deg_lon = 111.32 * math.cos(math.radians(lat))
    dlat_km = DEFAULT_CURRENT_V * 3.6 * hours_back
    dlon_km = DEFAULT_CURRENT_U * 3.6 * hours_back
    origin_lat = lat + dlat_km / km_per_deg_lat
    origin_lon = lon + dlon_km / km_per_deg_lon
    steps = max(1, abs(int(3600 * DURATION_HOURS / abs(TIME_STEP_S))))
    traj = [
        {"lat": lat + dlat_km / km_per_deg_lat * i / steps,
         "lon": lon + dlon_km / km_per_deg_lon * i / steps}
        for i in range(steps + 1)
    ]
    return {
        "origin_lat": origin_lat,
        "origin_lon": origin_lon,
        "trajectory": traj,
        "steps": steps,
    }


def run_hindcast(lat: float, lon: float, time_str) -> dict:
    """Estimate spill origin via a 4-hour backward trajectory.

    Returns ``[origin_lat, origin_lon]`` under the ``origin`` key plus the
    reconstructed trajectory for the frontend map.
    """
    t0 = _parse_time(time_str)
    st = time.time()

    if _opendrift_available():
        try:
            res = _run_opendrift(lat, lon, t0)
            res["engine"] = "opendrift-openoil"
            res["warnings"] = [
                "Using constant surface current forcing"
                f" (u={DEFAULT_CURRENT_U:.2f}, v={DEFAULT_CURRENT_V:.2f} m/s)."
                " Attach ocean model readers for operational hindcast."
            ]
            res["elapsed_s"] = round(time.time() - st, 2)
            return res
        except Exception as exc:  # pragma: no cover
            logger.warning("OpenDrift run failed (%s); analytic fallback.", exc)

    res = _analytic_fallback(lat, lon, t0)
    res["engine"] = "analytic-fallback"
    res["warnings"] = [
        "OpenDrift unavailable; origin estimated by reversing a"
        f" constant current (u={DEFAULT_CURRENT_U:.2f} m/s over {DURATION_HOURS}h)."
    ]
    res["elapsed_s"] = round(time.time() - st, 2)
    return res