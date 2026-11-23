import type { Model, Results } from "./types";

const BASE = (import.meta as unknown as { env: Record<string, string> }).env.VITE_API_URL ?? "";

async function post<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(`${BASE}${path}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!r.ok) {
    let msg = `${r.status} ${r.statusText}`;
    try { const j = await r.json(); msg = j.detail ?? msg; } catch { /* ignore */ }
    throw new Error(msg);
  }
  return r.json();
}

export const api = {
  generate: (params: Record<string, unknown>) => post<Model>("/api/generate", params),
  analyze: (model: Model) => post<Results>("/api/analyze", model),
  health: async () => { try { const r = await fetch(`${BASE}/api/health`); return r.ok; } catch { return false; } },
};
