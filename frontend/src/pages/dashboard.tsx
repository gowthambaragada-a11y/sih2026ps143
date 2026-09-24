import { useCallback, useEffect, useState } from "react";
import type { AnalysisBundle, LayerToggles, LogEntry } from "../types";
import { probeHealth, runAnalysis, type HealthInfo } from "../api";
import { MapView } from "../components/MapView";
import { Sidebar } from "../components/Sidebar";
import { Header } from "../components/Header";
import { StatusBadge, type PipelineMode } from "../components/StatusBadge";

const DEFAULT_EVENT = "SIH-2026-SPILL-001";
const MAX_LOGS = 120;
const STAGES = ["Detect", "Drift", "Attribute", "Report"];

function now(): string {
  return new Date().toLocaleTimeString(undefined, { hour12: false });
}

export function DashboardPage() {
  const [eventId, setEventId] = useState(DEFAULT_EVENT);
  const [bundle, setBundle] = useState<AnalysisBundle | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [health, setHealth] = useState<HealthInfo | null>(null);
  const [selectedMmsi, setSelectedMmsi] = useState<string | null>(null);
  const [fileName, setFileName] = useState<string | null>(null);
  const [toggles, setToggles] = useState<LayerToggles>({
    showBackward: true,
    showForward: false,
    showOrigin: true,
    showSlick: true,
  });
  const [logs, setLogs] = useState<LogEntry[]>([
    { at: now(), level: "info", msg: "OILTRACE-AI dashboard initialised" },
  ]);

  const addLog = useCallback((level: LogEntry["level"], msg: string) => {
    setLogs((prev) => [...prev.slice(-(MAX_LOGS - 1)), { at: now(), level, msg }]);
  }, []);

  const load = useCallback(
    async (id: string) => {
      setLoading(true);
      setError(null);
      setSelectedMmsi(null);
      addLog("info", `starting analysis for "${id}"`);
      try {
        const b = await runAnalysis(id);
        setBundle(b);
        if (b.offline) {
          addLog("warn", "live API unreachable → embedded synthetic scenario (offline demo)");
        } else {
          addLog(
            "ok",
            `analysis complete → detection ${(b.detection.confidence * 100).toFixed(0)}%, ` +
              `${b.origin.candidates.length} origin candidates, ` +
              `${b.attribution.ranked_vessels.length} vessels ranked`,
          );
        }
      } catch (e) {
        const m = e instanceof Error ? e.message : String(e);
        setError(m);
        addLog("error", m);
      } finally {
        setLoading(false);
        addLog("info", "analysis finished");
      }
    },
    [addLog],
  );

  useEffect(() => {
    void load(DEFAULT_EVENT);
  }, [load]);

  useEffect(() => {
    let alive = true;
    void probeHealth().then((h) => {
      if (!alive) return;
      setHealth(h);
      addLog(
        h.reachable ? "ok" : "warn",
        h.reachable ? `live backend reachable (${h.service})` : "live backend unreachable",
      );
    });
    return () => {
      alive = false;
    };
  }, [addLog]);

  const toggle = (key: keyof LayerToggles) => {
    setToggles((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  const onFile = (f: File | null) => {
    setFileName(f?.name ?? null);
    addLog(
      "info",
      f
        ? `scene file staged: ${f.name} (${(f.size / 1024).toFixed(0)} KB)`
        : "scene file cleared",
    );
  };

  const mode: PipelineMode = error
    ? "error"
    : bundle
      ? bundle.offline
        ? "offline"
        : "live"
      : loading
        ? health?.reachable
          ? "live"
          : "connecting"
        : health?.reachable
          ? "live"
          : "offline";

  const selVessel = bundle?.vessels.find((v) => v.mmsi === selectedMmsi) ?? null;

  const stageIndex = bundle ? STAGES.length : loading ? 2 : 1;
  const detPct = bundle ? Math.round(bundle.detection.confidence * 100) : null;
  const originN = bundle?.origin.candidates.length ?? null;
  const vesselN = bundle?.attribution.ranked_vessels.length ?? null;

  return (
    <div
      className="flex h-dvh w-full flex-col bg-[#07111c] text-[#eaf4fb]"
      style={{ fontFamily: "'Inter', ui-sans-serif, system-ui, sans-serif" }}
    >
      <Header active="dashboard" mode={mode} health={health} bundle={bundle} />

      {/* Hero band */}
      <section className="border-b border-[#1d3448] bg-[#091725] px-5 py-3">
        <div className="mx-auto flex max-w-[1500px] flex-col gap-2.5">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <div className="text-[10px] font-extrabold uppercase tracking-[0.2em] text-[#7cc8ff]">
                SIH 2026 · PS143 · Live spill forensic dashboard
              </div>
              <h1 className="mt-0.5 text-xl font-extrabold leading-tight">
                Oil spill detection, drift & <span className="text-[#7cc8ff]">vessel attribution</span>
              </h1>
            </div>
            <div className="flex flex-wrap items-center gap-1.5">
              {STAGES.map((s, i) => (
                <span
                  key={s}
                  className={`rounded-full px-3 py-1 text-[10.5px] font-bold ${
                    i + 1 <= stageIndex
                      ? "bg-[#7cc8ff] text-[#06101c]"
                      : "border border-[#20394f] bg-[#0c1a28] text-[#6f879b]"
                  }`}
                >
                  {i + 1} · {s}
                </span>
              ))}
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <div className="flex items-center gap-3 rounded-[15px] border border-[#203a51] bg-[#0c1c2b] px-4 py-2">
              <span className="text-[10px] font-bold uppercase tracking-widest text-[#6f879b]">
                Detected
              </span>
              <b className="text-base text-[#d9edff]">{detPct === null ? "—" : `${detPct}%`}</b>
              <span className="text-[10px] text-[#6f879b]">confidence</span>
            </div>
            <a
              href="./attribution.html"
              className="flex items-center gap-3 rounded-[15px] border border-[#203a51] bg-[#0c1c2b] px-4 py-2 hover:border-[#7cc8ff]"
            >
              <span className="text-[10px] font-bold uppercase tracking-widest text-[#6f879b]">
                Origins
              </span>
              <b className="text-base text-[#d9edff]">{originN === null ? "—" : originN}</b>
              <span className="text-[10px] text-[#7cc8ff]">candidates ›</span>
            </a>
            <a
              href="./attribution.html"
              className="flex items-center gap-3 rounded-[15px] border border-[#203a51] bg-[#0c1c2b] px-4 py-2 hover:border-[#7cc8ff]"
            >
              <span className="text-[10px] font-bold uppercase tracking-widest text-[#6f879b]">
                Vessels
              </span>
              <b className="text-base text-[#d9edff]">{vesselN === null ? "—" : vesselN}</b>
              <span className="text-[10px] text-[#7cc8ff]">ranked ›</span>
            </a>
            {mode === "offline" && (
              <span className="rounded-lg border border-[#6b4d08] bg-[#2a1c05] px-3 py-1.5 text-[11px] font-bold text-[#ffd98a]">
                Synthetic offline demo — live API unreachable
              </span>
            )}
            {mode === "live" && (
              <span className="rounded-lg border border-[#1f5c41] bg-[#0d2b20] px-3 py-1.5 text-[11px] font-bold text-[#6fe3ac]">
                Live backend pipeline connected
              </span>
            )}
            {mode === "connecting" && (
              <span className="rounded-lg border border-[#1d5c8a] bg-[#0c2030] px-3 py-1.5 text-[11px] font-bold text-[#9cd5ff]">
                Connecting to backend…
              </span>
            )}
          </div>
        </div>
      </section>

      <div className="flex min-h-0 flex-1 flex-col md:flex-row">
        {/* Left: scenario + controls */}
        <aside className="w-full shrink-0 overflow-y-auto border-r border-[#1d3448] bg-[#07111c] max-h-[52dvh] md:max-h-none md:h-full md:w-[380px] lg:w-[420px]">
          <Sidebar
            health={health}
            bundle={bundle}
            loading={loading}
            error={error}
            mode={mode}
            eventId={eventId}
            onEventIdChange={setEventId}
            onRun={() => void load(eventId)}
            fileName={fileName}
            onFile={onFile}
            logs={logs}
            toggles={toggles}
            onToggle={toggle}
          />
        </aside>

        {/* Right: dedicated interactive map */}
        <main className="relative min-h-0 flex-1">
          {bundle ? (
            <MapView
              bundle={bundle}
              selectedMmsi={selectedMmsi}
              onSelectVessel={setSelectedMmsi}
              showBackward={toggles.showBackward}
              showForward={toggles.showForward}
              showOrigin={toggles.showOrigin}
              showSlick={toggles.showSlick}
            />
          ) : (
            <div className="flex h-full items-center justify-center text-sm text-gray-400">
              {loading
                ? "Running satellite → drift → AIS → attribution pipeline…"
                : "No data yet — configure a scenario in the sidebar and run analysis."}
            </div>
          )}
        </main>
      </div>
    </div>
  );
}