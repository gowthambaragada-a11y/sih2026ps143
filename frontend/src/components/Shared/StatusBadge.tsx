interface Props {
  mode: "checking" | "live" | "mock";
  detail?: string;
  onRetry?: () => void;
}

export function StatusBadge({ mode, detail, onRetry }: Props) {
  if (mode === "checking") {
    return (
      <div className="flex items-center gap-2 rounded-full border border-[#1e293b] bg-[#0f172a] px-3 py-1.5 text-xs">
        <span className="h-2 w-2 animate-pulse rounded-full bg-slate-400" />
        <span className="font-semibold text-[#8496ab]">Checking backend…</span>
      </div>
    );
  }

  if (mode === "live") {
    return (
      <div
        className="flex items-center gap-2 rounded-full border border-emerald-500/40 bg-emerald-950/40 px-3 py-1.5 text-xs"
        title={detail}
      >
        <span className="h-2 w-2 rounded-full bg-emerald-400 shadow-[0_0_8px_#34d399]" />
        <span className="font-semibold text-emerald-200">Live Cloud Pipeline</span>
      </div>
    );
  }

  return (
    <div className="flex items-center gap-2 rounded-full border border-amber-500/40 bg-amber-950/40 px-3 py-1.5 text-xs">
      <span className="h-2 w-2 rounded-full bg-amber-400" />
      <span className="font-semibold text-amber-200">Mock Simulation Mode</span>
      {onRetry && (
        <button
          onClick={onRetry}
          className="rounded-full border border-amber-500/40 px-2 py-0.5 text-[10px] font-bold text-amber-200 transition hover:bg-amber-500/10"
        >
          Retry
        </button>
      )}
    </div>
  );
}