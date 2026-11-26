import { useThree } from "@react-three/fiber";
import { useRef, useState } from "react";
import * as THREE from "three";
import type { Model, Vec3 } from "../lib/types";
import { useStore } from "../store";
import { usePositions, useVisibleElements } from "./Members";

/** What the box selection needs from inside the canvas: the camera, the canvas size and the members shown. */
const probe: { camera: THREE.Camera | null; segs: { id: string; a: Vec3; b: Vec3 }[] } = { camera: null, segs: [] };

export function SelectProbe({ model }: { model: Model }) {
  const camera = useThree((s) => s.camera);
  const pos = usePositions(model);
  const els = useVisibleElements(model);
  probe.camera = camera;
  probe.segs = els.flatMap((e) => {
    const a = pos.get(e.i), b = pos.get(e.j);
    return a && b ? [{ id: e.id, a, b }] : [];
  });
  return null;
}

/** Drag a box over the 3D view: left to right selects members fully inside, right to left members touched. */
export function BoxSelectOverlay() {
  const { boxSelect, selectMembers, set } = useStore();
  const ref = useRef<HTMLDivElement>(null);
  const [box, setBox] = useState<{ x0: number; y0: number; x1: number; y1: number } | null>(null);
  if (!boxSelect) return null;
  const local = (e: React.PointerEvent) => {
    const r = ref.current!.getBoundingClientRect();
    return { x: e.clientX - r.left, y: e.clientY - r.top, w: r.width, h: r.height };
  };
  const finish = (e: React.PointerEvent) => {
    if (!box || !probe.camera) { setBox(null); return; }
    const { w, h } = local(e);
    const xa = Math.min(box.x0, box.x1), xb = Math.max(box.x0, box.x1), ya = Math.min(box.y0, box.y1), yb = Math.max(box.y0, box.y1);
    setBox(null);
    if (xb - xa < 4 && yb - ya < 4) return;
    const crossing = box.x1 < box.x0;
    const v = new THREE.Vector3();
    const inside = (p: number[]) => {
      v.set(p[0], p[1], p[2]).project(probe.camera!);
      if (v.z > 1 || v.z < -1) return false;
      const x = (v.x + 1) / 2 * w, y = (1 - v.y) / 2 * h;
      return x >= xa && x <= xb && y >= ya && y <= yb;
    };
    const ids = probe.segs.filter(({ a, b }) => {
      if (!crossing) return inside(a) && inside(b);
      for (let k = 0; k <= 16; k++) {
        const t = k / 16;
        if (inside([a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t])) return true;
      }
      return false;
    }).map((s) => s.id);
    if (ids.length) selectMembers(ids, e.shiftKey || e.ctrlKey);
  };
  const crossing = box && box.x1 < box.x0;
  return (
    <div ref={ref} className="absolute inset-0 cursor-crosshair"
      onPointerDown={(e) => { const p = local(e); (e.target as HTMLElement).setPointerCapture(e.pointerId); setBox({ x0: p.x, y0: p.y, x1: p.x, y1: p.y }); }}
      onPointerMove={(e) => { if (box) { const p = local(e); setBox({ ...box, x1: p.x, y1: p.y }); } }}
      onPointerUp={finish}>
      {box && (
        <div className={`absolute border ${crossing ? "border-dashed border-emerald-300 bg-emerald-300/10" : "border-sky-300 bg-sky-300/10"}`}
          style={{ left: Math.min(box.x0, box.x1), top: Math.min(box.y0, box.y1), width: Math.abs(box.x1 - box.x0), height: Math.abs(box.y1 - box.y0) }} />
      )}
      <div className="absolute left-1/2 -translate-x-1/2 bottom-3 rounded-md border border-sky-500/40 bg-ink-900/90 px-3 py-1.5 text-[11px] text-ink-200 pointer-events-auto">
        <b className="text-sky-300">Box select</b>: drag left → right for members fully inside, right → left for members touched. Shift adds to the selection.
        <button className="ml-2 btn !py-0" onClick={() => set({ boxSelect: false })}>Done (B)</button>
      </div>
    </div>
  );
}
