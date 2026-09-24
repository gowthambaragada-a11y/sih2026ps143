interface Props {
  stage: number;
  running: boolean;
}

const PIPELINE = [
  { label: "Ingestion" },
  { label: "Preprocessing" },
  { label: "Segmentation" },
  { label: "Severity Classification" },
];

export function PipelineStepper({ stage, running }: Props) {
  const active = running ? stage : -1;
  return (
    <div className="rounded-2xl border border-[#1e293b] bg-[#0f172a] p-4">
      <div className="mb-3 flex items-center justify-between">
        <div className="text-[10px] font-extrabold uppercase tracking-[0.2em] text-[#8496ab]">
          Detection pipeline
        </div>
        {running ? (
          <span className="flex items-center gap-1.5 text-[10px] font-bold text-[#22d3ee]">
            <span className="radar-pulse h-2 w-2 rounded-full bg-[#22d3ee]" /> RUNNING
          </span>
        ) : active === -1 ? (
          <span className="text-[10px] font-bold text-[#4b5c70]">IDLE</span>
        ) : (
          <span className="flex items-center gap-1.5 text-[10px] font-bold text-[#34d399]">
            <span className="h-2 w-2 rounded-full bg-[#34d399]" /> COMPLETE
          </span>
        )}
      </div>

      <ol className="relative space-y-2.5 before:absolute before:left-[11px] before:top-3 before:h-[calc(100%-24px)] before:w-px before:bg-[#1e293b]">
        {PIPELINE.map((p, i) => {
          const done = active > i;
          const current = active === i;
          return (
            <li key={p.label} className="relative flex items-center gap-3">
              <span
                className={`relative z-10 flex h-6 w-6 shrink-0 items-center justify-center rounded-full border text-[10px] font-black transition ${
                  current
                    ? "radar-pulse border-[#06b6d4] bg-[#06b6d4] text-[#062032]"
                    : done
                      ? "border-[#10b981] bg-[#10b981] text-[#062032]"
                      : "border-[#1e293b] bg-[#0b0f19] text-[#4b5c70]"
                }`}
              >
                {done ? "✓" : i + 1}
              </span>
              <span
                className={`text-[11px] font-bold ${
                  current || done ? "text-[#e6f1f8]" : "text-[#4b5c70]"
                }`}
              >
                {p.label}
              </span>
              {current && <span className="skeleton h-3 w-24 rounded" />}
            </li>
          );
        })}
      </ol>
    </div>
  );
}