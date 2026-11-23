import { useFrame } from "@react-three/fiber";
import { useLayoutEffect, useMemo, useRef } from "react";
import * as THREE from "three";

export interface ArrowSpec {
  tip: THREE.Vector3;    // arrow head position (point of application)
  dir: THREE.Vector3;    // unit direction the arrow points
  length: number;
  color: THREE.Color;
  radius?: number;
}

const up = new THREE.Vector3(0, 1, 0);

/** Instanced arrows (shaft + head). Optional "pulse" animates arrows along their direction. */
export function Arrows({ arrows, radius = 0.05, pulse = false, opacity = 1 }: { arrows: ArrowSpec[]; radius?: number; pulse?: boolean; opacity?: number }) {
  const shaft = useRef<THREE.InstancedMesh>(null!);
  const head = useRef<THREE.InstancedMesh>(null!);
  const geo = useMemo(() => ({
    shaft: new THREE.CylinderGeometry(1, 1, 1, 8).translate(0, 0.5, 0),
    head: new THREE.ConeGeometry(1, 1, 12).translate(0, 0.5, 0),
  }), []);
  const phase = useRef(0);

  const place = (offset: number) => {
    const m = new THREE.Matrix4(), q = new THREE.Quaternion(), s = new THREE.Vector3(), p = new THREE.Vector3();
    arrows.forEach((a, k) => {
      const r = a.radius ?? radius;
      const headLen = Math.min(a.length * 0.35, r * 6);
      q.setFromUnitVectors(up, a.dir);
      const tip = a.tip.clone().addScaledVector(a.dir, -offset * a.length * 0.25);
      // head: from tip-headLen to tip
      p.copy(tip).addScaledVector(a.dir, -headLen);
      s.set(r * 2.4, headLen, r * 2.4);
      m.compose(p, q, s);
      head.current.setMatrixAt(k, m);
      head.current.setColorAt(k, a.color);
      // shaft
      const sl = Math.max(a.length - headLen, 1e-4);
      p.copy(tip).addScaledVector(a.dir, -a.length);
      s.set(r, sl, r);
      m.compose(p, q, s);
      shaft.current.setMatrixAt(k, m);
      shaft.current.setColorAt(k, a.color);
    });
    shaft.current.instanceMatrix.needsUpdate = true;
    head.current.instanceMatrix.needsUpdate = true;
    if (shaft.current.instanceColor) shaft.current.instanceColor.needsUpdate = true;
    if (head.current.instanceColor) head.current.instanceColor.needsUpdate = true;
  };

  useLayoutEffect(() => {
    if (!arrows.length) return;
    place(0);
    shaft.current.computeBoundingSphere();
    head.current.computeBoundingSphere();
  });
  useFrame((_, dt) => {
    if (!pulse || !arrows.length) return;
    phase.current = (phase.current + dt * 0.8) % 1;
    place(1 - phase.current);
  });
  if (!arrows.length) return null;
  return (
    <group>
      <instancedMesh key={"s" + arrows.length} ref={shaft} args={[geo.shaft, undefined, arrows.length]} frustumCulled={false}>
        <meshStandardMaterial transparent={opacity < 1} opacity={opacity} roughness={0.4} />
      </instancedMesh>
      <instancedMesh key={"h" + arrows.length} ref={head} args={[geo.head, undefined, arrows.length]} frustumCulled={false}>
        <meshStandardMaterial transparent={opacity < 1} opacity={opacity} roughness={0.4} />
      </instancedMesh>
    </group>
  );
}
