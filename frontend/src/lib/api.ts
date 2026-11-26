import type { BucklingResult, WindParams, WindSummary, DeflectionLimits, DeflectionResult, Model, PDeltaResult, RcDesignResult, Results, SteelCatalog, SteelDesignResult, SuggestResult } from "./types";

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

async function postBlob(path: string, body: unknown): Promise<Blob> {
  const r = await fetch(`${BASE}${path}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!r.ok) {
    let msg = `${r.status} ${r.statusText}`;
    try { const j = await r.json(); msg = j.detail ?? msg; } catch { /* ignore */ }
    throw new Error(msg);
  }
  return r.blob();
}

export interface DxfOptions { units: string; material: "steel" | "concrete"; support: "fixed" | "pinned"; standard: string; tol: number; name: string; connect_crossings: boolean }
export interface ReportRequest {
  model: Model;
  include: Record<string, boolean>;
  steel_code?: string;
  rc_options?: Record<string, unknown>;
  stability_load?: string;
  image?: string;
  project?: { title?: string; project?: string; engineer?: string };
  lang?: "en" | "th";
  deflection?: { limits: Partial<DeflectionLimits>; wind_factor: number | null };
}

export const api = {
  generate: (params: Record<string, unknown>) => post<Model>("/api/generate", params),
  analyze: (model: Model) => post<Results>("/api/analyze", model),
  buckling: async (model: Model, load: string, n_modes = 4, n_seg = 4) =>
    ({ ...(await post<Omit<BucklingResult, "kind">>("/api/stability", { model, load, kind: "buckling", n_modes, n_seg })), kind: "buckling" as const }),
  pdelta: async (model: Model, load: string, n_seg = 2) =>
    ({ ...(await post<Omit<PDeltaResult, "kind">>("/api/stability", { model, load, kind: "pdelta", n_seg })), kind: "pdelta" as const }),
  steelDesign: (model: Model, code?: string) => post<SteelDesignResult>("/api/design/steel", { model, code }),
  suggestSteel: (model: Model, code: string | undefined, target: number, groups: Record<string, string>, limit_slenderness = true,
    deflection?: { limits: Partial<DeflectionLimits>; wind_factor: number | null }) =>
    post<SuggestResult>("/api/design/steel/suggest", { model, code, target, groups, limit_slenderness,
      ...(deflection ? { check_deflection: true, limits: deflection.limits, wind_factor: deflection.wind_factor } : {}) }),
  wind: (model: Model, params: Partial<WindParams>) => post<{ model: Model; summary: WindSummary }>("/api/loads/wind", { model, params }),
  deflection: (model: Model, limits: Partial<DeflectionLimits>, wind_factor: number | null) =>
    post<DeflectionResult>("/api/design/deflection", { model, limits, wind_factor }),
  catalog: async (): Promise<SteelCatalog> => {
    const r = await fetch(`${BASE}/api/sections/catalog`);
    if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
    return r.json();
  },
  rcDesign: (model: Model, options: Record<string, unknown>) => post<RcDesignResult>("/api/design/rc", { model, options }),
  importDxf: (dxf: string, options: Partial<DxfOptions>) => post<Model>("/api/import/dxf", { dxf, options }),
  report: (req: ReportRequest) => postBlob("/api/report", req),
  health: async () => { try { const r = await fetch(`${BASE}/api/health`); return r.ok; } catch { return false; } },
};
