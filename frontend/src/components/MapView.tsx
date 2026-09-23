import { useEffect, useRef, useState } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import type { AnalysisBundle, Point } from "../types";
import { toLonLat } from "../api";

interface Props {
  bundle: AnalysisBundle;
  selectedMmsi: string | null;
  onSelectVessel: (mmsi: string | null) => void;
  showBackward: boolean;
  showForward: boolean;
  showOrigin: boolean;
  showSlick: boolean;
}

interface LayerVis {
  showBackward: boolean;
  showForward: boolean;
  showOrigin: boolean;
  showSlick: boolean;
}

const SLICK_COLOR = "#f97316";
const BACK_COLOR = "#22d3ee";
const FWD_COLOR = "#a3e635";
const REGION_FILL = "rgba(250, 204, 21, 0.18)";

export function MapView({
  bundle,
  selectedMmsi,
  onSelectVessel,
  showBackward,
  showForward,
  showOrigin,
  showSlick,
}: Props) {
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const [mapError, setMapError] = useState(false);

  // Always hold the latest values so the style "load" handler can populate
  // sources even if state updates raced ahead of map initialisation.
  const bundleRef = useRef(bundle);
  const selectedRef = useRef<string | null>(selectedMmsi);
  const layerRef = useRef<LayerVis>({ showBackward, showForward, showOrigin, showSlick });

  // init map once; register everything behind the style 'load' event so
  // addSource/addLayer never run before the style is ready
  useEffect(() => {
    let map: maplibregl.Map;
    try {
      map = new maplibregl.Map({
        container: container.current!,
        style: {
          version: 8,
          sources: {
            osm: {
              type: "raster",
              tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
              tileSize: 256,
              attribution: "© OpenStreetMap contributors",
            },
            satellite: {
              type: "raster",
              tiles: [
                "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
              ],
              tileSize: 256,
              attribution: "Tiles © Esri — World Imagery",
              maxzoom: 19,
            },
          },
          layers: [
            {
              id: "bg",
              type: "background",
              paint: { "background-color": "#0d2137" },
            },
            { id: "osm-fallback", type: "raster", source: "osm" },
            { id: "satellite", type: "raster", source: "satellite" },
          ],
        },
        center: [60.0, 20.1],
        zoom: 8,
      });
    } catch (e) {
      console.error("Map init failed", e);
      setMapError(true);
      return;
    }
    mapRef.current = map;

    const core = () => {
      try {
        setupSourcesAndLayers(map);
        attachPickers(map, onSelectVessel);
        applyData(map, bundleRef.current, selectedRef.current);
        applyVisibility(map, layerRef.current);
        fitScene(map, bundleRef.current);
      } catch (e) {
        console.error("Map layer setup failed", e);
        setMapError(true);
      }
    };

    if (map.isStyleLoaded()) {
      core();
    } else {
      map.once("load", core);
    }

    return () => {
      map.remove();
      mapRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // keep refs fresh + re-apply data whenever the bundle or selection changes
  useEffect(() => {
    bundleRef.current = bundle;
    selectedRef.current = selectedMmsi;
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded()) return;
    try {
      applyData(map, bundle, selectedMmsi);
    } catch (e) {
      console.error("Map data update failed", e);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bundle, selectedMmsi]);

  // layer visibility toggles
  useEffect(() => {
    layerRef.current = { showBackward, showForward, showOrigin, showSlick };
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded()) return;
    applyVisibility(map, layerRef.current);
  }, [showBackward, showForward, showOrigin, showSlick]);

  if (mapError) {
    return (
      <div className="flex h-full w-full flex-col items-center justify-center gap-3 bg-gray-950 p-6 text-center text-gray-300">
        <div className="text-sm font-semibold text-red-300">
          Map failed to initialise (WebGL or tile loading error).
        </div>
        <div className="text-xs text-gray-400">
          Panels and vessel ranking still work below. Reload to retry.
        </div>
        <button
          onClick={() => location.reload()}
          className="rounded bg-cyan-600 px-4 py-1.5 text-xs font-semibold text-white"
        >
          Reload
        </button>
      </div>
    );
  }

  return (
    <div
      ref={container}
      className="absolute inset-0"
      style={{ width: "100%", height: "100%" }}
    />
  );
}

function setupSourcesAndLayers(map: maplibregl.Map) {
  const sources: Array<[string, maplibregl.GeoJSONSourceSpecification]> = [
    ["lick", { type: "geojson", data: emptyFC() }],
    ["drift-back", { type: "geojson", data: emptyFC() }],
    ["drift-fwd", { type: "geojson", data: emptyFC() }],
    ["origin-region", { type: "geojson", data: emptyFC() }],
    ["origin-cands", { type: "geojson", data: emptyFC() }],
    ["vessel-tracks", { type: "geojson", data: emptyFC() }],
  ];
  for (const [id, spec] of sources) {
    if (!map.getSource(id)) map.addSource(id, spec);
  }
  if (!map.getLayer("slick-line"))
    map.addLayer({
      id: "slick-line", type: "line", source: "lick",
      paint: { "line-color": SLICK_COLOR, "line-width": 2.5, "line-opacity": 0.9 },
      layout: { "line-cap": "round" },
    });
  if (!map.getLayer("slick-fill"))
    map.addLayer({
      id: "slick-fill", type: "fill", source: "lick",
      paint: { "fill-color": SLICK_COLOR, "fill-opacity": 0.12 },
    });
  if (!map.getLayer("back-line"))
    map.addLayer({
      id: "back-line", type: "line", source: "drift-back",
      paint: { "line-color": BACK_COLOR, "line-width": 2, "line-dasharray": [1, 1.5] },
    });
  if (!map.getLayer("fwd-line"))
    map.addLayer({
      id: "fwd-line", type: "line", source: "drift-fwd",
      paint: { "line-color": FWD_COLOR, "line-width": 2, "line-dasharray": [1, 1.5] },
    });
  if (!map.getLayer("region-fill"))
    map.addLayer({
      id: "region-fill", type: "fill", source: "origin-region",
      paint: {
        "fill-color": "#facc15", "fill-opacity": 0.18,
        "fill-outline-color": "#ca8a04",
      },
    });
  if (!map.getLayer("origin-cand"))
    map.addLayer({
      id: "origin-cand", type: "circle", source: "origin-cands",
      paint: {
        "circle-radius": ["interpolate", ["linear"], ["get", "prob"], 0.1, 5, 0.35, 14],
        "circle-color": "#f59e0b",
        "circle-stroke-width": 1.5,
        "circle-stroke-color": "#fff7ed",
      },
    });
  if (!map.getLayer("vessel-tracks"))
    map.addLayer({
      id: "vessel-tracks", type: "line", source: "vessel-tracks",
      paint: {
        "line-color": ["case", ["get", "selected"], "#ef4444", "#3b82f6"],
        "line-width": ["case", ["get", "selected"], 3.5, 2],
        "line-opacity": ["case", ["get", "selected"], 1, 0.7],
      },
    });
  if (!map.getLayer("vessel-pts"))
    map.addLayer({
      id: "vessel-pts", type: "circle", source: "vessel-tracks",
      paint: {
        "circle-radius": ["case", ["get", "selected"], 6, 4],
        "circle-color": ["case", ["get", "selected"], "#ef4444", "#2563eb"],
        "circle-stroke-width": 1.5,
        "circle-stroke-color": "#ffffff",
      },
    });
}

function attachPickers(map: maplibregl.Map, onSelectVessel: (mmsi: string | null) => void) {
  map.on("click", "vessel-pts", (e) => {
    const mmsi = (e.features?.[0]?.properties?.mmsi as string) ?? null;
    onSelectVessel(mmsi);
  });
  map.on("mouseenter", "vessel-pts", () => (map.getCanvas().style.cursor = "pointer"));
  map.on("mouseleave", "vessel-pts", () => (map.getCanvas().style.cursor = ""));
}

function applyData(map: maplibregl.Map, bundle: AnalysisBundle, selectedMmsi: string | null) {
  const det = bundle.detection;
  const origin = bundle.origin;
  try {
    if (map.getSource("lick"))
      setSource(map, "lick", {
        type: "Feature",
        properties: {},
        geometry: { type: "Polygon", coordinates: [toLonLat(det.polygons)] },
      });
  } catch (e) {
    console.warn("slick data ignored", e);
  }
  for (const [id, src] of [
    ["drift-back", "driftBackward"],
    ["drift-fwd", "driftForward"],
  ] as const) {
    try {
      if (map.getSource(id))
        setSource(map, id, lineFC(bundle[src].mean_trajectory));
    } catch (e) {
      console.warn(`${id} data ignored`, e);
    }
  }
  try {
    if (map.getSource("origin-region"))
      setSource(map, "origin-region", {
        type: "Feature",
        properties: {},
        geometry: {
          type: "Polygon",
          coordinates: origin.region_polygon.length
            ? [toLonLat(origin.region_polygon)]
            : [[toLonLat(origin.candidates.map((c) => ({ lat: c.lat, lon: c.lon })))]],
        },
      });
  } catch (e) {
    console.warn("origin-region data ignored", e);
  }
  try {
    if (map.getSource("origin-cands"))
      setSource(map, "origin-cands", {
        type: "FeatureCollection",
        features: origin.candidates.map((c) => ({
          type: "Feature",
          properties: { prob: c.probability, id: c.candidate_id },
          geometry: { type: "Point", coordinates: [c.lon, c.lat] },
        })),
      });
  } catch (e) {
    console.warn("origin-cands data ignored", e);
  }
  try {
    if (map.getSource("vessel-tracks")) {
      const features = Object.values(bundle.tracks)
        .filter((t) => t.lat.length > 1 && t.lon.length > 1)
        .map((t) => ({
          type: "Feature" as const,
          properties: { mmsi: t.mmsi, selected: t.mmsi === selectedMmsi },
          geometry: {
            type: "LineString" as const,
            coordinates: t.lon.map((lo, i) => [lo, t.lat[i]]),
          },
        }));
      setSource(map, "vessel-tracks", {
        type: "FeatureCollection",
        features: features as never,
      });
    }
  } catch (e) {
    console.warn("vessel-tracks data ignored", e);
  }
}

function fitScene(map: maplibregl.Map, bundle: AnalysisBundle) {
  try {
    const pts: Point[] = [
      ...(bundle.detection?.polygons ?? []),
      ...(bundle.origin?.candidates ?? []).map((c) => ({ lat: c.lat, lon: c.lon })),
    ].filter((p) => Number.isFinite(p.lat) && Number.isFinite(p.lon));
    if (pts.length === 0) return;
    const lats = pts.map((p) => p.lat);
    const lons = pts.map((p) => p.lon);
    let minLat = Math.min(...lats);
    let maxLat = Math.max(...lats);
    let minLon = Math.min(...lons);
    let maxLon = Math.max(...lons);
    if (minLat === maxLat) { minLat -= 0.05; maxLat += 0.05; }
    if (minLon === maxLon) { minLon -= 0.05; maxLon += 0.05; }
    map.fitBounds(
      [
        [minLon - 0.1, minLat - 0.1],
        [maxLon + 0.1, maxLat + 0.1],
      ],
      { padding: 40, duration: 500 },
    );
  } catch (e) {
    console.warn("fitBounds skipped", e);
  }
}

function applyVisibility(map: maplibregl.Map, vis: LayerVis) {
  setVis(map, "back-line", vis.showBackward);
  setVis(map, "fwd-line", vis.showForward);
  setVis(map, "region-fill", vis.showOrigin);
  setVis(map, "origin-cand", vis.showOrigin);
  setVis(map, "slick-line", vis.showSlick);
  setVis(map, "slick-fill", vis.showSlick);
}

function emptyFC(): maplibregl.GeoJSONSourceSpecification["data"] {
  return {
    type: "FeatureCollection",
    features: [],
  } as unknown as maplibregl.GeoJSONSourceSpecification["data"];
}
function lineFC(pts: Point[]) {
  return {
    type: "Feature",
    properties: {},
    geometry: { type: "LineString", coordinates: toLonLat(pts) },
  };
}
function setSource(map: maplibregl.Map, id: string, data: unknown) {
  const src = map.getSource(id) as maplibregl.GeoJSONSource | undefined;
  if (src) src.setData(data as never);
}
function setVis(map: maplibregl.Map, id: string, show: boolean) {
  if (map.getLayer(id)) map.setLayoutProperty(id, "visibility", show ? "visible" : "none");
}