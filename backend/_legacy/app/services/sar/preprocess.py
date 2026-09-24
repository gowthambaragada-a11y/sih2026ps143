"""SAR preprocessing pipeline.

Real Sentinel-1 GRD processing (calibration, radiometric terrain normalisation,
land masking, tiling) is wrapped here behind a uniform interface.  Because the
demo runs offline, a synthetic SAR renderer is provided that produces VV/VH
chips with realistic sea texture, look-alikes and oil slicks.  The exporter can
be pointed at real GeoTIFFs through the same API.

All heavy raster handling uses rasterio; numpy/OpenCV handle array ops.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

from ...core.logger import get_logger

logger = get_logger(__name__)

LOG = logging.getLogger(__name__)


@dataclass
class SARTile:
    """One preprocessed SAR chip: array shape (C, H, W), channels [VV, VH]."""
    array: np.ndarray                # (C, H, W), float32, ~[0,1]
    channels: List[str]
    geotransform: Optional[Tuple[float, float, float, float, float, float]] = None
    crs: Optional[str] = None
    meta: Dict = field(default_factory=dict)

    def as_vvh(self) -> Tuple[np.ndarray, Optional[np.ndarray]]:
        vv = self.array[0]
        vh = self.array[1] if self.array.shape[0] > 1 else None
        return vv, vh


def normalize_db(x: np.ndarray) -> np.ndarray:
    """Convert amplitude to normalised [0,1] for the network."""
    x = np.nan_to_num(x, nan=-30.0, posinf=30.0, neginf=-30.0)
    lo, hi = -30.0, 5.0
    return np.clip((x - lo) / (hi - lo), 0.0, 1.0).astype(np.float32)


def load_geotiff(path: Path, bands: Optional[List[int]] = None) -> SARTile:
    """Load a real GeoTIFF of Sentinel-1 GRD into a SARTile.

    If the raster has 1 band it is treated as VV.  Channel order is inferred
    from metadata band names when available.
    """
    import rasterio

    with rasterio.open(str(path)) as src:
        data = src.read()
        names = src.descriptions or []
        gt = src.transform
        crs = str(src.crs) if src.crs else None
        meta = {"source": str(path), "band_names": names}
    # data shape (C,H,W)
    data = np.nan_to_num(data.astype(np.float32), nan=-30.0)
    if data.ndim == 2:
        data = data[None, :, :]
    channels = [str(n) if n else f"band{i+1}" for i, n in enumerate(names)]
    norm = np.stack([normalize_db(data[i]) for i in range(data.shape[0])])
    return SARTile(array=norm, channels=channels, geotransform=tuple(gt), crs=crs, meta=meta)


def tile_image(tile: SARTile, tile_size: int = 256, step: Optional[int] = None) -> List[SARTile]:
    """Slide a window over a large scene returning overlapping tiles."""
    step = step or tile_size
    _, h, w = tile.array.shape
    out = []
    for y in range(0, max(h - tile_size + 1, 1), step):
        for x in range(0, max(w - tile_size + 1, 1), step):
            patch = tile.array[:, y:y + tile_size, x:x + tile_size]
            if patch.shape[1] < tile_size or patch.shape[2] < tile_size:
                p = np.pad(patch, ((0, 0), (0, tile_size - patch.shape[1]),
                                   (0, tile_size - patch.shape[2])), mode="edge")
                patch = p
            out.append(SARTile(
                array=patch, channels=tile.channels,
                geotransform=tile.geotransform, crs=tile.crs,
                meta={"offset": (y, x), **tile.meta},
            ))
    return out


def land_sea_simple_mask(tile: SARTile) -> np.ndarray:
    """A crude land/sea discriminator: land is very bright & speckly in SAR.

    This is intentionally simple; production uses a coastline dataset / SRTM.
    Returns boolean array True=land.
    """
    vv = tile.array[0]
    bright = vv > 0.75
    # close small holes -> connected land masses
    from scipy import ndimage
    opened = ndimage.binary_opening(bright, iterations=3)
    filled = ndimage.binary_fill_holes(opened)
    return filled
