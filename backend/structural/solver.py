"""3D linear-elastic frame finite element solver.

* 2-node Euler-Bernoulli space-frame element, 6 DOF per node
  (ux, uy, uz, rx, ry, rz), 12x12 element stiffness.
* Global stiffness assembled as a SciPy sparse matrix and solved with a sparse
  LU factorisation (SuperLU).
* Member loads: piecewise-linear distributed loads and concentrated loads at any
  position, converted to consistent (work-equivalent) nodal loads.
* Element end forces f = k u_local + f_fixed.
* Internal force diagrams (N, Vy, Vz, T, My, Mz) obtained by statics of the free
  body [0, x]; deflected shape by integrating curvature M/EI from end i.
* Global equilibrium check of applied loads vs. support reactions (forces and
  moments about the origin), computed from the *original* load definitions.
* Optional flat 4-node shell elements (see shell.py) for slabs and walls,
  assembled into the same global system; surface pressure and self-weight.
* Stability diagnostics: unsupported / disconnected parts, DOFs without
  stiffness, near-zero LU pivots (mechanisms) and solution residual.

Units: kN, m, rad. Sign conventions are documented in docs/conventions.md.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spla
from scipy.integrate import cumulative_simpson

from .sections import MATERIALS, material_props, section_properties
from .shell import ShellElement

DOF = 6
DOF_NAMES = ("ux", "uy", "uz", "rx", "ry", "rz")
SUPPORT_TYPES = {
    "fixed": [1, 1, 1, 1, 1, 1],
    "pinned": [1, 1, 1, 0, 0, 0],
    "roller": [0, 0, 1, 0, 0, 0],
}


class ModelError(ValueError):
    pass


# --------------------------------------------------------------------------
# Element formulation
# --------------------------------------------------------------------------
def local_axes(xi: np.ndarray, xj: np.ndarray, roll_deg: float = 0.0):
    """Return (L, R) where the rows of R are the local x, y, z unit vectors.

    local x : from node i to node j
    local z : lies in the vertical plane for non-vertical members (points "up");
              for vertical members local z = global +X.
    local y = z cross x  (right-handed).  ``roll_deg`` rotates y, z about x.
    """
    v = xj - xi
    L = float(np.linalg.norm(v))
    if L <= 1e-9:
        raise ModelError("Zero-length element")
    ex = v / L
    ref = np.array([1.0, 0.0, 0.0]) if abs(ex[2]) > 0.999999 else np.array([0.0, 0.0, 1.0])
    ey = np.cross(ref, ex)
    ey /= np.linalg.norm(ey)
    ez = np.cross(ex, ey)
    if roll_deg:
        c, s = math.cos(math.radians(roll_deg)), math.sin(math.radians(roll_deg))
        ey, ez = c * ey + s * ez, -s * ey + c * ez
    return L, np.vstack([ex, ey, ez])


def frame_stiffness_local(E, G, A, Iy, Iz, J, L) -> np.ndarray:
    """12x12 local stiffness of a 3D Euler-Bernoulli frame element."""
    k = np.zeros((12, 12))
    EA, GJ = E * A / L, G * J / L
    k[0, 0] = k[6, 6] = EA
    k[0, 6] = k[6, 0] = -EA
    k[3, 3] = k[9, 9] = GJ
    k[3, 9] = k[9, 3] = -GJ
    # bending in x-y plane (about local z): dofs 1(uy) 5(rz) 7 11
    a = E * Iz / L**3
    idx = [1, 5, 7, 11]
    kb = a * np.array([
        [12, 6 * L, -12, 6 * L],
        [6 * L, 4 * L**2, -6 * L, 2 * L**2],
        [-12, -6 * L, 12, -6 * L],
        [6 * L, 2 * L**2, -6 * L, 4 * L**2],
    ])
    k[np.ix_(idx, idx)] = kb
    # bending in x-z plane (about local y): dofs 2(uz) 4(ry) 8 10
    a = E * Iy / L**3
    idx = [2, 4, 8, 10]
    kb = a * np.array([
        [12, -6 * L, -12, -6 * L],
        [-6 * L, 4 * L**2, 6 * L, 2 * L**2],
        [-12, 6 * L, 12, 6 * L],
        [-6 * L, 2 * L**2, 6 * L, 4 * L**2],
    ])
    k[np.ix_(idx, idx)] = kb
    return k


def shape_matrix(xi: float, L: float) -> np.ndarray:
    """3x12 matrix N such that local displacement (u, v, w) = N @ d_local."""
    N = np.zeros((3, 12))
    h1 = 1 - 3 * xi**2 + 2 * xi**3
    h2 = L * (xi - 2 * xi**2 + xi**3)
    h3 = 3 * xi**2 - 2 * xi**3
    h4 = L * (-xi**2 + xi**3)
    N[0, 0], N[0, 6] = 1 - xi, xi
    N[1, 1], N[1, 5], N[1, 7], N[1, 11] = h1, h2, h3, h4
    # theta_y = -dw/dx
    N[2, 2], N[2, 4], N[2, 8], N[2, 10] = h1, -h2, h3, -h4
    return N


_GAUSS3 = (np.array([-math.sqrt(0.6), 0.0, math.sqrt(0.6)]), np.array([5 / 9, 8 / 9, 5 / 9]))


# --------------------------------------------------------------------------
# Member loads (local representation)
# --------------------------------------------------------------------------
@dataclass
class MemberLoadLocal:
    """Loads on one element for one load case, in LOCAL coordinates.

    dist  : list of (x0, x1, q0(3), q1(3)) linear segments, kN/m
    point : list of (a, P(3)) concentrated forces, kN
    """
    dist: list = field(default_factory=list)
    point: list = field(default_factory=list)

    def equivalent_nodal(self, L: float) -> np.ndarray:
        P = np.zeros(12)
        gp, gw = _GAUSS3
        for x0, x1, q0, q1 in self.dist:
            h = x1 - x0
            if h <= 0:
                continue
            for g, w in zip(gp, gw):
                t = 0.5 * (g + 1)
                x = x0 + t * h
                q = q0 + t * (q1 - q0)
                P += shape_matrix(x / L, L).T @ q * (w * h / 2)
        for a, F in self.point:
            P += shape_matrix(a / L, L).T @ F
        return P

    def integrals(self, xs):
        """For an array of stations xs: R = int_0^x q ds ;  Mq = int_0^x (s - x) q ds.
        Returns arrays of shape (n, 3)."""
        xs = np.asarray(xs, dtype=float)
        R = np.zeros((xs.size, 3))
        Mq = np.zeros((xs.size, 3))
        X = xs[:, None]
        for x0, x1, q0, q1 in self.dist:
            if x1 <= x0:
                continue
            b = np.clip(xs, x0, x1)[:, None]            # upper limit of the clipped segment
            h = b - x0                                   # zero where x <= x0
            qb = q0 + (q1 - q0) * (b - x0) / (x1 - x0)
            qm = 0.5 * (q0 + qb)
            m = 0.5 * (x0 + b)
            R += h / 2 * (q0 + qb)
            # Simpson is exact for the quadratic integrand (s - x) q(s)
            Mq += h / 6 * ((x0 - X) * q0 + 4 * (m - X) * qm + (b - X) * qb)
        for a, F in self.point:
            act = (xs > a)[:, None]
            R += act * F
            Mq += act * (a - X) * F
        return R, Mq

    def breakpoints(self):
        pts = []
        for x0, x1, _, _ in self.dist:
            pts += [x0, x1]
        for a, _ in self.point:
            pts.append(a)
        return pts


# --------------------------------------------------------------------------
# Model
# --------------------------------------------------------------------------
class FrameModel:
    """Analysis model built from a JSON-like dict (see docs/model-format.md)."""

    def __init__(self, data: dict):
        self.data = data
        self.warnings: list[dict] = []
        mats = {**{k: dict(v) for k, v in MATERIALS.items()}, **data.get("materials", {})}
        self.materials = mats
        self.sections = data.get("sections", {})

        self.node_ids = [n["id"] for n in data["nodes"]]
        if len(set(self.node_ids)) != len(self.node_ids):
            raise ModelError("Duplicate node ids")
        self.node_xyz = {n["id"]: np.array([float(n["x"]), float(n["y"]), float(n["z"])]) for n in data["nodes"]}

        self.elements = []
        seen = set()
        for e in data["elements"]:
            if e["id"] in seen:
                raise ModelError(f"Duplicate element id {e['id']}")
            seen.add(e["id"])
            if e["i"] not in self.node_xyz or e["j"] not in self.node_xyz:
                raise ModelError(f"Element {e['id']} references a missing node")
            sec = self.sections.get(e["section"])
            if sec is None:
                raise ModelError(f"Element {e['id']} references missing section {e['section']}")
            mat_id = e.get("material") or sec.get("material")
            if mat_id not in mats:
                raise ModelError(f"Element {e['id']} references missing material {mat_id}")
            props = section_properties(sec)
            mp = material_props(mats[mat_id])
            L, R = local_axes(self.node_xyz[e["i"]], self.node_xyz[e["j"]], float(e.get("roll", 0.0)))
            self.elements.append({
                "id": e["id"], "i": e["i"], "j": e["j"], "L": L, "R": R,
                "props": props, "mat": mp, "material": mat_id,
                "nst": e.get("n_stations"), "ndense": int(e.get("n_dense", 41)),
                "k_local": frame_stiffness_local(mp["E"], mp["G"], props.A, props.Iy, props.Iz, props.J, L),
            })
        self.el_index = {e["id"]: k for k, e in enumerate(self.elements)}

        self.shells = []
        for s in data.get("shells", []):
            if s["id"] in seen:
                raise ModelError(f"Duplicate element id {s['id']}")
            seen.add(s["id"])
            if len(s["nodes"]) != 4 or any(n not in self.node_xyz for n in s["nodes"]):
                raise ModelError(f"Shell {s['id']} must reference 4 existing nodes")
            mat = mats.get(s.get("material"))
            if mat is None:
                raise ModelError(f"Shell {s['id']} references missing material {s.get('material')}")
            mp = material_props(mat)
            nu = float(mat.get("nu", 0.2))
            dens = float(s["density"]) if s.get("density") is not None else mp["density"]
            X = np.array([self.node_xyz[n] for n in s["nodes"]])
            try:
                el = ShellElement(s["id"], X, mp["E"], nu, float(s["t"]), dens, s.get("xref"))
            except ValueError as exc:
                raise ModelError(str(exc)) from exc
            if el.warp > 0.01:
                self.warnings.append({"level": "warning", "code": "warped_shell",
                                      "message": f"Shell {s['id']} is warped ({el.warp * 100:.1f}% of its size); "
                                                 f"the flat element is approximate for it."})
            self.shells.append({"id": s["id"], "nodes": list(s["nodes"]), "el": el,
                                "group": s.get("group"), "material": s.get("material")})
        self.shell_index = {s["id"]: k for k, s in enumerate(self.shells)}
        if not self.elements and not self.shells:
            raise ModelError("The model has no elements")

        # Only nodes attached to elements take part in the analysis.
        used = set()
        for e in self.elements:
            used.add(e["i"])
            used.add(e["j"])
        for s in self.shells:
            used.update(s["nodes"])
        orphan = [n for n in self.node_ids if n not in used]
        if orphan:
            self.warnings.append({"level": "info", "code": "orphan_nodes",
                                  "message": f"{len(orphan)} node(s) not connected to any element were ignored",
                                  "nodes": orphan[:50]})
        self.active_nodes = [n for n in self.node_ids if n in used]
        self.nidx = {n: k for k, n in enumerate(self.active_nodes)}
        self.ndof = DOF * len(self.active_nodes)

        self.restrained = np.zeros(self.ndof, dtype=bool)
        self.supports = {}
        for s in data.get("supports", []):
            if s["node"] not in self.nidx:
                self.warnings.append({"level": "warning", "code": "support_on_orphan",
                                      "message": f"Support at node {s['node']} is not connected to any element"})
                continue
            dofs = s.get("dofs") or SUPPORT_TYPES[s.get("type", "fixed")]
            self.supports[s["node"]] = list(map(int, dofs))
            base = DOF * self.nidx[s["node"]]
            for d in range(DOF):
                if dofs[d]:
                    self.restrained[base + d] = True

        self._check_connectivity()
        self.K = self._assemble()
        self.free = np.where(~self.restrained)[0]
        self._factorize()

    # ---------------------------------------------------------------- checks
    def _check_connectivity(self):
        parent = list(range(len(self.active_nodes)))

        def find(a):
            while parent[a] != a:
                parent[a] = parent[parent[a]]
                a = parent[a]
            return a

        pairs = [(e["i"], e["j"]) for e in self.elements]
        pairs += [(s["nodes"][0], n) for s in self.shells for n in s["nodes"][1:]]
        for a, b in pairs:
            ra, rb = find(self.nidx[a]), find(self.nidx[b])
            if ra != rb:
                parent[ra] = rb
        groups: dict[int, list] = {}
        for n in self.active_nodes:
            groups.setdefault(find(self.nidx[n]), []).append(n)
        self.unsupported_nodes = []
        for g in groups.values():
            if not any(n in self.supports for n in g):
                self.unsupported_nodes += g
        if not self.supports:
            raise ModelError("The model has no supports - it cannot be analysed")
        if self.unsupported_nodes:
            self.warnings.append({
                "level": "error", "code": "disconnected",
                "message": f"{len(self.unsupported_nodes)} node(s) belong to parts of the structure that are not "
                           f"connected to any support. Those parts are unstable.",
                "nodes": self.unsupported_nodes[:50]})
        if len(groups) > 1:
            self.warnings.append({"level": "warning", "code": "multiple_parts",
                                  "message": f"The structure consists of {len(groups)} separate parts"})

    def _assemble(self):
        rows, cols, vals = [], [], []
        for e in self.elements:
            T = np.kron(np.eye(4), e["R"])
            kg = T.T @ e["k_local"] @ T
            e["T"] = T
            dofs = np.r_[DOF * self.nidx[e["i"]]: DOF * self.nidx[e["i"]] + 6,
                         DOF * self.nidx[e["j"]]: DOF * self.nidx[e["j"]] + 6]
            e["dofs"] = dofs
            rr, cc = np.meshgrid(dofs, dofs, indexing="ij")
            rows.append(rr.ravel())
            cols.append(cc.ravel())
            vals.append(kg.ravel())
        for s in self.shells:
            dofs = np.concatenate([np.arange(DOF * self.nidx[n], DOF * self.nidx[n] + 6) for n in s["nodes"]])
            s["dofs"] = dofs
            rr, cc = np.meshgrid(dofs, dofs, indexing="ij")
            rows.append(rr.ravel())
            cols.append(cc.ravel())
            vals.append(s["el"].k_global.ravel())
        return sp.csc_matrix((np.concatenate(vals), (np.concatenate(rows), np.concatenate(cols))),
                             shape=(self.ndof, self.ndof))

    def _dof_label(self, g):
        return f"node {self.active_nodes[g // DOF]} {DOF_NAMES[g % DOF]}"

    def _factorize(self):
        Kff = self.K[self.free][:, self.free].tocsc()
        diag = np.abs(Kff.diagonal())
        scale = diag.max() if diag.size else 1.0
        self.unstable_dofs = []
        zero = np.where(diag <= 1e-12 * scale)[0]
        if zero.size:
            labels = [self._dof_label(self.free[z]) for z in zero[:20]]
            self.unstable_dofs += [int(self.free[z]) for z in zero]
            self.warnings.append({"level": "error", "code": "zero_stiffness",
                                  "message": f"{zero.size} free DOF(s) have no stiffness (e.g. {', '.join(labels[:5])}). "
                                             f"They were restrained to allow a solution; results near them are not meaningful.",
                                  "dofs": labels})
            # restrain to make solvable but keep flag
            Kff = Kff + sp.csc_matrix((np.where(diag <= 1e-12 * scale, scale, 0.0), (np.arange(diag.size), np.arange(diag.size))),
                                      shape=Kff.shape)
        # Nodes in parts that are not connected to any support: restrain them so
        # the rest of the structure can still be solved (they are flagged above).
        if self.unsupported_nodes:
            fix = np.zeros(self.ndof, dtype=bool)
            for n in self.unsupported_nodes:
                fix[DOF * self.nidx[n]: DOF * self.nidx[n] + 6] = True
            mask = fix[self.free].astype(float) * scale
            Kff = Kff + sp.diags(mask, format="csc")
        self.regularized = False
        try:
            self.lu = spla.splu(Kff, permc_spec="COLAMD")
            Ud = np.abs(self.lu.U.diagonal())
            singular = bool((Ud <= 1e-10 * scale).any())
        except RuntimeError:
            singular = True
        if singular:
            # Mechanism: add a very soft spring to ground on every free DOF
            # (1e-9 x max stiffness) to locate the mechanism. Results are flagged.
            self.regularized = True
            self.lu = spla.splu(Kff + sp.diags(np.full(diag.size, 1e-9 * scale), format="csc"), permc_spec="COLAMD")
            Ud = np.abs(self.lu.U.diagonal())
            small = np.where(Ud <= 1e-7 * scale)[0]
            dofs = [int(self.free[self.lu.perm_c[k]]) for k in small]
            self.unstable_dofs += dofs
            labels = [self._dof_label(d) for d in dofs[:20]]
            self.warnings.append({"level": "error", "code": "mechanism",
                                  "message": "The stiffness matrix is singular: the structure or part of it is a mechanism "
                                             "(insufficient supports or internal instability). "
                                             + (f"Suspect DOFs: {', '.join(labels[:5])}. " if labels else "")
                                             + "Results are not valid until this is fixed.",
                                  "dofs": labels})
        self.Kff_scale = scale

    # ---------------------------------------------------------------- loads
    def _case_loads(self, case_id: str):
        """Return (F global nodal vector, {el_index: MemberLoadLocal}, applied resultant).

        Shell surface loads are converted to consistent nodal forces; they are
        also kept per shell (self._shell_f) so that element nodal forces can be recovered."""
        F = np.zeros(self.ndof)
        member: dict[int, MemberLoadLocal] = {}
        shell_f: dict[int, np.ndarray] = {}
        resultant = np.zeros(6)  # Fx Fy Fz Mx My Mz about origin
        lost = 0.0

        def ml(k):
            if k not in member:
                member[k] = MemberLoadLocal()
            return member[k]

        case = next((c for c in self.data.get("load_cases", []) if c["id"] == case_id), None)
        if case is None:
            raise ModelError(f"Unknown load case {case_id}")
        if case.get("self_weight"):
            for k, e in enumerate(self.elements):
                w = e["mat"]["density"] * e["props"].A
                if w > 0:
                    q = e["R"] @ np.array([0, 0, -w])
                    ml(k).dist.append((0.0, e["L"], q, q.copy()))
                    xi, xj = self.node_xyz[e["i"]], self.node_xyz[e["j"]]
                    Ftot = np.array([0, 0, -w * e["L"]])
                    resultant[:3] += Ftot
                    resultant[3:] += np.cross(0.5 * (xi + xj), Ftot)
            for k, s in enumerate(self.shells):
                el = s["el"]
                w = el.density * el.t
                if w > 0:
                    shell_f[k] = shell_f.get(k, 0) + el.pressure_load([0.0, 0.0, -w])

        def shell_targets(ld):
            ids = ld.get("shells") or ([ld["shell"]] if "shell" in ld else [])
            if ld.get("group") is not None:
                ids = [s["id"] for s in self.shells if s["group"] == ld["group"]]
            return ids

        for ld in self.data.get("loads", []):
            if ld.get("case") != case_id:
                continue
            kind = ld["kind"]
            if kind == "nodal":
                if ld["node"] not in self.nidx:
                    lost += float(np.linalg.norm(ld["values"][:3]))
                    continue
                vals = np.array(ld["values"], dtype=float)
                b = DOF * self.nidx[ld["node"]]
                F[b:b + 6] += vals
                resultant[:3] += vals[:3]
                resultant[3:] += vals[3:] + np.cross(self.node_xyz[ld["node"]], vals[:3])
            elif kind in ("dist", "point"):
                k = self.el_index.get(ld["element"])
                if k is None:
                    lost += 1.0
                    continue
                e = self.elements[k]
                xi = self.node_xyz[e["i"]]
                ex = e["R"][0]
                if "direction" in ld:
                    dvec = np.asarray(ld["direction"], dtype=float)
                    dvec = dvec / np.linalg.norm(dvec)
                    dloc = e["R"] @ dvec
                else:  # local axis 'x' | 'y' | 'z'
                    dloc = np.eye(3)["xyz".index(ld.get("local", "z"))]
                    dvec = e["R"].T @ dloc
                if kind == "dist":
                    pts = ld["points"]  # [[x, w], ...] with x in metres from end i (or relative if 'relative')
                    rel = ld.get("relative", False)
                    for (xa, wa), (xb, wb) in zip(pts[:-1], pts[1:]):
                        xa, xb = (xa * e["L"], xb * e["L"]) if rel else (xa, xb)
                        xa, xb = max(0.0, xa), min(e["L"], xb)
                        if xb - xa <= 1e-12:
                            continue
                        ml(k).dist.append((xa, xb, wa * dloc, wb * dloc))
                        Ftot = 0.5 * (wa + wb) * (xb - xa)
                        # centroid of trapezoid
                        xc = xa + (xb - xa) * ((wa + 2 * wb) / (3 * (wa + wb)) if abs(wa + wb) > 1e-15 else 0.5)
                        resultant[:3] += Ftot * dvec
                        resultant[3:] += np.cross(xi + xc * ex, Ftot * dvec)
                else:
                    a = ld["a"] * e["L"] if ld.get("relative", False) else ld["a"]
                    P = float(ld["P"])
                    ml(k).point.append((a, P * dloc))
                    resultant[:3] += P * dvec
                    resultant[3:] += np.cross(xi + a * ex, P * dvec)
            elif kind == "pressure":
                q = float(ld["q"])
                for sid in shell_targets(ld):
                    k = self.shell_index.get(sid)
                    if k is None:
                        lost += 1.0
                        continue
                    el = self.shells[k]["el"]
                    if ld.get("normal"):
                        dvec = el.R[2]
                    else:
                        dvec = np.asarray(ld.get("direction", [0, 0, -1]), dtype=float)
                        dvec = dvec / np.linalg.norm(dvec)
                    shell_f[k] = shell_f.get(k, 0) + el.pressure_load(q * dvec)
            else:
                raise ModelError(f"Unsupported load kind '{kind}' (area loads must be converted first)")
        for k, f in shell_f.items():
            s = self.shells[k]
            for a, n in enumerate(s["nodes"]):
                fa = f[6 * a: 6 * a + 3]
                F[DOF * self.nidx[n]: DOF * self.nidx[n] + 3] += fa
                resultant[:3] += fa
                resultant[3:] += np.cross(self.node_xyz[n], fa)
        self._lost = lost
        self._shell_f = shell_f
        return F, member, resultant

    # ---------------------------------------------------------------- solve
    def prepare_stations(self, case_ids):
        """Use the same output stations for an element in every load case so that
        results can be superposed exactly for load combinations."""
        self.extra_bps = {}
        for cid in case_ids:
            _, member, _ = self._case_loads(cid)[:3]
            for k, mlo in member.items():
                L = self.elements[k]["L"]
                pts = [b for b in mlo.breakpoints() if 1e-9 < b < L - 1e-9]
                pts += [a + 1e-6 * L for a, _ in mlo.point if 1e-9 < a < L * (1 - 2e-6)]
                self.extra_bps.setdefault(k, set()).update(round(x, 9) for x in pts)

    def solve_case(self, case_id: str, n_stations: int = 11) -> dict:
        F, member, applied = self._case_loads(case_id)
        Fe = F.copy()
        for k, mlo in member.items():
            e = self.elements[k]
            Fe[e["dofs"]] += e["T"].T @ mlo.equivalent_nodal(e["L"])

        u = np.zeros(self.ndof)
        rhs = Fe[self.free]
        u[self.free] = self.lu.solve(rhs)
        resid = self.K @ u - Fe
        rel_resid = float(np.linalg.norm(resid[self.free]) / max(np.linalg.norm(rhs), 1e-12))
        reactions_vec = resid  # K u - F at restrained dofs

        shell_f = self._shell_f
        warnings = []
        if self._lost:
            warnings.append({"level": "warning", "code": "load_target_missing",
                             "message": "Some loads refer to missing nodes or elements and were ignored."})
        if rel_resid > 1e-6:
            warnings.append({"level": "error", "code": "residual",
                             "message": f"Solution residual is high ({rel_resid:.2e}); the system is ill-conditioned or unstable."})

        displacements = {n: u[DOF * k: DOF * k + 6].tolist() for n, k in self.nidx.items()}
        reactions = {}
        react_res = np.zeros(6)
        for n in self.supports:
            b = DOF * self.nidx[n]
            r = np.where(self.restrained[b:b + 6], reactions_vec[b:b + 6], 0.0)
            reactions[n] = r.tolist()
            react_res[:3] += r[:3]
            react_res[3:] += r[3:] + np.cross(self.node_xyz[n], r[:3])

        el_results = {}
        for k, e in enumerate(self.elements):
            mlo = member.get(k, MemberLoadLocal())
            d_loc = e["T"] @ u[e["dofs"]]
            f = e["k_local"] @ d_loc - mlo.equivalent_nodal(e["L"])
            extra = sorted(getattr(self, "extra_bps", {}).get(k, ()))
            el_results[e["id"]] = self._stations(e, f, d_loc, mlo, e["nst"] or n_stations, extra)

        shell_results = {}
        shell_fe = {}
        shell_node_force = {}
        for k, s in enumerate(self.shells):
            el = s["el"]
            ue = u[s["dofs"]]
            fe = el.k_global @ ue - shell_f.get(k, 0)      # forces the nodes exert on the shell (global)
            rr = (el.recovery() @ ue).reshape(5, 8)
            shell_results[s["id"]] = {"c": rr[0].tolist(), "n": rr[1:].tolist()}
            shell_fe[s["id"]] = np.concatenate([fe[6 * a: 6 * a + 3] for a in range(4)])
            for a, n in enumerate(s["nodes"]):
                acc = shell_node_force.setdefault(n, np.zeros(3))
                acc -= fe[6 * a: 6 * a + 3]                # force the shell exerts on the node
        diff = applied + react_res
        size = max(1.0, *(np.linalg.norm(self.node_xyz[n]) for n in self.active_nodes))
        fscale = max(np.abs(applied[:3]).max(), 1e-9)
        ferr = float(np.abs(diff[:3]).max())
        merr = float(np.abs(diff[3:]).max())
        ok = ferr <= 1e-6 * fscale + 1e-9 and merr <= 1e-6 * fscale * size + 1e-9
        max_t = max((math.hypot(*u[DOF * k: DOF * k + 3]) for k in range(len(self.active_nodes))), default=0.0)
        if max_t > 0.1 * size:
            warnings.append({"level": "warning", "code": "large_displacement",
                             "message": f"Maximum displacement {max_t * 1000:.0f} mm is very large compared to the model size; "
                                        f"check for instability or under-sized members. Linear theory is not valid here."})

        return {
            "case": case_id,
            "displacements": displacements,
            "reactions": reactions,
            "elements": el_results,
            "shells": shell_results,
            "shell_node_force": {n: v.tolist() for n, v in shell_node_force.items()},
            "_shell_fe": shell_fe,
            "equilibrium": {
                "applied": applied.tolist(),
                "reactions": react_res.tolist(),
                "force_error": ferr, "moment_error": merr, "ok": bool(ok),
                "residual": rel_resid,
            },
            "warnings": warnings,
        }

    def _stations(self, e, f, d_loc, mlo: MemberLoadLocal, n_stations, extra=()):
        L = e["L"]
        p = e["props"]
        E, G = e["mat"]["E"], e["mat"]["G"]
        # dense grid for curvature integration (+ breakpoints)
        bps = [b for b in mlo.breakpoints() if 1e-9 < b < L - 1e-9]
        bps += [a + 1e-6 * L for a, _ in mlo.point if 1e-9 < a < L * (1 - 2e-6)]  # right side of jumps
        out_x = np.unique(np.r_[np.linspace(0, L, n_stations), bps, list(extra)])
        dense = np.unique(np.r_[np.linspace(0, L, e["ndense"]), bps, out_x])
        fi = f[:6]
        R, Mq = mlo.integrals(dense)
        x = dense
        Fd = np.column_stack([
            -fi[0] - R[:, 0],
            -fi[1] - R[:, 1],
            -fi[2] - R[:, 2],
            np.full_like(x, -fi[3]),
            -fi[4] - x * fi[2] + Mq[:, 2],
            -fi[5] + x * fi[1] - Mq[:, 1],
        ])
        # deflections in local coords: integrate strain / curvature from end i
        k1 = cumulative_simpson(np.vstack([Fd[:, 0] / (E * p.A), Fd[:, 5] / (E * p.Iz), Fd[:, 4] / (E * p.Iy)]),
                                x=dense, initial=0.0, axis=1)
        u = d_loc[0] + k1[0]
        thz = d_loc[5] + k1[1]
        thy = d_loc[4] + k1[2]
        k2 = cumulative_simpson(np.vstack([thz, thy]), x=dense, initial=0.0, axis=1)
        v = d_loc[1] + k2[0]
        w = d_loc[2] - k2[1]
        loc = np.vstack([u, v, w])  # 3 x n
        glob = e["R"].T @ loc
        sel = np.searchsorted(dense, out_x)
        # Point loads cause jumps: evaluate forces just left/right of a jump
        Fo = Fd[sel]
        # stresses (extreme fibre, elastic): sigma = N/A +- My/Sy +- Mz/Sz
        sig = Fo[:, 0] / p.A
        bend = np.abs(Fo[:, 4]) / p.Sy + np.abs(Fo[:, 5]) / p.Sz
        smax = sig + bend
        smin = sig - bend
        return {
            "x": out_x.tolist(),
            "N": Fo[:, 0].tolist(), "Vy": Fo[:, 1].tolist(), "Vz": Fo[:, 2].tolist(),
            "T": Fo[:, 3].tolist(), "My": Fo[:, 4].tolist(), "Mz": Fo[:, 5].tolist(),
            "disp": glob[:, sel].T.tolist(),            # global displacement at stations (m)
            "sigma_max": smax.tolist(), "sigma_min": smin.tolist(),   # kN/m^2
            "end_i": f[:6].tolist(), "end_j": f[6:].tolist(),          # local end forces (node on member)
            "end_check": float(abs(v[-1] - d_loc[7]) + abs(w[-1] - d_loc[8])),
        }

    def element_info(self):
        return {e["id"]: {"L": e["L"], "axes": e["R"].tolist(), "props": e["props"].as_dict(),
                          "E": e["mat"]["E"], "G": e["mat"]["G"], "material": e["material"]}
                for e in self.elements}
