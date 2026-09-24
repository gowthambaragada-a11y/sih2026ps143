import { useState } from "react";
import type { DetectionResult, LogEntry } from "../../types";
import { PipelineStepper } from "./PipelineStepper";

interface Props {
  result: DetectionResult | null;
  running: boolean;
  stage: number;
  logs: LogEntry[];
  onExportJSON: () => void;
  onExportReport: () => void;
}

function MetricCell({
  label,
  value,
  sub,
}: {
  label: string;
  value: string;
  sub?: string;
}) {
  return (
    <div className="rounded-xl border border-[#1e293b] bg-[#0b0f19] p-3">
      <div className="text-[9px] font-bold uppercase tracking-[0.16em] text-[#8496ab]">{label}</div>
      <div className="mt-1 text-sm font-black text-[#e6f1f8]" style={{ fontFamily: "'JetBrains Mono', monospace" }}>
        {value}
      </div>
      {sub && <div className="mt-0.5 text-[10px] text-[#5b6b80]">{sub}</div>}
    </div>
  );
}

const SEVERITY_STYLE: Record<string, string> = {
  low: "bg-[#10b981]/15 text-[#34d399] border-[#10b981]/40",
  medium: "bg-[#f59e0b]/15 text-[#fbbf24] border-[#f59e0b]/40",
  high: "bg-[#ef4444]/15 text-[#f87171] border-[#ef4444]/40",
  critical: "bg-[#ef4444]/25 text-red-200 border-red-400/60",
};

export function AnalysisMetrics({
  result,
  running,
  stage,
  logs,
  onExportJSON,
  onExportReport,
}: Props) {
  const [showLogs, setShowLogs] = useState(false);

  return (
    <div className="flex min-h-0 flex-col gap-3">
      <PipelineStepper stage={stage} running={running} />

      {running ? (
        <div className="rounded-2xl border border-[#1e293b] bg-[#0f172a] p-5 text-center">
          <div className="radar-pulse mx-auto h-4 w-4 rounded-full bg-[#34d399]" />
          <div className="mt-3 text-sm font-extrabold text-[#e6f1f8]">
            Pipeline analysing scene…
          </div>
          <div className="mt-1 text-[11px] text-[#8496ab]">
            Ingestion → Preprocessing → Segmentation → Severity Classification
          </div>
        </div>
      ) : result ? (
        <>
          {/* Pipeline status */}
          <div className="flex items-center justify-between gap-3 rounded-2xl border border-[#1e293b] bg-[#0f172a] p-4">
            <div>
              <div className="text-[10px] font-extrabold uppercase tracking-[0.2em] text-[#8496ab]">
                Pipeline status
              </div>
              <div className="mt-1 flex items-center gap-2">
                {result.offline ? (
                  <>
                    <span className="h-2 w-2 rounded-full bg-[#f59e0b]" />
                    <span className="text-xs font-black text-[#fbbf24]">
                      MOCK SIMULATION RESULT
                    </span>
                  </>
                ) : (
                  <>
                    <span className="h-2 w-2 rounded-full bg-[#34d399]" />
                    <span className="text-xs font-black text-[#34d399]">LIVE DETECTION</span>
                  </>
                )}
              </div>
            </div>
            <span
              className={`rounded-full border px-3 py-1 text-[10px] font-black uppercase tracking-wider ${SEVERITY_STYLE[result.severity]}`}
            >
              {result.severity}
            </span>
          </div>

          {/* Metrics grid */}
          <div className="grid grid-cols-2 gap-2">
            <div className="col-span-2 rounded-2xl border border-[#1e293b] bg-[#0f172a] p-4">
              <div className="flex items-end justify-between">
                <div>
                  <div className="text-[9px] font-bold uppercase tracking-[0.16em] text-[#8496ab]">
                    Model confidence
                  </div>
                  <div
                    className="mt-1 text-3xl font-black text-[#22d3ee]"
                    style={{ fontFamily: "'JetBrains Mono', monospace" }}
                  >
                    {result.confidence_pct.toFixed(1)}
                    <span className="text-base text-[#5b6b80]">%</span>
                  </div>
                </div>
                <svg width="96" height="96" viewBox="0 0 96 96" className="shrink-0 -rotate-90">
                  <circle cx="48" cy="48" r="40" fill="none" stroke="#1e293b" strokeWidth="8" />
                  <circle
                    cx="48"
                    cy="48"
                    r="40"
                    fill="none"
                    stroke="#22d3ee"
                    strokeWidth="8"
                    strokeLinecap="round"
                    strokeDasharray={`${2 * Math.PI * 40}`}
                    strokeDashoffset={`${2 * Math.PI * 40 * (1 - result.confidence / 100)}`}
                  />
                </svg>
              </div>
            </div>
            <MetricCell label="Spill area" value={`${result.area_km2.toFixed(2)}`} sub="km²" />
            <MetricCell label="Perimeter" value={`${result.perimeter_km.toFixed(2)}`} sub="km" />
            <MetricCell
              label="Drift"
              value={`${result.drift.bearing_deg.toFixed(0)}°`}
              sub={`${result.drift.direction_label} · ${result.drift.speed_kmh.toFixed(2)} km/h`}
            />
            <MetricCell
              label="Centroid"
              value={`${result.centroid.lat.toFixed(4)}, ${result.centroid.lon.toFixed(4)}`}
              sub="lat, lon"
            />
          </div>

          {result.warnings.length > 0 && (
            <div className="rounded-xl border border-[#f59e0b]/30 bg-[#f59e0b]/5 p-3 text-[11px] leading-relaxed text-[#fbbf24]">
              {result.warnings.join(" · ")}
            </div>
          )}

          {result.offline && (
            <div className="rounded-xl border border-[#1e293b] bg-[#0f172a] p-3 text-[10px] leading-relaxed text-[#8496ab]">
              Live backend unreachable — this result was synthesized as a deterministic demo.
              Connect <code className="text-[#67e8f9]">VITE_API_BASE_URL</code> to run the real
              U-Net pipeline.
            </div>
          )}
        </>
      ) : (
        <div className="rounded-2xl border border-dashed border-[#1e293b] bg-[#0f172a]/40 p-6 text-center">
          <div className="mx-auto flex h-10 w-10 items-center justify-center rounded-full border border-[#06b6d4]/40 bg-[#06b6d4]/10 text-lg">
            ⛽
          </div>
          <div className="mt-2 text-xs font-bold text-[#8496ab]">
            No detection yet — select a scene and run the pipeline
          </div>
        </div>
      )}

      {/* Action bar */}
      <div className="flex items-center gap-2">
        <button
          onClick={onExportJSON}
          disabled={!result || running}
          className="flex-1 rounded-xl bg-[#0e7490]/30 px-3 py-2.5 text-xs font-black text-[#67e8f9] transition hover:bg-[#0e7490]/50 disabled:cursor-not-allowed disabled:opacity-40"
        >
          Export JSON
        </button>
        <button
          onClick={onExportReport}
          disabled={!result || running}
          className="flex-1 rounded-xl bg-[#06b6d4]/20 px-3 py-2.5 text-xs font-black text-[#22d3ee] transition hover:bg-[#06b6d4]/35 disabled:cursor-not-allowed disabled:opacity-40"
        >
          Export Report (PDF)
        </button>
        <button
          onClick={() => setShowLogs((s) => !s)}
          className="rounded-xl border border-[#1e293b] px-3 py-2.5 text-xs font-black text-[#8496ab] transition hover:border-[#06b6d4]/50 hover:text-white"
        >
          {showLogs ? "Hide logs" : `Logs (${logs.length})`}
        </button>
      </div>

      {/* Detection log drawer */}
      {showLogs && (
        <div className="fade-up max-h-48 overflow-y-auto rounded-xl border border-[#1e293b] bg-[#0b0f19] p-3">
          <div className="mb-2 text-[10px] font-extrabold uppercase tracking-[0.2em] text-[#8496ab]">
            Detection log
          </div>
          <ul className="space-y-1.5">
            {[...logs].reverse().map((l, i) => (
              <li key={i} className="flex gap-2 text-[11px] leading-snug">
                <span className="shrink-0 font-mono text-[#4b5c70]">{l.at}</span>
                <span
                  className={
                    l.level === "ok"
                      ? "text-[#34d399]"
                      : l.level === "warn"
                        ? "text-[#fbbf24]"
                        : l.level === "error"
                          ? "text-[#f87171]"
                          : "text-[#8496ab]"
                  }
                >
                  {l.msg}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}