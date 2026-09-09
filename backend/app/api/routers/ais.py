"""AIS endpoints: candidate vessel list + trajectory polylines."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ...models.schemas import CandidateVessel
from ..state import get_analysis

router = APIRouter(tags=["ais"])


@router.get("/events/{event_id}/ais/vessels",
            response_model=list[CandidateVessel])
def ais_vessels(event_id: str) -> list:
    """Short list of vessels that passed the candidate filter (top-K fams)."""
    res = get_analysis(event_id)
    if res.candidates_ais is None or len(res.candidates_ais) == 0:
        return []
    candidates = res.candidates_ais
    fams = candidates[["mmsi"]].drop_duplicates("mmsi")
    attr = {v.mmsi: v for v in res.attribution.ranked_vessels}
    out = []
    for _, row in fams.iterrows():
        mmsi = str(row["mmsi"])
        va = attr.get(mmsi)
        out.append(CandidateVessel(
            mmsi=mmsi,
            name=va.name if va else None,
            score=round(va.scores.overall, 1) if va else 0.0,
            distance_to_origin_km=0.0,
            time_difference_hours=0.0,
            evidence_flags=[e.label for e in va.evidence] if va else [],
        ))
    out.sort(key=lambda v: -v.score)
    return out


@router.get("/events/{event_id}/ais/vessels/{mmsi}/track")
def ais_track(event_id: str, mmsi: str) -> dict:
    """Full track for one candidate vessel (lat/lon/timestamp)."""
    res = get_analysis(event_id)
    if res.candidates_ais is None or len(res.candidates_ais) == 0:
        raise HTTPException(status_code=404, detail="No AIS data")
    grp = res.candidates_ais[res.candidates_ais.mmsi == mmsi]
    if len(grp) == 0:
        raise HTTPException(status_code=404, detail=f"Vessel {mmsi} not in candidates")
    grp = grp.sort_values("timestamp")
    return {
        "mmsi": mmsi,
        "lat": [float(x) for x in grp["latitude"]],
        "lon": [float(x) for x in grp["longitude"]],
        "t": [float(x) for x in grp["timestamp"]],
        "sog": [float(x) for x in grp["sog"]],
    }
