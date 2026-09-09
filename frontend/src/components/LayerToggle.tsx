interface Props {
  showBackward: boolean;
  showForward: boolean;
  showOrigin: boolean;
  showSlick: boolean;
  onChange: (key: string, value: boolean) => void;
}

const TOGGLES = [
  { key: "showSlick", label: "Detected slick", color: "#f97316" },
  { key: "showOrigin", label: "Origin region + candidates", color: "#facc15" },
  { key: "showBackward", label: "Backward drift", color: "#22d3ee" },
  { key: "showForward", label: "Forward forecast", color: "#a3e635" },
] as const;

export function LayerToggle(props: Props) {
  const vals = {
    showSlick: props.showSlick,
    showOrigin: props.showOrigin,
    showBackward: props.showBackward,
    showForward: props.showForward,
  };
  return (
    <div className="flex flex-wrap gap-2">
      {TOGGLES.map((t) => {
        const on = vals[t.key];
        return (
          <button
            key={t.key}
            onClick={() => props.onChange(t.key, !on)}
            className={`rounded-full border px-3 py-1 text-xs transition ${
              on
                ? "border-gray-400 bg-gray-700 text-white"
                : "border-gray-700 bg-gray-900 text-gray-500"
            }`}
          >
            <span
              className="mr-1.5 inline-block h-2 w-2 rounded-full"
              style={{ backgroundColor: t.color }}
            />
            {t.label}
          </button>
        );
      })}
    </div>
  );
}