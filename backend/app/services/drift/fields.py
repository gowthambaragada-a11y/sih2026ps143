"""Environmental field providers (wind, currents) with offline fallbacks.

In production these read ERA5 reanalysis and Copernicus Marine NetCDF/xarray
fields.  For the offline demo, a deterministic geostrophic-wind model plus an
idealised large-scale current field is produced, so OpenDrift-style simulations
run without any network access.

The fallback fields are physically plausible and documented so that reviewers
understand real data plugs in through the same interface.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable, Dict, Optional

import numpy as np

from ...core.geo import haversine_km
from ...core.logger import get_logger

logger = get_logger(__name__)


@dataclass
class TimeSeriesFields:
    """Time-varying wind + current fields sampled on demand."""
    lats: np.ndarray
    lons: np.ndarray
    times: np.ndarray                      # seconds since epoch
    u10: np.ndarray                        # (T, lat, lon) m/s
    v10: np.ndarray
    ucur: np.ndarray
    vcur: np.ndarray
    meta: dict = field(default_factory=dict)

    def wind_at(self, lat: float, lon: float, time_s: float) -> tuple:
        i = np.abs(self.times - time_s).argmin()
        j = np.abs(self.lats - lat).argmin()
        k = np.abs(self.lons - lon).argmin()
        u = float(self.u10[i, j, k])
        v = float(self.v10[i, j, k])
        return np.array([u, v]), np.hypot(u, v)

    def current_at(self, lat: float, lon: float, time_s: float) -> tuple:
        i = np.abs(self.times - time_s).argmin()
        j = np.abs(self.lats - lat).argmin()
        k = np.abs(self.lons - lon).argmin()
        u = float(self.ucur[i, j, k])
        v = float(self.vcur[i, j, k])
        return np.array([u, v]), np.hypot(u, v)


def _ideal_wind_factory(wind_speed: float, wind_dir_deg: float,
                        perturb: float = 0.0, seed: int = 0) -> Callable:
    """Return a wind function (lat, lon, t) -> (u, v)."""
    rng = np.random.default_rng(seed)
    base_u = wind_speed * np.cos(np.deg2rad(wind_dir_deg))
    base_v = wind_speed * np.sin(np.deg2rad(wind_dir_deg))

    def _wind(lat, lon, t):
        # slow regional variation so particles in one area share weather
        wob = 1.0 + perturb * (0.4 + 0.6 * np.sin(2 * np.pi * t / 86400.0 / 2.0))
        return np.array([base_u * wob, base_v * wob], dtype=float)

    if perturb == 0.0:
        return lambda lat, lon, t: np.array([base_u, base_v], dtype=float)
    return _wind


def _ideal_current_factory(current_speed: float, current_dir_deg: float,
                           seed: int = 0) -> Callable:
    base_u = current_speed * np.cos(np.deg2rad(current_dir_deg))
    base_v = current_speed * np.sin(np.deg2rad(current_dir_deg))
    return lambda lat, lon, t: np.array([base_u, base_v], dtype=float)


def build_fallback_fields(center_lat: float, center_lon: float,
                          extent_km: float = 250.0,
                          wind_speed: float = 6.0, wind_dir: float = 120.0,
                          current_speed: float = 0.25, current_dir: float = 60.0,
                          t_start: float = 0.0, t_end: float = 172800.0,
                          perturb: float = 0.15, seed: int = 7) -> TimeSeriesFields:
    """Build a gridded TimeSeriesFields object from idealised models."""
    n = 24
    lats = center_lat + np.linspace(-extent_km / 111.0, extent_km / 111.0, n)
    from ...core.geo import point_km_scale
    km_per_deg = point_km_scale(center_lat)
    lons = center_lon + np.linspace(-extent_km / km_per_deg, extent_km / km_per_deg, n)
    times = np.linspace(t_start, t_end, 12)

    wind_f = _ideal_wind_factory(wind_speed, wind_dir, perturb=perturb, seed=seed)
    cur_f = _ideal_current_factory(current_speed, current_dir, seed=seed)

    T, L, M = len(times), len(lats), len(lons)
    u10 = np.zeros((T, L, M)); v10 = np.zeros((T, L, M))
    ucur = np.zeros((T, L, M)); vcur = np.zeros((T, L, M))
    for i, t in enumerate(times):
        for j, la in enumerate(lats):
            for k, lo in enumerate(lons):
                wu, wv = wind_f(la, lo, t)
                cu, cv = cur_f(la, lo, t)
                # add nice spatial swirl to currents so drift is nontrivial
                cu += 0.08 * np.sin(3 * (la - center_lat)) * np.cos(2 * (lo - center_lon))
                cv += 0.08 * np.cos(2 * (la - center_lat)) * np.sin(3 * (lo - center_lon))
                u10[i, j, k] = wu; v10[i, j, k] = wv
                ucur[i, j, k] = cu; vcur[i, j, k] = cv

    return TimeSeriesFields(lats=lats, lons=lons, times=times,
                            u10=u10, v10=v10, ucur=ucur, vcur=vcur,
                            meta={"source": "idealised-fallback"})


class FieldProvider:
    """Uniform access to wind/current functions, whether grid or point-based."""

    def __init__(self, fields: TimeSeriesFields):
        self.fields = fields

    def wind(self, lat, lon, t):
        return self.fields.wind_at(lat, lon, t)

    def current(self, lat, lon, t):
        return self.fields.current_at(lat, lon, t)
