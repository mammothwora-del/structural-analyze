/**
 * Display unit systems. The solver always works in SI (kN, m); values are
 * converted only for display and input.
 *
 *  - SI       : kN, m, mm, kN·m, MPa, kN/m², kN/m
 *  - Metric   : MKS / gravitational units common in Thai practice:
 *               tf, kgf, m, mm, tf·m, ksc (kgf/cm²), kgf/m², tf/m², kgf/m
 *  - Imperial : kip, ft, in, kip·ft, ksi, psf, ksf, kip/ft
 */
export type UnitSystem = "SI" | "MKS" | "IMP";
export type Kind =
  | "force" | "moment" | "stress" | "areaLoad" | "soil" | "lineLoad"
  | "length" | "disp" | "dim" | "forcePerLen" | "momentPerLen" | "area" | "inertia" | "density" | "modulus";

const G = 9.80665; // kN per tf

// [unit label, factor: displayed = SI value * factor]  (SI base: kN, m, kN/m², kN/m, kN·m, MPa for stress)
const TABLE: Record<UnitSystem, Record<Kind, [string, number]>> = {
  SI: {
    force: ["kN", 1], moment: ["kN·m", 1], stress: ["MPa", 1], areaLoad: ["kN/m²", 1], soil: ["kN/m²", 1], lineLoad: ["kN/m", 1],
    length: ["m", 1], disp: ["mm", 1000], dim: ["mm", 1000], forcePerLen: ["kN/m", 1], momentPerLen: ["kN·m/m", 1],
    area: ["cm²", 1e4], inertia: ["cm⁴", 1e8], density: ["kN/m³", 1], modulus: ["MPa", 1],
  },
  MKS: {
    force: ["tf", 1 / G], moment: ["tf·m", 1 / G], stress: ["ksc", 1 / 0.0980665], areaLoad: ["kg/m²", 1000 / G], soil: ["t/m²", 1 / G],
    lineLoad: ["kg/m", 1000 / G], length: ["m", 1], disp: ["mm", 1000], dim: ["mm", 1000], forcePerLen: ["t/m", 1 / G], momentPerLen: ["t·m/m", 1 / G],
    area: ["cm²", 1e4], inertia: ["cm⁴", 1e8], density: ["kg/m³", 1000 / G], modulus: ["ksc", 1 / 0.0980665],
  },
  IMP: {
    force: ["kip", 1 / 4.4482216], moment: ["kip·ft", 1 / 1.3558179], stress: ["ksi", 1 / 6.8947573], areaLoad: ["psf", 1 / 0.04788026],
    soil: ["ksf", 1 / 47.88026], lineLoad: ["kip/ft", 1 / 14.593903], length: ["ft", 1 / 0.3048], disp: ["in", 1 / 0.0254], dim: ["in", 1 / 0.0254],
    forcePerLen: ["kip/ft", 1 / 14.593903], momentPerLen: ["kip·ft/ft", 1 / 4.4482216], area: ["in²", 1 / 0.00064516], inertia: ["in⁴", 1 / 4.162314e-7],
    density: ["pcf", 1 / 0.157087], modulus: ["ksi", 1 / 6.8947573],
  },
};

export const SYSTEM_LABEL: Record<UnitSystem, string> = { SI: "SI (kN, m)", MKS: "Metric (tf, kg, ksc)", IMP: "Imperial (kip, ft)" };

/** Note: SI inputs for each kind: force kN, moment kN·m, stress MPa, areaLoad/soil kN/m², lineLoad kN/m,
 *  length m, disp m, dim m, forcePerLen kN/m, momentPerLen kN·m/m, area m², inertia m⁴, density kN/m³, modulus MPa. */
export function conv(sys: UnitSystem, kind: Kind, si: number) { return si * TABLE[sys][kind][1]; }
export function toSI(sys: UnitSystem, kind: Kind, v: number) { return v / TABLE[sys][kind][1]; }
export function unit(sys: UnitSystem, kind: Kind) { return TABLE[sys][kind][0]; }

function digits(v: number) {
  const a = Math.abs(v);
  if (a === 0) return 0;
  if (a >= 1000) return 0;
  if (a >= 100) return 1;
  if (a >= 1) return 2;
  return 3;
}
export function fmtU(sys: UnitSystem, kind: Kind, si: number, d?: number) {
  const v = conv(sys, kind, si);
  if (!isFinite(v)) return "–";
  if (Math.abs(v) >= 1e6) return v.toExponential(2);
  return v.toFixed(d ?? digits(v));
}
export function withU(sys: UnitSystem, kind: Kind, si: number, d?: number) {
  return `${fmtU(sys, kind, si, d)} ${unit(sys, kind)}`;
}

/** Hook-free accessor bound to a system. */
export function U(sys: UnitSystem) {
  return {
    sys,
    f: (kind: Kind, si: number, d?: number) => fmtU(sys, kind, si, d),
    w: (kind: Kind, si: number, d?: number) => withU(sys, kind, si, d),
    u: (kind: Kind) => unit(sys, kind),
    c: (kind: Kind, si: number) => conv(sys, kind, si),
    si: (kind: Kind, v: number) => toSI(sys, kind, v),
  };
}
export type UnitsApi = ReturnType<typeof U>;
