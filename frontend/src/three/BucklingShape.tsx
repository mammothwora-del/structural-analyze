import { Line } from "@react-three/drei";
import { useFrame } from "@react-three/fiber";
import { useMemo, useRef } from "react";
import * as THREE from "three";
import { colorAt } from "../lib/colormap";
import type { BucklingMode } from "../lib/types";
import { useStore } from "../store";

const SAMPLES = 6;   // drawn points per calculated segment (smooth curve through the calculated node values)
const MIN_AMP = 0.02;   // relative amplitude below which a segment is not drawn

/**
 * Buckling mode shape. The calculated quantities are the mode displacements at the member segment nodes; the
 * curve between them is a Catmull-Rom spline for display. Colour = relative mode amplitude (no physical units:
 * an eigenvector has no magnitude).
 */
export function BucklingShape({ mode, scale }: { mode: BucklingMode; scale: number }) {
  const animate = useStore((s) => s.animate);
  const geo = useMemo(() => {
    const base: number[] = [], disp: number[] = [], col: number[] = [];
    const c = new THREE.Color();
    for (const pts of Object.values(mode.members)) {
      if (pts.length < 2) continue;
      const P = new THREE.CatmullRomCurve3(pts.map((p) => new THREE.Vector3(p[0], p[1], p[2])), false, "centripetal");
      const D = new THREE.CatmullRomCurve3(pts.map((p) => new THREE.Vector3(p[3], p[4], p[5])), false, "catmullrom", 0.5);
      const n = (pts.length - 1) * SAMPLES;
      // sample both curves at the same parameter so the calculated nodes stay on the drawn line
      const ps = P.getPoints(n), ds = D.getPoints(n);
      for (let k = 0; k < n; k++) {
        // members that hardly move in this mode are left to the faded model underneath
        if (Math.max(ds[k].length(), ds[k + 1].length()) < MIN_AMP) continue;
        for (const q of [k, k + 1]) {
          base.push(ps[q].x, ps[q].y, ps[q].z);
          disp.push(ds[q].x, ds[q].y, ds[q].z);
          colorAt(0.15 + 0.85 * Math.min(1, ds[q].length()), c);
          col.push(c.r, c.g, c.b);
        }
      }
    }
    const points: [number, number, number][] = [], colors: [number, number, number][] = [];
    for (let k = 0; k < base.length; k += 3) { points.push([base[k], base[k + 1], base[k + 2]]); colors.push([col[k], col[k + 1], col[k + 2]]); }
    return { points, colors, base: new Float32Array(base), disp: new Float32Array(disp), cur: new Float32Array(base.length) };
  }, [mode]);

  const phase = useRef(0);
  const line = useRef<{ geometry: { setPositions: (a: Float32Array) => void } } | null>(null);
  useFrame((_, dt) => {
    if (!line.current || !geo.points.length) return;
    phase.current = animate ? phase.current + dt * 2.4 : Math.PI / 2;
    const f = scale * Math.sin(phase.current);
    for (let k = 0; k < geo.cur.length; k++) geo.cur[k] = geo.base[k] + f * geo.disp[k];
    line.current.geometry.setPositions(geo.cur);
  });

  if (!geo.points.length) return null;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  return <Line ref={line as any} points={geo.points} vertexColors={geo.colors} segments lineWidth={2.5} />;
}
