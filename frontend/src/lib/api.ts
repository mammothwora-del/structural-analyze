import type { BucklingResult, Model, PDeltaResult, Results, SteelDesignResult } from "./types";

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
  buckling: async (model: Model, load: string, n_modes = 4, n_seg = 4) =>
    ({ ...(await post<Omit<BucklingResult, "kind">>("/api/stability", { model, load, kind: "buckling", n_modes, n_seg })), kind: "buckling" as const }),
  pdelta: async (model: Model, load: string, n_seg = 2) =>
    ({ ...(await post<Omit<PDeltaResult, "kind">>("/api/stability", { model, load, kind: "pdelta", n_seg })), kind: "pdelta" as const }),
  steelDesign: (model: Model, code?: string) => post<SteelDesignResult>("/api/design/steel", { model, code }),
  health: async () => { try { const r = await fetch(`${BASE}/api/health`); return r.ok; } catch { return false; } },
};
