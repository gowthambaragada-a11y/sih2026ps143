"""Report generation endpoint."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from ...services.report import report_to_dict, render_markdown, save_report
from ..state import get_analysis

router = APIRouter(tags=["report"])


@router.get("/events/{event_id}/report")
def report(event_id: str, markdown: bool = False) -> JSONResponse:
    try:
        res = get_analysis(event_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    rep = report_to_dict(res)
    if markdown:
        return JSONResponse({"markdown": render_markdown(rep)},
                            media_type="application/json")
    return JSONResponse(rep)


@router.post("/events/{event_id}/report/persist")
def persist_report(event_id: str) -> dict:
    try:
        res = get_analysis(event_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    try:
        out = save_report(res)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    from ...services import store
    return {
        "report_dir": str(out),
        "events_in_store": store.get_event_count(),
        "audit": "analysis + report persisted with SHA-256 provenance hash",
    }
