import type { OriginResponse } from "../types";

function fmtH(epochS: number): string {
  const d = new Date(epochS * 1000);
  return `T+${(epochS / 3600).toFixed(0)}h (${d.toISOString().slice(11, 16)} UTC)`;
}

function fmtDist(km: number): string {
  return `${km.toFixed(1)} km`;
}

export function OriginPanel({ origin }: { origin: OriginResponse }) {
  const top = origin.candidates[0];
  return (
    <div>
      <div className="mb-2">
        <div className="text-sm text-gray-300">
          Region confidence{" "}
          <b className="text-yellow-300">{(origin.confidence * 100).toFixed(0)}%</b>{" "}
          · uncertainty{" "}
          <b className="text-yellow-300">{origin.uncertainty_km.toFixed(1)} km</b>
        </div>
        {top && (
          <div className="mt-1 text-xs text-gray-400">
            Most likely release:{" "}
            <b className="text-gray-200">
              {top.lat.toFixed(3)}, {top.lon.toFixed(3)}
            </b>{" "}
            · {fmtH(top.release_time)} · {top.drift_duration_h.toFixed(0)}h drift
          </div>
        )}
      </div>
      <table className="w-full text-xs">
        <thead>
          <tr className="text-left text-gray-400">
            <th className="py-1">Candidate</th>
            <th>Proba</th>
            <th>Release</th>
            <th>Dist</th>
          </tr>
        </thead>
        <tbody>
          {origin.candidates.map((c) => (
            <tr key={c.candidate_id} className="border-t border-gray-700">
              <td className="py-1 pr-2 font-mono">{c.candidate_id}</td>
              <td className="pr-2">
                <div className="flex items-center gap-1">
                  <div className="h-1.5 w-12 bg-gray-700">
                    <div
                      className="h-full bg-yellow-400"
                      style={{ width: `${c.probability * 280}%` }}
                    />
                  </div>
                  <span className="text-gray-300">{(c.probability * 100).toFixed(1)}%</span>
                </div>
              </td>
              <td className="pr-2 text-gray-300">{fmtH(c.release_time)}</td>
              <td className="text-gray-300">{fmtDist(c.distance_km)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}