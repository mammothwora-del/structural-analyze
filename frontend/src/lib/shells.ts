/**
 * Shell (slab / wall) results helpers. All values come from the shell FEM
 * (nodal-averaged resultants per panel, local panel axes, SI units).
 */
import type { Scale } from "./colormap";
import type { CaseResult, Model, Results, Vec3 } from "./types";
import type { Kind } from "./units";

export type ShellComp = "vm" | "Mx" | "My" | "Mxy" | "Nx" | "Ny" | "Nxy" | "Qx" | "Qy";
export const SHELL_COMPS: ShellComp[] = ["vm", "Mx", "My", "Mxy", "Nx", "Ny", "Nxy", "Qx", "Qy"];
export const SHELL_LABEL: Record<ShellComp, string> = {
  vm: "von Mises stress σv (max of top/bottom)", Mx: "Moment mx (bottom tension +)", My: "Moment my (bottom tension +)", Mxy: "Twisting moment mxy",
  Nx: "Membrane force nx (tension +)", Ny: "Membrane force ny (tension +)", Nxy: "Membrane shear nxy", Qx: "Transverse shear vx", Qy: "Transverse shear vy",
};
export const SHELL_KIND: Record<ShellComp, Kind> = {
  vm: "stress", Mx: "momentPerLen", My: "momentPerLen", Mxy: "momentPerLen", Nx: "forcePerLen", Ny: "forcePerLen", Nxy: "forcePerLen", Qx: "forcePerLen", Qy: "forcePerLen",
};
const IDX: Record<Exclude<ShellComp, "vm">, number> = { Nx: 0, Ny: 1, Nxy: 2, Mx: 3, My: 4, Mxy: 5, Qx: 6, Qy: 7 };

/** Surface stresses (kN/m²) at top (z+) and bottom (z-) from resultants r and thickness t. */
export function surfaceStress(r: number[], t: number) {
  const out = [];
  for (const side of [1, -1]) {        // +1: bottom (M positive = bottom tension), -1: top
    const sx = r[0] / t + side * 6 * r[3] / (t * t);
    const sy = r[1] / t + side * 6 * r[4] / (t * t);
    const txy = r[2] / t + side * 6 * r[5] / (t * t);
    out.push({ sx, sy, txy, vm: Math.sqrt(sx * sx - sx * sy + sy * sy + 3 * txy * txy) });
  }
  return { bottom: out[0], top: out[1] };
}

/** Value of a component at every node of a panel (vm in MPa, others SI kN, m). */
export function panelValues(res: CaseResult, results: Results, g: string, comp: ShellComp): number[] {
  const rows = res.panel_results?.[g];
  const info = results.mesh?.groups[g];
  if (!rows || !info) return [];
  if (comp === "vm") return rows.map((r) => { const s = surfaceStress(r, info.t); return Math.max(s.top.vm, s.bottom.vm) / 1000; });
  return rows.map((r) => r[IDX[comp]]);
}

export function shellScale(res: CaseResult, results: Results, comp: ShellComp, groups?: string[]): Scale {
  let lo = 0, hi = 0;
  for (const g of groups ?? Object.keys(results.mesh?.groups ?? {})) {
    for (const v of panelValues(res, results, g, comp)) { lo = Math.min(lo, v); hi = Math.max(hi, v); }
  }
  const signed = comp !== "vm";
  if (signed) { const m = Math.max(-lo, hi); lo = -m; hi = m; }
  return { min: lo, max: hi, signed, label: SHELL_LABEL[comp], unit: "", kind: SHELL_KIND[comp], transform: "linear",
    note: "Shell FEM (MITC4), nodal-averaged per panel, local panel axes" };
}

/** Load flux in a panel (kN/m, global vector) for load travelling along d:
 *  phi = -(dx [Nx, Nxy] + dy [Nxy, Ny] + dz [Qx, Qy]) in local axes (traction on a cut, projected on d). */
export function panelFlux(r: number[], axes: number[][], d: Vec3): Vec3 {
  const dl = axes.map((a) => a[0] * d[0] + a[1] * d[1] + a[2] * d[2]);
  const fx = -(dl[0] * r[0] + dl[1] * r[2] + dl[2] * r[6]);
  const fy = -(dl[0] * r[2] + dl[1] * r[1] + dl[2] * r[7]);
  const [ex, ey] = axes;
  return [fx * ex[0] + fy * ey[0], fx * ex[1] + fy * ey[1], fx * ex[2] + fy * ey[2]];
}

/** Positions of all nodes, including shell mesh nodes; exploded offset interpolated between levels. */
export function allPositions(model: Model, results: Results | null, exploded: number) {
  const m = new Map<string, Vec3>();
  for (const n of model.nodes) m.set(n.id, [n.x, n.y, n.z + (n.level ?? 0) * exploded]);
  const mesh = results?.mesh;
  if (mesh) {
    const lv = (model.grid?.levels ?? []).map((l) => l.z);
    const off = (z: number) => {
      if (!exploded || lv.length < 2) return 0;
      for (let k = 0; k < lv.length - 1; k++) if (z <= lv[k + 1] + 1e-9) return exploded * (k + (z - lv[k]) / (lv[k + 1] - lv[k] || 1));
      return exploded * (lv.length - 1);
    };
    for (const [id, p] of Object.entries(mesh.nodes)) m.set(id, [p[0], p[1], p[2] + off(p[2])]);
  }
  return m;
}

/** Level of a panel (for section cut). */
export function panelLevel(model: Model, g: string) {
  return model.slabs.find((s) => s.id === g)?.level ?? model.walls?.find((w) => w.id === g)?.level ?? 0;
}
