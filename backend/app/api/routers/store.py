"""Store query endpoints (Persistence / provenance read-back)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ...services import store

router = APIRouter(tags=["store"])


@router.get("/store/events")
def list_events():
    return {"count": store.get_event_count(), "events": store.list_events()}


@router.get("/store/audit/{event_id}")
def audit_log(event_id: str):
    return store.get_audit(event_id)


@router.get("/store/events/{event_id}/attribution")
def stored_attribution(event_id: str):
    rows = store.get_attribution(event_id)
    if not rows:
        raise HTTPException(status_code=404, detail="no stored attribution for event")
    return rows