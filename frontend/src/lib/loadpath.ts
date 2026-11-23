/**
 * Load path from analysis results.
 *
 * Everything here is derived from the solver's element end forces and internal
 * forces — nothing is invented:
 *
 *  - d            : load-path direction (unit vector). Default: direction of the
 *                   resultant applied force of the selected case/combination
 *                   (gravity -> -Z).
 *  - flow(x)      : force component along d transmitted through the section at x
 *                   of a member, positive when it travels toward end j:
 *                   flow = -(R^T [N, Vy, Vz]) . d
 *  - t_end        : force the member exerts on its end node, projected on d:
 *                   t = -(R^T f_end) . d.   t > 0 => member delivers load to node,
 *                   t < 0 => node delivers load into member.
 *  - member load  : t_i + t_j = load applied directly on the member (exact member
 *                   equilibrium), e.g. slab tributary loads + self weight.
 *  - node balance : sum_t + P.d + S.d + R.d = 0 (exact node equilibrium), S = force
 *                   from slab/wall shell elements on the node (shell FEM).
 *  - panel input  : with shell slabs, the force each slab/wall delivers to a member
 *                   along its length (FEM nodal forces at the mesh nodes on the member).
 *
 * Path tracing (trace up / trace down from a selected element) attributes the
 * flows using the proportional-sharing rule at nodes and members. The node and
 * member transfers are exact; the split of a mixed flow among several outlets
 * is an attribution convention and is labelled as such in the UI.
 */
import { combinedResult, factorsFor } from "./combine";
import { dot, toGlobal } from "./geometry";
import type { CaseResult, Model, Results, Vec3 } from "./types";

export type PathDir = "auto" | "-Z" | "+X" | "-X" | "+Y" | "-Y";

export function pathDirection(model: Model, res: CaseResult, mode: PathDir): Vec3 {
  const fixed: Record<string, Vec3> = { "-Z": [0, 0, -1], "+X": [1, 0, 0], "-X": [-1, 0, 0], "+Y": [0, 1, 0], "-Y": [0, -1, 0] };
  if (mode !== "auto") return fixed[mode];
  const a = res.equilibrium.applied;
  // Prefer gravity when there is any vertical load: the classic vertical load path.
  if (Math.abs(a[2]) > 1e-6 * Math.hypot(a[0], a[1], a[2])) return a[2] < 0 ? [0, 0, -1] : [0, 0, 1];
  const n = Math.hypot(a[0], a[1], a[2]);
  if (n < 1e-12) return [0, 0, -1];
  return [a[0] / n, a[1] / n, a[2] / n];
}

export interface FlowData {
  d: Vec3;
  flow: Record<string, number[]>;       // per element, per station
  ti: Record<string, number>;           // transfer at end i
  tj: Record<string, number>;           // transfer at end j
  memberLoad: Record<string, number>;   // load applied directly on member, along d
  through: Record<string, number>;      // max |flow| along member (load carried)
  nodeApplied: Record<string, number>;  // P.d at nodes
  nodeGround: Record<string, number>;   // load delivered to support (-R.d)
  nodeShell: Record<string, number>;    // S.d: load delivered to a node by slab/wall shells (FEM)
  panelIn: Record<string, Record<string, number>>; // member -> panel -> load delivered along d (FEM)
  maxThrough: number;
}

export function computeFlows(model: Model, results: Results, sel: string, dirMode: PathDir): FlowData | null {
  const res = combinedResult(model, results, sel);
  if (!res) return null;
  const d = pathDirection(model, res, dirMode);
  const flow: Record<string, number[]> = {}, ti: Record<string, number> = {}, tj: Record<string, number> = {};
  const memberLoad: Record<string, number> = {}, through: Record<string, number> = {};
  let maxThrough = 0;
  for (const el of model.elements) {
    const st = res.elements[el.id];
    const info = results.elements[el.id];
    if (!st || !info) continue;
    const R = info.axes;
    flow[el.id] = st.x.map((_, k) => -dot(toGlobal(R, [st.N[k], st.Vy[k], st.Vz[k]]), d));
    ti[el.id] = -dot(toGlobal(R, st.end_i.slice(0, 3)), d);
    tj[el.id] = -dot(toGlobal(R, st.end_j.slice(0, 3)), d);
    memberLoad[el.id] = ti[el.id] + tj[el.id];
    through[el.id] = Math.max(...flow[el.id].map(Math.abs));
    maxThrough = Math.max(maxThrough, through[el.id]);
  }
  const nodeApplied: Record<string, number> = {};
  const f = factorsFor(model, sel);
  for (const l of results.nodal_loads) {
    if (!(l.case in f) || !l.node || !l.values) continue;
    nodeApplied[l.node] = (nodeApplied[l.node] ?? 0) + f[l.case] * dot(l.values, d);
  }
  const nodeGround: Record<string, number> = {};
  for (const [n, r] of Object.entries(res.reactions)) nodeGround[n] = -dot(r, d);
  const nodeShell: Record<string, number> = {};
  for (const [n, f] of Object.entries(res.shell_node_force ?? {})) nodeShell[n] = dot(f, d);
  const panelIn: Record<string, Record<string, number>> = {};
  for (const [eid, per] of Object.entries(res.panel_transfer ?? {})) {
    panelIn[eid] = {};
    for (const [g, f] of Object.entries(per)) panelIn[eid][g] = dot(f, d);
  }
  return { d, flow, ti, tj, memberLoad, through, nodeApplied, nodeGround, nodeShell, panelIn, maxThrough };
}

/** Incoming / outgoing loads of one element (for the inspector). */
export function elementTransfers(model: Model, fd: FlowData, eid: string) {
  const panels = Object.entries(fd.panelIn[eid] ?? {}).map(([g, v]) => ({ panel: g, value: v }));
  const el = model.elements.find((e) => e.id === eid)!;
  const incoming: { from: string; via: string; value: number; kind: string }[] = [];
  const outgoing: { to: string; via: string; value: number; kind: string }[] = [];
  const atNode = nodeIncidence(model);
  for (const [end, n] of [["i", el.i], ["j", el.j]] as const) {
    const t = end === "i" ? fd.ti[eid] : fd.tj[eid];
    if (t < 0) {
      // node delivers |t| into this member; attribute to node's inputs proportionally
      const inputs = nodeInputs(fd, atNode, n);
      const tot = inputs.reduce((s, x) => s + x.value, 0);
      for (const x of inputs) if (x.id !== eid) incoming.push({ from: x.id, via: n, value: tot > 0 ? (-t * x.value) / tot : 0, kind: x.kind });
    } else if (t > 0) {
      const outs = nodeOutputs(fd, atNode, n);
      const tot = outs.reduce((s, x) => s + x.value, 0);
      for (const x of outs) if (x.id !== eid) outgoing.push({ to: x.id, via: n, value: tot > 0 ? (t * x.value) / tot : 0, kind: x.kind });
    }
  }
  return { incoming, outgoing, memberLoad: fd.memberLoad[eid], panels };
}

export function nodeIncidence(model: Model) {
  const m = new Map<string, { eid: string; end: "i" | "j" }[]>();
  for (const e of model.elements) {
    for (const [end, n] of [["i", e.i], ["j", e.j]] as const) {
      if (!m.has(n)) m.set(n, []);
      m.get(n)!.push({ eid: e.id, end });
    }
  }
  return m;
}

type Port = { id: string; kind: "element" | "load" | "support" | "panel"; value: number; end?: "i" | "j" };

function nodeInputs(fd: FlowData, inc: Map<string, { eid: string; end: "i" | "j" }[]>, n: string): Port[] {
  const out: Port[] = [];
  for (const { eid, end } of inc.get(n) ?? []) {
    const t = end === "i" ? fd.ti[eid] : fd.tj[eid];
    if (t > 1e-9) out.push({ id: eid, kind: "element", value: t, end });
  }
  const p = fd.nodeApplied[n] ?? 0;
  if (p > 1e-9) out.push({ id: `load@${n}`, kind: "load", value: p });
  const sh = fd.nodeShell[n] ?? 0;
  if (sh > 1e-9) out.push({ id: `shells@${n}`, kind: "panel", value: sh });
  const g = fd.nodeGround[n] ?? 0;
  if (g < -1e-9) out.push({ id: `support@${n}`, kind: "support", value: -g });
  return out;
}

function nodeOutputs(fd: FlowData, inc: Map<string, { eid: string; end: "i" | "j" }[]>, n: string): Port[] {
  const out: Port[] = [];
  for (const { eid, end } of inc.get(n) ?? []) {
    const t = end === "i" ? fd.ti[eid] : fd.tj[eid];
    if (t < -1e-9) out.push({ id: eid, kind: "element", value: -t, end });
  }
  const g = fd.nodeGround[n] ?? 0;
  if (g > 1e-9) out.push({ id: `support@${n}`, kind: "support", value: g });
  const p = fd.nodeApplied[n] ?? 0;
  if (p < -1e-9) out.push({ id: `load@${n}`, kind: "load", value: -p });
  const sh = fd.nodeShell[n] ?? 0;
  if (sh < -1e-9) out.push({ id: `shells@${n}`, kind: "panel", value: -sh });
  return out;
}

export interface TraceResult {
  direction: "down" | "up";
  start: string;
  total: number;
  elements: Record<string, number>;   // kN of the traced load passing through each element
  supports: Record<string, number>;   // kN reaching each support (down) / applied at node (up)
  sources: Record<string, number>;    // (up) kN originating as load applied directly on each element
}

/** Proportional-sharing trace of the load leaving (down) or entering (up) an element. */
export function trace(model: Model, fd: FlowData, start: string, direction: "down" | "up"): TraceResult {
  const inc = nodeIncidence(model);
  const el = new Map(model.elements.map((e) => [e.id, e]));
  const res: TraceResult = { direction, start, total: 0, elements: {}, supports: {}, sources: {} };
  const outEnds = (eid: string) => {
    const e = el.get(eid)!;
    const r: { n: string; v: number }[] = [];
    if (fd.ti[eid] > 1e-9) r.push({ n: e.i, v: fd.ti[eid] });
    if (fd.tj[eid] > 1e-9) r.push({ n: e.j, v: fd.tj[eid] });
    return r;
  };
  const inEnds = (eid: string) => {
    const e = el.get(eid)!;
    const r: { n: string; v: number }[] = [];
    if (fd.ti[eid] < -1e-9) r.push({ n: e.i, v: -fd.ti[eid] });
    if (fd.tj[eid] < -1e-9) r.push({ n: e.j, v: -fd.tj[eid] });
    return r;
  };
  const total = outEnds(start).reduce((s, x) => s + x.v, 0);
  res.total = total;
  if (total <= 1e-9) return res;
  const eps = 1e-5 * total;
  // worklist of pending amounts on elements
  const pending = new Map<string, number>([[start, total]]);
  let guard = 0;
  while (pending.size && guard++ < 200000) {
    const [eid, amt] = pending.entries().next().value as [string, number];
    pending.delete(eid);
    res.elements[eid] = (res.elements[eid] ?? 0) + amt;
    if (direction === "down") {
      const outs = outEnds(eid);
      const tot = outs.reduce((s, x) => s + x.v, 0);
      for (const { n, v } of outs) {
        const a = (amt * v) / tot;
        const ports = nodeOutputs(fd, inc, n);
        const pt = ports.reduce((s, x) => s + x.value, 0);
        for (const p of ports) {
          const b = (a * p.value) / pt;
          if (b < eps) continue;
          if (p.kind === "element") pending.set(p.id, (pending.get(p.id) ?? 0) + b);
          else res.supports[p.id] = (res.supports[p.id] ?? 0) + b;
        }
      }
    } else {
      const ins = inEnds(eid);
      const own = Math.max(0, fd.memberLoad[eid]);
      const tot = ins.reduce((s, x) => s + x.v, 0) + own;
      if (tot <= 0) continue;
      if (own > 0) res.sources[eid] = (res.sources[eid] ?? 0) + (amt * own) / tot;
      for (const { n, v } of ins) {
        const a = (amt * v) / tot;
        const ports = nodeInputs(fd, inc, n);
        const pt = ports.reduce((s, x) => s + x.value, 0);
        for (const p of ports) {
          const b = (a * p.value) / pt;
          if (b < eps) continue;
          if (p.kind === "element") pending.set(p.id, (pending.get(p.id) ?? 0) + b);
          else res.supports[p.id] = (res.supports[p.id] ?? 0) + b;
        }
      }
    }
  }
  return res;
}

/** Split a station flow array into directed segments for particle animation. */
export function flowSegments(xs: number[], flow: number[], L: number) {
  const segs: { s0: number; s1: number; dir: 1 | -1; mag: number }[] = [];
  let k0 = 0;
  const sign = (v: number) => (v > 0 ? 1 : v < 0 ? -1 : 0);
  const cut: number[] = [0];
  for (let k = 1; k < xs.length; k++) {
    if (sign(flow[k]) !== sign(flow[k - 1]) && sign(flow[k]) !== 0 && sign(flow[k - 1]) !== 0) {
      const t = flow[k - 1] / (flow[k - 1] - flow[k]);
      cut.push(xs[k - 1] + t * (xs[k] - xs[k - 1]));
    }
  }
  cut.push(L);
  for (let c = 0; c < cut.length - 1; c++) {
    const a = cut[c], b = cut[c + 1];
    if (b - a < 1e-6) continue;
    // average flow on [a, b]
    let sum = 0, n = 0;
    for (let k = k0; k < xs.length; k++) if (xs[k] >= a - 1e-9 && xs[k] <= b + 1e-9) { sum += flow[k]; n++; }
    const mid = (a + b) / 2;
    let m = 0;
    for (let k = 1; k < xs.length; k++) if (mid <= xs[k]) { const t = (mid - xs[k - 1]) / (xs[k] - xs[k - 1] || 1); m = flow[k - 1] + t * (flow[k] - flow[k - 1]); break; }
    const avg = n ? sum / n : m;
    const dir = (m !== 0 ? sign(m) : sign(avg)) as 1 | -1 | 0;
    if (dir === 0) continue;
    segs.push({ s0: a / L, s1: b / L, dir, mag: Math.abs(avg) });
  }
  return segs;
}
