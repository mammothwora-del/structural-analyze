import { useFrame } from "@react-three/fiber";
import { useMemo, useRef } from "react";
import * as THREE from "three";
import { colorAt, normalize, type Scale } from "../lib/colormap";
import { allPositions, panelFlux, panelLevel, panelValues, type ShellComp } from "../lib/shells";
import type { CaseResult, Model, Results, Vec3 } from "../lib/types";
import { useStore, useU } from "../store";
import { Arrows, type ArrowSpec } from "./Arrows";
import { Label } from "./Overlays";

export const WALL_COLOR = "#a7b4c2";
export const SLAB_COLOR = "#8fa3b8";

/** Deformation animation: drives morph target 0 of a mesh between 0 and 1 when animate is on. */
export function useDeformAnimation(enabled: boolean) {
  const ref = useRef<THREE.Mesh | THREE.LineSegments>(null);
  const animate = useStore((s) => s.animate);
  const t = useRef(0);
  useFrame((_, dt) => {
    const m = ref.current;
    if (!m || !m.morphTargetInfluences || !m.morphTargetInfluences.length) return;
    if (!enabled || !animate) { m.morphTargetInfluences[0] = 1; return; }
    t.current += dt;
    m.morphTargetInfluences[0] = 0.5 - 0.5 * Math.cos(t.current * Math.PI);   // 2 s period
  });
  return ref;
}

function visibleGroups(model: Model, results: Results) {
  const { hiddenTypes, maxLevel, showSlabs } = useStore.getState();
  return Object.entries(results.mesh?.groups ?? {}).filter(([g, info]) => {
    if (info.kind === "slab" && (!showSlabs || hiddenTypes.slab)) return false;
    if (info.kind === "wall" && hiddenTypes.wall) return false;
    if (maxLevel !== null && panelLevel(model, g) > maxLevel) return false;
    return true;
  });
}

interface SurfProps {
  model: Model; results: Results; res: CaseResult | null;
  colorMode: "type" | "values" | "neutral" | "disp";
  comp?: ShellComp; scale?: Scale | null;
  deform?: number; opacity?: number; edges?: boolean;
}

/** Shell mesh of slabs and walls: contour colours per node, optional deformed shape (animated). */
export function ShellSurfaces({ model, results, res, colorMode, comp = "vm", scale, deform = 0, opacity = 1, edges = true }: SurfProps) {
  const { hiddenTypes, maxLevel, showSlabs, exploded, selection, set } = useStore();
  const { geo, lines, owners } = useMemo(() => {
    const pos = allPositions(model, results, exploded);
    const P: number[] = [], D: number[] = [], C: number[] = [], I: number[] = [];
    const LP: number[] = [], LD: number[] = [];
    const owners: string[] = [];
    const col = new THREE.Color();
    for (const [g, info] of visibleGroups(model, results)) {
      const vals = res && (colorMode === "values") ? panelValues(res, results, g, comp) : null;
      const base = P.length / 3;
      const selected = selection && (selection.kind === "slab" || selection.kind === "wall") && selection.id === g;
      info.nodes.forEach((n, k) => {
        const p = pos.get(n)!;
        P.push(p[0], p[1], p[2]);
        const u = res?.displacements[n] ?? [0, 0, 0];
        D.push(u[0] * deform, u[1] * deform, u[2] * deform);
        if (selected) col.set("#3fb6ff");
        else if (vals && scale) colorAt(normalize(vals[k], scale), col);
        else if (colorMode === "disp" && scale) colorAt(normalize(Math.hypot(u[0], u[1], u[2]), scale), col);
        else if (colorMode === "neutral") col.set("#5b6b7e");
        else col.set(info.kind === "wall" ? WALL_COLOR : SLAB_COLOR);
        C.push(col.r, col.g, col.b);
      });
      for (const q of info.quads) {
        I.push(base + q[0], base + q[1], base + q[2], base + q[0], base + q[2], base + q[3]);
        owners.push(g, g);
        if (edges) {
          for (let a = 0; a < 4; a++) {
            const i0 = base + q[a], i1 = base + q[(a + 1) % 4];
            LP.push(P[3 * i0], P[3 * i0 + 1], P[3 * i0 + 2], P[3 * i1], P[3 * i1 + 1], P[3 * i1 + 2]);
            LD.push(D[3 * i0], D[3 * i0 + 1], D[3 * i0 + 2], D[3 * i1], D[3 * i1 + 1], D[3 * i1 + 2]);
          }
        }
      }
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.Float32BufferAttribute(P, 3));
    g.setAttribute("color", new THREE.Float32BufferAttribute(C, 3));
    g.setIndex(I);
    if (deform) { g.morphAttributes.position = [new THREE.Float32BufferAttribute(D, 3)]; g.morphTargetsRelative = true; }
    g.computeVertexNormals();
    g.computeBoundingSphere();
    const lg = new THREE.BufferGeometry();
    lg.setAttribute("position", new THREE.Float32BufferAttribute(LP, 3));
    if (deform) { lg.morphAttributes.position = [new THREE.Float32BufferAttribute(LD, 3)]; lg.morphTargetsRelative = true; }
    return { geo: g, lines: lg, owners };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [model, results, res, colorMode, comp, scale, deform, exploded, selection, hiddenTypes, maxLevel, showSlabs, edges]);
  const meshRef = useDeformAnimation(deform !== 0);
  const lineRef = useDeformAnimation(deform !== 0);
  const transparent = opacity < 1;
  return (
    <group>
      <mesh key={"s" + (deform ? 1 : 0)} ref={meshRef as React.RefObject<THREE.Mesh>} geometry={geo} renderOrder={1} morphTargetInfluences={deform ? [1] : undefined}
        onClick={(e) => {
          e.stopPropagation();
          const g = owners[e.faceIndex ?? -1];
          if (!g) return;
          const kind = results.mesh?.groups[g]?.kind === "wall" ? "wall" : "slab";
          set({ selection: { kind, id: g }, multi: [] });
        }}>
        <meshStandardMaterial vertexColors side={THREE.DoubleSide} roughness={0.7} transparent={transparent} opacity={opacity} depthWrite={!transparent}
          polygonOffset polygonOffsetFactor={1} polygonOffsetUnits={1} />
      </mesh>
      {edges && (
        <lineSegments key={"l" + (deform ? 1 : 0)} ref={lineRef as React.RefObject<THREE.LineSegments>} geometry={lines} renderOrder={2} morphTargetInfluences={deform ? [1] : undefined}>
          <lineBasicMaterial color="#0b0f14" transparent opacity={transparent ? 0.15 : 0.35} />
        </lineSegments>
      )}
    </group>
  );
}

/** Walls before analysis (no mesh yet): plain panels from their corner nodes. */
export function WallPanels({ model, opacity = 0.45 }: { model: Model; opacity?: number }) {
  const { hiddenTypes, maxLevel, exploded, selection, set } = useStore();
  const { geo, owners } = useMemo(() => {
    const pos = allPositions(model, null, exploded);
    const P: number[] = [], owners: string[] = [];
    for (const w of model.walls ?? []) {
      if (maxLevel !== null && (w.level ?? 0) > maxLevel) continue;
      const c = w.corners.map((n) => pos.get(n)!);
      if (c.some((x) => !x)) continue;
      for (const [a, b, d] of [[0, 1, 2], [0, 2, 3]]) { P.push(...c[a], ...c[b], ...c[d]); owners.push(w.id); }
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.Float32BufferAttribute(P, 3));
    g.computeVertexNormals();
    return { geo: g, owners };
  }, [model, exploded, maxLevel]);
  if (hiddenTypes.wall || !model.walls?.length) return null;
  const sel = selection?.kind === "wall" ? selection.id : null;
  return (
    <mesh geometry={geo} renderOrder={1} onClick={(e) => { e.stopPropagation(); const id = owners[e.faceIndex ?? -1]; if (id) set({ selection: { kind: "wall", id }, multi: [] }); }}>
      <meshStandardMaterial color={sel ? "#3fb6ff" : WALL_COLOR} transparent opacity={opacity} side={THREE.DoubleSide} depthWrite={false} />
    </mesh>
  );
}

/** Load flux arrows in slabs and walls: direction and size of the load travelling through the panel
 *  along d (from shell transverse shear and membrane forces, FEM). */
export function ShellFlowArrows({ model, results, res, d }: { model: Model; results: Results; res: CaseResult; d: Vec3 }) {
  const { exploded, animate, showLabels, selection } = useStore();
  const hidden = useStore((s) => s.hiddenTypes);
  const maxLevel = useStore((s) => s.maxLevel);
  const showSlabs = useStore((s) => s.showSlabs);
  const u = useU();
  const { arrows, labels } = useMemo(() => {
    const pos = allPositions(model, results, exploded);
    const items: { c: THREE.Vector3; f: THREE.Vector3; mag: number; size: number; g: string; n: THREE.Vector3 }[] = [];
    let fmax = 1e-9;
    for (const [g, info] of visibleGroups(model, results)) {
      const rows = res.panel_results?.[g];
      if (!rows) continue;
      const n = new THREE.Vector3(...(info.axes[2] as Vec3));
      for (const q of info.quads) {
        const r = [0, 0, 0, 0, 0, 0, 0, 0];
        const c = new THREE.Vector3();
        for (const k of q) { rows[k].forEach((v, i) => (r[i] += v / 4)); c.add(new THREE.Vector3(...pos.get(info.nodes[k])!)); }
        c.divideScalar(4);
        const p0 = pos.get(info.nodes[q[0]])!, p2 = pos.get(info.nodes[q[2]])!;
        const size = Math.hypot(p2[0] - p0[0], p2[1] - p0[1], p2[2] - p0[2]) / Math.SQRT2;
        const f = new THREE.Vector3(...panelFlux(r, info.axes, d));
        const mag = f.length();
        fmax = Math.max(fmax, mag);
        items.push({ c, f, mag, size, g, n });
      }
    }
    const arrows: ArrowSpec[] = [];
    const labels: { p: THREE.Vector3; text: string }[] = [];
    const selG = selection && (selection.kind === "slab" || selection.kind === "wall") ? selection.id : null;
    for (const it of items) {
      const t = it.mag / fmax;
      if (t < 0.02) continue;
      const dir = it.f.clone().normalize();
      const len = it.size * (0.35 + 0.55 * Math.sqrt(t));
      const lift = it.n.clone().multiplyScalar(0.03);
      const tip = it.c.clone().add(lift).addScaledVector(dir, len / 2);
      const color = colorAt(0.1 + 0.9 * Math.sqrt(t));
      if (selG && selG !== it.g) color.lerp(new THREE.Color("#1b2430"), 0.7);
      arrows.push({ tip, dir, length: len, color, radius: Math.max(0.015, it.size * 0.05) });
      if (showLabels && selG === it.g && t > 0.5) labels.push({ p: it.c, text: u.w("forcePerLen", it.mag) });
    }
    return { arrows, labels: labels.slice(0, 40) };
  }, [model, results, res, d, exploded, showLabels, selection, hidden, maxLevel, showSlabs, u.sys]);
  return (
    <group>
      <Arrows arrows={arrows} pulse={animate} />
      {labels.map((l, k) => <Label key={k} p={l.p}>{l.text}</Label>)}
    </group>
  );
}
