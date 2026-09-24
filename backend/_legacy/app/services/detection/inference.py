"""Oil spill detection inference + characterization.

Turns a segmentation mask into a georeferenced slick polygon, computes area,
spill geometry descriptors and a confidence estimate.  Also performs the
look-alike rejection stage (dark non-oil regions are separated by class).
"""
from __future__ import annotations

import logging
from typing import List, Optional, Tuple

import numpy as np

from ...core.geo import array_area_km2
from ...core.logger import get_logger
from ..sar.preprocess import SARTile
from ..sar.synthetic import SyntheticScene
from . import networks, training

logger = get_logger(__name__)

OIL_CLASS = 1


def predict_mask(model, tile: SARTile, binary: bool = False) -> np.ndarray:
    """Predict class mask for a (possibly tiled) SAR chip."""
    return training.inference_segmentation(model, tile.array, binary=binary)


def mask_to_polygon(mask: np.ndarray) -> Optional[np.ndarray]:
    """Convert a binary oil mask to an ordered polygon (N,2) of [lat,lon]-space
    pixel coordinates.  Returns None if nothing found."""
    from scipy import ndimage
    labeled, n = ndimage.label(mask > 0.5)
    if n == 0:
        return None
    # keep the largest connected component
    sizes = ndimage.sum(mask > 0.5, labeled, range(1, n + 1))
    comp = int(np.argmax(sizes)) + 1
    comp_mask = (labeled == comp)
    yy, xx = np.where(comp_mask)
    if len(yy) < 3:
        return None
    from shapely.geometry import MultiPoint
    pts = MultiPoint(list(zip(xx.tolist(), yy.tolist())))
    hull = pts.convex_hull
    if hull.geom_type == "Point":
        return np.array([[xx[0], yy[0]]])
    if hull.geom_type == "LineString":
        coords = np.array(hull.coords)
        return coords
    return np.array(hull.exterior.coords)


def georeference_polygon(poly_pixels: np.ndarray, tile_meta: dict,
                         tile_size: int, offset: Optional[Tuple[int, int]]) -> np.ndarray:
    """If a geotransform is present, map pixel polygon to lat/lon.

    Returns (N,2) array of [lat,lon] or original pixels when no geo info.
    """
    gt = tile_meta.get("geotransform")
    if gt is None:
        return poly_pixels
    ox = offset[1] if offset else 0
    oy = offset[0] if offset else 0
    # pixel -> geo (x easting, y northing); gt = (c,a,b,f,d,e)
    c, a, b, f, d, e = gt
    out = []
    for px, py in poly_pixels:
        gx = c + a * (px + ox) + b * (py + oy)
        gy = f + d * (px + ox) + e * (py + oy)
        out.append([gy, gx])  # [lat, lon]
    return np.asarray(out)


def characterize_spill(mask: np.ndarray, poly_pixels: np.ndarray,
                       pixel_size_km: float = 0.02) -> dict:
    """Compute spill geometry descriptors and a confidence proxy.

    Confidence is based on how compact and well-resolved the slick is
    (area vs boundary smoothness)."""
    area_px = float((mask > 0.5).sum())
    area_km2 = area_px * (pixel_size_km ** 2)
    # perimeter from polygon length in pixels
    if len(poly_pixels) > 2:
        perim = np.sum(np.hypot(np.diff(poly_pixels[:, 0]),
                                np.diff(poly_pixels[:, 1])))
    else:
        perim = 0.0
    compactness = (4 * np.pi * area_px) / (perim * perim + 1e-6) if perim > 0 else 0.0
    return {
        "area_km2": float(area_km2),
        "area_pixels": float(area_px),
        "compactness": float(np.clip(compactness, 0, 1)),
        "confidence": float(np.clip(0.5 + 0.5 * compactness * (1.0 - 1 / (1 + area_px / 500.0)), 0, 1)),
    }


def detect_in_scene(model, scene: SyntheticScene, pixel_size_km: float = 0.02) -> dict:
    """End-to-end detection on a synthetic scene object."""
    tile = SARTile(array=np.stack([scene.vv, scene.vh], axis=0).astype(np.float32),
                   channels=["VV", "VH"])
    mask = predict_mask(model, tile)
    oil = (mask == OIL_CLASS)
    poly = mask_to_polygon(oil.astype(np.float32))
    if poly is None:
        return {"detected": False, "mask": mask}
    desc = characterize_spill(oil.astype(np.float32), poly, pixel_size_km)
    return {"detected": True, "mask": mask, "polygon_pixels": poly, **desc}


def load_trained_model(model_dir, kind: str = "unet", n_channels: int = 2,
                       n_classes: int = 5, device: str = "auto"):
    """Load a saved segmentation model from a model store directory."""
    import json
    import torch
    path = model_dir / "oil_segmentation.pt"
    if not path.exists():
        raise FileNotFoundError(f"Model not found: {path}")
    binary, saved_classes = False, n_classes
    cfg_path = model_dir / "config.json"
    if cfg_path.exists():
        try:
            cfg = json.loads(cfg_path.read_text())
            binary = bool(cfg.get("binary", False))
            saved_classes = int(cfg.get("n_classes", n_classes))
        except Exception:  # noqa: BLE001
            binary, saved_classes = False, n_classes
    model = networks.build_segmentation_model(
        kind, n_channels=n_channels, n_classes=saved_classes if not binary else 1)
    if device == "auto":
        device = "cuda" if torch.cuda.is_available() else "cpu"
    model.load_state_dict(torch.load(str(path), map_location=device))
    model.eval()
    return model, binary
