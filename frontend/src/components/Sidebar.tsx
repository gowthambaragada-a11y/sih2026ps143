import type { AnalysisBundle, LayerToggles, LogEntry } from "../types";
import type { HealthInfo } from "../api";
import { API_BASE } from "../api";
import { LayerToggle } from "./LayerToggle";
import { SummaryPanel } from "./SummaryPanel";
import type { PipelineMode } from "./StatusBadge";

interface Props {
  health: HealthInfo | null;
  bundle: AnalysisBundle | null;
  loading: boolean;
  error: string | null;
  mode: PipelineMode;
  eventId: string;
  onEventIdChange: (v: string) => void;
  onRun: () => void;
  fileName: string | null;
  onFile: (file: File | null) => void;
  logs: LogEntry[];
  toggles: LayerToggles;
  onToggle: (key: keyof LayerToggles) => void;
}

const LEVEL_STYLE: Record<LogEntry["level"], string> = {
  info: "text-gray-300",
  ok: "text-emerald-300",
  warn: "text-amber-300",
  error: "text-red-300",
};

const MODE_DOT: Record<PipelineMode, string> = {
  connecting: "bg-sky-400 animate-pulse",
  live: "bg-emerald-400 shadow-[0_0_8px_#34d399]",
  offline: "bg-amber-400",
  error: "bg-red-400",
};

const SECTION =
  "rounded-lg border border-[#20394f] bg-[#0c1c2b] p-3";
const SECTION_TITLE =
  "mb-2 text-[11px] font-semibold uppercase tracking-wider text-[#7cc8ff]";

export function Sidebar({
  health,
  bundle,
  loading,
  error,
  mode,
  eventId,
  onEventIdChange,
  onRun,
  fileName,
  onFile,
  logs,
  toggles,
  onToggle,
}: Props) {
  const backendTarget = bundle?.offline ? "embedded demo data (no backend)" : API_BASE;

  return (
    <div className="flex h-full flex-col gap-3 p-3">
      {/* Pipeline status */}
      <section className={SECTION}>
        <h2 className={SECTION_TITLE}>Pipeline status</h2>
        <div className="flex items-center gap-2 text-sm">
          <span className={`h-2.5 w-2.5 rounded-full ${MODE_DOT[mode]}`} />
          <span className="font-semibold capitalize text-gray-100">
            {mode === "connecting" ? "Connecting…" : mode === "live" ? "Live" : "Offline demo"}
          </span>
        </div>
        <div className="mt-1 text-[11px] text-gray-400">
          {mode === "live" && health
            ? `${health.service} · v${health.version ?? "?"}`
            : bundle
              ? bundle.offline
                ? "synthetic reference scenario (SIH-2026-SPILL-001)"
                : "live analysis"
              : "no analysis yet"}
        </div>
        <div className="mt-1 truncate text-[10px] font-mono text-gray-600" title={backendTarget}>
          {backendTarget}
        </div>
      </section>

      {/* Telemetry */}
      {bundle && (
        <section className={SECTION}>
          <h2 className={SECTION_TITLE}>Telemetry · {bundle.event_id}</h2>
          <SummaryPanel bundle={bundle} />
        </section>
      )}

      {/* Scenario */}
      <section className={SECTION}>
        <h2 className={SECTION_TITLE}>Scenario</h2>
        <label className="mb-1 block text-[10px] text-gray-500">Event ID</label>
        <div className="flex gap-2">
          <input
            value={eventId}
            onChange={(e) => onEventIdChange(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && onRun()}
            className="min-w-0 flex-1 rounded border border-[#20394f] bg-[#07111c] px-2 py-1.5 text-xs text-gray-200 outline-none focus:border-[#7cc8ff]"
          />
          <button
            onClick={onRun}
            disabled={loading}
            className="shrink-0 rounded bg-gradient-to-r from-[#7cc8ff] to-[#4f9dff] px-4 py-1.5 text-xs font-bold text-[#06101c] disabled:opacity-50"
          >
            {loading ? "Running…" : "Run analysis"}
          </button>
        </div>

        <div className="mt-3">
          <label className="mb-1 block text-[10px] text-gray-500">
            SAR scene upload (local)
          </label>
          <label className="flex cursor-pointer items-center justify-between gap-2 rounded border border-dashed border-[#2a4358] px-3 py-2 text-xs text-gray-300 hover:border-[#7cc8ff]">
            <span className="truncate">
              {fileName ?? "Choose a scene file…"}
            </span>
            <span className="shrink-0 rounded bg-[#20394f] px-2 py-0.5 text-[10px] font-semibold text-gray-200">
              Browse
            </span>
            <input
              type="file"
              accept=".tif,.tiff,.png,.nc,.json"
              className="hidden"
              onChange={(e) => onFile(e.target.files?.[0] ?? null)}
            />
          </label>
          {fileName && (
            <p className="mt-1 text-[10px] text-amber-300/80">
              File staged locally only — backend ingestion endpoint not wired yet.
            </p>
          )}
        </div>
      </section>

      {/* Map layers */}
      <section className={SECTION}>
        <h2 className={SECTION_TITLE}>Map layers</h2>
        <LayerToggle toggles={toggles} onChange={onToggle} />
      </section>

      {/* Detection log */}
      <section className={SECTION}>
        <h2 className={SECTION_TITLE}>Detection log</h2>
        <div className="max-h-40 space-y-1 overflow-y-auto font-mono text-[10px] leading-snug">
          {logs.map((l, i) => (
            <div key={i} className="flex gap-1.5">
              <span className="shrink-0 text-gray-600">{l.at}</span>
              <span className={LEVEL_STYLE[l.level]}>· {l.msg}</span>
            </div>
          ))}
        </div>
      </section>

      {error && (
        <div className="rounded-lg border border-red-600/40 bg-red-950/40 p-2 text-xs text-red-200">
          {error}
        </div>
      )}
    </div>
  );
}