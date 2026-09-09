import { useCallback, useEffect, useState } from "react";
import type { AnalysisBundle } from "./types";
import { runAnalysis } from "./api";
import { MapView } from "./components/MapView";
import { VesselPanel } from "./components/VesselPanel";
import { OriginPanel } from "./components/OriginPanel";
import { SummaryPanel } from "./components/SummaryPanel";
import { LayerToggle } from "./components/LayerToggle";

const DEFAULT_EVENT = "SIH-2026-SPILL-001";

export default function App() {
  const [eventId, setEventId] = useState(DEFAULT_EVENT);
  const [bundle, setBundle] = useState<AnalysisBundle | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedMmsi, setSelectedMmsi] = useState<string | null>(null);
  const [showBackward, setShowBackward] = useState(true);
  const [showForward, setShowForward] = useState(false);
  const [showOrigin, setShowOrigin] = useState(true);
  const [showSlick, setShowSlick] = useState(true);

  const load = useCallback(async (id: string) => {
    setLoading(true);
    setError(null);
    setSelectedMmsi(null);
    try {
      const b = await runAnalysis(id);
      setBundle(b);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load(DEFAULT_EVENT);
  }, [load]);

  const toggle = (key: string, value: boolean) => {
    if (key === "showSlick") setShowSlick(value);
    if (key === "showOrigin") setShowOrigin(value);
    if (key === "showBackward") setShowBackward(value);
    if (key === "showForward") setShowForward(value);
  };

  const selVessel = bundle?.vessels.find((v) => v.mmsi === selectedMmsi) ?? null;
  const selAttr =
    bundle?.attribution.ranked_vessels.find((v) => v.mmsi === selectedMmsi) ?? null;

  return (
    <div className="h-screen w-screen bg-gray-950 text-gray-100" style={{ fontFamily: "ui-sans-serif, system-ui, sans-serif" }}>
      <div className="flex h-full flex-col">
        <header className="flex items-center justify-between border-b border-gray-800 bg-gray-900 px-4 py-2">
          <div className="flex items-center gap-3">
            <div className="flex h-8 w-8 items-center justify-center rounded-md bg-gradient-to-br from-cyan-500 to-blue-700 text-sm font-black">
              OT
            </div>
            <div>
              <div className="text-sm font-bold tracking-wide">OILTRACE-AI</div>
              <div className="text-[10px] text-gray-400">
                Oil spill origin & vessel attribution · SIH 2026 · PS143
              </div>
            </div>
          </div>
          <div className="flex items-center gap-2 text-xs">
            <input
              value={eventId}
              onChange={(e) => setEventId(e.target.value)}
              className="w-44 rounded border border-gray-700 bg-gray-800 px-2 py-1 text-gray-200 outline-none"
            />
            <button
              onClick={() => void load(eventId)}
              disabled={loading}
              className="rounded bg-gradient-to-r from-cyan-600 to-blue-600 px-4 py-1.5 font-semibold disabled:opacity-50"
            >
              {loading ? "Analysing…" : "Run analysis"}
            </button>
          </div>
        </header>

        {error && (
          <div className="bg-red-900/40 px-4 py-2 text-xs text-red-200">
            {error} — make sure the backend is running (uvicorn app.main:app on :8000).
          </div>
        )}
        {!error && !bundle && (
          <div className="flex flex-1 items-center justify-center text-sm text-gray-400">
            {loading ? "Running satellite → drift → AIS → attribution pipeline…" : "No data"}
          </div>
        )}

        {bundle && (
          <div className="grid flex-1 grid-cols-1 overflow-hidden md:grid-cols-[340px_1fr]">
            <aside className="flex flex-col gap-3 overflow-y-auto border-r border-gray-800 bg-gray-900/60 p-3">
              <SummaryPanel bundle={bundle} />
              <div>
                <h2 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-gray-400">
                  Estimated origin ({bundle.origin.candidates.length} hypotheses)
                </h2>
                <OriginPanel origin={bundle.origin} />
              </div>
              <div>
                <h2 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-gray-400">
                  Candidate vessels — ranked
                </h2>
                <VesselPanel
                  vessels={bundle.attribution.ranked_vessels}
                  selectedMmsi={selectedMmsi}
                  onSelect={setSelectedMmsi}
                />
              </div>
              {selVessel && (
                <div className="rounded-lg border border-green-600/40 bg-green-950/20 p-2 text-xs">
                  <b className="text-green-300">{selVessel.name ?? selVessel.mmsi}</b>
                  {selAttr ? (
                    <span className="text-gray-400">
                      {" "}
                      · AIS {selAttr.scores.ais_evidence.toFixed(0)} · behaviour{" "}
                      {selAttr.scores.behaviour.toFixed(0)}
                    </span>
                  ) : null}
                  <div className="mt-1 text-gray-400">
                    Track on map highlighted red · click again to deselect.
                  </div>
                  <button
                    onClick={() => setSelectedMmsi(null)}
                    className="mt-1 rounded bg-gray-700 px-2 py-0.5 text-gray-200"
                  >
                    Clear selection
                  </button>
                </div>
              )}
            </aside>

            <main className="relative">
              <div className="absolute left-3 top-3 z-10">
                <LayerToggle
                  showBackward={showBackward}
                  showForward={showForward}
                  showOrigin={showOrigin}
                  showSlick={showSlick}
                  onChange={toggle}
                />
              </div>
              <MapView
                bundle={bundle}
                selectedMmsi={selectedMmsi}
                onSelectVessel={setSelectedMmsi}
                showBackward={showBackward}
                showForward={showForward}
                showOrigin={showOrigin}
                showSlick={showSlick}
              />
            </main>
          </div>
        )}
      </div>
    </div>
  );
}