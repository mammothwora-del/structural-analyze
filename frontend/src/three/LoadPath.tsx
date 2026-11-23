import { useFrame } from "@react-three/fiber";
import { useLayoutEffect, useMemo, useRef } from "react";
import * as THREE from "three";
import { colorAt } from "../lib/colormap";
import { factorsFor } from "../lib/combine";
import { fmt } from "../lib/display";
import { modelBounds } from "../lib/geometry";
import { flowSegments, type FlowData, type TraceResult } from "../lib/loadpath";
import type { CaseResult, Model, Results } from "../lib/types";
import { useStore, useU } from "../store";
import { Arrows, type ArrowSpec } from "./Arrows";
import { Label } from "./Overlays";
import { usePositions, useVisibleElements } from "./Members";

interface Particle { a: THREE.Vector3; b: THREE.Vector3; u: number; speed: number; color: THREE.Color }

/**
 * Animated particles moving along each member in the direction the load
 * actually travels (sign of the internal force component along d), with density
 * proportional to its magnitude. Splits at zero-flow points (e.g. the zero-shear
 * point of a beam), exactly where the computed load divides between the supports.
 */
export function FlowParticles({ model, results, flows, trace }: { model: Model; results: Results; flows: FlowData; trace: TraceResult | null }) {
  const elements = useVisibleElements(model);
  const pos = usePositions(model);
  const res = useStore((s) => s.loadSel);
  const animate = useStore((s) => s.animate);
  const tf = useStore((s) => s.colorTransform);
  const size = modelBounds(model).size;
  const mesh = useRef<THREE.InstancedMesh>(null!);
  const { particles, arrows } = useMemo(() => {
    const parts: Particle[] = [];
    const arrows: ArrowSpec[] = [];
    const max = flows.maxThrough || 1;
    const traced = trace ? trace.elements : null;
    const tmax = trace ? Math.max(...Object.values(trace.elements)) : 1;
    for (const el of elements) {
      const f = flows.flow[el.id];
      const st = results.cases[Object.keys(results.cases)[0]]?.elements[el.id];
      if (!f || !st) continue;
      if (traced && !traced[el.id]) continue;
      const L = results.elements[el.id].L;
      const pi = new THREE.Vector3(...pos.get(el.i)!), pj = new THREE.Vector3(...pos.get(el.j)!);
      const scaleF = traced ? traced[el.id] / Math.max(flows.through[el.id], 1e-9) : 1;
      for (const sg of flowSegments(st.x, f, L)) {
        const mag = sg.mag * scaleF;
        const rel = mag / (traced ? tmax : max);
        if (rel < 0.01) continue;
        const a = pi.clone().lerp(pj, sg.dir > 0 ? sg.s0 : sg.s1);
        const b = pi.clone().lerp(pj, sg.dir > 0 ? sg.s1 : sg.s0);
        const segLen = a.distanceTo(b);
        const n = Math.max(1, Math.round((1 + 9 * Math.sqrt(rel)) * segLen / 2));
        const color = colorAt(tf === "sqrt" ? Math.sqrt(rel) : rel);
        for (let k = 0; k < n; k++) parts.push({ a, b, u: k / n, speed: (0.6 + 1.4 * Math.sqrt(rel)) / Math.max(segLen, 0.3), color });
        if (segLen > 0.8) {
          const dir = b.clone().sub(a).normalize();
          arrows.push({ tip: a.clone().lerp(b, 0.62), dir, length: Math.min(0.9, segLen * 0.3), color, radius: 0.045 + 0.06 * Math.sqrt(rel) });
        }
      }
    }
    return { particles: parts.slice(0, 12000), arrows };
  }, [elements, pos, flows, results, trace, res, size, tf]);

  const place = () => {
    const m = new THREE.Matrix4(), p = new THREE.Vector3();
    particles.forEach((q, k) => {
      p.copy(q.a).lerp(q.b, q.u);
      m.makeTranslation(p.x, p.y, p.z);
      mesh.current.setMatrixAt(k, m);
    });
    mesh.current.instanceMatrix.needsUpdate = true;
  };
  useLayoutEffect(() => {
    if (!particles.length) return;
    particles.forEach((q, k) => mesh.current.setColorAt(k, q.color));
    if (mesh.current.instanceColor) mesh.current.instanceColor.needsUpdate = true;
    place();
  });
  useFrame((_, dt) => {
    if (!animate || !particles.length) return;
    const d = Math.min(dt, 0.05);
    for (const q of particles) { q.u += q.speed * d; if (q.u > 1) q.u -= 1; }
    place();
  });
  return (
    <group>
      {particles.length > 0 && (
        <instancedMesh key={particles.length} ref={mesh} args={[undefined, undefined, particles.length]} frustumCulled={false}>
          <sphereGeometry args={[0.11, 8, 6]} />
          <meshBasicMaterial toneMapped={false} />
        </instancedMesh>
      )}
      <Arrows arrows={arrows} />
    </group>
  );
}

/** Slab tributary areas (Phase 1 assumption) with arrows toward the receiving beams. */
export function TributaryPanels({ model, results, highlightSlab }: { model: Model; results: Results; highlightSlab?: string | null }) {
  const u = useU();
  const { loadSel, maxLevel, hiddenTypes, showLabels } = useStore();
  const exploded = useStore((s) => s.exploded);
  const factors = factorsFor(model, loadSel);
  const { geo, arrows, labels } = useMemo(() => {
    // total q on each slab for this selection (area loads + slab self weight)
    const q: Record<string, number> = {};
    for (const l of model.loads) {
      if (l.kind !== "area" || !(l.case in factors)) continue;
      for (const s of l.slabs ?? (l.slab ? [l.slab] : [])) q[s] = (q[s] ?? 0) + factors[l.case] * (l.q ?? 0);
    }
    const swCase = model.load_cases.find((c) => c.self_weight && c.id in factors);
    if (swCase) for (const s of model.slabs) q[s.id] = (q[s.id] ?? 0) + factors[swCase.id] * s.thickness * (s.density ?? 25);
    const loads: number[] = [];
    for (const s of model.slabs) {
      const t = results.tributary[s.id];
      if (!t) continue;
      for (const e of t.edges) loads.push(Math.abs((q[s.id] ?? 0) * e.tributary_area));
    }
    const lmax = Math.max(1e-9, ...loads);
    const P: number[] = [], C: number[] = [];
    const arrows: ArrowSpec[] = [];
    const labels: { p: THREE.Vector3; text: string }[] = [];
    const col = new THREE.Color();
    for (const s of model.slabs) {
      if (maxLevel !== null && (s.level ?? 0) > maxLevel) continue;
      const t = results.tributary[s.id];
      if (!t) continue;
      const dz = (s.level ?? 0) * exploded + 0.02;
      for (const e of t.edges) {
        const load = (q[s.id] ?? 0) * e.tributary_area;
        if (e.tributary_area < 1e-9) continue;
        // neutral amber tint: lighter = larger share (assumed distribution, not a FEM result)
        col.set("#5a4326").lerp(new THREE.Color("#f0a14a"), 0.25 + 0.75 * Math.abs(load) / lmax);
        if (highlightSlab && highlightSlab !== s.id) col.lerp(new THREE.Color("#1b2430"), 0.75);
        const poly = e.polygon.map((p) => new THREE.Vector3(p[0], p[1], p[2] + dz));
        // fan triangulation (polygons are convex)
        const shrinkC = poly.reduce((a, b) => a.add(b), new THREE.Vector3()).divideScalar(poly.length);
        const pp = poly.map((p) => p.clone().lerp(shrinkC, 0.06));
        for (let k = 1; k < pp.length - 1; k++) {
          for (const v of [pp[0], pp[k], pp[k + 1]]) { P.push(v.x, v.y, v.z); C.push(col.r, col.g, col.b); }
        }
        // arrow from centroid toward edge midpoint
        const a = new THREE.Vector3(...e.polygon[0]), b = new THREE.Vector3(...e.polygon[1]);
        const mid = a.clone().lerp(b, 0.5).setZ(a.z + dz + 0.05);
        const dir = mid.clone().sub(shrinkC.clone().setZ(mid.z));
        const dist = dir.length();
        if (dist > 1e-6) arrows.push({ tip: mid.clone().addScaledVector(dir.normalize(), -0.25), dir, length: Math.max(0.4, dist * 0.55), color: col.clone(), radius: 0.05 });
        if (showLabels && highlightSlab === s.id) labels.push({ p: shrinkC, text: `${u.w("force", load)} (${(e.fraction * 100).toFixed(0)}%)` });
      }
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.Float32BufferAttribute(P, 3));
    g.setAttribute("color", new THREE.Float32BufferAttribute(C, 3));
    g.computeVertexNormals();
    return { geo: g, arrows, labels };
  }, [model, results, factors, maxLevel, exploded, highlightSlab, showLabels]);
  if (hiddenTypes.slab) return null;
  return (
    <group>
      <mesh geometry={geo}><meshBasicMaterial vertexColors transparent opacity={0.3} side={THREE.DoubleSide} depthWrite={false} /></mesh>
      <Arrows arrows={arrows} opacity={0.9} />
      {labels.map((l, k) => <Label key={k} p={l.p} color="#ffd9a0">{l.text}</Label>)}
    </group>
  );
}

/** Numeric labels for the load path: traced elements, or top members, and supports. */
export function PathLabels({ model, results, flows, trace, res }: { model: Model; results: Results; flows: FlowData; trace: TraceResult | null; res: CaseResult }) {
  const u = useU();
  const pos = usePositions(model);
  const elements = useVisibleElements(model);
  const items = useMemo(() => {
    const out: { p: THREE.Vector3; text: string; color: string }[] = [];
    const vis = new Set(elements.map((e) => e.id));
    const vals = trace ? Object.entries(trace.elements) : Object.entries(flows.through).filter(([id]) => model.elements.find((e) => e.id === id)?.type === "column");
    vals.filter(([id]) => vis.has(id)).sort((a, b) => b[1] - a[1]).slice(0, 60).forEach(([id, v]) => {
      const el = model.elements.find((e) => e.id === id)!;
      const p = new THREE.Vector3(...pos.get(el.i)!).lerp(new THREE.Vector3(...pos.get(el.j)!), 0.5);
      out.push({ p, text: `${id} ${u.w("force", v)}`, color: "#e6edf5" });
    });
    const sup = trace ? trace.supports : Object.fromEntries(Object.entries(flows.nodeGround).map(([n, v]) => [`support@${n}`, v]));
    for (const [k, v] of Object.entries(sup)) {
      if (!k.startsWith("support@")) continue;
      const n = k.slice(8);
      const s = model.supports.find((x) => x.node === n);
      const p = new THREE.Vector3(...pos.get(n)!).add(new THREE.Vector3(0, 0, -(s?.footing?.t ?? 0) - 0.9));
      out.push({ p, text: `R ${u.w("force", v)}`, color: "#7ef0b0" });
    }
    return out;
  }, [model, flows, trace, pos, elements, res]);
  return <group>{items.map((l, k) => <Label key={k} p={l.p} color={l.color}>{l.text}</Label>)}</group>;
}
