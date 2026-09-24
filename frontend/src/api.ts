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

// Live backend base URL. Set VITE_API_BASE_URL to the deployed API (e.g.
// https://oiltrace-api.onrender.com) when building for a cloud deployment.
// Falls back to the local FastAPI dev server. Trailing slashes are trimmed.
const BASE = (
  import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000"
).replace(/\/+$/, "");

export const API_BASE = BASE;

const DEMO_OFFLINE_MESSAGE =
  "Live backend API is unreachable or timed out on this host — showing the embedded " +
  "synthetic reference scenario (SIH-2026-SPILL-001). Point VITE_API_BASE_URL at the " +
  "deployed backend and rebuild to go live.";

const TIMEOUT_MS = {
  health: 6_000,
  request: 30_000,
  analyze: 120_000,
};

async function fetchWithTimeout(
  url: string,
  init: RequestInit,
  ms: number,
): Promise<Response> {
  const ctrl = new AbortController();
  const id = setTimeout(() => ctrl.abort(), ms);
  try {
    return await fetch(url, { ...init, signal: ctrl.signal });
  } finally {
    clearTimeout(id);
  }
}

async function get<T>(path: string, ms = TIMEOUT_MS.request): Promise<T> {
  try {
    const r = await fetchWithTimeout(`${BASE}/api/v1${path}`, {}, ms);
    if (!r.ok) throw new Error(`${path}: ${r.status} ${await r.text()}`);
    return (await r.json()) as T;
  } catch (e) {
    if (e instanceof Error) throw e;
    throw new Error(`${path}: failed to fetch`);
  }
}

async function post<T>(path: string, ms = TIMEOUT_MS.analyze): Promise<T> {
  try {
    const r = await fetchWithTimeout(`${BASE}/api/v1${path}`, { method: "POST" }, ms);
    if (!r.ok) throw new Error(`${path}: ${r.status} ${await r.text()}`);
    return (await r.json()) as T;
  } catch (e) {
    if (e instanceof Error) throw e;
    throw new Error(`${path}: failed to fetch`);
  }
}

export interface HealthInfo {
  status: string;
  service: string;
  version?: string;
  reachable: boolean;
}

/**
 * Lightweight liveness probe. Never throws — returns reachable:false on any
 * network error, timeout, redirect, or non-2xx response.
 */
export async function probeHealth(): Promise<HealthInfo> {
  try {
    const r = await fetchWithTimeout(
      `${BASE}/api/v1/health`,
      { method: "GET", cache: "no-store" },
      TIMEOUT_MS.health,
    );
    if (!r.ok) throw new Error(`health: ${r.status}`);
    const j = (await r.json()) as { status: string; service: string; version?: string };
    return { status: j.status, service: j.service, version: j.version, reachable: true };
  } catch (e) {
    console.warn("Health probe failed -> synthetic offline mode.", e);
    return { status: "unreachable", service: "live-pipeline", reachable: false };
  }
}

/**
 * Run the full analysis for an event. If the live API is unreachable, times
 * out, or returns an error at any stage, the embedded synthetic scenario is
 * returned (offline: true) instead of throwing.
 */
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