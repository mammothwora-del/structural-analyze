import { combinedResult } from "./combine";
import type { FlowData } from "./loadpath";
import type { Scale } from "./colormap";
import type { CaseResult, ForceComp, Mode, Model, Results } from "./types";
import type { Kind } from "./units";

export const UNITS: Record<ForceComp, string> = { N: "kN", Vy: "kN", Vz: "kN", T: "kN·m", My: "kN·m", Mz: "kN·m" };
export const COMP_KIND: Record<ForceComp, Kind> = { N: "force", Vy: "force", Vz: "force", T: "moment", My: "moment", Mz: "moment" };
export const COMP_LABEL: Record<ForceComp, string> = {
  N: "Axial force N", Vy: "Shear Vy (minor)", Vz: "Shear Vz (major)", T: "Torsion T", My: "Moment My (major)", Mz: "Moment Mz (minor)",
};

export function stressLimit(model: Model, results: Results, eid: string) {
  const mat = model.materials[results.elements[eid]?.material];
  if (mat?.kind === "steel") return model.settings.stress_limit_steel ?? 355000;
  return model.settings.stress_limit_concrete ?? 18000;
}

export interface Display {
  values: Record<string, number[]>; // per element per station (value used for colour)
  scale: Scale;
  res: CaseResult | null;
}

export function displayValues(mode: Mode, model: Model, results: Results | null, sel: string, comp: ForceComp, flows: FlowData | null, transform: "linear" | "sqrt" = "linear"): Display | null {
  const d = displayValuesInner(mode, model, results, sel, comp, flows);
  if (d) d.scale.transform = transform;
  return d;
}

function displayValuesInner(mode: Mode, model: Model, results: Results | null, sel: string, comp: ForceComp, flows: FlowData | null): Display | null {
  if (!results) return null;
  const res = combinedResult(model, results, sel);
  if (!res) return null;
  const values: Record<string, number[]> = {};
  let max = 0;
  if (mode === "loadpath" && flows) {
    for (const [eid, f] of Object.entries(flows.flow)) { values[eid] = f.map(Math.abs); }
    max = flows.maxThrough;
    return { values, res, scale: { min: 0, max, label: "Load carried along path |F·d|", unit: "kN", kind: "force", note: "From element internal forces (FEM)" } };
  }
  if (mode === "stress") {
    for (const [eid, st] of Object.entries(res.elements)) {
      const lim = stressLimit(model, results, eid);
      values[eid] = st.sigma_max.map((s, k) => Math.max(Math.abs(s), Math.abs(st.sigma_min[k])) / lim);
      max = Math.max(max, ...values[eid]);
    }
    return { values, res, scale: { min: 0, max: Math.max(1, max), label: "Stress ratio |σ|/σ_limit", unit: "–", limit: 1,
      note: "σ = N/A ± My/Sy ± Mz/Sz (elastic, extreme fibre). Limit is user-defined — not a code design check." } };
  }
  if (mode === "deformation") {
    for (const [eid, st] of Object.entries(res.elements)) {
      values[eid] = st.disp.map((d) => Math.hypot(d[0], d[1], d[2]));
      max = Math.max(max, ...values[eid]);
    }
    return { values, res, scale: { min: 0, max, label: "Global deformation |u|", unit: "mm", kind: "disp", note: "FEM nodal + exact curvature integration along members" } };
  }
  if (mode === "forces") {
    for (const [eid, st] of Object.entries(res.elements)) {
      values[eid] = st[comp].map(Math.abs);
      max = Math.max(max, ...values[eid]);
    }
    return { values, res, scale: { min: 0, max, label: `|${COMP_LABEL[comp]}|`, unit: UNITS[comp], kind: COMP_KIND[comp] } };
  }
  if (mode === "reactions") {
    return { values, res, scale: { min: 0, max: 0, label: "Soil pressure (rigid footing)", unit: "kN/m²", kind: "soil" } };
  }
  return { values, res, scale: { min: 0, max: 0, label: "", unit: "" } };
}

export const fmt = (v: number, d = 1) => (Math.abs(v) >= 1e5 ? v.toExponential(2) : v.toFixed(d));
