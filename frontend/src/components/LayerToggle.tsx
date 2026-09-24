import type { LayerToggles } from "../types";

interface Props {
  toggles: LayerToggles;
  onChange: (key: keyof LayerToggles) => void;
}

const TOGGLES: Array<{ key: keyof LayerToggles; label: string; color: string }> = [
  { key: "showSlick", label: "Detected slick", color: "#f97316" },
  { key: "showOrigin", label: "Origin region + candidates", color: "#facc15" },
  { key: "showBackward", label: "Backward drift", color: "#22d3ee" },
  { key: "showForward", label: "Forward forecast", color: "#a3e635" },
];

export function LayerToggle({ toggles, onChange }: Props) {
  return (
    <div className="flex flex-col gap-1.5">
      {TOGGLES.map((t) => {
        const on = toggles[t.key];
        return (
          <button
            key={t.key}
            onClick={() => onChange(t.key)}
            className={`flex items-center gap-2 rounded border px-3 py-1.5 text-left text-xs transition ${
              on
                ? "border-gray-400 bg-gray-700 text-white"
                : "border-gray-700 bg-gray-900 text-gray-500 hover:border-gray-500"
            }`}
          >
            <span
              className="inline-block h-2.5 w-2.5 shrink-0 rounded-full"
              style={{ backgroundColor: t.color, boxShadow: on ? "0 0 6px " + t.color : "none" }}
            />
            <span>{t.label}</span>
            <span className={`ml-auto text-[10px] font-bold ${on ? "text-emerald-300" : "text-gray-600"}`}>
              {on ? "ON" : "OFF"}
            </span>
          </button>
        );
      })}
    </div>
  );
}