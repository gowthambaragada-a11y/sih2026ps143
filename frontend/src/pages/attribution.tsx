import { useEffect, useState } from "react";
import type { AnalysisBundle } from "../types";
import { probeHealth, runAnalysis, type HealthInfo } from "../api";
import { Header } from "../components/Header";
import { OriginPanel } from "../components/OriginPanel";
import { VesselPanel } from "../components/VesselPanel";
import { SummaryPanel } from "../components/SummaryPanel";
import type { PipelineMode } from "../components/StatusBadge";

const DEFAULT_EVENT = "SIH-2026-SPILL-001";
const SECTION = "rounded-lg border border-[#20394f] bg-[#0c1c2b] p-3";
const SECTION_TITLE =
  "mb-2 text-[11px] font-semibold uppercase tracking-wider text-[#7cc8ff]";

export function AttributionPage() {
  const [bundle, setBundle] = useState<AnalysisBundle | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [health, setHealth] = useState<HealthInfo | null>(null);
  const [selectedMmsi, setSelectedMmsi] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    void probeHealth().then((h) => {
      if (alive) setHealth(h);
    });
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    void runAnalysis(DEFAULT_EVENT)
      .then((b) => {
        if (alive) setBundle(b);
      })
      .catch((e) => {
        if (alive) setError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, []);

  const mode: PipelineMode = bundle
    ? bundle.offline
      ? "offline"
      : "live"
    : health?.reachable
      ? "live"
      : "connecting";

  const toggleSel = (mmsi: string) =>
    setSelectedMmsi((prev) => (prev === mmsi ? null : mmsi));

  const selVessel =
    bundle?.vessels.find((v) => v.mmsi === selectedMmsi) ?? null;

  return (
    <div
      className="flex h-dvh w-full flex-col bg-[#07111c] text-[#eaf4fb]"
      style={{ fontFamily: "'Inter', ui-sans-serif, system-ui, sans-serif" }}
    >
      <Header active="attribution" mode={mode} health={health} bundle={bundle} />

      {/* Page strip */}
      <section className="border-b border-[#1d3448] bg-[#091725] px-5 py-3">
        <div className="mx-auto flex max-w-[1500px] flex-col gap-2">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <div className="text-[10px] font-extrabold uppercase tracking-[0.2em] text-[#7cc8ff]">
                Event {bundle?.event_id ?? DEFAULT_EVENT} · Attribution results
              </div>
              <h1 className="mt-0.5 text-xl font-extrabold leading-tight">
                Origin hypotheses & <span className="text-[#7cc8ff]">candidate vessels</span>
              </h1>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              {mode === "offline" && (
                <span className="rounded-lg border border-[#6b4d08] bg-[#2a1c05] px-3 py-1.5 text-[11px] font-bold text-[#ffd98a]">
                  Synthetic offline demo
                </span>
              )}
              {mode === "live" && (
                <span className="rounded-lg border border-[#1f5c41] bg-[#0d2b20] px-3 py-1.5 text-[11px] font-bold text-[#6fe3ac]">
                  Live backend pipeline
                </span>
              )}
              {selVessel && (
                <span className="hidden text-xs text-[#8fa6b9] md:inline">
                  <b className="text-[#7cc8ff]">{selVessel.name ?? selVessel.mmsi}</b> selected
                </span>
              )}
            </div>
          </div>
        </div>
      </section>

      <div className="flex min-h-0 flex-1 flex-col gap-3 p-4 lg:flex-row">
        {/* Left: case file + method */}
        <aside className="w-full shrink-0 space-y-3 overflow-y-auto lg:w-[360px]">
          <section className={SECTION}>
            <h2 className={SECTION_TITLE}>Case file</h2>
            {bundle ? (
              <SummaryPanel bundle={bundle} />
            ) : (
              <p className="text-sm text-gray-400">
                {loading ? "Loading results…" : error ?? "No data yet."}
              </p>
            )}
          </section>

          <section className={SECTION}>
            <h2 className={SECTION_TITLE}>Method & ethics</h2>
            <p className="text-xs leading-relaxed text-[#8fa6b9]">
              Origin is reconstructed probabilistically by backward drift from the
              detected slick; vessels are ranked by spatial, temporal, trajectory and
              vessel-suitability evidence. Ranking is probabilistic — not a
              determination of responsibility.
            </p>
          </section>
        </aside>

        {/* Right: origin hypotheses + candidate vessels */}
        <main className="min-h-0 flex-1 space-y-3 overflow-y-auto">
          <section className={SECTION}>
            <h2 className={SECTION_TITLE}>
              Origin hypotheses · {bundle?.origin.candidates.length ?? "…"}
            </h2>
            {bundle ? (
              <OriginPanel origin={bundle.origin} />
            ) : (
              <p className="text-sm text-gray-400">
                {loading ? "Computing backward drift…" : "No origin data yet."}
              </p>
            )}
          </section>

          <section className={SECTION}>
            <h2 className={SECTION_TITLE}>
              Candidate vessels — ranked · {bundle?.attribution.ranked_vessels.length ?? "…"}
            </h2>
            {bundle ? (
              <VesselPanel
                vessels={bundle.attribution.ranked_vessels}
                selectedMmsi={selectedMmsi}
                onSelect={toggleSel}
              />
            ) : (
              <p className="text-sm text-gray-400">
                {loading ? "Matching AIS tracks…" : "No candidate vessels yet."}
              </p>
            )}
          </section>
        </main>
      </div>
    </div>
  );
}