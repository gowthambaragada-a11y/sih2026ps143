"""Pydantic schemas defining every API request/response contract.

These are the source of truth for the React front-end types as well.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class DetectionStatus(str, Enum):
    detected = "detected"
    not_detected = "not_detected"
    degraded = "degraded"
    no_image = "no_image"


class Point(BaseModel):
    lat: float
    lon: float


class SpillInfo(BaseModel):
    spill_id: str
    detection_time: Optional[str] = None
    centroid: Point
    area_km2: float
    confidence: float = Field(ge=0, le=1)
    status: DetectionStatus = DetectionStatus.detected
    notes: List[str] = Field(default_factory=list)


class DetectionResponse(BaseModel):
    spill_id: str
    status: DetectionStatus
    polygons: List[Point]
    centroid: Point
    area_km2: float
    confidence: float
    metadata: Dict[str, Any] = Field(default_factory=dict)
    warnings: List[str] = Field(default_factory=list)


class DriftRequest(BaseModel):
    spill_id: str
    lat: float
    lon: float
    start_time: str
    direction: str  # "forward" | "backward"
    duration_hours: float = 72.0
    ensemble_size: int = 20
    engine: Optional[str] = None


class DriftResult(BaseModel):
    spill_id: str
    direction: str
    trajectories: List[List[Point]]
    mean_trajectory: List[Point]
    uncertainty_km: float
    warnings: List[str] = Field(default_factory=list)


class OriginCandidate(BaseModel):
    candidate_id: str
    lat: float
    lon: float
    release_time: float
    probability: float
    distance_km: float
    drift_duration_h: float


class OriginResponse(BaseModel):
    spill_id: str
    region_polygon: List[Point]
    candidates: List[OriginCandidate]
    uncertainty_km: float
    confidence: float
    warnings: List[str] = Field(default_factory=list)


class VesselBrief(BaseModel):
    mmsi: str
    imo: Optional[str] = None
    name: Optional[str] = None
    type: Optional[str] = None
    cargo: Optional[str] = None


class CandidateVessel(BaseModel):
    mmsi: str
    name: Optional[str] = None
    score: float
    distance_to_origin_km: float
    time_difference_hours: float
    evidence_flags: List[str] = Field(default_factory=list)


class AttributionEvidence(BaseModel):
    label: str
    flag: str  # "positive" | "warning" | "negative"
    detail: str


class AttributionScores(BaseModel):
    overall: float
    spatial: float
    temporal: float
    trajectory: float
    vessel_suitability: float
    behaviour: float
    ais_evidence: float


class VesselAttribution(BaseModel):
    mmsi: str
    name: Optional[str] = None
    imo: Optional[str] = None
    type: Optional[str] = None
    scores: AttributionScores
    evidence: List[AttributionEvidence]
    anomaly_score: float


class AttributionResponse(BaseModel):
    spill_id: str
    ranked_vessels: List[VesselAttribution]
    model_version: str
    uncertainty: str
    warnings: List[str] = Field(default_factory=list)
