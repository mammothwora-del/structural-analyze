import type { CaseResult, Model, Results, Stations } from "./types";

/** Load selection: a load case id or a combination id. */
export function factorsFor(model: Model, sel: string): Record<string, number> {
  const combo = model.combinations.find((c) => c.id === sel);
  if (combo) return combo.factors;
  return { [sel]: 1 };
}

function addArr(out: number[], a: number[], f: number) {
  for (let k = 0; k < a.length; k++) out[k] = (out[k] ?? 0) + f * a[k];
}

const STATION_KEYS = ["N", "Vy", "Vz", "T", "My", "Mz", "sigma_max", "sigma_min", "end_i", "end_j"] as const;

/**
 * Linear superposition of load-case results (exact for linear static analysis).
 * Note: sigma_max/min combine extreme-fibre values, which is conservative (upper bound)
 * because the governing fibre can differ between cases; they are recomputed from N, My, Mz
 * in the combined result below.
 */
const cache = new Map<string, CaseResult>();
export function combinedResult(model: Model, results: Results, sel: string): CaseResult | null {
  if (results.cases[sel]) return results.cases[sel];
  const key = sel + "|" + JSON.stringify(factorsFor(model, sel)) + "|" + results.solver.time_ms;
  const hit = cache.get(key);
  if (hit) return hit;
  const factors = factorsFor(model, sel);
  const ids = Object.keys(factors).filter((c) => results.cases[c]);
  if (!ids.length) return null;
  const base = results.cases[ids[0]];
  const out: CaseResult = {
    case: sel, displacements: {}, reactions: {}, elements: {},
    equilibrium: { applied: [0, 0, 0, 0, 0, 0], reactions: [0, 0, 0, 0, 0, 0], force_error: 0, moment_error: 0, ok: true, residual: 0 },
    warnings: [],
  };
  for (const n of Object.keys(base.displacements)) {
    const d: number[] = [0, 0, 0, 0, 0, 0];
    for (const c of ids) addArr(d, results.cases[c].displacements[n], factors[c]);
    out.displacements[n] = d;
  }
  for (const n of Object.keys(base.reactions)) {
    const d: number[] = [0, 0, 0, 0, 0, 0];
    for (const c of ids) addArr(d, results.cases[c].reactions[n], factors[c]);
    out.reactions[n] = d;
  }
  for (const eid of Object.keys(base.elements)) {
    const b = base.elements[eid];
    const s: Stations = { x: b.x, N: [], Vy: [], Vz: [], T: [], My: [], Mz: [], disp: b.disp.map(() => [0, 0, 0]), sigma_max: [], sigma_min: [], end_i: [], end_j: [] };
    for (const c of ids) {
      const e = results.cases[c].elements[eid];
      const f = factors[c];
      for (const k of STATION_KEYS) addArr(s[k] as number[], e[k] as number[], f);
      e.disp.forEach((p, i) => addArr(s.disp[i], p, f));
    }
    const info = results.elements[eid];
    if (info) {
      const { A, Sy, Sz } = info.props;
      s.sigma_max = s.N.map((N, i) => N / A + Math.abs(s.My[i]) / Sy + Math.abs(s.Mz[i]) / Sz);
      s.sigma_min = s.N.map((N, i) => N / A - Math.abs(s.My[i]) / Sy - Math.abs(s.Mz[i]) / Sz);
    }
    out.elements[eid] = s;
  }
  let fe = 0, me = 0;
  for (const c of ids) {
    addArr(out.equilibrium.applied, results.cases[c].equilibrium.applied, factors[c]);
    addArr(out.equilibrium.reactions, results.cases[c].equilibrium.reactions, factors[c]);
    out.equilibrium.ok = out.equilibrium.ok && results.cases[c].equilibrium.ok;
  }
  for (let k = 0; k < 3; k++) fe = Math.max(fe, Math.abs(out.equilibrium.applied[k] + out.equilibrium.reactions[k]));
  for (let k = 3; k < 6; k++) me = Math.max(me, Math.abs(out.equilibrium.applied[k] + out.equilibrium.reactions[k]));
  out.equilibrium.force_error = fe;
  out.equilibrium.moment_error = me;
  cache.set(key, out);
  return out;
}
