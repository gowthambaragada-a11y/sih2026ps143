"""Synthetic Sentinel-1-like SAR rendering for offline development/demonstration.

Generates realistic-looking VV/VH chips (or full scenes) containing:
  * Gaussian sea clutter (speckle-like texture)
  * a dark oil slick region with characteristic shape
  * SAR look-alikes (dark patches from wind shadows / biogenic films)
  * bright ship responses (point targets)
  * optional dark land mask

This lets the whole detection->drift->attribution pipeline run end-to-end
without real SAR downloads, while every stage also supports real GeoTIFF input
through the same code paths.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import numpy as np

from ...core.logger import get_logger

logger = get_logger(__name__)


def _speckle(shape, scale=1.0, rng: np.random.Generator = None) -> np.ndarray:
    rng = rng or np.random.default_rng(0)
    base = rng.gamma(shape=2.0, scale=1.0, size=shape)
    # smooth a little to emulate SAR resolution-cell averaging
    from scipy import ndimage
    base = ndimage.gaussian_filter(base, sigma=0.8)
    mean = base.mean()
    out = base / mean  # mean 1
    return out


def _gaussian_blob(shape, center, sigma, amplitude, rng=None, angle=0.0):
    yy, xx = np.mgrid[0:shape[0], 0:shape[1]]
    cy, cx = center
    if angle != 0.0:
        theta = np.deg2rad(angle)
        dx = xx - cx
        dy = yy - cy
        xr = dx * np.cos(theta) + dy * np.sin(theta)
        yr = -dx * np.sin(theta) + dy * np.cos(theta)
    else:
        xr = xx - cx
        yr = yy - cy
    g = np.exp(-0.5 * ((xr / sigma[1]) ** 2 + (yr / sigma[0]) ** 2))
    return amplitude * g


def _slick_mask(shape, center, rng) -> np.ndarray:
    """A realistic, slightly wrinkled oil slick shape (0..1 intensity mask)."""
    h, w = shape
    cy, cx = center
    yy, xx = np.mgrid[0:h, 0:w]
    scol = np.exp(-0.5 * (((xx - cx) / 55.0) ** 2 + ((yy - cy) / 22.0) ** 2))
    # add a few lobes/wrinkles
    for _ in range(5):
        ax, ay = rng.uniform(-60, 60, 2)
        s = np.exp(-0.5 * (((xx - (cx + ax)) / 30.0) ** 2 + ((yy - (cy + ay * 0.5)) / 12.0) ** 2))
        scol = np.maximum(scol, s * 0.9)
    # thin sheen tail
    for i in range(6):
        px = cx + 60 + i * 22
        py = cy + i * 4
        s = np.exp(-0.5 * (((xx - px) / 25.0) ** 2 + ((yy - py) / 6.0) ** 2))
        scol = np.maximum(scol, s * 0.7)
    scol = np.clip(scol, 0, 1)
    thr = 0.35
    mask = (scol > thr).astype(np.float32)
    mask = np.clip(mask + (scol - thr) * 1.5, 0, 1)
    return mask


@dataclass
class SyntheticScene:
    """A rendered SAR scene with ground-truth labels."""
    vv: np.ndarray
    vh: Optional[np.ndarray]
    oil_mask: np.ndarray            # 1 where oil
    land_mask: Optional[np.ndarray]
    ship_positions: List[Tuple[int, int]]
    lookalike_positions: List[Tuple[int, int]]
    meta: dict = field(default_factory=dict)

    def channels(self) -> List[np.ndarray]:
        if self.vh is None:
            return [self.vv]
        return [self.vv, self.vh]

    def label_rgb(self) -> np.ndarray:
        """Multi-class label for training: 0 sea,1 oil,2 lookalike,3 ship,4 land."""
        h, w = self.vv.shape
        lab = np.zeros((h, w), dtype=np.uint8)
        if self.land_mask is not None:
            lab[self.land_mask] = 4
        for ly, lx in self.lookalike_positions:
            lab[ly, lx] = 2
        lab[self.oil_mask > 0.5] = 1
        for ly, lx in self.ship_positions:
            lab[ly, lx] = 3
        return lab


def _place_lookalike(im, center, rng):
    """Random dark patch (natural look-alike)."""
    h, w = im.shape
    cy, cx = center
    r0 = rng.uniform(5, 12)
    r1 = rng.uniform(8, 18)
    g = _gaussian_blob((h, w), (cy, cx), (r0, r1), rng.uniform(0.5, 0.85))
    return g


def render_synthetic_scene(
    size: int = 512,
    wind_speed: float = 6.0,
    seed: int = 0,
    with_oil: bool = True,
    oil_center: Optional[Tuple[int, int]] = None,
) -> SyntheticScene:
    """Render one synthetic Sentinel-1-like scene."""
    rng = np.random.default_rng(seed)

    base_level = 0.42 + 0.02 * wind_speed
    speck = _speckle((size, size), rng=rng)
    vv = base_level * speck

    # optional low-wind dark lanes (wind shadow -> look-alike potential)
    lane = _gaussian_blob((size, size), (size * 0.25, size * 0.5), (size * 0.08, size * 0.35),
                          -0.18, angle=25.0)
    vv = vv + lane

    # ship point targets
    ships = []
    for s in range(4):
        sy, sx = rng.integers(30, size - 30, 2)
        ships.append((int(sy), int(sx)))
        vv[sy - 1:sy + 2, sx - 1:sx + 2] = 0.95
        vv[sy, sx] = 1.0

    # look-alikes
    lookalikes = []
    for a in range(3):
        cy, cx = rng.integers(40, size - 40, 2)
        lookalikes.append((int(cy), int(cx)))
        vv = vv + _place_lookalike(vv, (cy, cx), rng)

    oil_mask = np.zeros((size, size), dtype=np.float32)
    if with_oil:
        cy, cx = oil_center or (int(size * 0.55), int(size * 0.5))
        oil_mask = _slick_mask((size, size), (cy, cx), rng)
        # oil suppresses radar backscatter strongly
        vv = vv * (1.0 - 0.85 * oil_mask)

    vh = vv * 0.35  # VH much weaker

    # land mask (left part)
    land = np.zeros((size, size), dtype=bool)
    land[:, : int(size * 0.08)] = True

    vv = np.clip(vv, 0, 1)
    vh = np.clip(vh, 0, 1)

    return SyntheticScene(
        vv=vv, vh=vh, oil_mask=oil_mask, land_mask=land,
        ship_positions=ships, lookalike_positions=lookalikes,
        meta={"wind_speed": wind_speed, "with_oil": with_oil, "seed": seed},
    )
