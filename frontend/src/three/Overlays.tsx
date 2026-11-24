import { Html, Line } from "@react-three/drei";
import { useMemo } from "react";
import * as THREE from "three";
import { colorAt } from "../lib/colormap";
import { factorsFor } from "../lib/combine";
import { fmt } from "../lib/display";
import { footingPressure } from "../lib/footing";
import { modelBounds } from "../lib/geometry";
import type { CaseResult, Model, Results, Vec3 } from "../lib/types";
import { useStore, useU } from "../store";
import { Arrows, type ArrowSpec } from "./Arrows";
import { usePositions } from "./Members";

const V = (p: number[]) => new THREE.Vector3(p[0], p[1], p[2]);

export function Label({ p, children, color = "#d3dce6", bg = "rgba(11,15,20,0.78)" }: { p: THREE.Vector3 | Vec3; children: React.ReactNode; color?: string; bg?: string }) {
  const pos = p instanceof THREE.Vector3 ? p : V(p);
  return (
    <Html position={pos} center zIndexRange={[10, 0]} style={{ pointerEvents: "none" }}>
      <div style={{ color, background: bg, padding: "1px 5px", borderRadius: 3, fontSize: 10.5, fontFamily: "JetBrains Mono, monospace", whiteSpace: "nowrap", border: "1px solid rgba(127,147,171,0.25)" }}>{children}</div>
    </Html>
  );
}

export function Slabs({ model, opacity = 0.28, color = "#8fa3b8" }: { model: Model; opacity?: number; color?: string }) {
  const pos = usePositions(model);
  const { hiddenTypes, maxLevel, selection, set } = useStore();
  const geo = useMemo(() => {
    const P: number[] = [];
    const owners: string[] = [];
    for (const s of model.slabs) {
      if (maxLevel !== null && (s.level ?? 0) > maxLevel) continue;
      const c = s.corners.map((n) => pos.get(n)!);
      if (c.some((x) => !x)) continue;
      for (const [a, b, d] of [[0, 1, 2], [0, 2, 3]]) { P.push(...c[a], ...c[b], ...c[d]); owners.push(s.id); }
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.Float32BufferAttribute(P, 3));
    g.computeVertexNormals();
    return { g, owners };
  }, [model, pos, maxLevel]);
  if (hiddenTypes.slab) return null;
  const selSlab = selection?.kind === "slab" ? model.slabs.find((s) => s.id === selection.id) : null;
  return (
    <group>
      <mesh geometry={geo.g} renderOrder={1} onClick={(e) => { e.stopPropagation(); const id = geo.owners[e.faceIndex ?? -1]; if (id) set({ selection: { kind: "slab", id }, multi: [] }); }}>
        <meshStandardMaterial color={color} transparent opacity={opacity} side={THREE.DoubleSide} depthWrite={false} />
      </mesh>
      {selSlab && <Line points={[...selSlab.corners, selSlab.corners[0]].map((n) => pos.get(n)!)} color="#3fb6ff" lineWidth={3} />}
    </group>
  );
}

export function Footings({ model, results, res, colorBy }: { model: Model; results: Results | null; res: CaseResult | null; colorBy?: "pressure" }) {
  const pos = usePositions(model);
  const hidden = useStore((s) => s.hiddenTypes.footing);
  const sel = useStore((s) => s.loadSel);
  const qa = model.settings.allowable_bearing || 250;
  if (hidden) return null;
  const dlFactor = factorsFor(model, sel)["DL"] ?? 0;
  return (
    <group>
      {model.supports.map((s) => {
        const p = pos.get(s.node);
        if (!p || s.lateral) return null;
        const f = s.footing;
        const fixed = (s.type ?? "fixed") === "fixed";
        let color = "#6b7a8c";
        if (colorBy === "pressure" && res && f && res.reactions[s.node]) {
          const fp = footingPressure(res.reactions[s.node], f, 25 * f.B * f.L * f.t * dlFactor);
          color = "#" + colorAt(fp.qmax / qa).getHexString();
        }
        return (
          <group key={s.node} position={p}>
            {f && (
              <mesh position={[0, 0, -f.t / 2]}>
                <boxGeometry args={[f.B, f.L, f.t]} />
                <meshStandardMaterial color={color} roughness={0.8} transparent opacity={colorBy ? 0.95 : 0.85} />
              </mesh>
            )}
            <mesh position={[0, 0, -(f?.t ?? 0) - 0.12]} rotation={[Math.PI / 2, 0, 0]}>
              {fixed ? <boxGeometry args={[0.35, 0.12, 0.35]} /> : <coneGeometry args={[0.22, 0.3, 4]} />}
              <meshStandardMaterial color="#29d17a" emissive="#0c4d2b" />
            </mesh>
          </group>
        );
      })}
    </group>
  );
}

export function NodesLayer({ model }: { model: Model }) {
  const pos = usePositions(model);
  const { selection, set, maxLevel, multi } = useStore();
  const pts = useMemo(() => model.nodes.filter((n) => maxLevel === null || (n.level ?? 0) <= maxLevel), [model, maxLevel]);
  const selNodes = new Set([...(selection?.kind === "node" ? [selection.id] : []), ...multi]);
  return (
    <group>
      {pts.map((n) => (
        <mesh key={n.id} position={pos.get(n.id)!} onClick={(e) => {
          e.stopPropagation();
          if (e.nativeEvent.shiftKey || e.nativeEvent.ctrlKey) {
            const m = useStore.getState().multi;
            set({ multi: m.includes(n.id) ? m.filter((x) => x !== n.id) : [...m, n.id] });
          } else set({ selection: { kind: "node", id: n.id }, multi: [] });
        }}>
          <sphereGeometry args={[selNodes.has(n.id) ? 0.16 : 0.09, 10, 8]} />
          <meshBasicMaterial color={selNodes.has(n.id) ? "#3fb6ff" : "#c8d3df"} />
        </mesh>
      ))}
    </group>
  );
}

export function GridLines({ model }: { model: Model }) {
  if (!model.grid) return null;
  const b = modelBounds(model);
  const ext = 1.5;
  const { x, y } = model.grid;
  const x0 = x[0].pos - ext, x1 = x[x.length - 1].pos + ext, y0 = y[0].pos - ext, y1 = y[y.length - 1].pos + ext;
  const z = b.min[2] - 0.02;
  return (
    <group>
      {x.map((g) => (
        <group key={"x" + g.name}>
          <Line points={[[g.pos, y0, z], [g.pos, y1, z]]} color="#3d5168" lineWidth={1} dashed dashSize={0.4} gapSize={0.25} />
          <Label p={[g.pos, y0 - 0.6, z]} color="#9fc3e6">{g.name}</Label>
        </group>
      ))}
      {y.map((g) => (
        <group key={"y" + g.name}>
          <Line points={[[x0, g.pos, z], [x1, g.pos, z]]} color="#3d5168" lineWidth={1} dashed dashSize={0.4} gapSize={0.25} />
          <Label p={[x0 - 0.6, g.pos, z]} color="#9fc3e6">{g.name}</Label>
        </group>
      ))}
    </group>
  );
}

/** Applied loads of the selected case/combination (factored). */
export function LoadsLayer({ model, results }: { model: Model; results: Results | null }) {
  const u = useU();
  const pos = usePositions(model);
  const { loadSel, animate, showLabels, maxLevel } = useStore();
  const factors = factorsFor(model, loadSel);
  const size = modelBounds(model).size;
  const data = useMemo(() => {
    const arrows: ArrowSpec[] = [];
    const labels: { p: THREE.Vector3; text: string; color: string }[] = [];
    const slabColor = new THREE.Color("#ff9d3b"), nodalColor = new THREE.Color("#ff4d6d"), memberColor = new THREE.Color("#ffd166");
    // area loads: arrow grid on slabs
    const slabQ: Record<string, number> = {};
    for (const l of model.loads) {
      if (l.kind !== "area" || !(l.case in factors)) continue;
      for (const s of l.slabs ?? (l.slab ? [l.slab] : [])) slabQ[s] = (slabQ[s] ?? 0) + factors[l.case] * (l.q ?? 0);
    }
    const sw = model.load_cases.find((c) => c.self_weight && c.id in factors);
    if (sw) for (const s of model.slabs) slabQ[s.id] = (slabQ[s.id] ?? 0) + factors[sw.id] * s.thickness * (s.density ?? 25);
    const qmax = Math.max(1e-9, ...Object.values(slabQ).map(Math.abs));
    for (const s of model.slabs) {
      if (maxLevel !== null && (s.level ?? 0) > maxLevel) continue;
      const q = slabQ[s.id];
      if (!q) continue;
      const c = s.corners.map((n) => V(pos.get(n)!));
      const L = (0.06 + 0.06 * Math.abs(q) / qmax) * size * 0.35;
      for (const u of [0.25, 0.75]) for (const v of [0.25, 0.75]) {
        const p = c[0].clone().lerp(c[1], u).lerp(c[3].clone().lerp(c[2], u), v);
        arrows.push({ tip: p.clone().add(new THREE.Vector3(0, 0, 0.05)), dir: new THREE.Vector3(0, 0, Math.sign(-q) || -1), length: L, color: slabColor, radius: 0.035 });
      }
      if (showLabels) labels.push({ p: c[0].clone().lerp(c[2], 0.5).add(new THREE.Vector3(0, 0, L + 0.3)), text: u.w("areaLoad", q), color: "#ffb870" });
    }
    // nodal loads
    const nl = model.loads.filter((l) => l.kind === "nodal" && l.case in factors);
    const fmax = Math.max(1e-9, ...nl.map((l) => Math.hypot(...(l.values ?? [0, 0, 0]).slice(0, 3)) * Math.abs(factors[l.case])));
    for (const l of nl) {
      const F = V((l.values ?? [0, 0, 0]).slice(0, 3)).multiplyScalar(factors[l.case]);
      const m = F.length();
      if (m < 1e-9 || !pos.get(l.node!)) continue;
      const lev = model.nodes.find((n) => n.id === l.node)?.level ?? 0;
      if (maxLevel !== null && lev > maxLevel) continue;
      const len = (0.05 + 0.1 * m / fmax) * size;
      arrows.push({ tip: V(pos.get(l.node!)!), dir: F.clone().normalize(), length: len, color: nodalColor, radius: 0.06 });
      if (showLabels) labels.push({ p: V(pos.get(l.node!)!).addScaledVector(F.clone().normalize(), -len - 0.3), text: u.w("force", m), color: "#ff8fa3" });
    }
    // user member loads (dist/point)
    for (const l of model.loads) {
      if ((l.kind !== "dist" && l.kind !== "point") || !(l.case in factors)) continue;
      const el = model.elements.find((e) => e.id === l.element);
      if (!el) continue;
      const a = V(pos.get(el.i)!), b = V(pos.get(el.j)!);
      const dir = V(l.direction ?? [0, 0, -1]).normalize();
      const f = factors[l.case];
      if (l.kind === "point") {
        const Lm = a.distanceTo(b);
        arrows.push({ tip: a.clone().lerp(b, (l.a ?? 0) / Lm), dir: dir.clone().multiplyScalar(Math.sign(f * (l.P ?? 0)) || 1), length: 0.12 * size, color: nodalColor, radius: 0.06 });
      } else {
        const w = (l.points ?? []).map((p) => p[1] * f);
        for (let k = 0; k <= 6; k++) {
          const t = k / 6;
          arrows.push({ tip: a.clone().lerp(b, t), dir: dir.clone().multiplyScalar(Math.sign(w[0] || 1)), length: 0.06 * size, color: memberColor, radius: 0.03 });
        }
        if (showLabels) labels.push({ p: a.clone().lerp(b, 0.5).addScaledVector(dir, -0.08 * size), text: u.w("lineLoad", w[0]), color: "#ffe08a" });
      }
    }
    return { arrows, labels, sw: !!sw };
  }, [model, pos, factors, size, showLabels, maxLevel, u.sys]);
  return (
    <group>
      <Arrows arrows={data.arrows} pulse={animate} />
      {data.labels.slice(0, 120).map((l, k) => <Label key={k} p={l.p} color={l.color}>{l.text}</Label>)}
    </group>
  );
}

/** Support reactions as arrows (force from support on structure). */
export function ReactionsLayer({ model, res, labels }: { model: Model; res: CaseResult; labels: boolean }) {
  const u = useU();
  const pos = usePositions(model);
  const size = modelBounds(model).size;
  const arrows: ArrowSpec[] = [];
  const lab: { p: THREE.Vector3; text: string }[] = [];
  const rmax = Math.max(1e-9, ...Object.values(res.reactions).map((r) => Math.hypot(r[0], r[1], r[2])));
  for (const [n, r] of Object.entries(res.reactions)) {
    const F = V(r.slice(0, 3));
    const m = F.length();
    if (m < 1e-6) continue;
    const p = V(pos.get(n)!);
    const sup = model.supports.find((s) => s.node === n);
    const below = (sup?.footing?.t ?? 0) + 0.2;
    const len = (0.04 + 0.12 * m / rmax) * size;
    const dir = F.clone().normalize();
    arrows.push({ tip: p.clone().add(new THREE.Vector3(0, 0, -below)), dir, length: len, color: colorAt(m / rmax), radius: 0.08 });
    if (labels) lab.push({ p: p.clone().add(new THREE.Vector3(0, 0, -below)).addScaledVector(dir, -len - 0.35), text: u.w("force", r[2]) });
  }
  return (
    <group>
      <Arrows arrows={arrows} />
      {lab.map((l, k) => <Label key={k} p={l.p} color="#7ef0b0">{l.text}</Label>)}
    </group>
  );
}

/** Soil pressure under footings drawn as a coloured surface (rigid footing, linear pressure). */
export function FootingPressure({ model, res }: { model: Model; res: CaseResult }) {
  const u = useU();
  const pos = usePositions(model);
  const sel = useStore((s) => s.loadSel);
  const showLabels = useStore((s) => s.showLabels);
  const qa = model.settings.allowable_bearing || 250;
  const dlFactor = factorsFor(model, sel)["DL"] ?? 0;
  const items = model.supports.filter((s) => s.footing && res.reactions[s.node]).map((s) => {
    const f = s.footing!;
    const fp = footingPressure(res.reactions[s.node], f, 25 * f.B * f.L * f.t * dlFactor);
    return { s, f, fp, p: pos.get(s.node)! };
  });
  const qmaxAll = Math.max(qa, ...items.map((i) => i.fp.qmax));
  const hScale = 1.2 / qmaxAll;
  return (
    <group>
      {items.map(({ s, f, fp, p }) => {
        const n = 8;
        const P: number[] = [], C: number[] = [], I: number[] = [];
        const c = new THREE.Color();
        for (let i = 0; i <= n; i++) for (let j = 0; j <= n; j++) {
          const x = -f.B / 2 + (f.B * i) / n, y = -f.L / 2 + (f.L * j) / n;
          const q = fp.at(x, y);
          P.push(p[0] + x, p[1] + y, p[2] - f.t - 0.05 - Math.max(q, 0) * hScale);
          colorAt(q / qmaxAll, c);
          if (q < 0) c.set("#ff00ff");
          C.push(c.r, c.g, c.b);
        }
        for (let i = 0; i < n; i++) for (let j = 0; j < n; j++) {
          const a = i * (n + 1) + j, b = a + n + 1;
          I.push(a, b, a + 1, a + 1, b, b + 1);
        }
        const g = new THREE.BufferGeometry();
        g.setAttribute("position", new THREE.Float32BufferAttribute(P, 3));
        g.setAttribute("color", new THREE.Float32BufferAttribute(C, 3));
        g.setIndex(I);
        g.computeVertexNormals();
        return (
          <group key={s.node}>
            <mesh geometry={g}><meshStandardMaterial vertexColors side={THREE.DoubleSide} /></mesh>
            {showLabels && <Label p={[p[0], p[1], p[2] - f.t - 0.1 - fp.qmax * hScale - 0.4]} color={fp.uplift ? "#ff7ad9" : "#d3dce6"}>
              {u.f("soil", fp.qmax)} / {u.w("soil", fp.qmin)}{fp.uplift ? " ⚠" : ""}
            </Label>}
          </group>
        );
      })}
    </group>
  );
}
