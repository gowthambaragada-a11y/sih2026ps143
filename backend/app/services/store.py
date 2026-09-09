"""Persistence layer for OILTRACE-AI (Windows-friendly, zero-dependency).

Uses SQLAlchemy 2.0 ORM with a SQLite file by default so the whole stack runs
offline.  The DDL in ``db/schema.sql`` mirrors these tables for the production
PostGIS target (lat/lon columns here mirror PostGIS geometry points; GeoJSON
columns here mirror PostGIS geometry polygons / trajectories).

Legal-provenance design (spec SS18):
  * every persisted object carries ``source`` and ``ingested_at``;
  * the audit log records every state-changing action with a SHA-256 payload
    hash so reports cannot be silently altered after the fact.
"""

from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Union

from sqlalchemy import Float, Integer, String, Text, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from ..core.logger import get_logger

logger = get_logger(__name__)

DB_PATH = Path(__file__).resolve().parents[2] / "data" / "oiltrace.db"

_engine = None
_SessionLocal = None


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# ORM models
# ---------------------------------------------------------------------------
class EventRecord(Base):
    __tablename__ = "spill_events"
    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    date: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    time: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    latitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    longitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    status: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    source: Mapped[str] = mapped_column(String(64))
    ingested_at: Mapped[str] = mapped_column(String(40))
    model_detection: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    model_origin: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    model_attribution: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    model_anomaly: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    model_drift: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)


class DetectionRecord(Base):
    __tablename__ = "detections"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    spill_id: Mapped[str] = mapped_column(String(64), index=True)
    area_km2: Mapped[float] = mapped_column(Float)
    confidence: Mapped[float] = mapped_column(Float)
    centroid_lat: Mapped[float] = mapped_column(Float)
    centroid_lon: Mapped[float] = mapped_column(Float)
    polygon_geojson: Mapped[str] = mapped_column(Text)
    metadata_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(String(40))


class DriftRecord(Base):
    __tablename__ = "drift_ensembles"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    spill_id: Mapped[str] = mapped_column(String(64), index=True)
    direction: Mapped[str] = mapped_column(String(16))
    n_members: Mapped[int] = mapped_column(Integer)
    uncertainty_km: Mapped[float] = mapped_column(Float)
    mean_trajectory_geojson: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String(40))


class OriginRecord(Base):
    __tablename__ = "origin_hypotheses"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    spill_id: Mapped[str] = mapped_column(String(64), index=True)
    candidate_id: Mapped[str] = mapped_column(String(16))
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    release_time: Mapped[float] = mapped_column(Float)
    probability: Mapped[float] = mapped_column(Float)
    distance_km: Mapped[float] = mapped_column(Float)
    drift_duration_h: Mapped[float] = mapped_column(Float)
    created_at: Mapped[str] = mapped_column(String(40))


class VesselRecord(Base):
    __tablename__ = "vessels"
    mmsi: Mapped[str] = mapped_column(String(16), primary_key=True)
    imo: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    length: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    width: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    draft: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    cargo: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    source: Mapped[str] = mapped_column(String(64))


class AisFixRecord(Base):
    __tablename__ = "ais_fixes"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    mmsi: Mapped[str] = mapped_column(String(16), index=True)
    timestamp: Mapped[float] = mapped_column(Float)
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    sog: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    cog: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    heading: Mapped[Optional[float]] = mapped_column(Float, nullable=True)


class AttributionRecord(Base):
    __tablename__ = "attributions"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    spill_id: Mapped[str] = mapped_column(String(64), index=True)
    mmsi: Mapped[str] = mapped_column(String(16))
    rank: Mapped[int] = mapped_column(Integer)
    overall: Mapped[float] = mapped_column(Float)
    spatial: Mapped[float] = mapped_column(Float)
    temporal: Mapped[float] = mapped_column(Float)
    trajectory: Mapped[float] = mapped_column(Float)
    vessel_suitability: Mapped[float] = mapped_column(Float)
    behaviour: Mapped[float] = mapped_column(Float)
    ais_evidence: Mapped[float] = mapped_column(Float)
    anomaly_score: Mapped[float] = mapped_column(Float)
    created_at: Mapped[str] = mapped_column(String(40))


class EvidenceRecord(Base):
    __tablename__ = "attribution_evidence"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    spill_id: Mapped[str] = mapped_column(String(64), index=True)
    mmsi: Mapped[str] = mapped_column(String(16))
    label: Mapped[str] = mapped_column(String(128))
    flag: Mapped[str] = mapped_column(String(16))
    detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class ReportRecord(Base):
    __tablename__ = "reports"
    report_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    spill_id: Mapped[str] = mapped_column(String(64), index=True)
    generated_utc: Mapped[str] = mapped_column(String(40))
    sha256: Mapped[str] = mapped_column(String(64))
    report_json: Mapped[str] = mapped_column(Text)
    report_md: Mapped[str] = mapped_column(Text)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    spill_id: Mapped[str] = mapped_column(String(64), index=True)
    action: Mapped[str] = mapped_column(String(64))
    detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    payload_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[str] = mapped_column(String(40))


# ---------------------------------------------------------------------------
# Engine + session helpers
# ---------------------------------------------------------------------------
def get_engine(db_path: Optional[Path] = None):
    global _engine, _SessionLocal
    if _engine is None:
        path = db_path or DB_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        _engine = create_engine(f"sqlite:///{path}", pool_pre_ping=True)
        _SessionLocal = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False)
        Base.metadata.create_all(_engine)
        logger.info("persistence: initialised SQLite store at %s", path)
    return _engine


def get_session() -> Session:
    get_engine()
    return _SessionLocal()


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _point(p) -> Dict[str, float]:
    return {"lat": float(p.lat), "lon": float(p.lon)}


def _geojson_line(points) -> str:
    geo = {"type": "LineString", "coordinates": [[float(p.lon), float(p.lat)] for p in points]}
    return json.dumps(geo)


def _polygon_geojson(points) -> str:
    geo = {"type": "Polygon", "coordinates": [[[float(p.lon), float(p.lat)] for p in points]]}
    return json.dumps(geo)


# ---------------------------------------------------------------------------
# Persist operations
# ---------------------------------------------------------------------------
def persist_analysis(res) -> None:
    """Persist an AnalysisResult + candidate AIS fleet into the store.

    Uses insert-on-conflict semantics per table (SQLite dialect)."""
    get_engine()
    created = _now()
    with get_session() as s:
        _upsert_event(s, res, created)
        _upsert_detection(s, res, created)
        _upsert_drift(s, res, created)
        _upsert_origin(s, res, created)
        _upsert_vessels(s, res, created)
        _upsert_attribution(s, res, created)
        write_audit(res.event_id, "analysis_persisted",
                    "Detection, drift, origin, AIS and attribution rows stored.")
        s.commit()


def _upsert_event(s: Session, res, created: str) -> None:
    from . import demo as demo_mod
    try:
        demo_obj = demo_mod.build_demo_scenario(seed=res.meta.get("seed", 7), event_id=res.event_id)
        lat, lon = demo_obj.origin_geo
        data = demo_obj.events.iloc[0]
        dte, tm = str(data["date"]), str(data["time"])
    except Exception:  # noqa: BLE001
        lat = lon = dte = tm = None
    row = s.get(EventRecord, res.event_id)
    if row is None:
        s.add(EventRecord(
            event_id=res.event_id, date=dte, time=tm, latitude=lat, longitude=lon,
            status=res.detection.status.value if hasattr(res.detection.status, "value")
            else str(res.detection.status),
            source="synthetic-demo",
            ingested_at=created,
            model_detection=res.model_versions.get("detection"),
            model_origin=res.model_versions.get("origin"),
            model_attribution=res.model_versions.get("attribution"),
            model_anomaly=res.model_versions.get("anomaly"),
            model_drift=res.model_versions.get("drift_engine"),
        ))
    else:
        row.status = res.detection.status.value if hasattr(res.detection.status, "value") \
            else str(res.detection.status)
        row.ingested_at = created


def _upsert_detection(s: Session, res, created: str) -> None:
    det = res.detection
    s.add(DetectionRecord(
        spill_id=res.event_id, area_km2=det.area_km2, confidence=det.confidence,
        centroid_lat=det.centroid.lat, centroid_lon=det.centroid.lon,
        polygon_geojson=_polygon_geojson(det.polygons),
        metadata_json=json.dumps(det.metadata, default=str),
        created_at=created,
    ))


def _upsert_drift(s: Session, res, created: str) -> None:
    s.add_all([
        DriftRecord(
            spill_id=res.event_id, direction="backward",
            n_members=len(res.drift_backward.trajectories),
            uncertainty_km=res.drift_backward.uncertainty_km,
            mean_trajectory_geojson=_geojson_line(res.drift_backward.mean_trajectory),
            created_at=created,
        ),
        DriftRecord(
            spill_id=res.event_id, direction="forward",
            n_members=len(res.forward_tracks.trajectories) if res.forward_tracks else 0,
            uncertainty_km=res.forward_tracks.uncertainty_km if res.forward_tracks else 0.0,
            mean_trajectory_geojson=_geojson_line(
                res.forward_tracks.mean_trajectory) if res.forward_tracks else "{}",
            created_at=created,
        ),
    ])


def _upsert_origin(s: Session, res, created: str) -> None:
    s.add_all([
        OriginRecord(
            spill_id=res.event_id, candidate_id=c.candidate_id, lat=c.lat, lon=c.lon,
            release_time=c.release_time, probability=c.probability,
            distance_km=c.distance_km, drift_duration_h=c.drift_duration_h,
            created_at=created,
        )
        for c in res.origin.candidates
    ])


def _upsert_vessels(s: Session, res, created: str) -> None:
    ais = res.candidates_ais
    for mmsi in ais["mmsi"].unique():
        sub = ais[ais["mmsi"] == mmsi]
        cur = s.get(VesselRecord, str(mmsi))
        if cur is None:
            s.add(VesselRecord(
                mmsi=str(mmsi),
                type=str(sub["vessel_type"].iloc[0]) if "vessel_type" in sub.columns else None,
                cargo=str(sub["cargo"].iloc[0]) if "cargo" in sub.columns else None,
                source="synthetic-demo",
            ))
    fixes = ais.sort_values("timestamp").groupby("mmsi").apply(
        lambda g: g.iloc[:: max(1, len(g) // 80)]
    ).reset_index(drop=True)
    has_sog, has_cog, has_hdg = ("sog" in ais.columns, "cog" in ais.columns,
                                 "heading" in ais.columns)
    rows = [
        AisFixRecord(
            mmsi=str(r.mmsi),
            timestamp=float(r.timestamp),
            lat=float(r.latitude), lon=float(r.longitude),
            sog=float(r.sog) if has_sog and notna(r.sog) else None,
            cog=float(r.cog) if has_cog and notna(r.cog) else None,
            heading=float(r.heading) if has_hdg and notna(r.heading) else None,
        )
        for r in fixes.itertuples(index=False)
    ][:2000]
    s.add_all(rows)


def notna(v) -> bool:
    return v is not None and v == v  # NaN-aware


def _upsert_attribution(s: Session, res, created: str) -> None:
    for i, v in enumerate(res.attribution.ranked_vessels):
        sc = v.scores
        s.add(AttributionRecord(
            spill_id=res.event_id, mmsi=v.mmsi, rank=i + 1,
            overall=sc.overall, spatial=sc.spatial, temporal=sc.temporal,
            trajectory=sc.trajectory, vessel_suitability=sc.vessel_suitability,
            behaviour=sc.behaviour, ais_evidence=sc.ais_evidence,
            anomaly_score=v.anomaly_score, created_at=created,
        ))
        for e in v.evidence:
            s.add(EvidenceRecord(
                spill_id=res.event_id, mmsi=v.mmsi,
                label=e.label, flag=e.flag, detail=e.detail,
            ))


def persist_report(res, report_json: str, report_md: str, report_id: Optional[str] = None) -> str:
    """Store a report with a SHA-256 provenance hash; returns report_id."""
    get_engine()
    rid = report_id or res.event_id
    with get_session() as s:
        row = s.get(ReportRecord, rid)
        payload = report_json + report_md
        if row is None:
            s.add(ReportRecord(
                report_id=rid, spill_id=res.event_id,
                generated_utc=_now(), sha256=_sha256(payload),
                report_json=report_json, report_md=report_md,
            ))
        else:
            row.sha256 = _sha256(payload)
            row.report_json = report_json
            row.report_md = report_md
        write_audit(res.event_id, "report_persisted", f"report_id={rid}", _sha256(payload))
        s.commit()
    return rid


def write_audit(spill_id: str, action: str, detail: Optional[str] = None,
                payload_hash: Optional[str] = None) -> None:
    get_engine()
    with get_session() as s:
        s.add(AuditLog(spill_id=spill_id, action=action, detail=detail,
                       payload_hash=payload_hash, created_at=_now()))
        s.commit()


# ---------------------------------------------------------------------------
# Read queries
# ---------------------------------------------------------------------------
def list_events() -> List[dict]:
    get_engine()
    with get_session() as s:
        rows = s.execute(select(EventRecord).order_by(EventRecord.ingested_at)).scalars().all()
        return [
            {"event_id": r.event_id, "status": r.status, "lat": r.latitude, "lon": r.longitude,
             "ingested_at": r.ingested_at, "models": {
                 "detection": r.model_detection, "origin": r.model_origin,
                 "attribution": r.model_attribution, "anomaly": r.model_anomaly,
             }}
            for r in rows
        ]


def get_attribution(event_id: str) -> List[dict]:
    get_engine()
    with get_session() as s:
        rows = s.execute(
            select(AttributionRecord).where(AttributionRecord.spill_id == event_id)
            .order_by(AttributionRecord.rank)).scalars().all()
        return [
            {"rank": r.rank, "mmsi": r.mmsi, "overall": r.overall, "temporal": r.temporal,
             "spatial": r.spatial, "trajectory": r.trajectory,
             "vessel_suitability": r.vessel_suitability, "behaviour": r.behaviour,
             "ais_evidence": r.ais_evidence, "anomaly_score": r.anomaly_score}
            for r in rows
        ]


def get_event_count() -> int:
    get_engine()
    with get_session() as s:
        return len(s.execute(select(EventRecord)).scalars().all())


def get_audit(event_id: str) -> List[dict]:
    get_engine()
    with get_session() as s:
        rows = s.execute(
            select(AuditLog).where(AuditLog.spill_id == event_id)
            .order_by(AuditLog.id)).scalars().all()
        return [
            {"action": r.action, "detail": r.detail,
             "payload_hash": r.payload_hash, "created_at": r.created_at}
            for r in rows
        ]


def _fix_demo_reference(res) -> Dict:
    """(helper) expose lightweight facts about the synthetic reference, if any."""
    from . import demo as demo_mod
    try:
        d = demo_mod.build_demo_scenario(seed=int(res.meta.get("seed", 7)), event_id=res.event_id)
        return {
            "truth_mmsi": d.truth_mmsi,
            "origin_geo": list(d.origin_geo),
            "release_time_s": d.origin_release_time_s,
            "synthetic": True,
        }
    except Exception:  # noqa: BLE001
        return {"synthetic": False}