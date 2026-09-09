import type {
  AnalyzeResponse,
  AnalysisBundle,
  AttributionResponse,
  CandidateVessel,
  DetectionResponse,
  DriftResult,
  OriginMap,
  OriginResponse,
  VesselTrack,
} from "./types";

const BASE = "/api/v1";

async function get<T>(path: string): Promise<T> {
  const r = await fetch(`${BASE}${path}`);
  if (!r.ok) throw new Error(`${path}: ${r.status} ${await r.text()}`);
  return r.json() as Promise<T>;
}

async function post<T>(path: string): Promise<T> {
  const r = await fetch(`${BASE}${path}`, { method: "POST" });
  if (!r.ok) throw new Error(`${path}: ${r.status} ${await r.text()}`);
  return r.json() as Promise<T>;
}

export async function runAnalysis(
  eventId: string,
): Promise<AnalysisBundle> {
  const meta = await post<AnalyzeResponse>(
    `/events/${encodeURIComponent(eventId)}/analyze`,
  );
  const detection = await get<DetectionResponse>(
    `/events/${encodeURIComponent(eventId)}/detection`,
  );
  const driftBackward = await get<DriftResult>(
    `/events/${encodeURIComponent(eventId)}/drift/backward`,
  );
  const driftForward = await get<DriftResult>(
    `/events/${encodeURIComponent(eventId)}/drift/forward`,
  );
  const origin = await get<OriginResponse>(
    `/events/${encodeURIComponent(eventId)}/origins`,
  );
  const attribution = await get<AttributionResponse>(
    `/events/${encodeURIComponent(eventId)}/attribution`,
  );
  const vessels = await get<CandidateVessel[]>(
    `/events/${encodeURIComponent(eventId)}/ais/vessels`,
  );

  let originMap: OriginMap | null = null;
  try {
    originMap = await get<OriginMap>(
      `/events/${encodeURIComponent(eventId)}/origins/map`,
    );
  } catch {
    originMap = null;
  }

  const tracks: Record<string, VesselTrack> = {};
  for (const v of vessels) {
    try {
      tracks[v.mmsi] = await get<VesselTrack>(
        `/events/${encodeURIComponent(eventId)}/ais/vessels/${v.mmsi}/track`,
      );
    } catch {
      /* ignore track failures */
    }
  }

  return {
    event_id: eventId,
    detection,
    driftBackward,
    driftForward,
    origin,
    attribution,
    vessels,
    tracks,
    originMap,
    modelVersions: meta.model_versions,
    warnings: meta.warnings,
  };
}

/** Convert a list of {lat, lon} into a GeoJSON LineString/coordinate array. */
export function toLonLat(pts: { lat: number; lon: number }[]): number[][] {
  return pts.map((p) => [p.lon, p.lat]);
}