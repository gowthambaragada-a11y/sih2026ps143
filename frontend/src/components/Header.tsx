import type { HealthInfo } from "../api";
import type { AnalysisBundle } from "../types";
import { StatusBadge, type PipelineMode } from "./StatusBadge";

export type ActivePage = "dashboard" | "attribution";

interface Props {
  active: ActivePage;
  mode: PipelineMode;
  health: HealthInfo | null;
  bundle: AnalysisBundle | null;
}

const LINKS: Array<{ key: ActivePage; href: string; label: string }> = [
  { key: "dashboard", href: "./", label: "Detect & Map" },
  { key: "attribution", href: "./attribution.html", label: "Origin & Vessels" },
];

export function Header({ active, mode, health, bundle }: Props) {
  return (
    <header className="flex items-center justify-between gap-3 border-b border-[#1d3448] bg-[#091725] px-5 py-2.5">
      <div className="flex items-center gap-3 min-w-0">
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-[#7cc8ff] to-[#4f9dff] text-sm font-black text-[#06101c]">
          OT
        </div>
        <div className="min-w-0">
          <div className="text-sm font-extrabold tracking-wide">
            OIL<span className="text-[#7cc8ff]">TRACE</span>-AI
          </div>
          <div className="truncate text-[10px] text-[#6f879b]">
            Oil spill origin & vessel attribution · SIH 2026 · PS143
          </div>
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-1.5">
        <nav className="mr-1 hidden items-center gap-1 md:flex">
          {LINKS.map((l) => (
            <a
              key={l.key}
              href={l.href}
              className={`rounded-full px-3 py-1 text-xs font-bold ${
                active === l.key
                  ? "bg-[#7cc8ff] text-[#06101c]"
                  : "text-[#8fa6b9] hover:bg-[#12283a] hover:text-white"
              }`}
            >
              {l.label}
            </a>
          ))}
        </nav>
        <StatusBadge mode={mode} health={health} bundle={bundle} />
      </div>
    </header>
  );
}