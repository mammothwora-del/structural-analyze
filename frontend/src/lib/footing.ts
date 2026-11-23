import type { Footing } from "./types";

/**
 * Soil contact pressure under a rigid rectangular footing (linear distribution,
 * full contact assumed): q(x, y) = N/A + c*y + b*x, from the column base reaction.
 *
 * reaction R = [Rx, Ry, Rz, Mx, My, Mz] is the force of the support on the structure.
 * The column pushes the footing with -R at the top of the footing; the footing base
 * lies t below the support node, so horizontal reactions add a moment H*t.
 * footingWeight (kN) is added to N.
 * Footing B is along global X, L along global Y.
 */
export function footingPressure(R: number[], f: Footing, footingWeight: number) {
  const A = f.B * f.L;
  const N = R[2] + footingWeight; // downward load on soil
  // moment applied to footing about its base centre (vector)
  const Mc = [-R[3] + f.t * R[1], -R[4] - f.t * R[0]];
  const Ix = (f.B * f.L ** 3) / 12; // about X axis (variation along y)
  const Iy = (f.L * f.B ** 3) / 12; // about Y axis (variation along x)
  const c = -Mc[0] / Ix; // dq/dy
  const b = Mc[1] / Iy;  // dq/dx
  const q0 = N / A;
  const corners = [
    [-f.B / 2, -f.L / 2], [f.B / 2, -f.L / 2], [f.B / 2, f.L / 2], [-f.B / 2, f.L / 2],
  ].map(([x, y]) => q0 + b * x + c * y);
  const qmax = Math.max(...corners), qmin = Math.min(...corners);
  const ex = N !== 0 ? Mc[1] / N : 0, ey = N !== 0 ? -Mc[0] / N : 0;
  return { N, q0, b, c, corners, qmax, qmin, ex, ey, uplift: qmin < 0, at: (x: number, y: number) => q0 + b * x + c * y };
}
