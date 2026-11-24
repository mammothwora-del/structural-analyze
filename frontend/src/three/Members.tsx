import { useMemo } from "react";
import * as THREE from "three";
import { colorAt, normalize } from "../lib/colormap";
import type { Display } from "../lib/display";
import { elementAxes, sectionDims } from "../lib/geometry";
import type { Element, Model, Results, Vec3 } from "../lib/types";
import { useStore } from "../store";
import { allPositions } from "../lib/shells";
import { useDeformAnimation } from "./Shells";

export const TYPE_COLORS: Record<string, string> = {
  column: "#7fb6dc",
  main: "#d6a45e",
  secondary: "#b68fe0",
  brace: "#6fd3b0",
  chord: "#e0b25a",
  web: "#e58f6f",
  purlin: "#9fb7c9",
  rafter: "#d98b4a",
  rib: "#e6c06a",
  ring: "#8fc3e6",
  lattice: "#c792ea",
};

export const TYPE_LABELS: Record<string, string> = {
  column: "Columns", main: "Main beams", secondary: "Secondary beams", brace: "Bracing & ties",
  chord: "Truss chords", web: "Truss webs", purlin: "Purlins & eave struts", rafter: "Rafters",
  rib: "Ribs & arches", ring: "Rings & longitudinals", lattice: "Lattice diagonals",
};

export function elementColorKey(e: Element) {
  if (e.type === "column") return "column";
  if (e.type === "brace") return "brace";
  if (e.type === "truss") return e.role === "chord" ? "chord" : "web";
  if (e.role === "purlin" || e.role === "eave") return "purlin";
  if (e.role === "rafter") return "rafter";
  if (e.role === "rib" || e.role === "arch") return "rib";
  if (e.role === "ring" || e.role === "longitudinal") return "ring";
  if (e.role === "diagonal") return "lattice";
  return e.role === "secondary" ? "secondary" : "main";
}

export function useVisibleElements(model: Model) {
  const { hiddenTypes, maxLevel, isolated } = useStore();
  return useMemo(() => {
    const iso = isolated ? new Set(isolated) : null;
    return model.elements.filter((e) => {
      if (hiddenTypes[elementColorKey(e)]) return false;
      if (maxLevel !== null && (e.level ?? 0) > maxLevel) return false;
      if (iso && !iso.has(e.id)) return false;
      return true;
    });
  }, [model, hiddenTypes, maxLevel, isolated]);
}

/** Node positions (exploded view applied), including shell mesh nodes of the last analysis. */
export function usePositions(model: Model) {
  const exploded = useStore((s) => s.exploded);
  const results = useStore((s) => s.results);
  return useMemo(() => allPositions(model, results, exploded), [model, results, exploded]);
}

interface Props {
  model: Model;
  results: Results | null;
  display: Display | null;
  deform: number;        // deformation scale (0 = undeformed)
  colorMode: "type" | "values" | "neutral";
  highlight?: Record<string, number> | null;   // trace: element -> value (others dimmed)
  highlightMax?: number;
  opacity?: number;
}

/** All frame members merged into one swept-rectangle mesh with per-station vertex colours. */
export function Members({ model, results, display, deform, colorMode, highlight, highlightMax, opacity = 1 }: Props) {
  const elements = useVisibleElements(model);
  const pos = usePositions(model);
  const selection = useStore((s) => s.selection);
  const multi = useStore((s) => s.multi);
  const set = useStore((s) => s.set);
  const nodes = useMemo(() => new Map(model.nodes.map((n) => [n.id, [n.x, n.y, n.z] as Vec3])), [model]);

  const { geometry, triOwner } = useMemo(() => {
    const P: number[] = [], N: number[] = [], C: number[] = [], I: number[] = [], D: number[] = [];
    const triOwner: { start: number; id: string }[] = [];
    const col = new THREE.Color();
    const sel = new Set([...(selection?.kind === "element" ? [selection.id] : []), ...multi]);
    const res = display?.res;
    for (const el of elements) {
      const { L, R } = elementAxes(model, results, el, nodes);
      const pi = pos.get(el.i)!, pj = pos.get(el.j)!;
      const ex = new THREE.Vector3(pj[0] - pi[0], pj[1] - pi[1], pj[2] - pi[2]).divideScalar(L);
      const ey = new THREE.Vector3(...R[1]), ez = new THREE.Vector3(...R[2]);
      const { b, h } = sectionDims(model, el);
      const st = res?.elements[el.id];
      const xs = st ? st.x : [0, L];
      const vals = display?.values[el.id];
      // undeformed centre line; the deformed shape goes into a morph target (animated)
      const centers: THREE.Vector3[] = xs.map((x) => new THREE.Vector3(...pi).addScaledVector(ex, x));
      const dsp: number[][] = xs.map((_, k) => (deform && st ? (st.disp[k] as number[]).map((v) => v * deform) : [0, 0, 0]));
      const colors: THREE.Color[] = xs.map((_, k) => {
        if (sel.has(el.id)) return new THREE.Color("#3fb6ff");
        if (highlight) {
          const v = highlight[el.id];
          if (v === undefined) return new THREE.Color("#2a3442");
          return colorAt(0.15 + 0.85 * (v / (highlightMax || 1)), new THREE.Color());
        }
        if (colorMode === "values" && vals && display) return colorAt(normalize(vals[k], display.scale), new THREE.Color());
        if (colorMode === "values" && display && !display.res) return new THREE.Color("#3a4656");   // not part of a per-member value set
        if (colorMode === "neutral") return new THREE.Color("#5b6b7e");
        return col.set(TYPE_COLORS[elementColorKey(el)]).clone();
      });
      const start = I.length / 3;
      const corners = [[-1, -1], [1, -1], [1, 1], [-1, 1]] as const;
      const faceNormals = [ez.clone().negate(), ey.clone(), ez.clone(), ey.clone().negate()];
      // four side faces
      for (let f = 0; f < 4; f++) {
        const [a1, b1] = corners[f], [a2, b2] = corners[(f + 1) % 4];
        const base = P.length / 3;
        for (let k = 0; k < xs.length; k++) {
          for (const [aa, bb] of [[a1, b1], [a2, b2]]) {
            const p = centers[k].clone().addScaledVector(ey, (aa * b) / 2).addScaledVector(ez, (bb * h) / 2);
            P.push(p.x, p.y, p.z);
            D.push(dsp[k][0], dsp[k][1], dsp[k][2]);
            N.push(faceNormals[f].x, faceNormals[f].y, faceNormals[f].z);
            C.push(colors[k].r, colors[k].g, colors[k].b);
          }
        }
        for (let k = 0; k < xs.length - 1; k++) {
          const v0 = base + 2 * k, v1 = v0 + 1, v2 = v0 + 2, v3 = v0 + 3;
          I.push(v0, v2, v1, v1, v2, v3);
        }
      }
      // end caps
      for (const [k, sgn] of [[0, -1], [xs.length - 1, 1]] as const) {
        const base = P.length / 3;
        for (const [aa, bb] of corners) {
          const p = centers[k].clone().addScaledVector(ey, (aa * b) / 2).addScaledVector(ez, (bb * h) / 2);
          P.push(p.x, p.y, p.z);
          D.push(dsp[k][0], dsp[k][1], dsp[k][2]);
          N.push(ex.x * sgn, ex.y * sgn, ex.z * sgn);
          C.push(colors[k].r, colors[k].g, colors[k].b);
        }
        I.push(base, base + 1, base + 2, base, base + 2, base + 3);
      }
      triOwner.push({ start, id: el.id });
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.Float32BufferAttribute(P, 3));
    g.setAttribute("normal", new THREE.Float32BufferAttribute(N, 3));
    g.setAttribute("color", new THREE.Float32BufferAttribute(C, 3));
    g.setIndex(I);
    if (deform) { g.morphAttributes.position = [new THREE.Float32BufferAttribute(D, 3)]; g.morphTargetsRelative = true; }
    g.computeBoundingSphere();
    return { geometry: g, triOwner };
  }, [elements, pos, model, results, display, deform, colorMode, highlight, highlightMax, selection, multi, nodes]);

  const pick = (faceIndex: number | undefined) => {
    if (faceIndex === undefined) return null;
    let lo = 0, hi = triOwner.length - 1;
    while (lo < hi) {
      const mid = (lo + hi + 1) >> 1;
      if (triOwner[mid].start <= faceIndex) lo = mid; else hi = mid - 1;
    }
    return triOwner[lo]?.id ?? null;
  };

  const ref = useDeformAnimation(deform !== 0);
  return (
    <mesh
      key={deform ? "def" : "undef"}
      ref={ref as React.RefObject<THREE.Mesh>}
      morphTargetInfluences={deform ? [1] : undefined}
      geometry={geometry}
      onClick={(e) => {
        e.stopPropagation();
        const id = pick(e.faceIndex ?? undefined);
        if (!id) return;
        if (e.nativeEvent.shiftKey || e.nativeEvent.ctrlKey) {
          const m = useStore.getState().multi;
          set({ multi: m.includes(id) ? m.filter((x) => x !== id) : [...m, id] });
        } else set({ selection: { kind: "element", id }, multi: [] });
      }}
    >
      <meshStandardMaterial vertexColors side={THREE.DoubleSide} roughness={0.55} metalness={0.05} transparent={opacity < 1} opacity={opacity} />
    </mesh>
  );
}
