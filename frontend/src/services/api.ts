import type { DetectionResult } from "../types";
import { demoDetect } from "./demoDetect";

// Live backend base URL. Set VITE_API_BASE_URL to the deployed API (e.g.
// https://oiltrace-api.onrender.com) when building for a cloud deployment.
// Falls back to the local FastAPI dev server. Trailing slashes are trimmed.
const BASE = (
  import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000"
).replace(/\/+$/, "");

export const API_BASE = BASE;

const TIMEOUT_MS = {
  health: 6_000,
  request: 30_000,
  detect: 120_000,
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
    console.warn("Health probe failed -> mock simulation mode.", e);
    return { status: "unreachable", service: "oiltrace-api", reachable: false };
  }
}

/**
 * Run Stage-3 detection. Prefers the live backend; on any failure falls back
 * to a client-side synthetic result (offline:true). Never throws.
 */
export async function detectImage(
  input: { imageUrl?: string; fileName?: string } | { file: File; fileName: string },
): Promise<DetectionResult> {
  const seedFor = (s: string) =>
    s.replace(/[^a-z0-9]/gi, "").slice(0, 40) || String(Date.now());

  try {
    if ("file" in input && input.file) {
      const body = new FormData();
      body.append("file", input.file, input.fileName);
      const r = await fetchWithTimeout(
        `${BASE}/api/v1/detect/file`,
        { method: "POST", body },
        TIMEOUT_MS.detect,
      );
      if (!r.ok) throw new Error(`detect/file: ${r.status}`);
      return (await r.json()) as DetectionResult;
    }

    const imageUrl = ("imageUrl" in input ? input.imageUrl : undefined) ?? "";
    const r = await fetchWithTimeout(
      `${BASE}/api/v1/detect`,
      {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ image_url: imageUrl, event_id: seedFor(input.fileName ?? imageUrl) }),
      },
      TIMEOUT_MS.detect,
    );
    if (!r.ok) throw new Error(`detect: ${r.status}`);
    return (await r.json()) as DetectionResult;
  } catch (e) {
    console.warn("Detection backend unreachable -> client-side mock result.", e);
    return demoDetect(seedFor(input.fileName ?? ("imageUrl" in input ? input.imageUrl : "") ?? "sample"));
  }
}