"""Synthetic demonstration scenario generator.

Builds one complete, reproducible historical-style demonstration case that runs
the whole OILTRACE-AI pipeline end-to-end offline:

  1. a synthetic Sentinel-1 SAR scene (with a real oil slick),
  2. wind/current fields,
  3. a fleet of AIS vessels, one of which is the "responsible" source whose
     trajectory intersects the origin region around the spill time,
  4. vessel metadata,
  5. a ground-truth spill event record,
  6. physical consistency: the observed slick location is produced by an actual
     forward drift simulation from the release point O, so backward drift
     reconstruction genuinely recovers O.

All of it is clearly marked SYNTHETIC for training/demo; production loads real
data through the same adapter interfaces.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Tuple

import numpy as np
import pandas as pd

from ..core.config import DATA_DIR, MASTER_DIR, RAW_DIR
from ..core.geo import haversine_km, dest_point
from ..core.logger import get_logger
from .sar.synthetic import render_synthetic_scene
from .drift.fields import build_fallback_fields, FieldProvider
from .drift.engine import DriftSimulator, WINDAGE_DEFAULT, DIFFUSION_DEFAULT
from .ais.loader import generate_synthetic_ais

logger = get_logger(__name__)

PIXEL_SIZE_KM = 0.02

# physical scenario parameters (synthetic but physically plausible)
ORIGIN_LAT = 20.0
ORIGIN_LON = 60.0
RELEASE_TIME_S = 90000.0          # 25 h after scene epoch t0=0
DRIFT_DURATION_H = 18.0           # release -> detection
DETECTION_TIME_S = RELEASE_TIME_S + DRIFT_DURATION_H * 3600.0  # ~43 h


@dataclass
class DemoScenario:
    event_id: str
    scene: object                # SyntheticScene
    fields: object               # TimeSeriesFields
    ais: pd.DataFrame
    vessels: pd.DataFrame
    events: pd.DataFrame
    truth_mmsi: str
    slick_centroid_geo: Tuple[float, float]   # (lat, lon) where oil is observed
    origin_geo: Tuple[float, float]           # true release point
    origin_release_time_s: float
    detection_time_s: float
    meta: dict = field(default_factory=dict)


def _drift_position(lat0: float, lon0: float, t0: float, duration_s: float,
                    fields, seed: int) -> Tuple[float, float]:
    """Run a forward single-particle drift to locate the slick for the demo."""
    sim = DriftSimulator(FieldProvider(fields))
    traj = sim.run(lat0, lon0, t0, duration_s, dt=600.0,
                   windage=WINDAGE_DEFAULT, diff_coef=DIFFUSION_DEFAULT,
                   direction=1, seed=seed)
    return float(traj[-1, 0]), float(traj[-1, 1])


def _lane_missing_origin(min_dist_km: float, rng, size_deg: float = 3.0,
                         origin_lat=20.0, origin_lon=60.0):
    """Generate a straight lane whose closest approach to the origin exceeds
    min_dist_km, so it cannot be a false candidate close to the source."""
    for _ in range(200):
        p0 = (rng.uniform(origin_lat - size_deg * 1.2, origin_lat + size_deg * 1.2),
              rng.uniform(origin_lon - size_deg * 1.2, origin_lon + size_deg * 1.2))
        p1 = (rng.uniform(origin_lat - size_deg * 1.2, origin_lat + size_deg * 1.2),
              rng.uniform(origin_lon - size_deg * 1.2, origin_lon + size_deg * 1.2))
        # sample the segment and compute the minimum distance to the origin
        lats = np.linspace(p0[0], p1[0], 60)
        lons = np.linspace(p0[1], p1[1], 60)
        d_min = min(haversine_km(origin_lat, origin_lon, lats[i], lons[i])
                    for i in range(len(lats)))
        if d_min >= min_dist_km:
            return (float(p0[0]), float(p0[1]), float(p1[0]), float(p1[1]))
    return (origin_lat - 1.5, origin_lon - 2.0, origin_lat + 1.5, origin_lon - 1.0)


def _vessel_track(origin_lat, origin_lon, crossing_t, speed_kn, dur_s,
                  bearing_deg=80.0, dt=300.0, gap_frac=0.1, jitter_deg=0.0003,
                  seed=0, mmsi="200000000", vessel_type="tanker", cargo="crude_oil"):
    """Generate a clean straight AIS track that passes EXACTLY through the origin
    at time crossing_t (relative to the scene epoch), with small navigation
    jitter and occasional dropped transmissions (realistic AIS gaps)."""
    rng = np.random.default_rng(seed)
    speed_ms = speed_kn * 0.514444
    n = int(dur_s / dt)
    times = np.arange(n) * dt
    keep = rng.random(n) > gap_frac
    rows = []
    for i in range(n):
        if not keep[i]:
            continue
        t = times[i]
        offset_km = speed_ms * (t - crossing_t) / 1000.0
        lat, lon = dest_point(origin_lat, origin_lon, bearing_deg, offset_km)
        lat += rng.normal(0, jitter_deg)
        lon += rng.normal(0, jitter_deg)
        cog = (bearing_deg + rng.normal(0, 2.0)) % 360.0
        rows.append({
            "mmsi": mmsi,
            "imo": f"IMO{mmsi}",
            "timestamp": float(t),
            "latitude": float(lat),
            "longitude": float(lon),
            "sog": float(speed_kn + rng.normal(0, 0.4)),
            "cog": float(cog),
            "heading": float(cog),
            "navigation_status": "underway",
            "vessel_type": vessel_type,
            "vessel_length": 250.0 if vessel_type == "tanker" else 180.0,
            "vessel_width": 44.0 if vessel_type == "tanker" else 28.0,
            "draft": 13.5 if vessel_type == "tanker" else 9.0,
            "cargo": cargo,
        })
    return pd.DataFrame(rows)


def build_demo_scenario(seed: int = 7, size: int = 512,
                        event_id: str = "SIH-2026-SPILL-001",
                        pixel_size_km: float = PIXEL_SIZE_KM) -> DemoScenario:
    """Construct the complete offline demonstration case (physically consistent)."""
    rng = np.random.default_rng(seed)

    # --- 1. Environmental fields ---
    fields = build_fallback_fields(
        center_lat=ORIGIN_LAT, center_lon=ORIGIN_LON,
        wind_speed=6.5, wind_dir=120.0, current_speed=0.25, current_dir=60.0,
        t_start=0.0, t_end=DETECTION_TIME_S + 3 * 86400.0,
        perturb=0.2, seed=seed,
    )

    # --- 2. Physically-consistent slick position via forward drift ---
    origin_geo = (ORIGIN_LAT, ORIGIN_LON)
    slick_lat, slick_lon = _drift_position(
        ORIGIN_LAT, ORIGIN_LON, RELEASE_TIME_S,
        DRIFT_DURATION_H * 3600.0, fields, seed=seed)
    offset_km = haversine_km(ORIGIN_LAT, ORIGIN_LON, slick_lat, slick_lon)
    logger.info("demo: drift displaced slick %.1f km from origin", offset_km)

    # --- 3. SAR scene with an oil slick placed at the predicted position ---
    oil_center_pixel = (int(size * 0.55), int(size * 0.5))
    scene = render_synthetic_scene(size=size, wind_speed=6.5, seed=seed,
                                   with_oil=True, oil_center=oil_center_pixel)

    # Geotransform maps the slick pixel centroid exactly onto (slick_lat, slick_lon)
    px, py = oil_center_pixel
    px_size_deg = pixel_size_km / 111.32
    py_size_deg = pixel_size_km / 111.32
    origin_x = slick_lon - px * px_size_deg
    origin_y = slick_lat + py * py_size_deg
    geotransform = (origin_x, px_size_deg, 0.0, origin_y, 0.0, -py_size_deg)
    scene.meta["geotransform"] = geotransform
    scene.meta["pixel_size_km"] = pixel_size_km
    scene.meta["slick_centroid_geo"] = (slick_lat, slick_lon)

    # --- 4. Fleet of AIS vessels ---
    detection_time_s = DETECTION_TIME_S
    origin_release_time_s = RELEASE_TIME_S
    truth_speed_kn = 12.0

    # near-origin vessels built exactly (pass through origin at a known time)
    truth_mmsi = str(200000000)
    track0 = _vessel_track(ORIGIN_LAT, ORIGIN_LON, RELEASE_TIME_S,
                           truth_speed_kn, detection_time_s, seed=seed,
                           mmsi=truth_mmsi, vessel_type="tanker", cargo="crude_oil")
    track1 = _vessel_track(ORIGIN_LAT, ORIGIN_LON, RELEASE_TIME_S - 18 * 3600.0,
                           truth_speed_kn, detection_time_s, seed=seed + 1,
                           mmsi=str(200000001), vessel_type="cargo", cargo="containers")
    track2 = _vessel_track(ORIGIN_LAT, ORIGIN_LON, RELEASE_TIME_S + 10 * 3600.0,
                           truth_speed_kn, detection_time_s, seed=seed + 2,
                           mmsi=str(200000002), vessel_type="tanker", cargo="petroleum")

    # far distractor fleet (never approach the origin region)
    n_distractors = 11
    d_lanes = [_lane_missing_origin(min_dist_km=45.0, rng=rng)
               for _ in range(n_distractors)]
    distractor_ais = generate_synthetic_ais(
        n_vessels=n_distractors, t0=0.0, dur_s=detection_time_s,
        ship_lanes=d_lanes, seed=seed + 3, truth_mmsi=None,
    )
    # offset far-vessel MMSIs so they do not clash with 200000000-200000002
    base = 200000010
    distractor_ais["mmsi"] = [str(base + int(int(m) - 2e8)) for m in distractor_ais["mmsi"]]

    ais = pd.concat([track0, track1, track2, distractor_ais], ignore_index=True)
    n_vessels = 3 + n_distractors

    # vessel metadata
    vrows = []
    near_meta = [
        (truth_mmsi, "tanker", "crude_oil", 260.0, 44.0, 14.0),
        (str(200000001), "cargo", "containers", 190.0, 30.0, 10.0),
        (str(200000002), "tanker", "petroleum", 240.0, 40.0, 12.5),
    ]
    for mmsi, vtype, cargo, length, width, draft in near_meta:
        vrows.append({
            "mmsi": mmsi, "imo": f"IMO{mmsi}", "name": f"MV DEMO-{mmsi[3:]}",
            "type": vtype, "length": length, "width": width, "draft": draft,
            "cargo": cargo, "avg_speed": truth_speed_kn,
        })
    for vi, mmsi in enumerate(sorted(distractor_ais["mmsi"].unique())):
        vrows.append({
            "mmsi": mmsi, "imo": f"IMO{mmsi}", "name": f"MV DEMO-{mmsi[3:]}",
            "type": "general", "length": float(rng.uniform(100, 260)),
            "width": float(rng.uniform(18, 40)), "draft": float(rng.uniform(6, 14)),
            "cargo": "containers", "avg_speed": float(rng.uniform(9, 16)),
        })
    vessels = pd.DataFrame(vrows)

    # --- 5. Event master record ---
    events = pd.DataFrame([{
        "spill_id": event_id,
        "date": "2026-03-05",
        "time": "06:00:00",
        "latitude": ORIGIN_LAT, "longitude": ORIGIN_LON,
        "known_origin": "synthetic",
        "satellite_scene": f"syn_{event_id}",
        "spill_area": float(np.round(scene.oil_mask.mean() * (size * pixel_size_km) ** 2, 2)),
        "source": "synthetic-demo",
        "vessel": truth_mmsi,
        "validation_status": "synthetic-reference",
    }])

    return DemoScenario(
        event_id=event_id,
        scene=scene,
        fields=fields,
        ais=ais,
        vessels=vessels,
        events=events,
        truth_mmsi=truth_mmsi,
        slick_centroid_geo=(slick_lat, slick_lon),
        origin_geo=origin_geo,
        origin_release_time_s=origin_release_time_s,
        detection_time_s=detection_time_s,
        meta={"seed": seed, "size": size, "pixel_size_km": pixel_size_km},
    )


def persist_demo_scenario(demo: DemoScenario, outdir: Optional[Path] = None) -> Path:
    """Write the demo scenario artifacts to disk (CSV/parquet/GeoTIFF)."""
    outdir = outdir or (RAW_DIR / "demo" / demo.event_id)
    outdir.mkdir(parents=True, exist_ok=True)

    demo.ais.to_csv(outdir / "ais.csv", index=False)
    demo.vessels.to_csv(outdir / "vessels.csv", index=False)
    demo.events.to_csv(MASTER_DIR / "spill_events.csv", index=False)

    np.save(outdir / "scene_vv.npy", demo.scene.vv)
    np.save(outdir / "scene_vh.npy", demo.scene.vh)
    np.save(outdir / "oil_mask.npy", demo.scene.oil_mask)

    # write a synthetic GeoTIFF so the rasterio path is demonstrable
    try:
        import rasterio
        from rasterio.transform import from_origin
        bands = np.stack([demo.scene.vv, demo.scene.vh], axis=0)
        g = demo.scene.meta["geotransform"]
        px_size = demo.scene.meta["pixel_size_km"] / 111.32
        with rasterio.open(outdir / "sentinel1_grd.tif", "w",
                           driver="GTiff", height=demo.scene.vv.shape[0],
                           width=demo.scene.vv.shape[1], count=2, dtype="float32",
                           transform=from_origin(g[0], g[3], px_size, px_size),
                           crs="EPSG:4326") as dst:
            dst.write(bands.astype(np.float32) * 60.0 - 30.0)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not write demo GeoTIFF: %s", exc)

    return outdir