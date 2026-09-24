import { useEffect, useRef, useState } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import type { DetectionResult } from "../../types";

const SATELLITE_TILES =
  "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}";
const AE = "#06b6d4";

interface Props {
  result: DetectionResult | null;
  imageUrl?: string | null;
}

type Overlay = "sar" | "thermal" | "wind";

/** Build a georeferenced overlay raster (SAR-style or thermal colormap) as a data URL. */
function makeOverlayRaster(kind: "sar" | "thermal", w = 256, h = 256): string {
  const c = document.createElement("canvas");
  c.width = w;
  c.height = h;
  const ctx = c.getContext("2d")!;
  if (kind === "sar") {
    ctx.fillStyle = "#05070d";
    ctx.fillRect(0, 0, w, h);
    for (let i = 0; i < 4200; i++) {
      const g = 40 + Math.random() * 60;
      ctx.fillStyle = `rgba(${g},${g},${g + 18},0.5)`;
      ctx.fillRect(Math.random() * w, Math.random() * h, 1.4, 1.4);
    }
    ctx.fillStyle = "rgba(255,255,255,0.08)";
    for (let i = 0; i <= 8; i++) {
      ctx.beginPath();
      ctx.moveTo((i * w) / 8, 0);
      ctx.lineTo((i * w) / 8 + 26, h);
      ctx.stroke();
    }
    ctx.fillStyle = "rgba(210,235,255,0.55)";
    ctx.strokeStyle = "rgba(220,240,255,0.9)";
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.ellipse(w / 2, h / 2, w * 0.22, h * 0.14, -0.2, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
  } else {
    ctx.fillStyle = "#02040a";
    ctx.fillRect(0, 0, w, h);
    const grad = ctx.createRadialGradient(w * 0.5, h * 0.5, 6, w * 0.5, h * 0.5, w * 0.45);
    grad.addColorStop(0, "rgba(255,220,90,0.95)");
    grad.addColorStop(0.4, "rgba(255,120,40,0.8)");
    grad.addColorStop(0.7, "rgba(200,40,80,0.6)");
    grad.addColorStop(1, "rgba(0,80,160,0.15)");
    ctx.fillStyle = grad;
    ctx.beginPath();
    ctx.ellipse(w / 2, h / 2, w * 0.3, h * 0.2, 0.3, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = "rgba(255,255,255,0.05)";
    for (let i = 1; i < 8; i++) {
      ctx.fillRect(0, (h * i) / 8, w, 1);
      ctx.fillRect((w * i) / 8, 0, 1, h);
    }
  }
  return c.toDataURL("image/png");
}

function emptyFC() {
  return { type: "FeatureCollection" as const, features: [] };
}

function windArrows(
  res: DetectionResult,
  rows: number,
  cols: number,
): Array<{
  type: "Feature";
  properties: Record<string, never>;
  geometry: { type: "LineString"; coordinates: number[][] };
}> {
  const bbox = res.bounds.bbox;
  const [minLon, minLat, maxLon, maxLat] = bbox;
  const theta = (res.drift.bearing_deg * Math.PI) / 180;
  const dir = { x: Math.sin(theta), y: Math.cos(theta) };
  const cells: Array<{
    type: "Feature";
    properties: Record<string, never>;
    geometry: { type: "LineString"; coordinates: number[][] };
  }> = [];
  for (let i = 0; i < cols; i++) {
    for (let j = 0; j < rows; j++) {
      const lon0 = minLon + ((i + 0.5) / cols) * (maxLon - minLon);
      const lat0 = minLat + ((j + 0.5) / rows) * (maxLat - minLat);
      const frac = 0.6 / Math.max(cols, rows);
      const len = 0.45 + Math.random() * 0.5;
      cells.push({
        type: "Feature",
        properties: {},
        geometry: {
          type: "LineString",
          coordinates: [
            [lon0, lat0],
            [lon0 + dir.x * (maxLon - minLon) * frac * len, lat0 + dir.y * (maxLat - minLat) * frac * len],
          ],
        },
      });
    }
  }
  return cells;
}

export function MapView({ result, imageUrl }: Props) {
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const resultRef = useRef<DetectionResult | null>(result);
  const overlaysRef = useRef<Set<Overlay>>(new Set());
  const fittedRef = useRef<string | null>(null);
  const [mapError, setMapError] = useState(false);
  const [overlays, setOverlays] = useState<Set<Overlay>>(new Set());
  const [ready, setReady] = useState(false);

  resultRef.current = result;

  const applyOverlays = (map: maplibregl.Map | null, set: Set<Overlay>) => {
    if (!map) return;
    for (const id of ["sar-overlay", "thermal-overlay", "wind-line"]) {
      const l = map.getLayer(id);
      if (l) l.visibility = set.has(id as Overlay) ? "visible" : "none";
    }
  };

  useEffect(() => {
    applyOverlays(mapRef.current, overlays);
  }, [overlays]);

  const renderAll = (map: maplibregl.Map) => {
    const res = resultRef.current;
    const fcs = map.getSource("spill");
    if (!res) return;

    const ring: number[][] = res.polygon.geometry.coordinates[0];
    const traj: Array<[number, number]> = res.drift.trajectory.map((p) => [p.lon, p.lat]);
    const vector = [
      [res.centroid.lon, res.centroid.lat],
      traj.length ? traj[traj.length - 1] : traj[0],
    ];

    if (fcs) {
      (fcs as maplibregl.GeoJSONSource).setData({
        type: "FeatureCollection",
        features: [
          { type: "Feature", properties: {}, geometry: { type: "Polygon", coordinates: [ring] } },
          { type: "Feature", properties: {}, geometry: { type: "LineString", coordinates: vector } },
          ...windArrows(res, 5, 5),
        ],
      });
    }

    // Geographic overlays for SAR / Thermal rasters.
    const bbox = res.bounds.bbox;
    const coords: [[number, number], [number, number], [number, number], [number, number]] = [
      [bbox[0], bbox[1]],
      [bbox[2], bbox[1]],
      [bbox[2], bbox[3]],
      [bbox[0], bbox[3]],
    ];
    for (const [id, kind] of [
      ["sar-overlay", "sar"],
      ["thermal-overlay", "thermal"],
    ] as const) {
      if (!map.getSource(id)) {
        map.addSource(id, { type: "image", url: makeOverlayRaster(kind), coordinates: coords });
        map.addLayer({
          id,
          type: "raster",
          source: id,
          paint: { "raster-opacity": kind === "sar" ? 0.4 : 0.5 },
        });
      }
    }
    const wl = map.getLayer("wind-line");
    if (wl) wl.visibility = overlaysRef.current.has("wind") ? "visible" : "none";

    // Pulse marker at the centroid.
    const el = document.createElement("div");
    el.className = "radar-pulse";
    el.style.cssText =
      "width:18px;height:18px;border-radius:50%;background:rgba(6,182,212,.9);border:3px solid #fff;";
    new maplibregl.Marker({ element: el })
      .setLngLat([res.centroid.lon, res.centroid.lat])
      .addTo(map);

    // Drift-direction arrowhead marker.
    const ah = document.createElement("div");
    ah.style.cssText = `color:#f59e0b;font-size:18px;text-shadow:0 0 6px rgba(0,0,0,.8);transform:rotate(${res.drift.bearing_deg}deg);`;
    ah.textContent = "➤";
    if (traj.length) {
      new maplibregl.Marker({ element: ah }).setLngLat(traj[traj.length - 1]).addTo(map);
    }

    // Fit once per event.
    const key = res.event_id;
    if (fittedRef.current !== key) {
      fittedRef.current = key;
      try {
        map.fitBounds(
          [
            [bbox[0], bbox[1]],
            [bbox[2], bbox[3]],
          ],
          { padding: 70, duration: 900 },
        );
      } catch (e) {
        console.warn("fitBounds failed", e);
      }
    }
  };

  // Init the map once; render behind the 'load' event.
  useEffect(() => {
    if (!container.current) return;
    const map = new maplibregl.Map({
      container: container.current,
      style: {
        version: 8,
        sources: {
          sat: {
            type: "raster",
            tiles: [SATELLITE_TILES],
            tileSize: 256,
            attribution: "Esri World Imagery",
          },
        },
        layers: [{ id: "sat-bg", type: "raster", source: "sat", paint: { "raster-opacity": 1 } }],
      },
      center: [72.7, 18.9],
      zoom: 5,
      attributionControl: { compact: true },
    });
    mapRef.current = map;
    const resizeObs = new ResizeObserver(() => {
      if (mapRef.current) mapRef.current.resize();
    });
    if (container.current) resizeObs.observe(container.current);
    map.on("error", (e) => {
      if (e.error?.message?.includes("style")) console.warn("map style:", e.error.message);
    });

    map.once("load", () => {
      try {
        map.addSource("spill", { type: "geojson", data: emptyFC() });
        map.addLayer({
          id: "spill-fill",
          type: "fill",
          source: "spill",
          paint: { "fill-color": "#10b981", "fill-opacity": 0.22 },
        });
        map.addLayer({
          id: "spill-line",
          type: "line",
          source: "spill",
          paint: { "line-color": AE, "line-width": 2, "line-opacity": 0.95 },
        });
        map.addLayer({
          id: "drift-line",
          type: "line",
          source: "spill",
          paint: { "line-color": "#f59e0b", "line-width": 2, "line-dasharray": [1, 1.5] },
        });
        map.addLayer({
          id: "wind-line",
          type: "line",
          source: "spill",
          paint: { "line-color": "#67e8f9", "line-width": 1, "line-opacity": 0.7 },
        });
        setReady(true);
        map.resize();
        renderAll(map);
      } catch (e) {
        console.error("map init failed", e);
        setMapError(true);
      }
    });

    return () => {
      resizeObs?.disconnect();
      map.remove();
      mapRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (map && ready && result) {
      requestAnimationFrame(() => map.resize());
      requestAnimationFrame(() => renderAll(map));
      requestAnimationFrame(() => map.resize());
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [result, ready]);

  const toggleOverlay = (o: Overlay) => {
    setOverlays((prev) => {
      const next = new Set(prev);
      if (next.has(o)) next.delete(o);
      else next.add(o);
      overlaysRef.current = next;
      return next;
    });
  };

  if (mapError) {
    return (
      <div className="flex h-full w-full flex-col items-center justify-center gap-3 bg-[#0b0f19] p-6 text-center text-[#8496ab]">
        <div className="text-sm font-semibold text-red-300">Map failed to initialise (WebGL).</div>
        <button
          onClick={() => location.reload()}
          className="rounded-lg bg-[#06b6d4] px-4 py-1.5 text-xs font-bold text-[#062032]"
        >
          Reload
        </button>
      </div>
    );
  }

  return (
    <div className="relative h-full w-full overflow-hidden rounded-2xl border border-[#1e293b]">
      <div
        ref={container}
        className="maplibregl-map"
        style={{ position: "absolute", top: 0, bottom: 0, left: 0, right: 0 }}
      />

      {/* Layer toggle control */}
      <div className="absolute left-3 top-3 z-10 flex flex-wrap items-center gap-1.5 rounded-xl border border-[#1e293b] bg-[#0b0f19]/85 p-1.5 backdrop-blur">
        <span className="flex items-center gap-1.5 px-2 text-[10px] font-bold text-[#67e8f9]">
          <span className="h-2 w-2 rounded-full bg-[#06b6d4]" /> RGB Satellite
        </span>
        {(
          [
            ["sar", "SAR Mask"],
            ["thermal", "Thermal / IR"],
            ["wind", "Weather"],
          ] as [Overlay, string][]
        ).map(([key, label]) => {
          const on = overlays.has(key);
          return (
            <button
              key={key}
              onClick={() => toggleOverlay(key)}
              className={`rounded-lg border px-2.5 py-1 text-[10px] font-bold transition ${
                on
                  ? "border-[#06b6d4] bg-[#06b6d4]/20 text-white"
                  : "border-[#1e293b] bg-transparent text-[#8496ab] hover:border-[#06b6d4]/50"
              }`}
            >
              {label}
            </button>
          );
        })}
      </div>

      {/* Image preview chip */}
      {imageUrl && (
        <div className="absolute bottom-2 left-2 z-10 flex items-center gap-2 rounded-xl border border-[#1e293b] bg-[#0b0f19]/85 p-1.5 backdrop-blur">
          <img src={imageUrl} alt="" className="h-9 w-9 rounded-lg object-cover" />
          <div className="pr-1">
            <div className="text-[9px] font-bold uppercase tracking-widest text-[#8496ab]">
              Input scene
            </div>
            <div className="max-w-[140px] truncate text-[10px] text-[#e6f1f8]">{result?.source}</div>
          </div>
        </div>
      )}
    </div>
  );
}