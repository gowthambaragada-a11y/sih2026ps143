"""Origin estimation endpoints."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ...models.schemas import OriginResponse
from ..state import get_analysis

router = APIRouter(tags=["origin"])


@router.get("/events/{event_id}/origins", response_model=OriginResponse)
def origins(event_id: str) -> OriginResponse:
    try:
        return get_analysis(event_id).origin
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/events/{event_id}/origins/map")
def origins_map(event_id: str) -> dict:
    res = get_analysis(event_id)
    if not res.origin_map:
        raise HTTPException(status_code=404, detail="No origin map available")
    om = res.origin_map
    return {
        "prob": [round(float(x), 6) for row in om["prob"] for x in row],
        "n_lat": om["n_lat"], "n_lon": om["n_lon"],
        "lat_min": om["lat_min"], "lat_max": om["lat_max"],
        "lon_min": om["lon_min"], "lon_max": om["lon_max"],
    }
