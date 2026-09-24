/**
 * Demo-mode detector + pre-loaded sample dataset.
 *
 * Used only when the FastAPI backend is unreachable (Mock Simulation Mode).
 * Produces the same response contract as POST /api/v1/detect, seeded
 * deterministically from the image identity so results are reproducible.
 */
import type { DetectionResult, StoredImage } from "../types";

/** Deterministic PRNG from a string seed. */
function rng(seed: string) {
  let h = 2166136261;
  for (let i = 0; i < seed.length; i++) {
    h ^= seed.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  let s = h >>> 0;
  return () => {
    s = (Math.imul(s, 1664525) + 1013904223) >>> 0;
    return s / 4294967296;
  };
}

/** Synthesize a DetectionResult for a given image identity. */
export function demoDetect(seed: string): DetectionResult {
  const r = rng(seed);
  const lat = 18.8 + r() * 0.9;
  const lon = 72.6 + r() * 0.9;

  const n = 16;
  const rLat = 0.045 + r() * 0.075;
  const rLon = 0.05 + r() * 0.1;
  const ring: Array<{ lat: number; lon: number }> = [];
  for (let i = 0; i < n; i++) {
    const a = (2 * Math.PI * i) / n;
    const jitter = 0.72 + r() * 0.56;
    ring.push({
      lat: lat + Math.sin(a) * rLat * jitter,
      lon: lon + Math.cos(a) * rLon * jitter,
    });
  }

  const ringLL = ring.map((p) => [p.lon, p.lat] as [number, number]);
  ringLL.push([ringLL[0][0], ringLL[0][1]]);

  // Approximate area via shoelace (local km scale).
  const kmLat = 111.32;
  const kmLon = 111.32 * Math.cos((lat * Math.PI) / 180);
  const pts = ring.map((p) => [p.lon * kmLon, p.lat * kmLat]);
  let area = 0;
  for (let i = 0; i < n; i++) {
    const [x1, y1] = pts[i];
    const [x2, y2] = pts[(i + 1) % n];
    area += x1 * y2 - x2 * y1;
  }
  area = Math.abs(area) / 2;

  let perim = 0;
  for (let i = 0; i < n; i++) {
    const a = ring[i];
    const b = ring[(i + 1) % n];
    perim += haversine(a, b);
  }

  const confidence = 0.74 + r() * 0.2;
  const severity = area > 25 || confidence > 0.9 ? "high" : area > 12 ? "medium" : "low";

  const bearing = r() * 359.9;
  const speed = 0.15 + r() * 1.25;
  const dirs = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"];
  const direction = dirs[Math.floor((bearing + 22.5) / 45) % 8];

  const trajectory: Array<{ lat: number; lon: number }> = [];
  for (let step = 1; step <= 12; step++) {
    const dKm = step * speed * 0.5;
    trajectory.push({
      lat: lat + (dKm * Math.cos((bearing * Math.PI) / 180)) / 111.32,
      lon:
        lon +
        (dKm * Math.sin((bearing * Math.PI) / 180)) /
          (111.32 * Math.cos((lat * Math.PI) / 180)),
    });
  }

  const lons = ring.map((p) => p.lon);
  const lats = ring.map((p) => p.lat);
  const minLon = Math.min(...lons);
  const maxLon = Math.max(...lons);
  const minLat = Math.min(...lats);
  const maxLat = Math.max(...lats);

  return {
    event_id: seed,
    status: "detected",
    model: "unet-v1-mock (client synth)",
    source: seed,
    image_size: null,
    bounds: {
      type: "Feature",
      bbox: [minLon, minLat, maxLon, maxLat],
      geometry: {
        type: "Polygon",
        coordinates: [
          [
            [minLon, minLat],
            [maxLon, minLat],
            [maxLon, maxLat],
            [minLon, maxLat],
            [minLon, minLat],
          ],
        ],
      },
    },
    polygon: {
      type: "Feature",
      properties: {
        confidence,
        severity,
        area_km2: Math.round(area * 1000) / 1000,
        perimeter_km: Math.round(perim * 1000) / 1000,
        confidence_pct: Math.round(confidence * 1000) / 10,
      },
      geometry: { type: "Polygon", coordinates: [ringLL] },
    },
    masks: {
      type: "FeatureCollection",
      features: [
        {
          type: "Feature",
          properties: { class: "oil", prob: confidence },
          geometry: { type: "Polygon", coordinates: [ringLL] },
        },
      ],
    },
    centroid: { lat, lon },
    confidence,
    confidence_pct: Math.round(confidence * 1000) / 10,
    severity,
    area_km2: Math.round(area * 1000) / 1000,
    perimeter_km: Math.round(perim * 1000) / 1000,
    drift: { bearing_deg: bearing, speed_kmh: speed, direction_label: direction, trajectory },
    warnings: [
      "Client-side synthetic reconstruction for demonstration — no live backend detected.",
      "Verify against the original scene before operational use.",
    ],
    offline: true,
    latency_ms: 340,
  };
}

function haversine(a: { lat: number; lon: number }, b: { lat: number; lon: number }): number {
  const R = 6371;
  const p1 = (a.lat * Math.PI) / 180;
  const p2 = (b.lat * Math.PI) / 180;
  const dp = p2 - p1;
  const dl = ((b.lon - a.lon) * Math.PI) / 180;
  const x = Math.sin(dp / 2) ** 2 + Math.cos(p1) * Math.cos(p2) * Math.sin(dl / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(x));
}

/* ---------------- Pre-loaded sample dataset ---------------- */

function makeScene(name: string, hue1: string, hue2: string, label: string): string {
  const svg = `<svg xmlns='http://www.w3.org/2000/svg' width='640' height='480' viewBox='0 0 640 480'>
<defs><radialGradient id='g' cx='50%' cy='50%' r='70%'>
<stop offset='0%' stop-color='${hue1}'/><stop offset='60%' stop-color='${hue2}'/><stop offset='100%' stop-color='#0a0e18'/>
</radialGradient></defs>
<rect width='640' height='480' fill="url(#g)"/>
<g fill-opacity='0.12'>
<rect x='40' y='60' width='180' height='30' fill='#fff'/><rect x='120' y='140' width='260' height='22' fill='#fff'/>
<rect x='220' y='200' width='160' height='26' fill='#fff'/><rect x='60' y='300' width='220' height='20' fill='#fff'/>
<rect x='340' y='330' width='180' height='24' fill='#fff'/>
</g>
<ellipse cx='330' cy='210' rx='150' ry='90' fill='#ffedb3' fill-opacity='0.32' stroke='#ffe27a' stroke-width='2'/>
<ellipse cx='330' cy='210' rx='90' ry='52' fill='#ffe27a' fill-opacity='0.35'/>
<g stroke='#7be8ff' stroke-opacity='0.55' stroke-width='2' fill='none'>
<path d='M300 460 C 320 380 330 320 335 260'/><path d='M340 460 C 355 380 362 320 342 258'/>
</g>
<g stroke-width='3' stroke='#7be8ff' fill='none' opacity='0.8'>
<path d='M40 440 L600 440 M40 20 L600 20' stroke-dasharray='4 8'/>
</g>
<text x='16' y='38' font-family='monospace' font-size='14' fill='${hue1}'>${label} · SENTINEL-1A · IW GRD</text>
</svg>`;
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
}

const SAMPLE_DEFS: Array<{ name: string; type: string; width: number; height: number }> = [
  { name: "S1A-IW_SAR_GRDH_2026-02-14", type: "image/svg+xml", width: 640, height: 480 },
  { name: "S1A-IW_SAR_GRDH_2026-02-21", type: "image/svg+xml", width: 640, height: 480 },
  { name: "GOSAT_IR_THERMAL_2026-02-28", type: "image/svg+xml", width: 640, height: 480 },
  { name: "L8_OLI_RGB_MULTI_2026-03-02", type: "image/svg+xml", width: 640, height: 480 },
];

const SCENES: Array<[string, string, string]> = [
  ["#0f766e", "#042f2e", "SAR C-BAND"],
  ["#155e75", "#083344", "SAR C-BAND"],
  ["#b45309", "#2a1a05", "THERMAL IR"],
  ["#1d4ed8", "#0c1433", "RGB MULTISPECTRAL"],
];

function makeSampleImage(): StoredImage[] {
  return SAMPLE_DEFS.map((d, i) => {
    const [a, b, label] = SCENES[i % SCENES.length];
    return {
      id: `sample-${i}${Date.now().toString(36)}`,
      name: d.name,
      size: Math.round(1400 + Math.random() * 2200) * 1024,
      type: d.type,
      url: makeScene(d.name, a, b, label),
      storagePath: `demo:sample/${d.name}`,
      uploadedAt: Date.now(),
      progress: 100,
      width: d.width,
      height: d.height,
    };
  });
}

/** "Load Pre-loaded Sample Dataset" action. */
export function loadSampleDataset(): StoredImage[] {
  return makeSampleImage();
}