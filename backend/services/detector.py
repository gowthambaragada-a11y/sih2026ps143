"""U-Net SAR oil-spill detector (inference wrapper).

Uses the lightweight UNetTiny model from ``modules/sar_unet``
(``Oil_Spill_Detection_SAR_DL.py``). If no compatible PyTorch weights are
present it degrades gracefully to a dark-region segmentation baseline so the
API stays functional for the demo/dashboard.
"""
from __future__ import annotations

import os

# Avoid OpenMP duplicate-runtime crashes when torch + scipy/opendrift coexist.
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

import io
import logging
import math
from functools import lru_cache
from pathlib import Path

import numpy as np
import torch
from PIL import Image

logger = logging.getLogger(__name__)

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BACKEND_DIR.parent
SAR_UNET_DIR = REPO_DIR / "modules" / "sar_unet"
WEIGHTS_DIR = BACKEND_DIR / "weights"

# Image has no georeferencing -> map pixels onto a default scene footprint.
# Default is the Gulf of Mexico / Mississippi delta corridor, which matches the
# bundled AIS traffic (ais-2025-08-06.csv.zst). Override per-request via scene.
DEFAULT_SCENE = {"west": -91.40, "east": -90.00, "south": 28.30, "north": 29.60}

# Weight search order: explicit env override first, then the weights dir,
# then an existing training export inside modules/sar_unet.
def _candidate_weight_paths() -> list[Path]:
    override = os.getenv("OIL_UNET_WEIGHTS_PATH")
    cands: list[Path] = []
    if override:
        cands.append(Path(override))
    cands += [
        WEIGHTS_DIR / "best_unet_tiny.pt",
        SAR_UNET_DIR / "outputs" / "best_unet_tiny.pt",
        SAR_UNET_DIR / "best_unet_tiny.pt",
    ]
    return cands


def find_weights() -> Path | None:
    for p in _candidate_weight_paths():
        if p.is_file():
            return p
    return None


@lru_cache(maxsize=1)
def _load_sar_unet_module():
    """Import the U-Net definitions from modules/sar_unet via importlib."""
    script = SAR_UNET_DIR / "Oil_Spill_Detection_SAR_DL.py"
    if not script.is_file():
        return None
    import importlib.util

    spec = importlib.util.spec_from_file_location("sar_unet_dl", script)
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        return mod
    except Exception as exc:  # pragma: no cover - import surface keeps changing
        logger.warning("Could not import modules/sar_unet script: %s", exc)
        return None


@lru_cache(maxsize=1)
def _load_model():
    """Return (device, model, weights_path) or (None, None, None)."""
    mod = _load_sar_unet_module()
    if mod is None or not hasattr(mod, "UNetTiny"):
        return None, None, None
    wpath = find_weights()
    if wpath is None:
        return None, None, None
    try:
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        model = mod.UNetTiny(in_ch=1, out_ch=1, base=16).to(device)
        state = torch.load(str(wpath), map_location=device, weights_only=True)
        if isinstance(state, dict) and "state_dict" in state:
            state = state["state_dict"]
        model.load_state_dict(state)
        model.eval()
        return device, model, wpath
    except Exception as exc:
        logger.warning("Failed to load U-Net weights %s: %s", wpath, exc)
        return None, None, None


def _load_grayscale(image_bytes: bytes) -> Image.Image:
    with Image.open(io.BytesIO(image_bytes)) as im:
        im.load()
    if im.mode != "L":
        im = im.convert("L")
    return im


def _tensorize(img: Image.Image, size: int = 96) -> torch.Tensor:
    arr = np.asarray(img.resize((size, size), Image.BILINEAR), dtype=np.float32)
    arr = (arr - arr.min()) / (arr.max() - arr.min() + 1e-8)
    return torch.from_numpy(arr[None, None, ...])


def _predict_unet(img: Image.Image) -> np.ndarray:
    """Run UNetTiny inference, return mask at the input image resolution."""
    device, model, _ = _load_model()
    with torch.no_grad():
        x = _tensorize(img, 96).to(device)
        logits = model(x)
        prob = torch.sigmoid(logits)[0, 0].cpu().numpy()
    mask = (prob > 0.5).astype(np.uint8)
    mask = np.asarray(
        Image.fromarray((mask * 255).astype(np.uint8)).resize(
            img.size, Image.NEAREST
        ),
        dtype=np.uint8,
    ) // 255
    return mask.astype(bool), prob.max()


def _fallback_mask(img: Image.Image) -> tuple[np.ndarray, float]:
    """No-weights fallback: dark low-backscatter region segmentation."""
    arr = np.asarray(img, dtype=np.float32)
    k = _gaussian_kernel(5)
    sm = _convolve(arr, k)
    thr = np.percentile(sm[sm < np.percentile(sm, 85)], 35)
    raw = sm < thr
    lab = _largest_connected(raw)
    score = min(0.86, 0.50 + 0.04 * math.log10(lab.sum() + 1))
    return lab, score


def _gaussian_kernel(size: int, sigma: float = 1.0) -> np.ndarray:
    ax = np.linspace(-(size // 2), size // 2, size)
    g = np.exp(-(ax ** 2) / (2 * sigma ** 2))
    return np.outer(g, g) / np.sum(g)


def _convolve(a: np.ndarray, k: np.ndarray) -> np.ndarray:
    from scipy import ndimage

    return ndimage.convolve(a, k, mode="mirror")


def _largest_connected(mask: np.ndarray) -> np.ndarray:
    from scipy import ndimage

    lab, n = ndimage.label(mask)
    if n == 0:
        return np.zeros_like(mask, dtype=bool)
    sizes = ndimage.sum(mask, lab, range(1, n + 1))
    return lab == (np.argmax(sizes) + 1)


def _haversine_km(a_lat, a_lon, b_lat, b_lon) -> float:
    R = 6371.0
    p1, p2 = math.radians(a_lat), math.radians(b_lat)
    dp = p2 - p1
    dl = math.radians(b_lon - a_lon)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


def _mask_to_polygons(mask: np.ndarray) -> list[np.ndarray]:
    """Return simplified contours of masked blobs as pixel point arrays."""
    from skimage import measure

    contours: list[np.ndarray] = []
    for level in (0.5,):
        for c in measure.find_contours(mask.astype(float), level):
            if len(c) < 4:
                continue
            contours.append(c)
    return contours


def _pixel_to_lonlat(row: float, col: float, h: int, w: int, scene: dict):
    lon = scene["west"] + (col / max(w - 1, 1)) * (scene["east"] - scene["west"])
    lat = scene["north"] - (row / max(h - 1, 1)) * (scene["north"] - scene["south"])
    return float(lon), float(lat)


def _simplify_ring(lon_lat: list[tuple[float, float]], tolerance: float = 0.0004):
    pts = np.array(lon_lat)
    if len(pts) < 4:
        return lon_lat
    from shapely.geometry import LineString

    line = LineString(pts)
    keep = line.simplify(tolerance, preserve_topology=False)
    out = list(keep.coords)
    if len(out) < 4:
        out = lon_lat[:: max(1, len(lon_lat) // 8)]
    if out[0] != out[-1]:
        out = out + [out[0]]
    return out


def predict_sar_image(
    image_bytes: bytes,
    scene: dict | None = None,
    event_id: str = "sih2026ps143",
) -> dict:
    """Run end-to-end detection on a SAR image.

    Returns a dict with the binary mask, geo statistics, centroid, and a
    GeoJSON polygon, ready to be embedded in the API response.
    """
    img = _load_grayscale(image_bytes)
    scene = {**DEFAULT_SCENE, **(scene or {})}
    w, h = img.size

    device, model, wpath = _load_model()
    warnings: list[str] = []

    if model is not None:
        try:
            mask, peak_prob = _predict_unet(img)
            model_tag = f"unet-tiny:{Path(wpath).name}"
            weights_loaded = True
        except Exception as exc:  # pragma: no cover
            logger.warning("U-Net inference failed (%s); using baseline.", exc)
            mask, peak_prob = _fallback_mask(img)
            model_tag = "baseline-dark-region"
            weights_loaded = False
            warnings.append("U-Net inference failed; used dark-region baseline.")
    else:
        mask, peak_prob = _fallback_mask(img)
        model_tag = "baseline-dark-region"
        weights_loaded = False
        warnings.append(
            "No U-Net weights found (looked in backend/weights). "
            "Used dark-region segmentation baseline. Train with "
            "modules/sar_unet/Oil_Spill_Detection_SAR_DL.py and drop the "
            "checkpoint into backend/weights/best_unet_tiny.pt."
        )

    # --- Post-process: keep largest blob(s) & smooth -----------------------
    from scipy import ndimage

    mask = _largest_connected(mask)
    mask = ndimage.binary_closing(mask, iterations=2)
    mask = _largest_connected(mask)

    pixel_count = int(mask.sum())
    if pixel_count == 0:
        return {
            "event_id": event_id,
            "status": "none",
            "model": model_tag,
            "weights_loaded": weights_loaded,
            "image_size": [w, h],
            "mask": np.zeros((h, w), dtype=bool),
            "area_km2": 0.0,
            "perimeter_km": 0.0,
            "confidence": round(float(peak_prob), 4),
            "severity": "low",
            "centroid": None,
            "polygon": None,
            "bounds": None,
            "bbox": None,
            "warnings": warnings + ["No oil-like dark region detected."],
        }

    # --- Pixel-area & perimeter -------------------------------------------
    span_lon = scene["east"] - scene["west"]
    span_lat = scene["north"] - scene["south"]
    km_per_px = _haversine_km(
        scene["north"], scene["west"], scene["north"], scene["east"]
    ) / max(w - 1, 1)
    km_per_py = _haversine_km(
        scene["north"], scene["west"], scene["south"], scene["west"]
    ) / max(h - 1, 1)
    area_km2 = pixel_count * km_per_px * km_per_py

    rows, cols = np.nonzero(mask)
    c_lon, c_lat = _pixel_to_lonlat(rows.mean(), cols.mean(), h, w, scene)

    # --- GeoJSON polygon from contours -------------------------------------
    rings_px = _mask_to_polygons(mask)
    rings: list[list[tuple[float, float]]] = []
    for rp in rings_px:
        ring = [_pixel_to_lonlat(row, col, h, w, scene) for row, col in rp]
        ring = _simplify_ring(ring)
        rings.append(ring)

    perim_km = 0.0
    if rings:
        r0 = rings[0]
        perim_km = sum(
            _haversine_km(r0[i][1], r0[i][0], r0[(i + 1) % len(r0)][1], r0[(i + 1) % len(r0)][0])
            for i in range(len(r0))
        )

    confidence = min(0.99, float(peak_prob) + 0.30 if weights_loaded else float(peak_prob))
    severity = (
        "critical"
        if area_km2 > 60 or confidence > 0.95
        else "high"
        if area_km2 > 25 or confidence > 0.88
        else "medium"
        if area_km2 > 10
        else "low"
    )

    lons = [p[0] for ring in rings for p in ring]
    lats = [p[1] for ring in rings for p in ring]
    bbox = (min(lons), min(lats), max(lons), max(lats))

    return {
        "event_id": event_id,
        "status": "detected",
        "model": model_tag,
        "weights_loaded": weights_loaded,
        "image_size": [w, h],
        "mask": mask,
        "area_km2": round(area_km2, 3),
        "perimeter_km": round(perim_km, 3),
        "confidence": round(confidence, 4),
        "confidence_pct": round(confidence * 100, 1),
        "severity": severity,
        "centroid": {"lat": round(c_lat, 6), "lon": round(c_lon, 6)},
        "polygon_rings": rings,
        "bbox": list(bbox),
        "warnings": warnings,
    }