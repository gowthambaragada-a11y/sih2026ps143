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
import demoData from "./demo.data.json";

// Composes with the Vite base path (/sih2026ps143/) so API calls stay on the
// same origin on GitHub Pages; resolves to "/api/v1" in local dev.
const BASE = `${import.meta.env.BASE_URL}api/v1`;

const DEMO_OFFLINE_MESSAGE =
  "Backend API unreachable on this host — showing the embedded synthetic reference " +
  "scenario (SIH-2026-SPILL-001). Run the FastAPI stack locally for live analysis.";

async function get<T>(path: string): Promise<T> {
  try {
    const r = await fetch(`${BASE}${path}`);
    if (!r.ok) throw new Error(`${path}: ${r.status} ${await r.text()}`);
    return (await r.json()) as T;
  } catch (e) {
    if (e instanceof Error) throw e;
    throw new Error(`${path}: failed to fetch`);
  }
}

async function post<T>(path: string): Promise<T> {
  try {
    const r = await fetch(`${BASE}${path}`, { method: "POST" });
    if (!r.ok) throw new Error(`${path}: ${r.status} ${await r.text()}`);
    return (await r.json()) as T;
  } catch (e) {
    if (e instanceof Error) throw e;
    throw new Error(`${path}: failed to fetch`);
  }
}

export async function runAnalysis(
  eventId: string,
): Promise<AnalysisBundle> {
  function demoBundle(): AnalysisBundle {
    const bundle = JSON.parse(JSON.stringify(demoData)) as AnalysisBundle;
    bundle.offline = true;
    const warns = Array.isArray(bundle.warnings) ? bundle.warnings : [];
    bundle.warnings = Array.from(new Set([...warns, DEMO_OFFLINE_MESSAGE]));
    return bundle;
  }

  try {
    let meta: AnalyzeResponse;
    try {
      meta = await post<AnalyzeResponse>(
        `/events/${encodeURIComponent(eventId)}/analyze`,
      );
    } catch (e) {
      console.warn("Backend unreachable, showing embedded demo scenario.", e);
      return demoBundle();
    }

    try {
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
      } catch (e) {
        console.warn("origins/map unavailable, continuing.", e);
        originMap = null;
      }

      const tracks: Record<string, VesselTrack> = {};
      for (const v of vessels) {
        try {
          tracks[v.mmsi] = await get<VesselTrack>(
            `/events/${encodeURIComponent(eventId)}/ais/vessels/${v.mmsi}/track`,
          );
        } catch (e) {
          console.warn(`track for ${v.mmsi} unavailable, skipping.`, e);
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
    } catch (e) {
      console.warn("Analysis partially failed, falling back to demo scenario.", e);
      return demoBundle();
    }
  } catch (e) {
    console.error("runAnalysis failed entirely, falling back to demo scenario.", e);
    return demoBundle();
  }
}

/** Convert a list of {lat, lon} into a GeoJSON LineString/coordinate array. */
export function toLonLat(pts: { lat: number; lon: number }[]): number[][] {
  return pts.map((p) => [p.lon, p.lat]);
}