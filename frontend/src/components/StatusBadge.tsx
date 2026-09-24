import type { HealthInfo } from "../api";
import type { AnalysisBundle } from "../types";

export type PipelineMode = "connecting" | "live" | "offline" | "error";

interface Props {
  mode: PipelineMode;
  health: HealthInfo | null;
  bundle: AnalysisBundle | null;
}

const STYLES: Record<PipelineMode, { dot: string; pill: string; label: string; sub: string }> = {
  connecting: {
    dot: "bg-sky-400 animate-pulse",
    pill: "border-sky-500/40 bg-sky-950/50 text-sky-100",
    label: "Connecting…",
    sub: "probing backend /api/v1/health",
  },
  live: {
    dot: "bg-emerald-400 shadow-[0_0_8px_#34d399]",
    pill: "border-emerald-500/40 bg-emerald-950/40 text-emerald-100",
    label: "Live Backend Pipeline",
    sub: "connected",
  },
  offline: {
    dot: "bg-amber-400",
    pill: "border-amber-500/40 bg-amber-950/40 text-amber-100",
    label: "Synthetic Offline Demo",
    sub: "embedded reference scenario",
  },
  error: {
    dot: "bg-red-400",
    pill: "border-red-500/40 bg-red-950/40 text-red-100",
    label: "Error",
    sub: "check console / backend logs",
  },
};

export function StatusBadge({ mode, health, bundle }: Props) {
  const s = STYLES[mode];
  const target =
    mode === "offline"
      ? "embedded demo data"
      : health?.version
        ? `${health.service} · v${health.version}`
        : bundle?.event_id ?? "backend API";

  return (
    <div className={`flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs ${s.pill}`} title={target}>
      <span className={`h-2 w-2 rounded-full ${s.dot}`} />
      <div className="leading-tight">
        <div className="font-semibold">{s.label}</div>
        <div className="text-[10px] opacity-70">{s.sub}</div>
      </div>
    </div>
  );
}