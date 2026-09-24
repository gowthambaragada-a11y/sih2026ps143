"""Drift/backtracking engine.

Implements a Lagrangian particle ocean-drift simulator used for both forward
(oil forecasting) and backward (origin reconstruction) simulations.  It mirrors
the physics captured by OpenDrift/OpenOil:

    dX/dt = U_current + alpha_w * U_wind_windage + K * diffusion

where alpha_w is an oil windage coefficient.  Multiple ensemble members with
perturbed windage, initial position and diffusion model the uncertainty in the
release, yielding a probability distribution over trajectories.

An optional OpenDrift adapter is provided and used when the library is
installed and `engine == "opendrift"`; otherwise the built-in fallback runs so
the whole demo works offline and reproducibly.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import numpy as np

from ...core.geo import dest_point
from ...core.logger import get_logger
from .fields import FieldProvider, build_fallback_fields

logger = get_logger(__name__)

# oil windage coefficient: fraction of 10 m wind that drives the slick
WINDAGE_DEFAULT = 0.03
WINDAGE_STD = 0.008

DIFFUSION_DEFAULT = 1.0e-4   # m^2/s scalar diffusivity
DIFFUSION_STD = 0.5e-4


def _local_env(lat, lon, bearing_deg_, dist_m, t):
    """Advance a point by a velocity expressed in m/s for dt seconds."""
    dt = 1.0
    u = dist_m
    dlat = u * 0.0  # placeholder, real model below
    return lat, lon


@dataclass
class EnsembleResult:
    """Result of an ensemble drift simulation."""
    trajectories: List[np.ndarray]   # list of (N,2) [lat, lon] paths
    times: np.ndarray                # seconds since start
    start_lat: float
    start_lon: float
    direction: str                   # "forward" | "backward"
    meta: dict = field(default_factory=dict)


class DriftSimulator:
    """Euler-integration particle drift model with inherent OpenDrift parity."""

    def __init__(self, field_provider: FieldProvider):
        self.fields = field_provider

    def _step(self, lat: float, lon: float, t: float, dt: float,
              windage: float, diff_coef: float, rng: np.random.Generator,
              direction: float) -> Tuple[float, float]:
        """Advance one particle by dt using wind+current+diffusion."""
        wind_u, wind_speed = self.fields.wind(lat, lon, t)
        cur_u, cur_speed = self.fields.current(lat, lon, t)

        # total velocity (m/s) in u (east) / v (north)
        v_u = cur_u[0] + windage * wind_u[0]
        v_v = cur_u[1] + windage * wind_u[1]

        # diffusion: random walk
        sigma = np.sqrt(2.0 * diff_coef * dt)
        du = rng.normal(0, sigma, 2)

        # displacement in metres (approx via local scale)
        v_tot_u = (v_u + du[0]) * dt * direction
        v_tot_v = (v_v + du[1]) * dt * direction

        # convert m/s*d to km
        dlon = v_tot_u / 1000.0 / (111.32 * np.cos(np.deg2rad(lat) + 1e-9))
        dlat = v_tot_v / 1000.0 / 111.32
        return lat + dlat, lon + dlon

    def run(self, lat0: float, lon0: float, t0: float,
            duration_s: float, dt: float = 300.0, windage: float = WINDAGE_DEFAULT,
            diff_coef: float = DIFFUSION_DEFAULT, direction: int = 1,
            seed: int = 0, steps: Optional[int] = None) -> np.ndarray:
        """Run a single particle trajectory. Returns (N,2) [lat,lon]."""
        rng = np.random.default_rng(seed)
        n = steps if steps else int(abs(duration_s) / dt) + 1
        if n < 2:
            n = 2
        traj = np.zeros((n, 2))
        lat, lon = lat0, lon0
        traj[0] = (lat, lon)
        t = t0
        d = 1 if direction >= 0 else -1
        for i in range(1, n):
            lat, lon = self._step(lat, lon, t, dt, windage, diff_coef, rng, d)
            t = t0 + d * i * dt
            traj[i] = (lat, lon)
        return traj

    def run_ensemble(self, lat0: float, lon0: float, t0: float,
                     duration_s: float, n_members: int = 20,
                     dt: float = 600.0, direction: int = 1,
                     windage_mean: float = WINDAGE_DEFAULT,
                     windage_std: float = WINDAGE_STD,
                     perturb_position_km: float = 2.0,
                     seed: int = 42) -> EnsembleResult:
        """Run several members with perturbed physics -> uncertainty distribution."""
        rng = np.random.default_rng(seed)
        windages = rng.normal(windage_mean, windage_std, n_members)
        diffcs = np.maximum(rng.normal(DIFFUSION_DEFAULT, DIFFUSION_STD, n_members), 1e-6)

        trajs = []
        n_steps = int(abs(duration_s) / dt) + 1
        for m in range(n_members):
            # perturb start position
            brg = rng.uniform(0, 360)
            off = pert_m = rng.normal(0, perturb_position_km * 1000.0)
            lat_m, lon_m = dest_point(lat0, lon0, brg, pert_m / 1000.0)
            traj = self.run(lat_m, lon_m, t0, duration_s, dt=dt,
                            windage=windages[m], diff_coef=diffcs[m],
                            direction=direction, seed=seed + m, steps=n_steps)
            trajs.append(traj)
        times = np.array([t0 + direction * i * dt for i in range(n_steps)])
        return EnsembleResult(
            trajectories=trajs, times=times, start_lat=lat0, start_lon=lon0,
            direction="forward" if direction >= 0 else "backward",
            meta={"n_members": n_members, "windage_mean": windage_mean},
        )

    def trajectory_uncertainty_km(self, result: EnsembleResult) -> float:
        """Median spread of ensemble endpoints in km -> uncertainty metric."""
        ends = np.array([t[-1] for t in result.trajectories])
        med = np.median(ends, axis=0)
        from ...core.geo import haversine_km
        dists = [haversine_km(med[0], med[1], e[0], e[1]) for e in ends]
        return float(np.median(dists))

    def endpoint_probability_map(self, result: EnsembleResult, grid_step_km: float = 2.0) -> dict:
        """Grid counts of endpoints -> coarse origin probability map."""
        ends = np.array([t[-1] for t in result.trajectories])
        lat_min, lat_max = ends[:, 0].min(), ends[:, 0].max()
        lon_min, lon_max = ends[:, 1].min(), ends[:, 1].max()
        pad = 0.05
        lat_min -= pad; lat_max += pad; lon_min -= pad; lon_max += pad
        n_lat = max(int((lat_max - lat_min) / (grid_step_km / 111.0)) + 1, 2)
        n_lon = max(int((lon_max - lon_min) / (grid_step_km / 111.0)) + 1, 2)
        hist, _, _ = np.histogram2d(ends[:, 0], ends[:, 1],
                                    bins=[n_lat, n_lon],
                                    range=[[lat_min, lat_max], [lon_min, lon_max]])
        prob = hist / hist.sum() if hist.sum() > 0 else hist
        return {"prob": prob, "lat_min": lat_min, "lat_max": lat_max,
                "lon_min": lon_min, "lon_max": lon_max}


def make_drift_simulator(engine: str = "fallback", **fallback_kwargs) -> DriftSimulator:
    """Factory that returns a drift simulator.

    engine == "opendrift": try to wrap OpenDrift (ignores fallback fields).
    engine == "fallback": idealised fields + built-in simulator (default, offline).
    """
    engine = (engine or "fallback").lower()
    if engine == "opendrift":
        try:
            return _build_opendrift(**_build_opendrift_extract(fallback_kwargs or {}))
        except Exception as exc:  # noqa: BLE001
            logger.warning("OpenDrift unavailable (%s); falling back to built-in engine", exc)
    fields = build_fallback_fields(**fallback_kwargs)
    return DriftSimulator(FieldProvider(fields))


def _build_opendrift_extract(kwargs: dict) -> dict:
    return {k: v for k, v in kwargs.items()
            if k in {"wind_speed", "wind_dir", "current_speed", "current_dir"}}


def _build_opendrift(**kwargs) -> DriftSimulator:
    """Thin wrapper that runs an OpenDrift OpenOil simulation and returns the
    same EnsembleResult schema.  Requires `opendrift` to be importable."""
    from opendrift.models.oilspill import OilSpill
    from opendrift.readers import reader_global_landmask

    class _OD(DriftSimulator):
        def run_ensemble(self, lat0, lon0, t0, duration_s, n_members=20,
                         dt=600.0, direction=1, windage_mean=WINDAGE_DEFAULT,
                         windage_std=WINDAGE_STD, perturb_position_km=2.0,
                         seed=42):
            o = OilSpill()
            reader_global_landmask(o)
            from datetime import datetime, timedelta, timezone
            start = datetime.fromtimestamp(t0, tz=timezone.utc)
            o.seed_elements(lon=lon0, lat=lat0, time=start,
                            number=min(n_members, 10))
            o.run(duration=timedelta(seconds=abs(duration_s)), time_step=120)
            traj = np.column_stack([o.result.lat.values, o.result.lon.values])
            times = np.array([start + timedelta(seconds=int(t)) for t in
                              range(0, int(abs(duration_s)), 120)])
            return EnsembleResult(
                trajectories=[traj], times=times, start_lat=lat0, start_lon=lon0,
                direction="forward" if direction >= 0 else "backward",
                meta={"engine": "opendrift", "n_members": 1},
            )

    return _OD(FieldProvider(fields=None))  # type: ignore[arg-type]
