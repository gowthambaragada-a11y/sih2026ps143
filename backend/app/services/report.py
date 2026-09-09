"""OILTRACE-AI analysis report generator.

Produces a structured, timestamped investigation report from an
AnalysisResult.  The report is deliberately non-accusatory: it lists
evidence + uncertainties and ranks vessels probabilistically.  It is written
both as JSON (machine-readable) and Markdown (human-readable).
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional

from ..core.config import REPORTS_DIR
from ..core.logger import get_logger

logger = get_logger(__name__)


def report_to_dict(res) -> dict:
    """Flatten an AnalysisResult into an ordered, serializable report."""
    det = res.detection
    origin = res.origin
    attr = res.attribution

    report = {
        "report_id": f"{res.event_id}-{int(time.time())}",
        "event_id": res.event_id,
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "model_versions": dict(res.model_versions),
        "summary": {
            "detection_status": det.status.value if hasattr(det.status, "value") else str(det.status),
            "detection_confidence": det.confidence,
            "area_km2": det.area_km2,
            "centroid": {"lat": det.centroid.lat, "lon": det.centroid.lon},
            "origin_region_confidence": origin.confidence,
            "origin_uncertainty_km": origin.uncertainty_km,
            "n_origin_candidates": len(origin.candidates),
            "n_candidate_vessels": len(attr.ranked_vessels),
            "top_vessel": {
                "mmsi": attr.ranked_vessels[0].mmsi,
                "name": attr.ranked_vessels[0].name,
                "score": attr.ranked_vessels[0].scores.overall,
            } if attr.ranked_vessels else None,
        },
        "detection": {
            "status": det.status.value if hasattr(det.status, "value") else str(det.status),
            "area_km2": det.area_km2,
            "confidence": det.confidence,
            "centroid": {"lat": det.centroid.lat, "lon": det.centroid.lon},
            "metadata": det.metadata,
        },
        "drift": {
            "backward": {
                "uncertainty_km": res.drift_backward.uncertainty_km,
                "n_trajectories": len(res.drift_backward.trajectories),
                "mean_trajectory": [{"lat": p.lat, "lon": p.lon}
                                    for p in res.drift_backward.mean_trajectory],
            },
            "forward": {
                "uncertainty_km": res.forward_tracks.uncertainty_km,
                "n_trajectories": len(res.forward_tracks.trajectories),
            },
        },
        "origin": {
            "region_polygon": [{"lat": p.lat, "lon": p.lon} for p in origin.region_polygon],
            "candidates": [
                {"candidate_id": c.candidate_id, "lat": c.lat, "lon": c.lon,
                 "release_time": c.release_time, "probability": c.probability,
                 "distance_km": c.distance_km, "drift_duration_h": c.drift_duration_h}
                for c in origin.candidates
            ],
            "uncertainty_km": origin.uncertainty_km,
            "confidence": origin.confidence,
        },
        "vessel_ranking": [
            {
                "rank": i + 1,
                "mmsi": v.mmsi, "name": v.name, "type": v.type,
                "scores": {
                    "overall": v.scores.overall, "spatial": v.scores.spatial,
                    "temporal": v.scores.temporal, "trajectory": v.scores.trajectory,
                    "vessel_suitability": v.scores.vessel_suitability,
                    "behaviour": v.scores.behaviour, "ais_evidence": v.scores.ais_evidence,
                },
                "anomaly_score": v.anomaly_score,
                "evidence": [{"label": e.label, "flag": e.flag, "detail": e.detail}
                             for e in v.evidence],
            }
            for i, v in enumerate(attr.ranked_vessels)
        ],
        "uncertainty": attr.uncertainty,
        "warnings": res.warnings,
        "disclaimer": (
            "This analysis is evidence-based and probabilistic.  A high ranking is "
            "not a determination of responsibility; it identifies the vessel most "
            "consistent with the observed slick subject to drift and AIS uncertainty. "
            "Ground truth linking requires supplementary investigation."
        ),
    }
    return report


def render_markdown(report: dict) -> str:
    """Human-readable Markdown rendition of the report dict."""
    s = report["summary"]
    lines = [
        f"# OILTRACE-AI Analysis Report",
        "",
        f"- **Event**: {report['event_id']}",
        f"- **Generated (UTC)**: {report['generated_utc']}",
        f"- **Models**: {json.dumps(report['model_versions'])}",
        "",
        "## 1. Detection",
        f"- Status: **{report['detection']['status']}**  (confidence {report['detection']['confidence']:.2f})",
        f"- Area: **{report['detection']['area_km2']} km²**  at "
        f"({report['detection']['centroid']['lat']:.3f}, {report['detection']['centroid']['lon']:.3f})",
        "",
        "## 2. Drift Reconstruction",
        f"- Backward uncertainty: **{report['drift']['backward']['uncertainty_km']} km** "
        f"({report['drift']['backward']['n_trajectories']} member trajectories)",
        f"- Forward forecast uncertainty: **{report['drift']['forward']['uncertainty_km']} km**",
        "",
        "## 3. Origin Estimation",
        f"- Region confidence: **{report['origin']['confidence']:.2f}**, "
        f"uncertainty **{report['origin']['uncertainty_km']} km**",
        "",
        "| Candidate | Lat | Lon | Release (h) | Duration (h) | Prob |",
        "|---|---|---|---|---|---|",
    ]
    for c in report["origin"]["candidates"][:8]:
        from datetime import datetime, timezone
        rt = datetime.fromtimestamp(c["release_time"], tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
        lines.append(f"| {c['candidate_id']} | {c['lat']:.3f} | {c['lon']:.3f} | {rt} | "
                     f"{c['drift_duration_h']:.0f} | {c['probability']:.3f} |")

    lines += ["", "## 4. Candidate Vessel Ranking", "",
              "| Rank | Vessel | Type | Overall | Spatial | Temporal | Trajectory | Suitability |",
              "|---|---|---|---|---|---|---|---|"]
    for v in report["vessel_ranking"]:
        s4 = v["scores"]
        lines.append(f"| {v['rank']} | {v['name'] or v['mmsi']} | {v['type'] or '-'} | "
                     f"{s4['overall']:.1f} | {s4['spatial']:.1f} | {s4['temporal']:.1f} | "
                     f"{s4['trajectory']:.1f} | {s4['vessel_suitability']:.1f} |")

    lines += ["", "### Evidence detail", ""]
    for v in report["vessel_ranking"][:5]:
        lines.append(f"**{v['rank']}. {v['name'] or v['mmsi']}** (score {v['scores']['overall']:.1f})")
        for e in v["evidence"]:
            lines.append(f"- `{e['flag']}` {e['label']}"
                         + (f" — {e['detail']}" if e["detail"] else ""))
        if v["anomaly_score"] > 0.7:
            lines.append("- Unusual behavioural pattern detected (requires verification)")
        lines.append("")

    lines += ["## 5. Uncertainties & Warnings", ""]
    for w in report["warnings"]:
        lines.append(f"- {w}")
    lines += ["", "> " + report["disclaimer"]]
    return "\n".join(lines)


def save_report(res, out_dir: Optional[Path] = None) -> Path:
    """Persist JSON + Markdown copies, persist to the store, and return the dir."""
    out_dir = out_dir or (REPORTS_DIR / res.event_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = report_to_dict(res)
    report_json = json.dumps(report, indent=2)
    report_md = render_markdown(report)
    (out_dir / "report.json").write_text(report_json, encoding="utf-8")
    (out_dir / "report.md").write_text(report_md, encoding="utf-8")
    logger.info("Report saved to %s", out_dir)
    try:
        from . import store
        store.persist_analysis(res)
        store.persist_report(res, report_json, report_md,
                             report_id=report["report_id"])
    except Exception:  # noqa: BLE001
        logger.warning("report files written; store persist skipped", exc_info=True)
    return out_dir