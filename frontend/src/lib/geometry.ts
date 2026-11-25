import type { Element, Model, Results, Vec3 } from "./types";

export function nodeMap(model: Model): Map<string, Vec3> {
  const m = new Map<string, Vec3>();
  for (const n of model.nodes) m.set(n.id, [n.x, n.y, n.z]);
  return m;
}

const sub = (a: Vec3, b: Vec3): Vec3 => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
const cross = (a: Vec3, b: Vec3): Vec3 => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const norm = (a: Vec3) => Math.hypot(a[0], a[1], a[2]);
const scale = (a: Vec3, s: number): Vec3 => [a[0] * s, a[1] * s, a[2] * s];
export const dot = (a: number[], b: number[]) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];

/** Same convention as backend solver.local_axes: rows = local x, y, z. */
export function localAxes(pi: Vec3, pj: Vec3, rollDeg = 0): { L: number; R: Vec3[] } {
  const v = sub(pj, pi);
  const L = norm(v);
  const ex = scale(v, 1 / L);
  const ref: Vec3 = Math.abs(ex[2]) > 0.999999 ? [1, 0, 0] : [0, 0, 1];
  let ey = cross(ref, ex);
  ey = scale(ey, 1 / norm(ey));
  let ez = cross(ex, ey);
  if (rollDeg) {
    const c = Math.cos((rollDeg * Math.PI) / 180), s = Math.sin((rollDeg * Math.PI) / 180);
    const ny: Vec3 = [c * ey[0] + s * ez[0], c * ey[1] + s * ez[1], c * ey[2] + s * ez[2]];
    const nz: Vec3 = [-s * ey[0] + c * ez[0], -s * ey[1] + c * ez[1], -s * ey[2] + c * ez[2]];
    ey = ny; ez = nz;
  }
  return { L, R: [ex, ey, ez] };
}

export function toGlobal(R: number[][], v: number[]): Vec3 {
  // R rows are local axes => global = R^T v
  return [
    R[0][0] * v[0] + R[1][0] * v[1] + R[2][0] * v[2],
    R[0][1] * v[0] + R[1][1] * v[1] + R[2][1] * v[2],
    R[0][2] * v[0] + R[1][2] * v[1] + R[2][2] * v[2],
  ];
}

export function sectionDims(model: Model, el: Element): { b: number; h: number; shape: string } {
  const s = model.sections[el.section];
  if (!s) return { b: 0.3, h: 0.3, shape: "rect" };
  if (s.shape === "rect") return { b: s.b!, h: s.h!, shape: "rect" };
  if (s.shape === "I") return { b: s.bf!, h: s.h!, shape: "I" };
  if (s.shape === "circle") return { b: s.d!, h: s.d!, shape: "circle" };
  if (s.shape === "pipe") return { b: s.d!, h: s.d!, shape: "circle" };
  if (s.shape === "box") return { b: s.b!, h: s.h!, shape: "rect" };
  if (s.shape === "channel" || s.shape === "lipchannel") return { b: s.b!, h: s.h!, shape: "rect" };
  if (s.shape === "angle") return { b: s.b!, h: s.b!, shape: "rect" };
  return { b: s.b ?? 0.3, h: s.h ?? 0.3, shape: "rect" };
}

export function modelBounds(model: Model) {
  const min: Vec3 = [Infinity, Infinity, Infinity], max: Vec3 = [-Infinity, -Infinity, -Infinity];
  for (const n of model.nodes) {
    const p = [n.x, n.y, n.z];
    for (let k = 0; k < 3; k++) { min[k] = Math.min(min[k], p[k]); max[k] = Math.max(max[k], p[k]); }
  }
  if (!isFinite(min[0])) return { min: [0, 0, 0] as Vec3, max: [10, 10, 10] as Vec3, center: [5, 5, 5] as Vec3, size: 10 };
  const center: Vec3 = [(min[0] + max[0]) / 2, (min[1] + max[1]) / 2, (min[2] + max[2]) / 2];
  return { min, max, center, size: Math.max(max[0] - min[0], max[1] - min[1], max[2] - min[2], 1) };
}

export function elementAxes(model: Model, results: Results | null, el: Element, nodes: Map<string, Vec3>) {
  const info = results?.elements[el.id];
  if (info) return { L: info.L, R: info.axes as Vec3[] };
  return localAxes(nodes.get(el.i)!, nodes.get(el.j)!, el.roll ?? 0);
}

/** Interpolate along a station array */
export function interp(xs: number[], ys: number[], x: number) {
  if (x <= xs[0]) return ys[0];
  for (let k = 1; k < xs.length; k++) {
    if (x <= xs[k]) {
      const t = (x - xs[k - 1]) / (xs[k] - xs[k - 1] || 1);
      return ys[k - 1] + t * (ys[k] - ys[k - 1]);
    }
  }
  return ys[ys.length - 1];
}

export const TRUSS_RELEASES: [number[], number[]] = [[0, 0, 0, 0, 1, 1], [0, 0, 0, 1, 1, 1]];
/** Released local DOFs at ends i and j (mirrors backend solver.element_releases). */
export function elementReleases(e: import("./types").Element): [number[], number[]] {
  if (e.releases) return [e.releases.i ?? [0, 0, 0, 0, 0, 0], e.releases.j ?? [0, 0, 0, 0, 0, 0]];
  if (e.truss || e.type === "truss") return TRUSS_RELEASES;
  return [[0, 0, 0, 0, 0, 0], [0, 0, 0, 0, 0, 0]];
}
/** True when bending moments are released at an end (a hinge). */
export const isHinged = (r: number[]) => !!(r[4] && r[5]);
