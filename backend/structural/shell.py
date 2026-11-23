"""Flat 4-node shell element (6 DOF per node).

* Membrane: bilinear plane-stress quadrilateral (2x2 Gauss).
* Bending: Reissner-Mindlin plate with MITC4 assumed transverse shear strains
  (Bathe & Dvorkin 1985) to avoid shear locking for thin plates.
* Drilling rotation (about the element normal): a weak penalty ties rz to the
  in-plane rotation of the membrane, omega = (dv/dx - du/dy)/2 (Hughes-Brezzi
  type, gamma = 1e-3 G, 2x2 Gauss). It is rigid-body invariant, so it does not
  leak load to ground, and it keeps rz non-singular at nodes with only shells.

Local element frame: z = normal (from the diagonals, right-hand rule on the node
order), x = projection of global X onto the element plane (global Y when the
element is nearly perpendicular to X, or a user reference vector), y = z x x.
All elements of a slab or wall therefore report resultants in the same axes. Local nodal DOFs: [u, v, w, rx, ry, rz]. Plate rotations of the
normal: beta_x = ry, beta_y = -rx.

Stress resultants (per unit length, local axes):
  Nx, Ny, Nxy            membrane forces (kN/m, tension +)
  Mx, My, Mxy            bending moments (kN·m/m), reported with "bottom fibre in
                         tension = +" (sagging positive for a slab with z up)
  Qx, Qy                 transverse shear (kN/m): force in +z on a face with
                         outward normal +x / +y.
"""
from __future__ import annotations

import math

import numpy as np

XI = np.array([-1.0, 1.0, 1.0, -1.0])
ETA = np.array([-1.0, -1.0, 1.0, 1.0])
_G = 1 / math.sqrt(3)
GAUSS2 = [(-_G, -_G), (_G, -_G), (_G, _G), (-_G, _G)]
KAPPA = 5.0 / 6.0
DRILL = 1e-3


def shape(xi, eta):
    N = 0.25 * (1 + XI * xi) * (1 + ETA * eta)
    dxi = 0.25 * XI * (1 + ETA * eta)
    deta = 0.25 * ETA * (1 + XI * xi)
    return N, dxi, deta


def shell_frame(X: np.ndarray, xref=None):
    """X: 4x3 global coordinates -> (R 3x3 rows = local axes, xy 4x2 local coords, centre, warp)."""
    c = X.mean(axis=0)
    ez = np.cross(X[2] - X[0], X[3] - X[1])
    ez /= np.linalg.norm(ez)
    cands = [np.asarray(xref, dtype=float)] if xref is not None else []
    cands += [np.array([1.0, 0, 0]), np.array([0, 1.0, 0])]
    for e1 in cands:
        ex = e1 - np.dot(e1, ez) * ez
        if np.linalg.norm(ex) > 0.3 * np.linalg.norm(e1):
            break
    ex /= np.linalg.norm(ex)
    ey = np.cross(ez, ex)
    R = np.vstack([ex, ey, ez])
    loc = (X - c) @ R.T
    size = max(np.linalg.norm(X[2] - X[0]), np.linalg.norm(X[3] - X[1]))
    return R, loc[:, :2], c, float(np.abs(loc[:, 2]).max() / size)


def _jac(xy, dxi, deta):
    J = np.array([[dxi @ xy[:, 0], dxi @ xy[:, 1]], [deta @ xy[:, 0], deta @ xy[:, 1]]])
    return J


def _mitc_shear_row(xy, point, which):
    """Covariant transverse shear strain (gamma_xi or gamma_eta) at a tying point, as a 24-row."""
    N, dxi, deta = shape(*point)
    row = np.zeros(24)
    dN = dxi if which == "xi" else deta
    xd = dN @ xy[:, 0]
    yd = dN @ xy[:, 1]
    for i in range(4):
        row[6 * i + 2] = dN[i]            # dw/dxi
        row[6 * i + 4] = N[i] * xd        # beta_x = ry
        row[6 * i + 3] = -N[i] * yd       # beta_y = -rx
    return row


def B_matrices(xy, xi, eta):
    """Return (Bm 3x24, Bb 3x24, Bs 2x24, detJ) at a point."""
    N, dxi, deta = shape(xi, eta)
    J = _jac(xy, dxi, deta)
    detJ = float(np.linalg.det(J))
    Jinv = np.linalg.inv(J)
    dN = Jinv @ np.vstack([dxi, deta])   # 2x4: d/dx, d/dy
    Bm = np.zeros((3, 24))
    Bb = np.zeros((3, 24))
    for i in range(4):
        Nx, Ny = dN[0, i], dN[1, i]
        Bm[0, 6 * i] = Nx
        Bm[1, 6 * i + 1] = Ny
        Bm[2, 6 * i] = Ny
        Bm[2, 6 * i + 1] = Nx
        # kx = d(beta_x)/dx = d(ry)/dx ; ky = d(beta_y)/dy = -d(rx)/dy ; kxy = d(bx)/dy + d(by)/dx
        Bb[0, 6 * i + 4] = Nx
        Bb[1, 6 * i + 3] = -Ny
        Bb[2, 6 * i + 4] = Ny
        Bb[2, 6 * i + 3] = -Nx
    gA = _mitc_shear_row(xy, (0.0, 1.0), "xi")
    gC = _mitc_shear_row(xy, (0.0, -1.0), "xi")
    gB = _mitc_shear_row(xy, (-1.0, 0.0), "eta")
    gD = _mitc_shear_row(xy, (1.0, 0.0), "eta")
    g_xi = 0.5 * (1 - eta) * gC + 0.5 * (1 + eta) * gA
    g_eta = 0.5 * (1 - xi) * gB + 0.5 * (1 + xi) * gD
    Bs = Jinv @ np.vstack([g_xi, g_eta])
    Bd = np.zeros(24)
    for i in range(4):
        Bd[6 * i + 5] = N[i]
        Bd[6 * i + 1] = -0.5 * dN[0, i]
        Bd[6 * i] = 0.5 * dN[1, i]
    return Bm, Bb, Bs, detJ, N, Bd


def constitutive(E, nu, t):
    C = E / (1 - nu**2) * np.array([[1, nu, 0], [nu, 1, 0], [0, 0, (1 - nu) / 2]])
    G = E / (2 * (1 + nu))
    return C * t, C * t**3 / 12, KAPPA * G * t * np.eye(2)


class ShellElement:
    def __init__(self, eid, X, E, nu, t, density=0.0, xref=None):
        self.id = eid
        self.X = np.asarray(X, dtype=float)
        self.E, self.nu, self.t, self.density = E, nu, t, density
        self.R, self.xy, self.c, self.warp = shell_frame(self.X, xref)
        self.Dm, self.Db, self.Ds = constitutive(E, nu, t)
        self.T = np.kron(np.eye(8), self.R)  # 24x24 (4 nodes x [trans, rot])
        self.area = 0.0
        k = np.zeros((24, 24))
        gd = DRILL * E / (2 * (1 + nu)) * t
        self._B = []
        for xi, eta in GAUSS2:
            Bm, Bb, Bs, detJ, N, Bd = B_matrices(self.xy, xi, eta)
            if detJ <= 0:
                raise ValueError(f"Shell {eid}: distorted or wrongly ordered element (detJ <= 0)")
            k += (Bm.T @ self.Dm @ Bm + Bb.T @ self.Db @ Bb + Bs.T @ self.Ds @ Bs + gd * np.outer(Bd, Bd)) * detJ
            self.area += detJ
            self._B.append((N, detJ))
        self.k_local = k
        self.k_global = self.T.T @ k @ self.T

    def pressure_load(self, qvec):
        """Consistent nodal forces (global, 24) for a uniform surface load qvec (kN/m², global)."""
        f = np.zeros(24)
        for N, detJ in self._B:
            for i in range(4):
                f[6 * i: 6 * i + 3] += N[i] * detJ * np.asarray(qvec)
        return f

    def resultant_matrix(self, xi=0.0, eta=0.0):
        """8x24 matrix S such that S @ d_local = [Nx, Ny, Nxy, Mx, My, Mxy, Qx, Qy] (M: bottom tension +).

        With beta_x = ry the plate curvature convention gives M = int(sigma z dz) (top tension +);
        the moment rows are negated so that bottom-fibre tension is positive."""
        Bm, Bb, Bs, *_ = B_matrices(self.xy, xi, eta)
        return np.vstack([self.Dm @ Bm, -(self.Db @ Bb), self.Ds @ Bs])

    def recovery(self):
        """(40x24 global) matrix: resultants at the centre and the 4 corners from global nodal displacements."""
        if not hasattr(self, "_S"):
            pts = [(0.0, 0.0), (-1, -1), (1, -1), (1, 1), (-1, 1)]
            self._S = np.vstack([self.resultant_matrix(*p) for p in pts]) @ self.T
        return self._S

    def resultants(self, u_global, xi=0.0, eta=0.0):
        """[Nx, Ny, Nxy, Mx, My, Mxy, Qx, Qy] at (xi, eta) in local axes (M: bottom tension +)."""
        return self.resultant_matrix(xi, eta) @ (self.T @ u_global)
