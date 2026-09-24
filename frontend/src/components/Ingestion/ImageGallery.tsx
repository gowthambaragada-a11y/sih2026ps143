import type { StoredImage } from "../../types";

interface Props {
  images: StoredImage[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  onDelete: (id: string) => void;
  onLoadSamples: () => void;
  disabled?: boolean;
}

function fmtSize(bytes: number): string {
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  if (bytes >= 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${bytes} B`;
}

export function ImageGallery({
  images,
  selectedId,
  onSelect,
  onDelete,
  onLoadSamples,
  disabled,
}: Props) {
  return (
    <div>
      <div className="grid grid-cols-2 gap-2">
        {images.map((img) => {
          const selected = img.id === selectedId;
          const uploading = (img.progress ?? 100) < 100;
          return (
            <div
              key={img.id}
              onClick={() => !uploading && !disabled && onSelect(img.id)}
              className={`group relative cursor-pointer overflow-hidden rounded-xl border bg-[#0b0f19] transition ${
                selected ? "border-[#06b6d4] ring-2 ring-[#06b6d4]/40" : "border-[#1e293b] hover:border-[#06b6d4]/50"
              }`}
            >
              <div className="flex aspect-square items-center justify-center overflow-hidden bg-[#0b0f19]">
                {img.url ? (
                  <img
                    src={img.url}
                    alt={img.name}
                    className="h-full w-full object-cover transition group-hover:scale-105"
                  />
                ) : (
                  <div className="skeleton h-full w-full" />
                )}
              </div>
              <div className="border-t border-[#1e293b] bg-[#0f172a] px-2 py-1.5">
                <div className="truncate text-[10px] font-semibold text-[#e6f1f8]" title={img.name}>
                  {img.name}
                </div>
                <div className="mt-0.5 flex items-center justify-between text-[9px] text-[#8496ab]">
                  <span>{fmtSize(img.size)}</span>
                  <span className={uploading ? "text-[#22d3ee]" : selected ? "text-[#06b6d4]" : "text-[#4b5c70]"}>
                    {uploading ? "uploading…" : selected ? "selected ✓" : "tap to select"}
                  </span>
                </div>
              </div>
              {uploading && (
                <div className="absolute inset-x-0 bottom-10 h-1 bg-[#1e293b]">
                  <div
                    className="h-full bg-[#06b6d4] transition-all"
                    style={{ width: `${img.progress ?? 0}%` }}
                  />
                </div>
              )}
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  if (!disabled) onDelete(img.id);
                }}
                className="absolute right-1.5 top-1.5 rounded-md border border-[#1e293b] bg-[#0b0f19]/90 px-1.5 py-0.5 text-[10px] font-bold text-[#8496ab] opacity-0 transition hover:border-red-500/60 hover:text-red-300 group-hover:opacity-100"
                title="Delete upload"
              >
                ✕
              </button>
            </div>
          );
        })}
      </div>

      <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
        <button
          onClick={onLoadSamples}
          disabled={disabled}
          className="rounded-lg border border-[#164e63] bg-[#083344] px-3 py-2 text-xs font-bold text-[#67e8f9] transition hover:border-[#06b6d4] disabled:opacity-40"
        >
          ⬇ Load Pre-loaded Sample Dataset
        </button>
        <span className="text-[10px] text-[#4b5c70]">
          {images.length} file{images.length === 1 ? "" : "s"} staged in your analysis space
        </span>
      </div>
    </div>
  );
}