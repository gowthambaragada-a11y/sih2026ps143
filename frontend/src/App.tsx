import { useCallback, useEffect, useRef, useState } from "react";
import type { DetectionResult, LogEntry, StoredImage } from "./types";
import { probeHealth, detectImage } from "./services/api";
import {
  logoutUser,
  onAuthChange,
  uploadImageToFirebase,
  deleteImageFromFirebase,
  type AuthUser,
} from "./services/firebase";
import { loadSampleDataset } from "./services/demoDetect";
import { LoginCard } from "./components/Auth/LoginCard";
import { UserBadge } from "./components/Auth/UserBadge";
import { Dropzone } from "./components/Ingestion/Dropzone";
import { ImageGallery } from "./components/Ingestion/ImageGallery";
import { AnalysisMetrics } from "./components/Dashboard/AnalysisMetrics";
import { MapView } from "./components/Dashboard/MapView";
import { StatusBadge } from "./components/Shared/StatusBadge";

type Stage = "auth" | "ingest" | "detect";
type Backend = "checking" | "live" | "mock";

const MAX_LOGS = 120;
const STAGE_NAMES = ["Ingestion", "Preprocessing", "Segmentation", "Severity Classification"];
const STEPS: Array<{ key: Stage; label: string }> = [
  { key: "auth", label: "1 · Sign in" },
  { key: "ingest", label: "2 · Upload scenes" },
  { key: "detect", label: "3 · Analyze" },
];

function now(): string {
  return new Date().toLocaleTimeString(undefined, { hour12: false });
}
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

export default function App() {
  const [stage, setStage] = useState<Stage>("auth");
  const [user, setUser] = useState<AuthUser | null>(null);
  const [backend, setBackend] = useState<Backend>("checking");
  const [images, setImages] = useState<StoredImage[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [result, setResult] = useState<DetectionResult | null>(null);
  const [running, setRunning] = useState(false);
  const [stageIdx, setStageIdx] = useState(-1);
  const [logs, setLogs] = useState<LogEntry[]>([
    { at: now(), level: "info", msg: "OILTRACE-AI console ready" },
  ]);
  const fileRefs = useRef<Map<string, File>>(new Map());
  const busyRef = useRef(false);

  const addLog = useCallback((level: LogEntry["level"], msg: string) => {
    setLogs((prev) => [...prev.slice(-(MAX_LOGS - 1)), { at: now(), level, msg }]);
  }, []);

  const checkBackend = useCallback(async () => {
    setBackend("checking");
    const h = await probeHealth();
    setBackend(h.reachable ? "live" : "mock");
    addLog(h.reachable ? "ok" : "warn", h.reachable ? `backend live (${h.service})` : "backend unreachable → mock simulation mode");
    return h.reachable;
  }, [addLog]);

  useEffect(() => {
    void checkBackend();
  }, [checkBackend]);

  // Firebase auth listener (guest mode signals null immediately).
  useEffect(() => {
    const unsub = onAuthChange((u) => {
      setUser(u);
      if (u) setStage("ingest");
    });
    return unsub;
  }, []);

  const signOut = useCallback(async () => {
    await logoutUser();
    setUser(null);
    setStage("auth");
    setImages([]);
    setSelectedId(null);
    setResult(null);
    fileRefs.current.clear();
    addLog("info", "signed out");
  }, [addLog]);

  const stageFiles = useCallback(
    async (files: File[]) => {
      if (!user) return;
      const uid = user.uid;
      const pending = files.map((f) => {
        const id = `up-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
        fileRefs.current.set(id, f);
        return { id, file: f };
      });
      setImages((prev) => [
        ...prev,
        ...pending.map((p) => ({
          id: p.id,
          name: p.file.name,
          size: p.file.size,
          type: p.file.type || "image/*",
          url: "",
          storagePath: "",
          uploadedAt: Date.now(),
          progress: 0,
        })),
      ]);
      for (const p of pending) {
        try {
          const { image, isLive } = await uploadImageToFirebase(
            p.file,
            uid,
            (pct) => {
              setImages((prev) =>
                prev.map((img) => (img.id === p.id ? { ...img, progress: pct } : img)),
              );
            },
          );
          setImages((prev) => prev.map((img) => (img.id === p.id ? { ...image, progress: 100 } : img)));
          addLog(
            "ok",
            `staged "${p.file.name}" → ${isLive ? "Firebase Storage" : "local demo space"} (${(p.file.size / 1024).toFixed(0)} KB)`,
          );
        } catch (e) {
          addLog("error", `upload failed: ${e instanceof Error ? e.message : e}`);
          setImages((prev) => prev.filter((img) => img.id !== p.id));
        }
      }
    },
    [user, addLog],
  );

  const loadSamples = useCallback(() => {
    const samples = loadSampleDataset();
    setImages((prev) => {
      const existing = new Set(prev.map((i) => i.storagePath));
      const fresh = samples.filter((s) => !existing.has(s.storagePath));
      addLog("ok", `loaded ${fresh.length} pre-loaded sample scenes`);
      return [...prev, ...fresh];
    });
    if (!selectedId && samples[0]) setSelectedId(samples[0].id);
  }, [addLog, selectedId]);

  const deleteImage = useCallback(
    (id: string) => {
      const img = images.find((i) => i.id === id);
      if (!img) return;
      void deleteImageFromFirebase(img.storagePath).catch(() => {});
      fileRefs.current.delete(id);
      setImages((prev) => prev.filter((i) => i.id !== id));
      setSelectedId((prev) => (prev === id ? null : prev));
      addLog("info", `removed "${img.name}"`);
    },
    [images, addLog],
  );

  const runPipeline = useCallback(async () => {
    const img = images.find((i) => i.id === selectedId);
    if (!img || busyRef.current) return;
    busyRef.current = true;
    setRunning(true);
    setStageIdx(0);
    setStage("detect");
    addLog("info", `pipeline started → ${img.name}`);

    for (let i = 0; i < STAGE_NAMES.length; i++) {
      setStageIdx(i);
      addLog("info", STAGE_NAMES[i]);
      await sleep(600 + i * 260);
    }

    const file = fileRefs.current.get(img.id) ?? null;
    const input = file
      ? { file, fileName: img.name }
      : { imageUrl: img.url, fileName: img.name };

    const res = await detectImage(input);
    setResult(res);
    setStageIdx(-1);
    setRunning(false);
    busyRef.current = false;
    addLog(
      res.offline ? "warn" : "ok",
      res.offline
        ? `mock result — confidence ${res.confidence_pct}%, area ${res.area_km2.toFixed(1)} km²`
        : `detection complete — confidence ${res.confidence_pct}%, area ${res.area_km2.toFixed(1)} km²`,
    );
  }, [images, selectedId, addLog]);

  const exportJSON = useCallback(() => {
    if (!result) return;
    const blob = new Blob([JSON.stringify(result, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `oiltrace-${result.event_id}.json`;
    a.click();
    URL.revokeObjectURL(a.href);
    addLog("ok", `exported JSON report (${result.event_id}.json)`);
  }, [result, addLog]);

  const exportReport = useCallback(() => {
    if (!result) return;
    const w = window.open("", "_blank");
    if (!w) return;
    w.document.write(`<!doctype html><html><head><title>OILTRACE-AI Report</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;700&family=JetBrains+Mono&display=swap" rel="stylesheet">
<style>body{font-family:Inter,sans-serif;color:#0f172a;padding:40px;max-width:820px;margin:auto}code,pre{font-family:'JetBrains Mono',monospace;font-size:12px}h1{font-size:22px}h2{margin-top:26px;font-size:13px;text-transform:uppercase;letter-spacing:.12em;color:#0e7490}table{border-collapse:collapse;width:100%}td,th{border:1px solid #e2e8f0;padding:8px 10px;text-align:left}th{background:#f1f5f9}.badge{display:inline-block;padding:3px 10px;border-radius:999px;background:#ccfbf1;color:#065f46;font-size:12px;font-weight:700}</style></head><body>
<h1>OILTRACE-AI · Detection Report</h1>
<p>Event <code>${result.event_id}</code> · ${result.status.toUpperCase()} · <span class="badge">${result.severity.toUpperCase()}</span></p>
<h2>Detection metrics</h2>
<table><tr><th>Confidence</th><td>${result.confidence_pct.toFixed(1)}%</td></tr>
<tr><th>Spill area</th><td>${result.area_km2.toFixed(2)} km²</td></tr>
<tr><th>Perimeter</th><td>${result.perimeter_km.toFixed(2)} km</td></tr>
<tr><th>Centroid</th><td>${result.centroid.lat.toFixed(4)}, ${result.centroid.lon.toFixed(4)}</td></tr>
<tr><th>Drift</th><td>${result.drift.direction_label} ${result.drift.bearing_deg.toFixed(0)}° @ ${result.drift.speed_kmh.toFixed(2)} km/h</td></tr>
<tr><th>Model</th><td><code>${result.model}</code></td></tr></table>
<h2>Source & warnings</h2><p><code>${result.source}</code></p>
<ul>${result.warnings.map((x) => `<li>${x}</li>`).join("")}</ul>
<h2>GeoJSON</h2><pre>${JSON.stringify(result.polygon).slice(0, 900)}…</pre>
<script>setTimeout(()=>window.print(),250)<\/script></body></html>`);
    w.document.close();
    addLog("ok", "opened printable PDF report");
  }, [result, addLog]);

  const selectedImage = images.find((i) => i.id === selectedId) ?? null;

  return (
    <div
      className="flex h-dvh w-full flex-col overflow-hidden bg-[#0b0f19] text-[#e6f1f8]"
      style={{ fontFamily: "'Inter', ui-sans-serif, system-ui, sans-serif" }}
    >
      {/* Top navigation */}
      <header className="flex shrink-0 items-center justify-between gap-3 border-b border-[#1e293b] bg-[#0f172a] px-5 py-2.5">
        <div className="flex items-center gap-3 min-w-0">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-[#06b6d4] to-[#0e7490] text-sm font-black text-[#062032]">
            OT
          </div>
          <div className="min-w-0">
            <div className="text-sm font-extrabold tracking-wide">
              OIL<span className="text-[#22d3ee]">TRACE</span>-AI
            </div>
            <div className="truncate text-[10px] text-[#8496ab]">
              Satellite spill detection · SIH 2026 · PS143
            </div>
          </div>
        </div>

        <nav className="hidden items-center gap-1 md:flex">
          {STEPS.map((s, i) => (
            <div key={s.key} className="flex items-center">
              <span
                className={`rounded-full px-3 py-1 text-[10.5px] font-bold ${
                  stage === s.key
                    ? "bg-[#06b6d4] text-[#062032]"
                    : i < STEPS.findIndex((x) => x.key === stage) || stage === "detect"
                      ? "bg-[#0e7490]/40 text-[#67e8f9]"
                      : "text-[#4b5c70]"
                }`}
              >
                {s.label}
              </span>
              {i < STEPS.length - 1 && <span className="mx-1 text-[10px] text-[#1e293b]">—</span>}
            </div>
          ))}
        </nav>

        <div className="flex shrink-0 items-center gap-2">
          {user ? (
            <UserBadge user={user} onSignOut={() => void signOut()} />
          ) : (
            <span className="hidden text-[10px] text-[#4b5c70] sm:inline">not signed in</span>
          )}
          <StatusBadge mode={backend} onRetry={() => void checkBackend()} />
        </div>
      </header>

      {/* ------------------------------------------------ Stage 1 · Auth */}
      {stage === "auth" && (
        <main
          className="relative flex min-h-0 flex-1 items-center justify-center overflow-hidden p-6"
          style={{
            background:
              "radial-gradient(1200px 600px at 50% -10%, rgba(6,182,212,0.16), transparent 60%), radial-gradient(900px 500px at 80% 110%, rgba(16,185,129,0.10), transparent 60%), #0b0f19",
          }}
        >
          <div className="scanline pointer-events-none absolute inset-x-0 top-0 h-16 bg-gradient-to-b from-[#06b6d4]/20 to-transparent" />
          <div className="pointer-events-none absolute inset-0 opacity-[0.05]" style={{ backgroundImage: "linear-gradient(#22d3ee 1px, transparent 1px), linear-gradient(90deg, #22d3ee 1px, transparent 1px)", backgroundSize: "46px 46px" }} />
          <div className="fade-up pointer-events-auto relative">
            <LoginCard
              onAuthed={(u) => {
                setUser(u);
                setStage("ingest");
                addLog("ok", `authenticated as ${u.email ?? u.name}`);
              }}
              onGuest={() => {
                setUser({ uid: "guest", name: "Guest Evaluator", email: null, photoURL: null, isGuest: true });
                setStage("ingest");
                addLog("info", "entered Guest / Evaluator demo mode");
              }}
            />
          </div>
        </main>
      )}

      {/* ------------------------------------------------ Stage 2 · Ingestion */}
      {stage === "ingest" && (
        <main className="grid min-h-0 flex-1 grid-cols-1 gap-4 overflow-y-auto p-4 lg:grid-cols-5">
          <section className="space-y-3 lg:col-span-2">
            <div className="flex items-center justify-between">
              <div>
                <div className="text-[10px] font-extrabold uppercase tracking-[0.2em] text-[#22d3ee]">
                  Stage 2 · Data ingestion
                </div>
                <h1 className="mt-1 text-lg font-extrabold leading-tight">
                  Stage satellite scenes for <span className="text-[#22d3ee]">detection</span>
                </h1>
              </div>
            </div>

            <Dropzone onFiles={(files) => void stageFiles(files)} />

            {selectedImage ? (
              <div className="fade-up overflow-hidden rounded-2xl border border-[#1e293b] bg-[#0f172a]">
                <div className="flex items-end justify-center bg-[#0b0f19] p-2">
                  <img
                    src={selectedImage.url}
                    alt={selectedImage.name}
                    className="max-h-44 object-contain"
                  />
                </div>
                <div className="flex items-center justify-between gap-2 border-t border-[#1e293b] px-3 py-2">
                  <div className="min-w-0">
                    <div className="truncate text-xs font-bold text-[#e6f1f8]">{selectedImage.name}</div>
                    <div className="text-[10px] font-mono text-[#8496ab]">
                      {(selectedImage.size / 1024).toFixed(0)} KB
                      {selectedImage.width ? ` · ${selectedImage.width}×${selectedImage.height}px` : ""}
                    </div>
                  </div>
                  <span className="rounded-full border border-[#06b6d4]/40 bg-[#06b6d4]/10 px-2 py-0.5 text-[9px] font-bold uppercase text-[#67e8f9]">
                    active scene
                  </span>
                </div>
              </div>
            ) : (
              <div className="rounded-2xl border border-dashed border-[#1e293b] bg-[#0f172a]/50 p-4 text-center text-xs leading-relaxed text-[#8496ab]">
                Select a scene from your uploads (or load the sample dataset) to arm the
                detection pipeline.
              </div>
            )}

            <button
              onClick={() => void runPipeline()}
              disabled={!selectedImage || running}
              className="radar-pulse w-full rounded-2xl bg-gradient-to-r from-[#06b6d4] to-[#0e7490] py-3.5 text-sm font-extrabold text-[#f0feff] transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-40"
            >
              {running ? "Running pipeline…" : "Run Detection Pipeline →"}
            </button>
            <p className="text-center text-[10px] leading-relaxed text-[#4b5c70]">
              Sends the Firebase Storage URL to the FastAPI backend (or multipart file).
              Unreachable backend falls back to Mock Simulation Mode.
            </p>
          </section>

          <section className="lg:col-span-3">
            <div className="mb-3 flex items-center justify-between">
              <div>
                <div className="text-[10px] font-extrabold uppercase tracking-[0.2em] text-[#8496ab]">
                  Uploads · Firebase Storage
                </div>
                <h2 className="mt-0.5 text-sm font-bold text-[#e6f1f8]">
                  Your staged scenes {user ? `· ${user.uid.slice(0, 6)}` : ""}
                </h2>
              </div>
            </div>
            <ImageGallery
              images={images}
              selectedId={selectedId}
              onSelect={setSelectedId}
              onDelete={deleteImage}
              onLoadSamples={loadSamples}
            />
          </section>
        </main>
      )}

      {/* ------------------------------------------------ Stage 3 · Detection dashboard */}
      {stage === "detect" && (
        <main className="grid min-h-0 flex-1 grid-cols-1 gap-4 overflow-y-auto p-4 lg:grid-cols-5">
          <section className="flex min-h-0 flex-col gap-3 lg:col-span-2">
            <div className="flex items-center justify-between">
              <div>
                <div className="text-[10px] font-extrabold uppercase tracking-[0.2em] text-[#22d3ee]">
                  Stage 3 · Analysis dashboard
                </div>
                <h1 className="mt-1 text-lg font-extrabold leading-tight">
                  Detection, drift & <span className="text-[#22d3ee]">severity</span>
                </h1>
              </div>
              {stage === "detect" && user && (
                <button
                  onClick={() => setStage("ingest")}
                  className="rounded-lg border border-[#1e293b] px-3 py-1.5 text-xs font-bold text-[#8496ab] transition hover:border-[#06b6d4] hover:text-white"
                >
                  ← Re-stage scenes
                </button>
              )}
            </div>
            <AnalysisMetrics
              result={result}
              running={running}
              stage={stageIdx}
              logs={logs}
              onExportJSON={exportJSON}
              onExportReport={exportReport}
            />
          </section>

          <section className="min-h-[420px] lg:col-span-3 lg:min-h-0">
            <MapView result={result} imageUrl={selectedImage?.url} />
          </section>
        </main>
      )}
    </div>
  );
}