import { useLayoutEffect, useMemo, useRef } from "react";
import * as THREE from "three";
import { elementReleases, isHinged } from "../lib/geometry";
import type { Model } from "../lib/types";
import { usePositions, useVisibleElements } from "./Members";

/** Hinge symbols (small white rings/spheres) at member ends whose bending moments are released. */
export function Hinges({ model }: { model: Model }) {
  const elements = useVisibleElements(model);
  const pos = usePositions(model);
  const ref = useRef<THREE.InstancedMesh>(null!);
  const pts = useMemo(() => {
    const out: { p: THREE.Vector3; r: number }[] = [];
    for (const e of elements) {
      const [ri, rj] = elementReleases(e);
      if (!isHinged(ri) && !isHinged(rj)) continue;
      const a = new THREE.Vector3(...pos.get(e.i)!), b = new THREE.Vector3(...pos.get(e.j)!);
      const L = a.distanceTo(b);
      const off = Math.min(0.35, Math.max(0.12, 0.07 * L));
      const r = Math.min(0.09, Math.max(0.045, 0.02 * L));
      const dir = b.clone().sub(a).normalize();
      if (isHinged(ri)) out.push({ p: a.clone().addScaledVector(dir, off), r });
      if (isHinged(rj)) out.push({ p: b.clone().addScaledVector(dir, -off), r });
    }
    return out;
  }, [elements, pos]);
  useLayoutEffect(() => {
    if (!ref.current) return;
    const m = new THREE.Matrix4();
    pts.forEach((h, k) => { m.makeScale(h.r, h.r, h.r).setPosition(h.p); ref.current.setMatrixAt(k, m); });
    ref.current.instanceMatrix.needsUpdate = true;
    ref.current.computeBoundingSphere();
  }, [pts]);
  if (!pts.length) return null;
  return (
    <instancedMesh key={pts.length} ref={ref} args={[undefined, undefined, pts.length]} renderOrder={4}>
      <sphereGeometry args={[1, 10, 8]} />
      <meshBasicMaterial color="#ffffff" depthTest={false} transparent opacity={0.9} />
    </instancedMesh>
  );
}
