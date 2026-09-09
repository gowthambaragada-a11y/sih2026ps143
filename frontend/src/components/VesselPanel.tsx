import type { VesselAttribution } from "../types";

interface Props {
  vessels: VesselAttribution[];
  selectedMmsi: string | null;
  onSelect: (mmsi: string) => void;
}

const FLAG_COLORS: Record<string, string> = {
  positive: "#16a34a",
  warning: "#f59e0b",
  negative: "#dc2626",
};

export function VesselPanel({ vessels, selectedMmsi, onSelect }: Props) {
  return (
    <div className="flex flex-col gap-2">
      {vessels.length === 0 && (
        <p className="text-sm text-gray-400">
          No candidate vessels — AIS shows no track near the probable origin.
        </p>
      )}
      {vessels.map((v, i) => {
        const sel = v.mmsi === selectedMmsi;
        const s = v.scores;
        return (
          <button
            key={v.mmsi}
            onClick={() => onSelect(v.mmsi)}
            className={`rounded-lg border p-2 text-left transition ${
              sel
                ? "border-red-400 bg-red-50"
                : "border-gray-700 bg-gray-800/50 hover:border-gray-400"
            }`}
          >
            <div className="flex items-center justify-between">
              <div>
                <span className={`mr-2 text-xs font-semibold ${sel ? "text-red-500" : "text-gray-400"}`}>
                  #{i + 1}
                </span>
                <span className="font-semibold">{v.name ?? v.mmsi}</span>
                {v.type && (
                  <span className="ml-2 rounded bg-gray-700 px-1.5 py-0.5 text-[10px] uppercase text-gray-300">
                    {v.type}
                  </span>
                )}
              </div>
              <div className="text-lg font-bold">{s.overall.toFixed(1)}</div>
            </div>
            <div className="mt-1 flex h-1.5 w-full overflow-hidden rounded bg-gray-700">
              {(
                [
                  [s.spatial, "#22d3ee"],
                  [s.temporal, "#facc15"],
                  [s.trajectory, "#a3e635"],
                  [s.vessel_suitability, "#c084fc"],
                ] as [number, string][]
              ).map(([val, color], idx) => (
                <div
                  key={idx}
                  style={{ width: `${val}%`, backgroundColor: color }}
                />
              ))}
            </div>
            <div className="mt-1 flex flex-wrap gap-1 text-[10px]">
              <span className="rounded bg-cyan-900/60 px-1">Sp {s.spatial.toFixed(0)}</span>
              <span className="rounded bg-yellow-900/60 px-1">Te {s.temporal.toFixed(0)}</span>
              <span className="rounded bg-lime-900/60 px-1">Tr {s.trajectory.toFixed(0)}</span>
              <span className="rounded bg-purple-900/60 px-1">Vs {s.vessel_suitability.toFixed(0)}</span>
              {v.anomaly_score > 0.7 && (
                <span className="rounded bg-red-900/70 px-1">anomaly</span>
              )}
            </div>
            {sel && (
              <ul className="mt-2 space-y-1">
                {v.evidence.map((e, j) => (
                  <li key={j} className="text-[11px]">
                    <span
                      className="mr-1 inline-block h-2 w-2 rounded-full"
                      style={{ backgroundColor: FLAG_COLORS[e.flag] ?? "#666" }}
                    />
                    <span className="text-gray-200">{e.label}</span>
                    {e.detail && <span className="text-gray-400"> — {e.detail}</span>}
                  </li>
                ))}
              </ul>
            )}
          </button>
        );
      })}
    </div>
  );
}