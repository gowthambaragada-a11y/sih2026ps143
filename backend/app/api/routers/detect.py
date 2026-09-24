"""Stage-3 detection endpoint: image -> GeoJSON bounds, confidence, masks.

Accepts either:
  * POST /detect           JSON  {"image_url": "..."}      (Firebase Storage URL)
  * POST /detect/file      multipart/form-data  (file: ...)

The segmentation model is not bundled in this deployment, so results are a
deterministic synthetic reconstruction seeded from the image identity — the
response shape matches the live pipeline contract and is labelled as such.
"""
from __future__ import annotations

import hashlib
import io
import math
import random
import time
from typing import Any, Optional

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

router = APIRouter(tags=["detect"])


class DetectUrlRequest(BaseModel):
    image_url: str
    event_id: Optional[str] = None


def _rng(key: str) -> random.Random:
    h = int(hashlib.sha256(key.encode("utf-8")).hexdigest()[:12], 16)
    return random.Random(h)


def _image_size(data: Optional[bytes]) -> Optional[tuple[int, int]]:
    if not data:
        return None
    try:
        from PIL import Image

        with Image.open(io.BytesIO(data)) as im:
            return im.size  # (w, h)
    except Exception:  # noqa: BLE001 - unknown/unsupported format is fine
        return None


def _haversine_km(a: dict, b: dict) -> float:
    r = 6371.0
    p1, p2 = math.radians(a["lat"]), math.radians(b["lat"])
    dp = p2 - p1
    dl = math.radians(b["lon"] - a["lon"])
    x = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(x))


def _shoelace_km2(ring: list[dict]) -> float:
    lat0 = sum(p["lat"] for p in ring) / len(ring)
    km_lat = 111.32
    km_lon = 111.32 * math.cos(math.radians(lat0))
    pts = [(p["lon"] * km_lon, p["lat"] * km_lat) for p in ring]
    area = 0.0
    n = len(pts)
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        area += x1 * y2 - x2 * y1
    return abs(area) / 2.0


def _build_result(key: str, source: str, size: Optional[tuple[int, int]]) -> dict[str, Any]:
    r = _rng(key)
    # Plausible offshore centre (Arabian Sea / Mumbai coast).
    lat = r.uniform(18.35, 19.45)
    lon = r.uniform(72.30, 73.25)

    n = 16
    r_lat = r.uniform(0.045, 0.12)
    r_lon = r.uniform(0.05, 0.15)
    ring: list[dict] = []
    for i in range(n):
        a = 2 * math.pi * i / n
        jitter = r.uniform(0.72, 1.28)
        ring.append(
            {
                "lat": round(lat + math.sin(a) * r_lat * jitter, 6),
                "lon": round(lon + math.cos(a) * r_lon * jitter, 6),
            }
        )

    area = round(_shoelace_km2(ring), 3)
    perimeter = round(sum(_haversine_km(ring[i], ring[(i + 1) % n]) for i in range(n)), 3)
    confidence = round(r.uniform(0.74, 0.945), 3)

    if area > 25 or confidence > 0.9:
        severity = "high"
    elif area > 12 or confidence > 0.84:
        severity = "medium"
    else:
        severity = "low"

    bearing = round(r.uniform(0, 359.9), 1)
    speed = round(r.uniform(0.15, 1.4), 2)
    dirs = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    direction = dirs[int((bearing + 22.5) // 45) % 8]

    # Forward drift trajectory: polyline along the bearing from the centroid.
    traj: list[dict] = []
    for step in range(1, 13):
        d_km = step * speed * 0.5
        dlat = (d_km * math.cos(math.radians(bearing))) / 111.32
        dlon = (d_km * math.sin(math.radians(bearing))) / (
            111.32 * math.cos(math.radians(lat))
        )
        traj.append({"lat": round(lat + dlat, 6), "lon": round(lon + dlon, 6)})

    ring_ll = [[p["lon"], p["lat"]] for p in ring] + [[ring[0]["lon"], ring[0]["lat"]]]
    lons = [p["lon"] for p in ring]
    lats = [p["lat"] for p in ring]
    bbox = [[min(lons), min(lats)], [max(lons), max(lats)]]

    polygon_geojson = {
        "type": "Feature",
        "properties": {
            "confidence": confidence,
            "severity": severity,
            "area_km2": area,
            "perimeter_km": perimeter,
            "confidence_pct": round(confidence * 100, 1),
        },
        "geometry": {"type": "Polygon", "coordinates": [ring_ll]},
    }
    mask_geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"class": "oil", "prob": confidence},
                "geometry": {"type": "Polygon", "coordinates": [ring_ll]},
            }
        ],
    }

    warnings: list[str] = []
    if size is None and source.startswith("http"):
        warnings.append(
            "Source image dimensions unreadable — geometry is synthetic and "
            "must be verified against the original scene before operational use."
        )
    else:
        warnings.append(
            "Synthetic reconstruction for demonstration — verify against the "
            "original scene before operational use."
        )

    return {
        "event_id": key,
        "status": "detected",
        "model": "unet-v1-mock",
        "source": source,
        "image_size": list(size) if size else None,
        "bounds": {
            "type": "Feature",
            "properties": {"kind": "bbox"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [
                        [bbox[0][0], bbox[0][1]],
                        [bbox[1][0], bbox[0][1]],
                        [bbox[1][0], bbox[1][1]],
                        [bbox[0][0], bbox[1][1]],
                        [bbox[0][0], bbox[0][1]],
                    ]
                ],
            },
            "bbox": [bbox[0][0], bbox[0][1], bbox[1][0], bbox[1][1]],
        },
        "polygon": polygon_geojson,
        "masks": mask_geojson,
        "centroid": {"lat": round(lat, 6), "lon": round(lon, 6)},
        "confidence": confidence,
        "confidence_pct": round(confidence * 100, 1),
        "severity": severity,
        "area_km2": area,
        "perimeter_km": perimeter,
        "drift": {
            "bearing_deg": bearing,
            "speed_kmh": speed,
            "direction_label": direction,
            "trajectory": traj,
        },
        "warnings": warnings,
    }


@router.post("/detect")
def detect_url(payload: DetectUrlRequest) -> dict[str, Any]:
    """Run detection on a remote image (Firebase Storage URL)."""
    t0 = time.time()
    if not payload.image_url or not payload.image_url.strip():
        raise HTTPException(status_code=422, detail="image_url is required")
    key = payload.event_id or hashlib.sha1(payload.image_url.encode("utf-8")).hexdigest()[:16]
    res = _build_result(key, payload.image_url, _image_size(None))
    res["latency_ms"] = int((time.time() - t0) * 1000)
    return res


@router.post("/detect/file")
async def detect_file(file: UploadFile = File(...)) -> dict[str, Any]:
    """Run detection on an uploaded image file (multipart/form-data)."""
    t0 = time.time()
    if not file.filename:
        raise HTTPException(status_code=422, detail="file is required")
    data = await file.read()
    if not data:
        raise HTTPException(status_code=422, detail="empty file")
    digest = hashlib.sha1(data).hexdigest()[:16]
    size = _image_size(data)
    res = _build_result(digest, file.filename, size)
    res["latency_ms"] = int((time.time() - t0) * 1000)
    return res
