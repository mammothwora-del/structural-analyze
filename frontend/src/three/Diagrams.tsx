import { useMemo } from "react";
import * as THREE from "three";
import { colorAt } from "../lib/colormap";
import { COMP_KIND } from "../lib/display";
import { modelBounds } from "../lib/geometry";
import type { CaseResult, ForceComp, Model, Results } from "../lib/types";
import { useStore, useU } from "../store";
import { Label } from "./Overlays";
import { usePositions, useVisibleElements } from "./Members";

/**
 * Internal force diagrams drawn on the members.
 * Offset direction (local axes): My -> +z (drawn on the tension side for the sign
 * convention used), Mz -> -y, Vz/N -> +z, Vy/T -> +y.
 */
const OFFSET_AXIS: Record<ForceComp, [number, number]> = { N: [2, 1], Vz: [2, 1], My: [2, 1], Vy: [1, 1], T: [1, 1], Mz: [1, -1] };

export function ForceDiagrams({ model, results, res, comp }: { model: Model; results: Results; res: CaseResult; comp: ForceComp }) {
  const u = useU();
  const elements = useVisibleElements(model);
  const pos = usePositions(model);
  const showLabels = useStore((s) => s.showLabels);
  const selection = useStore((s) => s.selection);
  const size = modelBounds(model).size;
  const { geo, lines, labels } = useMemo(() => {
    let vmax = 1e-9;
    for (const el of elements) { const st = res.elements[el.id]; if (st) vmax = Math.max(vmax, ...st[comp].map(Math.abs)); }
    const scale = (0.1 * size) / vmax;
    const P: number[] = [], C: number[] = [], Lp: number[] = [];
    const labels: { p: THREE.Vector3; text: string }[] = [];
    const col = new THREE.Color();
    const [axis, sgn] = OFFSET_AXIS[comp];
    for (const el of elements) {
      const st = res.elements[el.id];
      const info = results.elements[el.id];
      if (!st || !info) continue;
      const pi = new THREE.Vector3(...pos.get(el.i)!);
      const pj = new THREE.Vector3(...pos.get(el.j)!);
      const off = new THREE.Vector3(...info.axes[axis]).multiplyScalar(sgn);
      const base = st.x.map((x) => pi.clone().lerp(pj, x / info.L));
      const tip = st.x.map((_, k) => base[k].clone().addScaledVector(off, st[comp][k] * scale));
      for (let k = 0; k < st.x.length - 1; k++) {
        const quad = [base[k], tip[k], base[k + 1], base[k + 1], tip[k], tip[k + 1]];
        const idx = [k, k, k + 1, k + 1, k, k + 1];
        quad.forEach((v, q) => {
          P.push(v.x, v.y, v.z);
          colorAt(0.2 + 0.8 * Math.abs(st[comp][idx[q]]) / vmax, col);
          C.push(col.r, col.g, col.b);
        });
        Lp.push(tip[k].x, tip[k].y, tip[k].z, tip[k + 1].x, tip[k + 1].y, tip[k + 1].z);
      }
      Lp.push(base[0].x, base[0].y, base[0].z, tip[0].x, tip[0].y, tip[0].z);
      const n = st.x.length - 1;
      Lp.push(base[n].x, base[n].y, base[n].z, tip[n].x, tip[n].y, tip[n].z);
      // label extreme values: for selected element always, otherwise when labels on
      if (showLabels || (selection?.kind === "element" && selection.id === el.id)) {
        let km = 0;
        st[comp].forEach((v, k) => { if (Math.abs(v) > Math.abs(st[comp][km])) km = k; });
        if (Math.abs(st[comp][km]) > 0.02 * vmax) labels.push({ p: tip[km], text: u.w(COMP_KIND[comp], st[comp][km]) });
      }
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.Float32BufferAttribute(P, 3));
    g.setAttribute("color", new THREE.Float32BufferAttribute(C, 3));
    const lg = new THREE.BufferGeometry();
    lg.setAttribute("position", new THREE.Float32BufferAttribute(Lp, 3));
    return { geo: g, lines: lg, labels: labels.slice(0, 150) };
  }, [elements, pos, res, results, comp, size, showLabels, selection, u.sys]);
  return (
    <group>
      <mesh geometry={geo} renderOrder={2}><meshBasicMaterial vertexColors transparent opacity={0.6} side={THREE.DoubleSide} depthWrite={false} /></mesh>
      <lineSegments geometry={lines} renderOrder={3}><lineBasicMaterial color="#ffffff" /></lineSegments>
      {labels.map((l, k) => <Label key={k} p={l.p}>{l.text}</Label>)}
    </group>
  );
}
