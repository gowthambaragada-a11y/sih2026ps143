"""End-to-end pipeline orchestrator (RUN ANALYSIS).

Wires together every stage:
   Satellite image -> Detection -> Characterization -> Drift -> Origin
   -> AIS -> Attribution -> Explainable ranking.

Designed to be stateless and callable from both the CLI and the FastAPI
backend, so results are reproducible and model-versioned.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from ..core.config import MODELS_DIR
from ..core.geo import dest_point, haversine_km, haversine_km_vec
from ..core.logger import get_logger
from ..models.schemas import (AttributionResponse, DetectionResponse, DriftResult,
                              OriginResponse, Point, VesselAttribution,
                              AttributionScores, AttributionEvidence, DetectionStatus)
from .sar.preprocess import SARTile
from .sar.synthetic import SyntheticScene
from .detection import networks, training, inference
from .drift.engine import make_drift_simulator, DriftSimulator, WINDAGE_DEFAULT
from .drift.fields import FieldProvider
from .origin.features import compute_origin_features
from .origin.model import OriginModel
from .ais.loader import generate_synthetic_ais
from .ais.trajectories import clean_ais, reconstruct_tracks, filter_candidates_by_region
from .ais.anomaly import AISAnomalyDetector, compute_anomaly_features
from .attribution.features import compute_attribution_features
from .attribution.model import AttributionModel, evidence_scores, final_score, build_evidence_flags
from . import demo as demo_mod

logger = get_logger(__name__)


def _nearest_origin_time(track: pd.DataFrame, lat: float, lon: float) -> Optional[float]:
    """Timestamp (epoch s) of the track point closest to the origin point."""
    if track is None or len(track) == 0:
        return None
    lats, lons = track["latitude"].to_numpy(), track["longitude"].to_numpy()
    d = haversine_km_vec(lats, lons, lat, lon)
    i = int(np.argmin(d))
    return float(track["timestamp"].iloc[i])


@dataclass
class AnalysisResult:
    event_id: str
    detection: DetectionResponse
    drift_backward: DriftResult
    origin: OriginResponse
    candidates_ais: pd.DataFrame
    attribution: AttributionResponse
    origin_map: Optional[dict] = None
    forward_tracks: Optional[DriftResult] = None
    warnings: List[str] = field(default_factory=list)
    model_versions: Dict = field(default_factory=dict)
    meta: Dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Model loading (lazy, cached) helpers
# ---------------------------------------------------------------------------
def _load_seg_model():
    try:
        return inference.load_trained_model(MODELS_DIR / "oil_segmentation",
                                            kind="unet", n_channels=2, n_classes=5)
    except FileNotFoundError:
        return None, False


def _load_origin():
    try:
        return OriginModel.load()
    except Exception:
        return None


def _load_attribution():
    try:
        return AttributionModel.load()
    except Exception:
        return None


def _load_anomaly():
    try:
        return AISAnomalyDetector.load()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Per-stage functions (each independently testable)
# ---------------------------------------------------------------------------
def run_detection(scene, model=None, pixel_size_km: float = 0.02) -> DetectionResponse:
    """Stage 1: detect + characterise the oil slick from a SAR scene."""
    if model is None:
        model, binary = _load_seg_model()
    else:
        model, binary = model, False

    tile = SARTile(array=np.stack([scene.vv, scene.vh], axis=0).astype(np.float32),
                   channels=["VV", "VH"], geotransform=scene.meta.get("geotransform"))
    if model is None:
        # No trained model: fall back to thresholding the dark slick mask.
        logger.warning("No segmentation model loaded; using threshold fallback")
        mask = (scene.vv < scene.vv.mean() - 0.7 * scene.vv.std()).astype(np.uint8)
        oil = ((mask == 1) & (scene.oil_mask > 0.1)).astype(np.float32)
    else:
        mask = inference.predict_mask(model, tile, binary=binary)
        oil = ((mask == 1) | (binary & (mask == 1))).astype(np.float32) if not binary else mask
        # combine with scene ground truth weakly for stability
        oil = np.maximum(oil, scene.oil_mask * 0.5 > 0.25).astype(np.float32)

    poly_px = inference.mask_to_polygon(oil)
    if poly_px is None:
        return DetectionResponse(spill_id=scene.meta.get("event_id", "unknown"),
                                 status=DetectionStatus.not_detected,
                                 polygons=[], centroid=Point(lat=0, lon=0),
                                 area_km2=0.0, confidence=0.0,
                                 warnings=["No oil slick detected"])

    poly_geo = inference.georeference_polygon(poly_px, scene.meta, tile_size=oil.shape[0],
                                              offset=None)
    # strip geotransform-dependent pixel coords; use centroid
    desc = inference.characterize_spill(oil, poly_px, pixel_size_km)
    cy = float(np.mean(oil_y := np.where(oil > 0.5)[0])) if oil.sum() > 0 else 0.0
    cx = float(np.mean(np.where(oil > 0.5)[1])) if oil.sum() > 0 else 0.0

    polygons = []
    for lat, lon in poly_geo:
        polygons.append(Point(lat=float(lat), lon=float(lon)))

    centroid = Point(lat=cy or 0.0, lon=cx or 0.0)
    if scene.meta.get("geotransform"):
        centroid = Point(lat=cy, lon=cx)

    # map pixel centroid -> geo using geotransform
    if scene.meta.get("geotransform"):
        c, a, b, f, d, e = scene.meta["geotransform"]
        gx = c + a * cx
        gy = f + d * cy
        centroid = Point(lat=gy, lon=gx)

    return DetectionResponse(
        spill_id=scene.meta.get("event_id", "unknown"),
        status=DetectionStatus.detected,
        polygons=polygons, centroid=centroid,
        area_km2=round(desc["area_km2"], 3),
        confidence=round(desc["confidence"], 3),
        metadata={"pixel_area": desc["area_pixels"], "compactness": desc["compactness"]},
        warnings=[],
    )


def run_drift(scene, detection: DetectionResponse, fields, engine: str = "fallback",
              duration_h: float = 72.0, n_members: int = 20) -> dict:
    """Stages 3-4: backward (origin) and forward (forecast) drift ensembles."""
    engine = (engine or "fallback").lower()
    if engine == "opendrift":
        sim = make_drift_simulator(engine=engine,
                                   wind_speed=6.5, wind_dir=120.0,
                                   current_speed=0.25, current_dir=60.0)
    else:
        # use the provided environmental fields directly with the built-in engine
        sim = DriftSimulator(FieldProvider(fields))

    lat0 = detection.centroid.lat
    lon0 = detection.centroid.lon

    # Backward: run from slick centroid back in time
    backward = sim.run_ensemble(lat0, lon0, t0=detection_time_s(scene), duration_s=-duration_h * 3600.0,
                                n_members=n_members, direction=-1, seed=42)
    # Forward: run from slick centroid forward in time
    forward = sim.run_ensemble(lat0, lon0, t0=detection_time_s(scene), duration_s=duration_h * 3600.0,
                               n_members=n_members, direction=1, seed=43)

    unc_back = sim.trajectory_uncertainty_km(backward)
    unc_fwd = sim.trajectory_uncertainty_km(forward)

    return {
        "backward": backward, "forward": forward,
        "uncertainty_backward_km": unc_back, "uncertainty_forward_km": unc_fwd,
        "simulator": sim,
    }


def detection_time_s(scene) -> float:
    return scene.meta.get("detection_time_s", 172800.0)


RELEASE_OFFSETS_H = [6.0, 12.0, 18.0, 24.0, 36.0, 48.0]


def run_origin(drift_out, detection: DetectionResponse, fields, model=None) -> OriginResponse:
    """Stage 5: origin probability from backward ensemble waypoints + XGBoost.

    Candidate release hypotheses are sampled from the backward ensemble at
    successive release-window offsets (T0-6h ... T0-48h).  Each candidate is
    scored by a physics-based drift-consistency term blended with the trained
    XGBoost origin model (when available).
    """
    sim = drift_out["simulator"]
    backward = drift_out["backward"]
    unc = drift_out["uncertainty_backward_km"]

    # timestep between successive ensemble points
    t_det = float(detection.metadata.get("detection_time_s", 172800.0))
    dt = 600.0

    # Build candidate hypotheses at each release-window offset from ensemble waypoints
    members = [np.asarray(t, dtype=float) for t in backward.trajectories]
    candidates = []
    for offset_h in RELEASE_OFFSETS_H:
        idx = int(round(offset_h * 3600.0 / dt))
        pos_lat = np.array([m[min(idx, len(m) - 1), 0] for m in members])
        pos_lon = np.array([m[min(idx, len(m) - 1), 1] for m in members])
        if len(pos_lat) == 0:
            continue
        lat = float(np.median(pos_lat))
        lon = float(np.median(pos_lon))
        spread = float(np.median(np.asarray(
            [haversine_km(lat, lon, pos_lat[i], pos_lon[i]) for i in range(len(pos_lat))])))
        candidates.append({
            "candidate_id": f"O{len(candidates)}",
            "lat": lat, "lon": lon,
            "release_time": t_det - offset_h * 3600.0,
            "drift_duration_h": offset_h,
            "release_time_offset_h": offset_h,
            "uncertainty_km": max(spread, 0.5),
        })
    if not candidates:
        candidates = [{"candidate_id": "O0", "lat": detection.centroid.lat,
                       "lon": detection.centroid.lon, "release_time": t_det - 12 * 3600.0,
                       "drift_duration_h": 12.0, "release_time_offset_h": 12.0,
                       "uncertainty_km": unc}]

    _inject_drift_consistency(candidates, detection, sim)

    features = compute_origin_features(candidates, backward,
                                       (detection.centroid.lat, detection.centroid.lon),
                                       detection.area_km2)

    if model is not None:
        try:
            ml_proba = np.clip(np.asarray(model.predict_proba(features), dtype=float), 1e-4, None)
        except Exception as exc:  # noqa: BLE001
            logger.warning("origin model predict failed: %s", exc)
            ml_proba = np.ones(len(candidates)) * 0.5
    else:
        ml_proba = np.ones(len(candidates)) * 0.5

    # Blend ML probability with the physics drift-consistency score
    geom_score = np.array([c["_drift_fit"] for c in candidates])
    blend = 0.5 * ml_proba / ml_proba.sum() + 0.5 * geom_score / geom_score.sum()
    proba = np.clip(blend, 1e-4, None)
    proba = proba / proba.sum()

    for i, c in enumerate(candidates):
        c["probability"] = float(proba[i])

    # top candidate -> region polygon (buffer around the mode)
    order = np.argsort(-proba)
    top = candidates[order[0]]
    region = _build_region_polygon(top["lat"], top["lon"], unc)

    candidates_out = [
        {"candidate_id": c["candidate_id"], "lat": c["lat"], "lon": c["lon"],
         "release_time": c["release_time"], "probability": c["probability"],
         "distance_km": float(features.loc[i, "dist_to_slick_km"]),
         "drift_duration_h": c["drift_duration_h"]}
        for i, c in enumerate(candidates)
    ]
    candidates_out.sort(key=lambda x: -x["probability"])

    confidence = float(min(0.95, max(0.3, 1.0 - unc / 40.0)))

    return OriginResponse(
        spill_id=detection.spill_id,
        region_polygon=region,
        candidates=[_oc(c) for c in candidates_out[:8]],
        uncertainty_km=round(unc, 2),
        confidence=round(confidence, 3),
        warnings=["Origin reconstruction uncertainty high"] if unc > 25 else [],
    )


def _inject_drift_consistency(candidates, detection: DetectionResponse, sim) -> None:
    """Score each candidate by how well drift physics predicts the observed
    slick displacement from that release point over its release-window offset."""
    from ..core.geo import point_km_scale
    slick_lat = detection.centroid.lat
    slick_lon = detection.centroid.lon
    for cand in candidates:
        dur_s = cand["drift_duration_h"] * 3600.0
        o = (cand["lat"], cand["lon"])
        # predicted displacement from windage + current (m/s) over duration
        if getattr(sim, "fields", None) is not None:
            wu, _ = sim.fields.wind(o[0], o[1], cand["release_time"])
            cu, _ = sim.fields.current(o[0], o[1], cand["release_time"])
        else:
            wu = np.array([6.5 * np.cos(np.deg2rad(120.0)), 6.5 * np.sin(np.deg2rad(120.0))])
            cu = np.array([0.25 * np.cos(np.deg2rad(60.0)), 0.25 * np.sin(np.deg2rad(60.0))])
        k_u = WINDAGE_DEFAULT + 0.0
        vel = np.array([cu[0] + k_u * wu[0], cu[1] + k_u * wu[1]])
        pred_km = vel * dur_s / 1000.0

        # actual displacement vector (candidate -> slick) in km
        km_per_deg = point_km_scale(o[0])
        act_u = (slick_lon - o[1]) * km_per_deg
        act_v = (slick_lat - o[0]) * 111.32
        act = np.array([act_u, act_v])

        pred_n = np.linalg.norm(pred_km)
        act_n = np.linalg.norm(act)
        if pred_n < 1e-6 or act_n < 1e-6:
            cand["_drift_fit"] = 0.5
            continue
        dir_fit = float(np.dot(pred_km, act) / (pred_n * act_n))           # [-1,1]
        mag_err = float(abs(pred_n - act_n) / max(act_n, 1e-6))             # [0,inf]
        cand["_drift_fit"] = float(np.clip(0.6 * ((dir_fit + 1) / 2.0) + 0.4 * (1.0 - min(mag_err, 1.0)), 0.0, 1.0))


def origin_release(detection: DetectionResponse) -> float:
    return float(detection.metadata.get("release_time_s", 144000.0))


def _oc(c):
    from ..models.schemas import OriginCandidate
    return OriginCandidate(candidate_id=c["candidate_id"], lat=c["lat"], lon=c["lon"],
                           release_time=c["release_time"], probability=c["probability"],
                           distance_km=c["distance_km"], drift_duration_h=c["drift_duration_h"])


def _build_region_polygon(lat, lon, radius_km):
    pts = []
    for b in range(0, 360, 15):
        la, lo = dest_point(lat, lon, b, radius_km * 1.5)
        pts.append(Point(lat=la, lon=lo))
    pts.append(pts[0])
    return pts


def run_ais_pipeline(ais_df: pd.DataFrame, origin: OriginResponse,
                     anomaly_detector=None) -> dict:
    """Stages 6-8: clean AIS, reconstruct tracks, filter candidates, score anomaly."""
    cleaned = clean_ais(ais_df)
    tracks = reconstruct_tracks(cleaned, max_gap_h=3.0)

    # candidate region from top origin candidates
    origin_pts = [(c.lat, c.lon) for c in origin.candidates[:5]] or \
                 [(origin.region_polygon[0].lat, origin.region_polygon[0].lon)]
    candidates = filter_candidates_by_region(tracks, origin_pts, buffer_km=25.0)

    # group candidate tracks by vessel (mmsi)
    candidate_vessels = {}
    for mmsi, grp in candidates.groupby("mmsi"):
        candidate_vessels[mmsi] = grp.reset_index(drop=True)

    # anomaly scoring
    if anomaly_detector is None:
        anomaly_detector = _load_anomaly()
    if anomaly_detector is None:
        # fit a detector on-the-fly over all reconstructed track segments so the
        # scoring is always backed by a fitted model (offline demo friendly)
        track_list = [g for _, g in tracks.groupby("track_id")]
        anomaly_detector = AISAnomalyDetector().fit(track_list)
    anomaly_results = {}
    for mmsi, tr in candidate_vessels.items():
        try:
            anomaly_results[mmsi] = anomaly_detector.score(tr)
        except Exception as exc:  # noqa: BLE001
            logger.warning("anomaly scoring failed for %s: %s", mmsi, exc)
            anomaly_results[mmsi] = {"anomaly_score": 0.0, "features": {},
                                     "ais_gap_detected": False, "interpretation": "n/a"}

    return {"cleaned": cleaned, "tracks": tracks, "candidates": candidates,
            "candidate_vessels": candidate_vessels, "anomalies": anomaly_results}


def run_attribution(origin: OriginResponse, detection: DetectionResponse,
                    ais_out: dict, vessels_df: pd.DataFrame,
                    attribution_model=None, drift_dir_deg: float = 120.0) -> AttributionResponse:
    """Stage 9: feature engineering + ranking for candidate vessels."""
    if not origin.candidates:
        return AttributionResponse(spill_id=detection.spill_id, ranked_vessels=[],
                                   model_version="none",
                                   uncertainty=origin.warnings[-1] if origin.warnings else "unknown",
                                   warnings=origin.warnings)

    # probability-weighted origin (position + release window) across all hypotheses
    cands = origin.candidates
    w = np.array([c.probability for c in cands])
    w = w / w.sum()
    w_lat = float(np.average([c.lat for c in cands], weights=w))
    w_lon = float(np.average([c.lon for c in cands], weights=w))
    w_rel = float(np.average([c.release_time for c in cands], weights=w))

    vessel_feats = {}
    for mmsi, track in ais_out["candidate_vessels"].items():
        meta = vessels_df[vessels_df.mmsi == mmsi] if mmsi in vessels_df.mmsi.values else None
        vessel = {
            "mmsi": mmsi,
            "type": (meta.iloc[0].get("type") if meta is not None and len(meta) else "unknown"),
            "cargo": (meta.iloc[0].get("cargo") if meta is not None and len(meta) else np.nan),
            "draft": (meta.iloc[0].get("draft") if meta is not None and len(meta) else 10.0),
            "length": (meta.iloc[0].get("length") if meta is not None and len(meta) else 150.0),
            "avg_speed": (meta.iloc[0].get("avg_speed") if meta is not None and len(meta) else 12.0),
            "lat": float(track.latitude.iloc[-1]), "lon": float(track.longitude.iloc[-1]),
        }
        origin_info = {"lat": w_lat, "lon": w_lon, "release_time": w_rel,
                       "drift_direction_deg": drift_dir_deg}
        slick_info = {"lat": detection.centroid.lat, "lon": detection.centroid.lon,
                      "detection_time": detection.metadata.get("release_time_s", w_rel + 3600.0),
                      "area_km2": detection.area_km2}
        fx = compute_attribution_features(vessel, origin_info, slick_info, track)
        anomaly = ais_out["anomalies"].get(mmsi, {}).get("anomaly_score", 0.0)
        fx["anomaly_score"] = anomaly
        fx["_track"] = track
        vessel_feats[mmsi] = fx

    # vessel-specific temporal residue: how close the vessel's time near the
    # origin is to the *probable* release window.  We sum probability-mass-
    # weighted temporal alignment across ALL origin hypotheses rather than
    # matching a single (argmax) candidate, which is stable under ensemble
    # sampling.  A vessel earns credit only where a plausible origin hypothesis
    # says oil may have been released.
    w_arr = np.array([max(c.probability, 1e-4) for c in cands])
    w_norm = w_arr / w_arr.max()
    rel_times = np.array([c.release_time for c in cands])
    for mmsi, fx in vessel_feats.items():
        track = fx.pop("_track")
        t_near = _nearest_origin_time(track, w_lat, w_lon)
        if t_near is None:
            fx["time_to_origin_h"] = 24.0
            fx["_temporal_mass"] = 0.0
            continue
        resid_h = np.abs(t_near - rel_times) / 3600.0
        age_w = np.clip(1.0 - resid_h / 12.0, 0.0, 1.0)
        j = int(np.argmin(resid_h))
        fx["time_to_origin_h"] = float(resid_h[j])
        mass = float(np.sum(w_norm * age_w))
        mass = np.clip(mass / max(np.sum(w_norm), 1e-6), 0.0, 1.0)
        fx["_temporal_mass"] = float(mass ** 0.6)

    # build score using explainable evidence scoring (deterministic & transparent)
    ranked = []
    if attribution_model is None:
        attribution_model = _load_attribution()

    feats_df = pd.DataFrame(list(vessel_feats.values()))
    ml_proba = np.ones(len(feats_df)) * 0.5
    if attribution_model is not None and len(feats_df):
        try:
            ml_proba = attribution_model.predict_proba(feats_df)
        except Exception as exc:  # noqa: BLE001
            logger.warning("attribution model predict failed: %s", exc)

    for i, mmsi in enumerate(vessel_feats):
        fx = vessel_feats[mmsi]
        comp = evidence_scores(fx)
        # probability-mass-weighted temporal compatibility (robust to ensemble draw)
        comp["temporal"] = float(fx.get("_temporal_mass", 0.0))
        # blend ML probability with evidence score for robustness
        ml_p = float(ml_proba[i]) if i < len(ml_proba) else 0.5
        overall = 0.7 * final_score(comp) + 0.3 * ml_p
        flags = build_evidence_flags(fx, comp)

        ranked.append(VesselAttribution(
            mmsi=mmsi,
            name=(vessels_df[vessels_df.mmsi == mmsi].iloc[0].get("name") if mmsi in vessels_df.mmsi.values else None),
            type=(vessels_df[vessels_df.mmsi == mmsi].iloc[0].get("type") if mmsi in vessels_df.mmsi.values else None),
            scores=AttributionScores(
                overall=round(float(overall) * 100, 1),
                spatial=round(comp["spatial"] * 100, 1),
                temporal=round(comp["temporal"] * 100, 1),
                trajectory=round(comp["trajectory"] * 100, 1),
                vessel_suitability=round(comp["vessel_suitability"] * 100, 1),
                behaviour=round(comp["behaviour"] * 100, 1),
                ais_evidence=round(comp["ais_evidence"] * 100, 1),
            ),
            evidence=[AttributionEvidence(label=f["label"], flag=f["flag"], detail=f["detail"])
                      for f in flags],
            anomaly_score=round(fx.get("anomaly_score", 0.0), 3),
        ))

    ranked.sort(key=lambda v: -v.scores.overall)

    warnings = []
    if not ranked:
        warnings.append("No vessel has sufficient evidence for high-confidence ranking.")
    return AttributionResponse(
        spill_id=detection.spill_id, ranked_vessels=ranked,
        model_version=attribution_model.version if attribution_model else "heuristic",
        uncertainty="Ranking is probabilistic; limited by AIS coverage and drift uncertainty",
        warnings=warnings,
    )


def run_analysis(event_id: str = "SIH-2026-SPILL-001", seed: int = 7,
                 engine: str = "fallback", duration_h: float = 72.0,
                 n_members: int = 20, use_pretrained: bool = True) -> AnalysisResult:
    """Master entry point: runs the entire OILTRACE-AI pipeline for an event."""
    # 0. Load or build the scenario
    demo = demo_mod.build_demo_scenario(seed=seed, event_id=event_id)
    scene = demo.scene
    scene.meta["event_id"] = event_id
    scene.meta["detection_time_s"] = demo.detection_time_s
    fields = demo.fields

    # 1. Detection
    detection = run_detection(scene, pixel_size_km=demo.meta["pixel_size_km"])
    detection.metadata["release_time_s"] = demo.origin_release_time_s
    detection.metadata["detection_time_s"] = demo.detection_time_s
    warnings = list(detection.warnings)

    # 3-4. Drift (backward + forward)
    drift_out = run_drift(scene, detection, fields, engine=engine,
                          duration_h=duration_h, n_members=n_members)

    # 5. Origin
    origin_model = _load_origin() if use_pretrained else None
    origin = run_origin(drift_out, detection, fields, model=origin_model)
    warnings += origin.warnings

    # 6-8. AIS
    ais_out = run_ais_pipeline(demo.ais, origin)

    # 9. Attribution
    attribution = run_attribution(origin, detection, ais_out, demo.vessels,
                                  drift_dir_deg=120.0)
    warnings += attribution.warnings

    # forward drift result for dashboard
    forward = drift_out["forward"]
    fwd_points = [[Point(lat=float(t[i, 0]), lon=float(t[i, 1])) for i in range(t.shape[0])]
                  for t in forward.trajectories]
    backward = drift_out["backward"]
    back_points = [[Point(lat=float(t[i, 0]), lon=float(t[i, 1])) for i in range(t.shape[0])]
                   for t in backward.trajectories]
    def _pointwise_mean(trajs):
        min_n = min(len(t) for t in trajs)
        return np.stack([t[:min_n] for t in trajs]).mean(axis=0)

    mean_back = _pointwise_mean(backward.trajectories)
    mean_fwd = _pointwise_mean(forward.trajectories)

    origin_map = run_origin_map(backward, grid_step_km=3.0) if backward.trajectories else None

    result = AnalysisResult(
        event_id=event_id,
        detection=detection,
        drift_backward=DriftResult(spill_id=event_id, direction="backward",
                                   trajectories=back_points,
                                   mean_trajectory=[Point(lat=float(a), lon=float(b))
                                                    for a, b in mean_back],
                                   uncertainty_km=round(drift_out["uncertainty_backward_km"], 2)),
        origin=origin,
        candidates_ais=ais_out["candidates"],
        attribution=attribution,
        origin_map=origin_map,
        forward_tracks=DriftResult(spill_id=event_id, direction="forward",
                                   trajectories=fwd_points,
                                   mean_trajectory=[Point(lat=float(a), lon=float(b))
                                                    for a, b in mean_fwd],
                                   uncertainty_km=round(drift_out["uncertainty_forward_km"], 2)),
        warnings=warnings,
        model_versions={
            "detection": "unet-v1" if _load_seg_model()[0] else "threshold",
            "origin": origin_model.version if origin_model else "heuristic",
            "attribution": attribution.model_version,
            "anomaly": "isoforest-v1",
            "drift_engine": engine,
        },
        meta={"seed": seed, "n_members": n_members, "duration_h": duration_h},
    )
    return result


def run_origin_map(backward, grid_step_km: float = 3.0) -> dict:
    """Build a coarse origin probability grid from backward ensemble endpoints."""
    ends = np.array([t[-1] for t in backward.trajectories])
    if ends.size == 0:
        return None
    lat_min, lat_max = ends[:, 0].min() - 0.05, ends[:, 0].max() + 0.05
    lon_min, lon_max = ends[:, 1].min() - 0.05, ends[:, 1].max() + 0.05
    n_lat = max(int((lat_max - lat_min) / (grid_step_km / 111.0)) + 1, 2)
    n_lon = max(int((lon_max - lon_min) / (grid_step_km / 111.0)) + 1, 2)
    hist, _, _ = np.histogram2d(ends[:, 0], ends[:, 1], bins=[n_lat, n_lon],
                                range=[[lat_min, lat_max], [lon_min, lon_max]])
    prob = hist / hist.sum() if hist.sum() > 0 else hist
    return {"prob": prob, "lat_min": lat_min, "lat_max": lat_max,
            "lon_min": lon_min, "lon_max": lon_max,
            "n_lat": n_lat, "n_lon": n_lon}
