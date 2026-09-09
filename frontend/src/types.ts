export interface Point {
  lat: number;
  lon: number;
}

export interface DetectionResponse {
  spill_id: string;
  status: string;
  polygons: Point[];
  centroid: Point;
  area_km2: number;
  confidence: number;
  metadata: Record<string, unknown>;
  warnings: string[];
}

export interface DriftResult {
  spill_id: string;
  direction: string;
  trajectories: Point[][];
  mean_trajectory: Point[];
  uncertainty_km: number;
  warnings: string[];
}

export interface OriginCandidate {
  candidate_id: string;
  lat: number;
  lon: number;
  release_time: number;
  probability: number;
  distance_km: number;
  drift_duration_h: number;
}

export interface OriginResponse {
  spill_id: string;
  region_polygon: Point[];
  candidates: OriginCandidate[];
  uncertainty_km: number;
  confidence: number;
  warnings: string[];
}

export interface AttributionEvidence {
  label: string;
  flag: string;
  detail: string;
}

export interface AttributionScores {
  overall: number;
  spatial: number;
  temporal: number;
  trajectory: number;
  vessel_suitability: number;
  behaviour: number;
  ais_evidence: number;
}

export interface VesselAttribution {
  mmsi: string;
  name: string | null;
  imo: string | null;
  type: string | null;
  scores: AttributionScores;
  evidence: AttributionEvidence[];
  anomaly_score: number;
}

export interface AttributionResponse {
  spill_id: string;
  ranked_vessels: VesselAttribution[];
  model_version: string;
  uncertainty: string;
  warnings: string[];
}

export interface CandidateVessel {
  mmsi: string;
  name: string | null;
  score: number;
  distance_to_origin_km: number;
  time_difference_hours: number;
  evidence_flags: string[];
}

export interface VesselTrack {
  mmsi: string;
  lat: number[];
  lon: number[];
  t: number[];
  sog: number[];
}

export interface OriginMap {
  prob: number[];
  n_lat: number;
  n_lon: number;
  lat_min: number;
  lat_max: number;
  lon_min: number;
  lon_max: number;
}

export interface AnalyzeResponse {
  event_id: string;
  status: string;
  model_versions: Record<string, string>;
  warnings: string[];
}

export interface AnalysisBundle {
  event_id: string;
  detection: DetectionResponse;
  driftBackward: DriftResult;
  driftForward: DriftResult;
  origin: OriginResponse;
  attribution: AttributionResponse;
  vessels: CandidateVessel[];
  tracks: Record<string, VesselTrack>;
  originMap: OriginMap | null;
  modelVersions: Record<string, string>;
  warnings: string[];
}