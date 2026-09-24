import { useState } from "react";
import { isFirebaseConfigured, loginUser, loginWithGoogle } from "../../services/firebase";
import type { AuthUser } from "../../services/firebase";

interface Props {
  onAuthed: (user: AuthUser) => void;
  onGuest: () => void;
}

export function LoginCard({ onAuthed, onGuest }: Props) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async (fn: () => Promise<AuthUser>) => {
    setBusy(true);
    setError(null);
    try {
      onAuthed(await fn());
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!email || !password) {
      setError("Enter an email and password.");
      return;
    }
    void run(() => loginUser(email, password));
  };

  return (
    <div className="w-full max-w-sm rounded-2xl border border-white/10 bg-white/[0.04] p-7 backdrop-blur-xl shadow-2xl shadow-black/40">
      <div className="mb-6 text-center">
        <div className="radar-pulse mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-gradient-to-br from-[#06b6d4] to-[#0e7490] text-lg font-black text-[#062032]">
          OT
        </div>
        <h1 className="text-xl font-extrabold tracking-wide">
          OIL<span className="text-[#22d3ee]">TRACE</span>-AI
        </h1>
        <p className="mt-1 text-xs text-[#8496ab]">
          Satellite oil-spill detection · SIH 2026 · PS143
        </p>
      </div>

      <form onSubmit={submit} className="flex flex-col gap-3">
        {!isFirebaseConfigured && (
          <p className="rounded-lg border border-amber-600/40 bg-amber-950/40 px-3 py-2 text-[11px] leading-relaxed text-amber-200">
            Firebase env vars not set in this build — use <b>Guest / Evaluator Demo</b> below.
          </p>
        )}
        <label className="flex flex-col gap-1">
          <span className="text-[10px] font-semibold uppercase tracking-widest text-[#8496ab]">
            Email
          </span>
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="you@example.com"
            autoComplete="email"
            disabled={!isFirebaseConfigured}
            className="rounded-lg border border-[#1e293b] bg-[#0b0f19] px-3 py-2.5 text-sm text-[#e6f1f8] outline-none transition focus:border-[#06b6d4] disabled:opacity-40"
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-[10px] font-semibold uppercase tracking-widest text-[#8496ab]">
            Password
          </span>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="••••••••"
            autoComplete="current-password"
            disabled={!isFirebaseConfigured}
            className="rounded-lg border border-[#1e293b] bg-[#0b0f19] px-3 py-2.5 text-sm text-[#e6f1f8] outline-none transition focus:border-[#06b6d4] disabled:opacity-40"
          />
        </label>

        {error && (
          <p className="rounded-lg border border-red-500/40 bg-red-950/40 px-3 py-2 text-[11px] text-red-200">
            {error}
          </p>
        )}

        <button
          type="submit"
          disabled={busy || !isFirebaseConfigured}
          className="mt-1 rounded-lg bg-gradient-to-r from-[#06b6d4] to-[#0e7490] py-2.5 text-sm font-bold text-[#f0feff] transition hover:brightness-110 disabled:opacity-40"
        >
          {busy ? "Signing in…" : "Sign in"}
        </button>
      </form>

      <div className="my-5 flex items-center gap-3 text-[10px] uppercase tracking-widest text-[#4b5c70]">
        <span className="h-px flex-1 bg-[#1e293b]" />
        or
        <span className="h-px flex-1 bg-[#1e293b]" />
      </div>

      <button
        onClick={() => void run(loginWithGoogle)}
        disabled={busy || !isFirebaseConfigured}
        className="flex w-full items-center justify-center gap-2 rounded-lg border border-[#1e293b] bg-[#0f172a] py-2.5 text-sm font-semibold text-[#e6f1f8] transition hover:border-[#06b6d4] disabled:opacity-40"
      >
        <svg width="16" height="16" viewBox="0 0 24 24">
          <path fill="#EA4335" d="M12 5.4c1.6 0 3 .6 4.1 1.6l3.1-3.1C17.4 2.1 14.9 1 12 1 7.5 1 3.6 3.6 1.6 7.4l3.6 2.8C6.2 7.4 8.9 5.4 12 5.4z" />
          <path fill="#4285F4" d="M23 12.3c0-.9-.1-1.6-.2-2.3H12v4.5h6.2c-.3 1.5-1.1 2.7-2.3 3.6l3.5 2.7c2.1-1.9 3.6-4.7 3.6-8.5z" />
          <path fill="#FBBC05" d="M5.2 14.2c-.3-.9-.4-1.8-.4-2.8s.2-1.9.4-2.8l-3.6-2.8C.7 7.2 0 9.5 0 12s.6 4.8 1.6 6.9l3.6-2.7z" />
          <path fill="#34A853" d="M12 23c3 0 5.5-1 7.3-2.7l-3.5-2.7c-1 .7-2.3 1.1-3.8 1.1-3.1 0-5.7-2-6.7-4.8l-3.6 2.8C3.6 20.4 7.5 23 12 23z" />
        </svg>
        Continue with Google
      </button>

      <button
        onClick={onGuest}
        disabled={busy}
        className="mt-3 w-full rounded-lg border border-emerald-500/40 bg-emerald-950/40 py-2.5 text-sm font-bold text-emerald-300 transition hover:border-emerald-400 disabled:opacity-40"
      >
        Guest / Evaluator Demo Mode
      </button>
      <p className="mt-3 text-center text-[10px] leading-relaxed text-[#4b5c70]">
        Guest mode stages files locally and runs a mocked pipeline —
        everything else behaves identically.
      </p>
    </div>
  );
}