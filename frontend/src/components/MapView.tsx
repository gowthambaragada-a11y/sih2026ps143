import { useEffect, useRef } from "react";
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

  // init map once
  useEffect(() => {
    const map = new maplibregl.Map({
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
    mapRef.current = map;
    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, []);

  // add data sources / layers once
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
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
        paint: { "fill-color": "#facc15", "fill-opacity": 0.18,
                 "fill-outline-color": "#ca8a04" },
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
    map.on("click", "vessel-pts", (e) => {
      const mmsi = (e.features?.[0]?.properties?.mmsi as string) ?? null;
      onSelectVessel(mmsi);
    });
    map.on("mouseenter", "vessel-pts", () => map.getCanvas().style.cursor = "pointer");
    map.on("mouseleave", "vessel-pts", () => map.getCanvas().style.cursor = "");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // update data sources
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const det = bundle.detection;
    if (map.getSource("lick"))
      setSource(map, "lick", {
        type: "Feature",
        properties: {},
        geometry: {
          type: "Polygon",
          coordinates: [toLonLat(det.polygons)],
        },
      });
    if (map.getSource("drift-back"))
      setSource(map, "drift-back", lineFC(bundle.driftBackward.mean_trajectory));
    if (map.getSource("drift-fwd"))
      setSource(map, "drift-fwd", lineFC(bundle.driftForward.mean_trajectory));
    if (map.getSource("origin-region"))
      setSource(map, "origin-region", {
        type: "Feature",
        properties: {},
        geometry: {
          type: "Polygon",
          coordinates: bundle.origin.region_polygon.length
            ? [toLonLat(bundle.origin.region_polygon)]
            : [[toLonLat(bundle.origin.candidates.map((c) => ({ lat: c.lat, lon: c.lon })))]],
        },
      });
    if (map.getSource("origin-cands"))
      setSource(map, "origin-cands", {
        type: "FeatureCollection",
        features: bundle.origin.candidates.map((c) => ({
          type: "Feature",
          properties: { prob: c.probability, id: c.candidate_id },
          geometry: { type: "Point", coordinates: [c.lon, c.lat] },
        })),
      });
    if (map.getSource("vessel-tracks")) {
      const features = Object.values(bundle.tracks)
        .filter((t) => t.lat.length > 1)
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
    // fit bounds around scene
    const pts: Point[] = [
      ...det.polygons,
      ...bundle.origin.candidates.map((c) => ({ lat: c.lat, lon: c.lon })),
    ];
    if (pts.length) {
      const lats = pts.map((p) => p.lat);
      const lons = pts.map((p) => p.lon);
      map.fitBounds(
        [
          [Math.min(...lons) - 0.1, Math.min(...lats) - 0.1],
          [Math.max(...lons) + 0.1, Math.max(...lats) + 0.1],
        ],
        { padding: 40, duration: 500 },
      );
    }
  }, [bundle, selectedMmsi]);

  // layer visibility
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    setVis(map, "back-line", showBackward);
    setVis(map, "fwd-line", showForward);
    setVis(map, "region-fill", showOrigin);
    setVis(map, "origin-cand", showOrigin);
    setVis(map, "slick-line", showSlick);
    setVis(map, "slick-fill", showSlick);
  }, [showBackward, showForward, showOrigin, showSlick]);

  return (
    <div
      ref={container}
      className="absolute inset-0"
      style={{ width: "100%", height: "100%" }}
    />
  );
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
function setSource(
  map: maplibregl.Map,
  id: string,
  data: unknown,
) {
  const src = map.getSource(id) as maplibregl.GeoJSONSource | undefined;
  if (src) src.setData(data as never);
}
function setVis(map: maplibregl.Map, id: string, show: boolean) {
  if (map.getLayer(id)) map.setLayoutProperty(id, "visibility", show ? "visible" : "none");
}