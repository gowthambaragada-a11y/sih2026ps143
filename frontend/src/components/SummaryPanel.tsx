import type { AnalysisBundle } from "../types";

export function SummaryPanel({ bundle }: { bundle: AnalysisBundle }) {
  const d = bundle.detection;
  const a = bundle.attribution;
  const top = a.ranked_vessels[0];
  return (
    <div>
      <div className="grid grid-cols-2 gap-2 text-center text-xs">
        <div className="rounded-md bg-gray-800/70 p-2">
          <div className="text-gray-400">Slick area</div>
          <div className="text-base font-semibold text-orange-300">
            {d.area_km2.toFixed(2)} km²
          </div>
        </div>
        <div className="rounded-md bg-gray-800/70 p-2">
          <div className="text-gray-400">Detection conf.</div>
          <div className="text-base font-semibold text-orange-300">
            {(d.confidence * 100).toFixed(0)}%
          </div>
        </div>
        <div className="rounded-md bg-gray-800/70 p-2">
          <div className="text-gray-400">Candidate vessels</div>
          <div className="text-base font-semibold text-sky-300">
            {a.ranked_vessels.length}
          </div>
        </div>
        <div className="rounded-md bg-gray-800/70 p-2">
          <div className="text-gray-400">Drift back unc.</div>
          <div className="text-base font-semibold text-sky-300">
            {bundle.driftBackward.uncertainty_km.toFixed(1)} km
          </div>
        </div>
      </div>

      {top && (
        <div className="mt-2 rounded-md border border-red-600/50 bg-red-950/30 p-2 text-xs">
          <span className="text-gray-400">Highest-evidence vessel: </span>
          <b className="text-red-200">{top.name ?? top.mmsi}</b>
          <span className="ml-1 text-gray-400">
            · score <b className="text-white">{top.scores.overall.toFixed(1)}</b>
          </span>
          <div className="mt-0.5 text-gray-400 italic">
            Ranking is probabilistic — not a determination of responsibility.
          </div>
        </div>
      )}

      <div className="mt-2 flex flex-wrap gap-1 text-[10px] text-gray-400">
        <span className="rounded bg-gray-800 px-1.5 py-0.5">det {bundle.modelVersions.detection}</span>
        <span className="rounded bg-gray-800 px-1.5 py-0.5">origin {bundle.modelVersions.origin}</span>
        <span className="rounded bg-gray-800 px-1.5 py-0.5">attr {bundle.modelVersions.attribution}</span>
        <span className="rounded bg-gray-800 px-1.5 py-0.5">drift {bundle.modelVersions.drift_engine}</span>
      </div>

      {bundle.warnings.length > 0 && (
        <div className="mt-2 space-y-1">
          {bundle.warnings.map((w, i) => (
            <div key={i} className="rounded bg-yellow-900/30 p-1.5 text-[11px] text-yellow-200">
              ⚠ {w}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}