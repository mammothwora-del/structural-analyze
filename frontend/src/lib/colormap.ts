import * as THREE from "three";

// Engineering contour scale: blue (low) -> green (moderate) -> yellow (high) -> orange (very high) -> red (critical)
const STOPS: [number, string][] = [
  [0.0, "#1b1fa8"],
  [0.1, "#1446ff"],
  [0.2, "#0a8cff"],
  [0.3, "#00c8e6"],
  [0.4, "#00d68f"],
  [0.5, "#16d93a"],
  [0.6, "#9be21d"],
  [0.7, "#f2e600"],
  [0.8, "#ffb000"],
  [0.9, "#ff6a00"],
  [1.0, "#e0161b"],
];
const STOP_COLORS = STOPS.map(([t, c]) => [t, new THREE.Color(c)] as const);

export function colorAt(t: number, out = new THREE.Color()): THREE.Color {
  if (!isFinite(t)) t = 0;
  t = Math.min(1, Math.max(0, t));
  for (let k = 1; k < STOP_COLORS.length; k++) {
    const [t1, c1] = STOP_COLORS[k];
    if (t <= t1) {
      const [t0, c0] = STOP_COLORS[k - 1];
      return out.copy(c0).lerp(c1, (t - t0) / (t1 - t0));
    }
  }
  return out.copy(STOP_COLORS[STOP_COLORS.length - 1][1]);
}

export function cssColorAt(t: number) {
  return "#" + colorAt(t).getHexString();
}

export interface Scale {
  min: number; max: number; label: string; unit: string;
  /** symmetric diverging scale (for signed quantities shown with sign) */
  signed?: boolean;
  /** optional critical limit: values above are red */
  limit?: number;
  note?: string;
  /** colour mapping: linear or square-root (emphasises small values; legend values stay exact) */
  transform?: "linear" | "sqrt";
}

export function normalize(v: number, s: Scale) {
  if (s.max - s.min < 1e-15) return 0;
  const t = Math.min(1, Math.max(0, (v - s.min) / (s.max - s.min)));
  return s.transform === "sqrt" ? Math.sqrt(t) : t;
}

/** inverse of normalize: colour position -> value */
export function valueAt(t: number, s: Scale) {
  const u = s.transform === "sqrt" ? t * t : t;
  return s.min + u * (s.max - s.min);
}

export const BANDS = 11;
