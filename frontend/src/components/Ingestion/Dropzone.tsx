import { useRef, useState } from "react";

interface Props {
  onFiles: (files: File[]) => void;
  disabled?: boolean;
}

const ACCEPT = "image/*,.tif,.tiff,.png,.jpg,.jpeg,.nc";

export function Dropzone({ onFiles, disabled }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);

  const handle = (files: FileList | null) => {
    if (!files || files.length === 0) return;
    onFiles(Array.from(files));
  };

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={() => !disabled && inputRef.current?.click()}
      onKeyDown={(e) => e.key === "Enter" && !disabled && inputRef.current?.click()}
      onDragOver={(e) => {
        e.preventDefault();
        if (!disabled) setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setOver(false);
        if (!disabled) handle(e.dataTransfer.files);
      }}
      className={`group flex cursor-pointer flex-col items-center justify-center gap-3 rounded-2xl border-2 border-dashed px-6 py-10 text-center transition ${
        over
          ? "border-[#06b6d4] bg-[#06b6d4]/10"
          : "border-[#1e293b] bg-[#0f172a] hover:border-[#06b6d4]/60"
      } ${disabled ? "cursor-not-allowed opacity-40" : ""}`}
    >
      <div className="flex h-14 w-14 items-center justify-center rounded-full border border-[#1e293b] bg-[#0b0f19] text-2xl">
        🛰️
      </div>
      <div>
        <p className="text-sm font-bold text-[#e6f1f8]">
          Drag &amp; drop satellite / SAR images
        </p>
        <p className="mt-1 text-xs text-[#8496ab]">
          or <span className="font-semibold text-[#22d3ee]">browse</span> · TIF · PNG · JPG · NC
        </p>
      </div>
      <span className="rounded-lg border border-[#1e293b] bg-[#0b0f19] px-4 py-1.5 text-xs font-semibold text-[#22d3ee] group-hover:border-[#06b6d4]">
        Select files
      </span>
      <input
        ref={inputRef}
        type="file"
        accept={ACCEPT}
        multiple
        className="hidden"
        onChange={(e) => {
          handle(e.target.files);
          e.target.value = "";
        }}
      />
    </div>
  );
}