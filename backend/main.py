"""OILTRACE-AI · SIHP-2026 PS143 FastAPI backend.

Pipeline: SAR image -> U-Net spill detection -> OpenDrift backward hindcast
-> AIS vessel attribution in a single POST /api/v1/detect call.

Run locally (from backend/):
    uvicorn main:app --reload --port 8000
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import requests
from fastapi import FastAPI, File, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from services import attribution, detector, hindcast

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("oiltrace")

VERSION = "2.0.0"
BACKEND_DIR = Path(__file__).resolve().parent
DEFAULT_EVENT_TIME = "2025-08-06T12:00:00"  # matches the bundled AIS day

app = FastAPI(
    title="OILTRACE-AI · PS143 Oil Spill Detection & Vessel Attribution",
    version=VERSION,
    description=(
        "Detect oil spills in SAR imagery, reconstruct the spill origin with "
        "OpenDrift, and attribute responsibility using AIS vessel traffic."
    ),
)

# CORS: local dev servers + the GitHub Pages dashboard.
CORS_ORIGINS = [
    "http://localhost:5173",
    "http://localhost:3000",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:8000",
    "https://gowthambaragada-a11y.github.io",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------------------------------- #
# Health
# --------------------------------------------------------------------------- #
@app.get("/health", tags=["meta"])
@app.get("/api/v1/health", tags=["meta"])
def health():
    return {
        "status": "ok",
        "service": "oiltrace-api",
        "version": VERSION,
        "modules": {
            "weights": bool(detector.find_weights()),
            "ais": bool(attribution.resolve_ais_csv()),
            "opendrift": bool(hindcast._opendrift_available()),
        },
    }


# --------------------------------------------------------------------------- #
# Detection pipeline
# --------------------------------------------------------------------------- #
def _bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Forward azimuth from point 1 -> point 2 (degrees, 0..360)."""
    import math

    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def _direction_label(bearing: float) -> str:
    dirs = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    return dirs[int(((bearing + 22.5) % 360) // 45)]


def _haversine_km(lat1, lon1, lat2, lon2) -> float:
    import math

    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


def run_pipeline(
    image_bytes: bytes | None = None,
    image_url: str | None = None,
    event_id: str = "sih2026ps143",
    event_time: str = DEFAULT_EVENT_TIME,
    scene: dict | None = None,
    source: str = "upload",
) -> dict:
    t_start = time.time()
    warnings: list[str] = []

    # 1) Obtain SAR image bytes ----------------------------------------------
    if image_bytes is None and image_url:
        try:
            r = requests.get(image_url, timeout=20)
            r.raise_for_status()
            image_bytes = r.content
            source = image_url
        except Exception as exc:
            return pipeline_error(event_id, f"Could not fetch image_url: {exc}")

    if image_bytes is None:
        return pipeline_error(event_id, "No SAR image provided.")

    # 2) Detection -----------------------------------------------------------
    det = detector.predict_sar_image(image_bytes, scene=scene, event_id=event_id)
    warnings += det["warnings"]

    if det["status"] != "detected" or det["centroid"] is None:
        return {
            "event_id": event_id,
            "status": "none",
            "model": det["model"],
            "source": source,
            "image_size": det["image_size"],
            "bounds": None,
            "polygon": None,
            "masks": None,
            "centroid": None,
            "confidence": det["confidence"],
            "confidence_pct": round(det["confidence"] * 100, 1),
            "severity": "low",
            "area_km2": 0.0,
            "perimeter_km": 0.0,
            "drift": None,
            "origin": None,
            "vessels": None,
            "tracks": None,
            "warnings": warnings,
            "latency_ms": int((time.time() - t_start) * 1000),
            "offline": False,
        }

    centroid = det["centroid"]
    rings_ll = det["polygon_rings"]
    bbox = det["bbox"]

    # 3) Hindcast the origin ---------------------------------------------------
    origin_res = hindcast.run_hindcast(centroid["lat"], centroid["lon"], event_time)
    warnings += origin_res["warnings"]
    origin = {
        "lat": origin_res["origin_lat"],
        "lon": origin_res["origin_lon"],
        "engine": origin_res["engine"],
        "backward_hours": hindcast.DURATION_HOURS,
    }

    # 4) Attribution -----------------------------------------------------------
    attr_res = attribution.correlate_vessel(
        origin["lat"], origin["lon"], event_time
    )
    warnings += attr_res["warnings"]
    vessels = attr_res["top"]
    tracks: dict = {}
    for v in vessels:
        mmsi = v["mmsi"]
        t = v["track"]
        tracks[mmsi] = {
            "lat": t["lat"],
            "lon": t["lon"],
            "t": t["t"],
            "sog": t["sog"],
        }
        v.pop("track", None)

    # 5) Drift summary -----------------------------------------------------------
    bearing = _bearing_deg(centroid["lat"], centroid["lon"], origin["lat"], origin["lon"])
    origin_dist_km = _haversine_km(
        centroid["lat"], centroid["lon"], origin["lat"], origin["lon"]
    )
    drift_speed = origin_dist_km / hindcast.DURATION_HOURS  # km/h
    traj = origin_res["trajectory"]
    drift = {
        "bearing_deg": round(bearing, 1),
        "speed_kmh": round(drift_speed, 3),
        "direction_label": _direction_label(bearing),
        "trajectory": traj,
    }

    # 6) Compose the frontend contract -------------------------------------------
    ring = rings_ll[0]
    coords = [ring]
    min_lon, min_lat, max_lon, max_lat = bbox

    return {
        "event_id": event_id,
        "status": "detected",
        "model": det["model"],
        "source": source,
        "image_size": det["image_size"],
        "bounds": {
            "type": "Feature",
            "bbox": [min_lon, min_lat, max_lon, max_lat],
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [
                        [min_lon, min_lat],
                        [max_lon, min_lat],
                        [max_lon, max_lat],
                        [min_lon, max_lat],
                        [min_lon, min_lat],
                    ]
                ],
            },
        },
        "polygon": {
            "type": "Feature",
            "properties": {
                "confidence": det["confidence"],
                "confidence_pct": det["confidence_pct"],
                "severity": det["severity"],
                "area_km2": det["area_km2"],
                "perimeter_km": det["perimeter_km"],
            },
            "geometry": {"type": "Polygon", "coordinates": coords},
        },
        "masks": {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {"class": "oil", "prob": det["confidence"]},
                    "geometry": {"type": "Polygon", "coordinates": coords},
                }
            ],
        },
        "centroid": centroid,
        "confidence": det["confidence"],
        "confidence_pct": det["confidence_pct"],
        "severity": det["severity"],
        "area_km2": det["area_km2"],
        "perimeter_km": det["perimeter_km"],
        "drift": drift,
        "origin": origin,
        "vessels": vessels,
        "tracks": tracks,
        "warnings": warnings,
        "latency_ms": int((time.time() - t_start) * 1000),
        "offline": False,
    }


def pipeline_error(event_id: str, message: str) -> dict:
    logger.error(message)
    return {
        "event_id": event_id,
        "status": "error",
        "model": None,
        "source": None,
        "image_size": None,
        "bounds": None,
        "polygon": None,
        "masks": None,
        "centroid": None,
        "confidence": 0.0,
        "confidence_pct": 0.0,
        "severity": "low",
        "area_km2": 0.0,
        "perimeter_km": 0.0,
        "drift": None,
        "origin": None,
        "vessels": None,
        "tracks": None,
        "warnings": [message],
        "latency_ms": 0,
        "offline": False,
    }


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #
@app.post("/api/v1/detect/file", tags=["detection"])
async def detect_file(
    file: UploadFile = File(..., description="SAR image (PNG/JPEG/TIFF)"),
    event_time: Optional[str] = None,
    scene: Optional[str] = None,  # optional JSON string: {"west":...,...}
):
    data = await file.read()
    _scene = _coerce_scene(scene)
    return run_pipeline(
        image_bytes=data,
        event_id=_strip_nonalnum(file.filename or "upload") or "upload",
        event_time=event_time or DEFAULT_EVENT_TIME,
        scene=_scene,
        source=f"upload:{file.filename}",
    )


@app.post("/api/v1/detect", tags=["detection"])
async def detect(request: Request):
    """Single detect route. Accepts multipart (UploadFile) OR JSON
    ``{"image_url": ..., "event_id": ..., "event_time": ...}``."""
    content_type = request.headers.get("content-type", "")
    if "multipart/form-data" in content_type:
        form = await request.form()
        file = form.get("file")
        if not isinstance(file, UploadFile):
            return JSONResponse(status_code=400, content={"detail": "Missing 'file' part."})
        data = await file.read()
        return run_pipeline(
            image_bytes=data,
            event_id=_strip_nonalnum(form.get("event_id") or file.filename or "upload") or "upload",
            event_time=str(form.get("event_time") or DEFAULT_EVENT_TIME),
            scene=_coerce_scene(form.get("scene")),
            source=f"upload:{file.filename}",
        )

    body = await request.json()
    return run_pipeline(
        image_url=(body or {}).get("image_url"),
        event_id=_strip_nonalnum((body or {}).get("event_id") or "ps143") or "ps143",
        event_time=str((body or {}).get("event_time") or DEFAULT_EVENT_TIME),
        scene=_coerce_scene((body or {}).get("scene")),
        source=(body or {}).get("image_url", "url"),
    )


def _coerce_scene(raw):
    if not raw:
        return None
    try:
        import json

        return json.loads(raw) if isinstance(raw, str) else dict(raw)
    except Exception:
        return None


def _strip_nonalnum(s: str) -> str:
    return "".join(ch for ch in s if ch.isalnum())[:40]


if __name__ == "__main__":
    import os

    import uvicorn

    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("main:app", host="0.0.0.0", port=port)