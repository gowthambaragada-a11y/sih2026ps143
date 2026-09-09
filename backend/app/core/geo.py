"""Geodetic helpers built on pyproj/shapely with no network requirements.

Haversine and a simple equidistant azimuthal projection are used for local
distance computations on the order of 100s of km, which is sufficient for
oil-drift and vessel-attribution work.
"""
from __future__ import annotations

import math
from typing import Iterable, Sequence, Tuple

import numpy as np
from pyproj import Geod

_geod = Geod(ellps="WGS84")


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometres between two lat/lon points."""
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def haversine_km_vec(lat1, lon1, lat2, lon2) -> np.ndarray:
    """Vectorised great-circle distance (km) in NumPy, broadcasting-friendly.

    Each argument may be an array or scalar; broadcasting is applied.
    """
    r = 6371.0088
    lat1, lon1, lat2, lon2 = (np.asarray(v, dtype=float) for v in (lat1, lon1, lat2, lon2))
    p1 = np.radians(lat1)
    p2 = np.radians(lat2)
    dp = p2 - p1
    dl = np.radians(lon2 - lon1)
    a = np.sin(dp / 2.0) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2.0) ** 2
    return 2 * r * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))


def point_km_scale(lat: float) -> float:
    """Length of one degree of longitude in km at a given latitude."""
    return 111.32 * math.cos(math.radians(lat))


def distance_km_matrix(lats: np.ndarray, lons: np.ndarray) -> np.ndarray:
    """Pairwise distances (km) for arrays of points."""
    n = len(lats)
    out = np.zeros((n, n))
    for i in range(n):
        for j in range(i + 1, n):
            d = haversine_km(lats[i], lons[i], lats[j], lons[j])
            out[i, j] = out[j, i] = d
    return out


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Initial bearing from point1 to point2 in degrees [0,360)."""
    fwd, _, _ = _geod.inv(lon1, lat1, lon2, lat2)
    return fwd % 360.0


def dest_point(lat: float, lon: float, bearing_deg_: float, dist_km: float) -> Tuple[float, float]:
    """Destination lat/lon after travelling dist_km along a bearing."""
    lon2, lat2, _ = _geod.fwd(lon, lat, bearing_deg_, dist_km * 1000.0)
    return lat2, lon2


def angular_diff_deg(a: float, b: float) -> float:
    """Smallest absolute angular difference in degrees between two bearings."""
    d = (a - b) % 360.0
    if d > 180.0:
        d = 360.0 - d
    return d


def linspace_between(lat1: float, lon1: float, lat2: float, lon2: float, n: int) -> np.ndarray:
    """n intermediate points (inclusive of both ends) via geodesic interpolation."""
    g = Geod(ellps="WGS84")
    lonl, latl = g.npts(lon1, lat1, lon2, lat2, n - 2)
    lats = [lat1] + list(latl) + [lat2]
    lons = [lon1] + list(lonl) + [lon2]
    return np.vstack([np.asarray(lats), np.asarray(lons)])


def polygon_area_km2(lons: Sequence[float], lats: Sequence[float]) -> float:
    """Area (km^2) of a polygon using the geodesic method (shoelace on geodesic)."""
    area_m2, _ = _geod.polygon_area_perimeter(lons, lats)
    return abs(area_m2) / 1e6


def array_area_km2(lats: np.ndarray, lons: np.ndarray) -> float:
    return polygon_area_km2(list(lons), list(lats))


def path_length_km(lats: Iterable[float], lons: Iterable[float]) -> float:
    lats = list(lats)
    lons = list(lons)
    total = 0.0
    for i in range(len(lats) - 1):
        total += haversine_km(lats[i], lons[i], lats[i + 1], lons[i + 1])
    return total
