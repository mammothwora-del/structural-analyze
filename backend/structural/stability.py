"""Stability analyses: linear (eigenvalue) buckling and P-Delta second-order analysis.

Both use the geometric stiffness of the 3D frame element (consistent with the cubic Hermitian shape functions
used for the elastic stiffness):

    Kg = N * integral( N_v'^T N_v' + N_w'^T N_w' ) dx  +  N * (Iy + Iz) / (A L) * torsion term

with N the axial force (tension positive). For members with end releases the geometric stiffness is condensed
to first order in the load factor, consistently with the condensed elastic stiffness.

* Buckling: K phi = lambda (-Kg(N)) phi for the axial forces N of the selected load case or combination. Every
  member is subdivided (default 4 segments) so that member (Euler) buckling between nodes is captured.
* P-Delta: (K + Kg(N)) u = F, iterated until the axial forces converge, for one load case or combination
  (second-order effects do not superpose). Members are not subdivided: this captures the P-Delta effect of the
  displaced nodes (sway); the P-delta effect along a member is only approximated by its one element.

Shell elements (slabs, walls) contribute elastic stiffness only: plate and wall buckling are NOT captured.
"""
from __future__ import annotations

import copy
import math
import time

import numpy as np
import scipy.linalg as sla
import scipy.sparse as sp
import scipy.sparse.linalg as spla

from .mesh import _split_member_load, build_fe_model
from .slabs import expand_area_loads
from .solver import DOF, FrameModel, MemberLoadLocal, ModelError, element_releases, shape_matrix

_G3 = (np.array([-math.sqrt(0.6), 0.0, math.sqrt(0.6)]), np.array([5 / 9, 8 / 9, 5 / 9]))


def _dshape(xi, L, h=1e-6):
    """d/dx of the transverse rows (v, w) of the shape matrix (central difference of exact cubics)."""
    a, b = max(0.0, xi - h), min(1.0, xi + h)
    return (shape_matrix(b, L)[1:] - shape_matrix(a, L)[1:]) / ((b - a) * L)


def kg_unit(L, A, Iy, Iz):
    """Local 12x12 geometric stiffness for N = +1 (tension)."""
    G = np.zeros((12, 12))
    for g, w in zip(*_G3):
        xi = 0.5 * (g + 1)
        D = _dshape(xi, L)
        G += (D.T @ D) * (w * L / 2)
    G[np.abs(G) < 1e-12 * np.abs(G).max()] = 0.0
    t = (Iy + Iz) / (A * L)
    G[3, 3] += t
    G[9, 9] += t
    G[3, 9] -= t
    G[9, 3] -= t
    # exact Hermitian values (removes the finite-difference noise)
    return 0.5 * (G + G.T)


def _kg_local(e, N):
    p = e["props"]
    G = N * kg_unit(e["L"], p.A, p.Iy, p.Iz)
    if e["rel"].size:
        r, c = e["rel"], e["keep"]
        X = e["Krr_inv"] @ e["Krc"]
        Gc = np.zeros((12, 12))
        Gc[np.ix_(c, c)] = (G[np.ix_(c, c)] - G[np.ix_(c, r)] @ X - X.T @ G[np.ix_(r, c)] + X.T @ G[np.ix_(r, r)] @ X)
        return Gc
    return G


def assemble_kg(fm: FrameModel, N: np.ndarray):
    rows, cols, vals = [], [], []
    for k, e in enumerate(fm.elements):
        if abs(N[k]) < 1e-14:
            continue
        kg = e["T"].T @ _kg_local(e, N[k]) @ e["T"]
        rr, cc = np.meshgrid(e["dofs"], e["dofs"], indexing="ij")
        rows.append(rr.ravel())
        cols.append(cc.ravel())
        vals.append(kg.ravel())
    if not vals:
        return sp.csc_matrix((fm.ndof, fm.ndof))
    return sp.csc_matrix((np.concatenate(vals), (np.concatenate(rows), np.concatenate(cols))), shape=(fm.ndof, fm.ndof))


def _scaled(mlo: MemberLoadLocal, f: float) -> MemberLoadLocal:
    return MemberLoadLocal(dist=[(a, b, f * q0, f * q1) for a, b, q0, q1 in mlo.dist],
                           point=[(a, f * P) for a, P in mlo.point])


def combined_loads(fm: FrameModel, factors: dict):
    """Global nodal vector (incl. equivalent member loads), member loads and applied resultant of a combination."""
    F = np.zeros(fm.ndof)
    member: dict[int, MemberLoadLocal] = {}
    applied = np.zeros(6)
    shell_f = {}
    for cid, f in factors.items():
        Fc, mc, ac = fm._case_loads(cid)
        F += f * Fc
        applied += f * ac
        for k, v in fm._shell_f.items():
            shell_f[k] = shell_f.get(k, 0) + f * v
        for k, mlo in mc.items():
            s = _scaled(mlo, f)
            m = member.setdefault(k, MemberLoadLocal())
            m.dist += s.dist
            m.point += s.point
    Fe = F.copy()
    for k, mlo in member.items():
        e = fm.elements[k]
        Fe[e["dofs"]] += e["T"].T @ fm._eq(e, mlo)[0]
    fm._shell_f = shell_f
    return Fe, member, applied


def _axial(fm, u, member, N_prev=None):
    """Average axial force of every element (tension +) for displacements u."""
    N = np.zeros(len(fm.elements))
    for k, e in enumerate(fm.elements):
        d = e["T"] @ u[e["dofs"]]
        Pc, _ = fm._eq(e, member.get(k, MemberLoadLocal()))
        kl = e["k_local"] + (_kg_local(e, N_prev[k]) if N_prev is not None else 0)
        f = kl @ d - Pc
        N[k] = 0.5 * (-f[0] + f[6])
    return N


def _active(fm):
    """Free DOFs that carry stiffness (pin-joint rotations removed)."""
    pinned = set(getattr(fm, "pinned_rotations", []))
    return np.array([d for d in fm.free if d not in pinned], dtype=int)


def subdivide(fe_model: dict, n_seg: int):
    """Split every frame member into n_seg equal segments (bending end releases kept at the member ends)."""
    if n_seg <= 1:
        return copy.deepcopy(fe_model), {}
    out = copy.deepcopy(fe_model)
    xyz = {n["id"]: np.array([n["x"], n["y"], n["z"]], dtype=float) for n in out["nodes"]}
    new_nodes, new_el, split, twist = [], [], {}, []
    for e in fe_model["elements"]:
        xi, xj = xyz[e["i"]], xyz[e["j"]]
        L = float(np.linalg.norm(xj - xi))
        chain = [e["i"]]
        for s in range(1, n_seg):
            p = xi + (xj - xi) * s / n_seg
            nid = f"{e['id']}#n{s}"
            new_nodes.append({"id": nid, "x": float(p[0]), "y": float(p[1]), "z": float(p[2]), "sub": True})
            chain.append(nid)
        chain.append(e["j"])
        ri, rj = list(element_releases(e))
        if ri[3] or rj[3]:
            # Pin-ended member with a torsion release: release torsion at both ends of the segment chain (so the
            # joints stay pin joints, as in the linear model) and hold the chain's free twist about its own axis
            # with a spring at the interior nodes (twist of a pin-ended rod carries no load).
            ri, rj = list(ri), list(rj)
            ri[3] = rj[3] = 1
            axis = ((xj - xi) / L).tolist()
            twist += [{"node": c, "axis": axis} for c in chain[1:-1]]
        subs = []
        for s in range(n_seg):
            sub = {**copy.deepcopy(e), "id": f"{e['id']}#{s + 1}", "i": chain[s], "j": chain[s + 1],
                   "releases": {"i": ri if s == 0 else [0] * 6, "j": rj if s == n_seg - 1 else [0] * 6},
                   "n_stations": 3, "n_dense": 9}
            sub.pop("truss", None)
            new_el.append(sub)
            subs.append({"id": sub["id"], "s0": L * s / n_seg, "s1": L * (s + 1) / n_seg, "j": chain[s + 1]})
        split[e["id"]] = {"L": L, "subs": subs, "chain": chain}
    out["nodes"] = out["nodes"] + new_nodes
    out["elements"] = new_el
    out["_twist_springs"] = twist
    loads = []
    for ld in out.get("loads", []):
        if ld.get("kind") in ("dist", "point") and ld.get("element") in split:
            loads += _split_member_load(ld, split[ld["element"]])
        else:
            loads.append(ld)
    out["loads"] = loads
    return out, split


def _prepare(model: dict):
    slab_shells = model.get("settings", {}).get("slab_model") == "shell" and bool(model.get("slabs"))
    if slab_shells:
        analysis_model, warnings = copy.deepcopy(model), []
    else:
        analysis_model, _, warnings = expand_area_loads(model)
    try:
        fe_model, meta, mw = build_fe_model(analysis_model, slab_shells)
    except ValueError as exc:
        raise ModelError(str(exc)) from exc
    return fe_model, meta, warnings + mw


def _factors(model: dict, load_id: str):
    cases = {c["id"] for c in model.get("load_cases", [])}
    if load_id in cases:
        return {load_id: 1.0}, load_id
    for c in model.get("combinations", []):
        if c["id"] == load_id:
            return {k: float(v) for k, v in c["factors"].items() if k in cases}, c.get("name", load_id)
    raise ModelError(f"Unknown load case or combination '{load_id}'")


def buckling(model: dict, load_id: str, n_modes: int = 4, n_seg: int = 4) -> dict:
    t0 = time.perf_counter()
    factors, name = _factors(model, load_id)
    fe_model, meta, warnings = _prepare(model)
    fe_b, split = subdivide(fe_model, n_seg)
    fm = FrameModel(fe_b)
    warnings = warnings + fm.warnings
    if fm.regularized or any(w["level"] == "error" for w in fm.warnings):
        raise ModelError("The structure is unstable (mechanism or unsupported parts) - fix the linear analysis "
                         "errors before running a buckling analysis.")
    Fe, member, _ = combined_loads(fm, factors)
    u = np.zeros(fm.ndof)
    u[fm.free] = fm.lu.solve(Fe[fm.free])
    N = _axial(fm, u, member)
    Kg = assemble_kg(fm, N)
    act = _active(fm)
    K = (fm.K + fm.K_fix)[act][:, act].tocsc()
    G = (-Kg[act][:, act]).tocsc()
    n = len(act)
    k = max(1, min(int(n_modes), n - 2))
    if abs(G).max() < 1e-12 or n < 3:
        mu, vec = np.zeros(0), np.zeros((n, 0))
    elif n <= 1800:
        mu, vec = sla.eigh(G.toarray(), K.toarray(), subset_by_index=[n - k, n - 1])
    else:
        mu, vec = spla.eigsh(G, k=k, M=K, which="LA", ncv=min(n - 1, max(4 * k + 1, 40)), tol=1e-9, maxiter=5000)
    order = np.argsort(-mu)
    modes = []
    for idx in order:
        if mu[idx] <= 1e-12:
            continue
        lam = 1.0 / mu[idx]
        phi = np.zeros(fm.ndof)
        phi[act] = vec[:, idx]
        trans = np.array([phi[DOF * j: DOF * j + 3] for j in range(len(fm.active_nodes))])
        s = np.linalg.norm(trans, axis=1).max()
        phi /= s if s > 0 else 1.0
        nodes = {nid: phi[DOF * j: DOF * j + 3].tolist() for nid, j in fm.nidx.items() if "#n" not in nid}
        members = {}
        for eid, info in split.items():
            members[eid] = [[*map(float, fm.node_xyz[c]), *phi[DOF * fm.nidx[c]: DOF * fm.nidx[c] + 3].tolist()] for c in info["chain"]]
        members = _merge_mesh_split(members, meta)
        modes.append({"factor": float(lam), "nodes": nodes, "members": members})   # members: [x, y, z, ux, uy, uz] along each member
    notes = [f"Axial forces from a linear analysis of {name}; every member subdivided into {n_seg} segments.",
             "Load factor = multiple of this load at which the elastic structure buckles (no imperfections, "
             "no material yielding). A factor below 1 means elastic buckling before the full load is reached."]
    if fm.shells:
        notes.append("Slabs and walls (shells) give elastic stiffness only: plate/wall buckling is NOT included.")
    if not modes:
        notes.append("No buckling mode found: under this load every member is in tension or the axial forces are negligible.")
    return {"load": load_id, "load_name": name, "factors": factors, "n_seg": n_seg, "modes": modes, "notes": notes,
            "warnings": warnings, "ndof": int(n), "time_ms": (time.perf_counter() - t0) * 1000}


def _merge_mesh_split(members, meta):
    """Members split at slab/wall mesh nodes: join the sub-element polylines under the parent id."""
    if not meta:
        return members
    for pid, info in meta["split"].items():
        pts = []
        for k, sb in enumerate(info["subs"]):
            seg = members.pop(sb["id"], [])
            pts += seg if k == 0 else seg[1:]
        members[pid] = pts
    return members


def _merge_sub(els: dict, split: dict):
    """Join the station results of subdivided members under the member id."""
    for pid, info in split.items():
        parts = [els.pop(sb["id"]) for sb in info["subs"]]
        L = info["L"]
        m = {k: [] for k in ("x", "N", "Vy", "Vz", "T", "My", "Mz", "disp", "sigma_max", "sigma_min")}
        for k, (sb, st) in enumerate(zip(info["subs"], parts)):
            xs = [sb["s0"] + x for x in st["x"]]
            if k > 0:
                xs, st = xs[1:], {c: st[c][1:] for c in m if c != "x"}
            m["x"] += xs
            for c in m:
                if c != "x":
                    m[c] += st[c]
        m["end_i"], m["end_j"] = parts[0]["end_i"], parts[-1]["end_j"]
        m["end_check"] = max(p["end_check"] for p in parts)
        els[pid] = m
    return els


def pdelta(model: dict, load_id: str, max_iter: int = 30, tol: float = 1e-5, n_stations: int = 11, n_seg: int = 2) -> dict:
    """Second-order (P-Delta) analysis of one load case or combination."""
    from .analysis import _r
    from .mesh import merge_case
    t0 = time.perf_counter()
    factors, name = _factors(model, load_id)
    fe_model, meta, warnings = _prepare(model)
    fe_model, split = subdivide(fe_model, n_seg)
    fm = FrameModel(fe_model)
    warnings = warnings + fm.warnings
    if fm.regularized or any(w["level"] == "error" for w in fm.warnings):
        raise ModelError("The structure is unstable - fix the linear analysis errors before running P-Delta.")
    Fe, member, applied = combined_loads(fm, factors)
    act = _active(fm)
    u = np.zeros(fm.ndof)
    u[fm.free] = fm.lu.solve(Fe[fm.free])
    u_lin = u.copy()
    N = _axial(fm, u, member)
    hist, converged = [], False
    for it in range(1, max_iter + 1):
        Kt = (fm.K + fm.K_fix + assemble_kg(fm, N))[act][:, act].tocsc()
        lu, neg = _sym_factor(Kt)
        if lu is None:
            raise ModelError("The tangent stiffness K + Kg is singular: the load is at the elastic buckling load.")
        if neg:
            raise ModelError("The tangent stiffness K + Kg is not positive definite: this load exceeds the elastic "
                             "buckling load. Run a buckling analysis.")
        u = np.zeros(fm.ndof)
        u[act] = lu.solve(Fe[act])
        N_new = _axial(fm, u, member, N)
        dN = float(np.abs(N_new - N).max() / max(np.abs(N_new).max(), 1e-9))
        hist.append(dN)
        N = N_new
        if dN < tol:
            converged = True
            break
    if not converged:
        warnings.append({"level": "error", "code": "pdelta_not_converged",
                         "message": f"P-Delta did not converge in {max_iter} iterations (load close to buckling?)."})
    # results in the same format as a linear case
    Kt = fm.K + assemble_kg(fm, N)
    resid = Kt @ u - Fe
    displacements = {n: u[DOF * k: DOF * k + 6].tolist() for n, k in fm.nidx.items() if "#n" not in n}
    reactions = {}
    react_res = np.zeros(6)
    for nid in fm.supports:
        b = DOF * fm.nidx[nid]
        r = np.where(fm.restrained[b:b + 6], resid[b:b + 6], 0.0)
        reactions[nid] = r.tolist()
        react_res[:3] += r[:3]
        react_res[3:] += r[3:] + np.cross(fm.node_xyz[nid], r[:3])
    el_results = {}
    for k, e in enumerate(fm.elements):
        mlo = member.get(k, MemberLoadLocal())
        d = e["T"] @ u[e["dofs"]]
        Pc, Pf = fm._eq(e, mlo)
        f = (e["k_local"] + _kg_local(e, N[k])) @ d - Pc
        d = fm._recover(e, d, Pf)
        el_results[e["id"]] = fm._stations(e, f, d, mlo, max(3, math.ceil(n_stations / n_seg) + 1))
    el_results = _merge_sub(el_results, split)
    shell_results, shell_fe, shell_node_force = {}, {}, {}
    for k, s_ in enumerate(fm.shells):
        el = s_["el"]
        ue = u[s_["dofs"]]
        fe = el.k_global @ ue - fm._shell_f.get(k, 0)
        rr = (el.recovery() @ ue).reshape(5, 8)
        shell_results[s_["id"]] = {"c": rr[0].tolist(), "n": rr[1:].tolist()}
        shell_fe[s_["id"]] = np.concatenate([fe[6 * a: 6 * a + 3] for a in range(4)])
        for a, nid in enumerate(s_["nodes"]):
            acc = shell_node_force.setdefault(nid, np.zeros(3))
            acc -= fe[6 * a: 6 * a + 3]
    res = {"case": load_id, "displacements": displacements, "reactions": reactions, "elements": el_results,
           "shells": shell_results, "_shell_fe": shell_fe, "shell_node_force": {n: v.tolist() for n, v in shell_node_force.items()},
           "equilibrium": {"applied": applied.tolist(), "reactions": react_res.tolist(),
                           "force_error": float(np.abs(applied[:3] + react_res[:3]).max()), "moment_error": 0.0,
                           "ok": bool(np.abs(applied[:3] + react_res[:3]).max() <= 1e-6 * max(np.abs(applied[:3]).max(), 1e-9) + 1e-9),
                           "residual": 0.0, "note": "Vertical/horizontal force balance; moments are taken on the deformed shape."},
           "warnings": []}
    if meta:
        res = merge_case(res, meta)
    else:
        res.pop("_shell_fe", None)
        res.pop("shells", None)

    def max_t(v):
        return max((math.hypot(*v[DOF * j: DOF * j + 3]) for j in range(len(fm.active_nodes))), default=0.0)
    amp = max_t(u) / max(max_t(u_lin), 1e-15)
    out = {"load": load_id, "load_name": name, "factors": factors, "converged": converged, "iterations": len(hist),
           "history": hist, "amplification": amp, "max_disp_linear": max_t(u_lin), "max_disp_pdelta": max_t(u),
           "result": res, "warnings": warnings,
           "notes": [f"P-Delta: equilibrium on the deformed shape through the geometric stiffness (P-Δ sway and, with "
                     f"every member split into {n_seg} elements, P-δ along members approximately).",
                     "Second-order results do not superpose: they are for this load combination only."]
           + (["Slabs and walls give elastic stiffness only (no geometric stiffness)."] if fm.shells else []),
           "time_ms": (time.perf_counter() - t0) * 1000}
    return _r(out)


def _sym_factor(Kt):
    """Symmetric-mode LU without pivoting (an LDL^T): returns (lu, number of negative pivots).

    By Sylvester's law of inertia the number of negative pivots equals the number of negative eigenvalues,
    i.e. the number of buckling loads below the current load level."""
    try:
        lu = spla.splu(Kt, permc_spec="MMD_AT_PLUS_A", diag_pivot_thresh=0.0, options={"SymmetricMode": True})
    except RuntimeError:
        return None, 0
    d = lu.U.diagonal()
    if (np.abs(d) <= 1e-14 * np.abs(d).max()).any():
        return None, 0
    return lu, int((d < 0).sum())


__all__ = ["buckling", "pdelta", "kg_unit", "assemble_kg", "subdivide"]
