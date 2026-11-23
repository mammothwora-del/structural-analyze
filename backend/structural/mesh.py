"""Shell meshing of slabs and walls and the frame/shell model hand-off.

``build_fe_model(model, slabs_as_shells)`` returns an analysis model in which

* every wall (and every slab when ``slabs_as_shells``) is meshed with 4-node
  shell elements. Axis-aligned rectangular panels share one set of global mesh
  lines per axis, so neighbouring panels, walls and the beams on their edges
  always have matching nodes (a conforming mesh). Other quadrilateral panels get
  a mapped mesh;
* frame members that pass through mesh nodes are split into sub-elements
  ``"<id>~<k>"`` so that slabs and walls are connected to them along their
  length, not just at the corners. Member loads are re-mapped onto the
  sub-elements;
* area loads on slabs become shell pressure loads (slab self-weight comes from
  the shell's thickness and density in self-weight cases);
* wall base nodes get the wall's base support.

``merge_case`` puts the sub-element results back together under the original
member ids, averages shell resultants at nodes per panel for contour plots and
reports the force each panel delivers to each member (slab -> beam transfer
computed by FEM, not by a tributary assumption).
"""
from __future__ import annotations

import copy
import math

import numpy as np

from .slabs import CONCRETE_DENSITY

TOL = 1e-6


def _key(p):
    return tuple(int(round(c / 1e-5)) for c in p)


def _axis_aligned(C: np.ndarray):
    """Return (normal_axis, (a1, a2)) if C (4x3) is an axis-aligned rectangle, else None."""
    span = C.max(axis=0) - C.min(axis=0)
    flat = [a for a in range(3) if span[a] < TOL]
    if len(flat) != 1:
        return None
    n = flat[0]
    a1, a2 = [a for a in range(3) if a != n]
    lo, hi = C.min(axis=0), C.max(axis=0)
    for p in C:
        if not ((abs(p[a1] - lo[a1]) < TOL or abs(p[a1] - hi[a1]) < TOL) and
                (abs(p[a2] - lo[a2]) < TOL or abs(p[a2] - hi[a2]) < TOL)):
            return None
    return n, (a1, a2)


def _subdivide(breaks, h):
    out = []
    for a, b in zip(breaks[:-1], breaks[1:]):
        m = max(1, math.ceil((b - a) / h - 1e-9))
        out += [a + (b - a) * k / m for k in range(m)]
    out.append(breaks[-1])
    return np.array(out)


def build_fe_model(model: dict, slabs_as_shells: bool):
    settings = model.get("settings", {})
    h = float(settings.get("mesh_size", 1.0) or 1.0)
    h = min(max(h, 0.1), 10.0)
    xyz = {n["id"]: np.array([n["x"], n["y"], n["z"]], dtype=float) for n in model["nodes"]}
    warnings = []

    panels = []
    if slabs_as_shells:
        for s in model.get("slabs", []):
            panels.append({"id": s["id"], "kind": "slab", "corners": s["corners"], "t": float(s.get("thickness", 0.2)),
                           "material": s.get("material"), "density": s.get("density", CONCRETE_DENSITY)})
    for w in model.get("walls", []):
        panels.append({"id": w["id"], "kind": "wall", "corners": w["corners"], "t": float(w.get("thickness", 0.2)),
                       "material": w.get("material"), "density": w.get("density"),
                       "base_support": w.get("base_support")})
    if not panels:
        return model, None, warnings

    mats = model.get("materials", {})
    default_mat = next((k for k, v in mats.items() if v.get("kind") == "concrete"), "C30/37")
    for p in panels:
        if any(c not in xyz for c in p["corners"]) or len(p["corners"]) != 4:
            raise ValueError(f"{p['kind'].capitalize()} {p['id']} must have 4 existing corner nodes")
        p["C"] = np.array([xyz[c] for c in p["corners"]])
        p["aa"] = _axis_aligned(p["C"])
        if not p.get("material"):
            p["material"] = default_mat

    # global mesh lines per axis from all axis-aligned panels
    breaks = [set(), set(), set()]
    for p in panels:
        if p["aa"]:
            _, (a1, a2) = p["aa"]
            for a in (a1, a2):
                breaks[a].update(round(float(v), 6) for v in p["C"][:, a])
    lines = [_subdivide(sorted(b), h) if len(b) > 1 else np.array(sorted(b)) for b in breaks]

    node_at = {_key(p): nid for nid, p in xyz.items()}
    new_nodes: dict[str, list] = {}

    def get_node(p):
        k = _key(p)
        nid = node_at.get(k)
        if nid is None:
            nid = f"m{len(new_nodes) + 1}"
            node_at[k] = nid
            new_nodes[nid] = [float(v) for v in p]
        return nid

    shells, groups = [], {}
    for p in panels:
        C = p["C"]
        normal = np.cross(C[2] - C[0], C[3] - C[1])
        if p["aa"]:
            n, (a1, a2) = p["aa"]
            lo, hi = C.min(axis=0), C.max(axis=0)
            u = lines[a1][(lines[a1] >= lo[a1] - TOL) & (lines[a1] <= hi[a1] + TOL)]
            v = lines[a2][(lines[a2] >= lo[a2] - TOL) & (lines[a2] <= hi[a2] + TOL)]
            grid = np.zeros((len(u), len(v), 3))
            grid[:, :, a1] = u[:, None]
            grid[:, :, a2] = v[None, :]
            grid[:, :, n] = C[0, n]
            e1, e2 = np.eye(3)[a1], np.eye(3)[a2]
            flip = np.dot(np.cross(e1, e2), normal) < 0
        else:
            n1 = max(1, math.ceil(max(np.linalg.norm(C[1] - C[0]), np.linalg.norm(C[2] - C[3])) / h - 1e-9))
            n2 = max(1, math.ceil(max(np.linalg.norm(C[3] - C[0]), np.linalg.norm(C[2] - C[1])) / h - 1e-9))
            s = np.linspace(0, 1, n1 + 1)[:, None, None]
            t = np.linspace(0, 1, n2 + 1)[None, :, None]
            grid = (1 - s) * (1 - t) * C[0] + s * (1 - t) * C[1] + s * t * C[2] + (1 - s) * t * C[3]
            flip = False
        ids = [[get_node(grid[i, j]) for j in range(grid.shape[1])] for i in range(grid.shape[0])]
        gnodes, gidx, quads = [], {}, []
        for i in range(grid.shape[0] - 1):
            for j in range(grid.shape[1] - 1):
                q = [ids[i][j], ids[i + 1][j], ids[i + 1][j + 1], ids[i][j + 1]]
                if flip:
                    q = q[::-1]
                sid = f"{p['id']}:{len(quads) + 1}"
                shells.append({"id": sid, "nodes": q, "t": p["t"], "material": p["material"],
                               "density": p["density"], "group": p["id"]})
                for nn in q:
                    if nn not in gidx:
                        gidx[nn] = len(gnodes)
                        gnodes.append(nn)
                quads.append([gidx[nn] for nn in q])
        groups[p["id"]] = {"kind": p["kind"], "t": p["t"], "nodes": gnodes, "quads": quads,
                           "shells": [s["id"] for s in shells[-len(quads):]]}
        p["grid_ids"] = ids

    out = copy.deepcopy(model)
    all_xyz = {**xyz, **{k: np.array(v) for k, v in new_nodes.items()}}
    out["nodes"] = out["nodes"] + [{"id": k, "x": v[0], "y": v[1], "z": v[2], "mesh": True} for k, v in new_nodes.items()]

    # ---- split frame members at mesh nodes lying on them
    M = np.array(list(new_nodes.values())) if new_nodes else np.zeros((0, 3))
    mids = list(new_nodes.keys())
    new_elements, split = [], {}
    for e in model["elements"]:
        xi, xj = xyz[e["i"]], xyz[e["j"]]
        L = float(np.linalg.norm(xj - xi))
        hits = []
        if len(M):
            tdir = (xj - xi) / L
            lo, hi = np.minimum(xi, xj) - TOL, np.maximum(xi, xj) + TOL
            box = np.all((M >= lo) & (M <= hi), axis=1)
            for k in np.where(box)[0]:
                d = M[k] - xi
                s = float(d @ tdir)
                if TOL < s < L - TOL and np.linalg.norm(d - s * tdir) < TOL:
                    hits.append((s, mids[k]))
        if not hits:
            new_elements.append(copy.deepcopy(e))
            continue
        hits.sort()
        chain = [(0.0, e["i"])] + hits + [(L, e["j"])]
        subs = []
        for k, ((sa, na), (sb, nb)) in enumerate(zip(chain[:-1], chain[1:])):
            sub = {**copy.deepcopy(e), "id": f"{e['id']}~{k + 1}", "i": na, "j": nb, "parent": e["id"],
                   "n_stations": max(3, math.ceil(11 * (sb - sa) / L) + 1), "n_dense": 9}
            new_elements.append(sub)
            subs.append({"id": sub["id"], "s0": sa, "s1": sb, "j": nb})
        split[e["id"]] = {"L": L, "subs": subs}
    out["elements"] = new_elements
    out["shells"] = shells

    # ---- loads
    loads = []
    slab_ids = {p["id"] for p in panels if p["kind"] == "slab"}
    for ld in out.get("loads", []):
        kind = ld.get("kind")
        if kind == "area":
            targets = ld.get("slabs") or [ld["slab"]]
            for sid in targets:
                if sid in slab_ids:
                    loads.append({"case": ld["case"], "kind": "pressure", "group": sid, "q": float(ld["q"]),
                                  "direction": [0, 0, -1], "source": {"type": "area_load", "slab": sid, "q": ld["q"]}})
                else:
                    warnings.append({"level": "warning", "code": "missing_slab",
                                     "message": f"Area load refers to unknown slab {sid}"})
        elif kind in ("dist", "point") and ld.get("element") in split:
            loads += _split_member_load(ld, split[ld["element"]])
        else:
            loads.append(ld)
    out["loads"] = loads

    # ---- wall base supports
    supported = {s["node"] for s in out.get("supports", [])}
    for p in panels:
        bs = p.get("base_support")
        if p["kind"] != "wall" or not bs:
            continue
        zmin = p["C"][:, 2].min()
        for row in p["grid_ids"]:
            for nid in row:
                if abs(all_xyz[nid][2] - zmin) < TOL and nid not in supported:
                    out.setdefault("supports", []).append({"node": nid, "type": bs, "wall": p["id"]})
                    supported.add(nid)

    # axes of each group (from the first element, for the legend / interpretation)
    from .shell import shell_frame
    for gid, g in groups.items():
        s0 = shells[[s["id"] for s in shells].index(g["shells"][0])] if g["shells"] else None
        if s0:
            R, *_ = shell_frame(np.array([all_xyz[n] for n in s0["nodes"]]))
            g["axes"] = R.tolist()
        g.pop("shells")

    meta = {"split": split, "groups": groups, "mesh_nodes": new_nodes, "mesh_size": h,
            "original_nodes": set(xyz.keys()), "shell_group": {s["id"]: s["group"] for s in shells},
            "shell_nodes": {s["id"]: s["nodes"] for s in shells}}
    return out, meta, warnings


def _split_member_load(ld, info):
    L = info["L"]
    out = []
    if ld["kind"] == "point":
        a = ld["a"] * L if ld.get("relative") else float(ld["a"])
        for k, sb in enumerate(info["subs"]):
            last = k == len(info["subs"]) - 1
            if sb["s0"] - 1e-12 <= a < sb["s1"] or (last and a <= sb["s1"] + 1e-12):
                out.append({**ld, "element": sb["id"], "a": a - sb["s0"], "relative": False, "parent": ld["element"]})
                break
        return out
    pts = [[x * L if ld.get("relative") else float(x), float(w)] for x, w in ld["points"]]
    xs = np.array([p[0] for p in pts])
    ws = np.array([p[1] for p in pts])
    for sb in info["subs"]:
        s0, s1 = sb["s0"], sb["s1"]
        a, b = max(s0, xs[0]), min(s1, xs[-1])
        if b - a <= 1e-12:
            continue
        inner = [x for x in xs if a < x < b]
        seg = [a, *inner, b]
        # values: interpolate, taking the left/right limits at a and b inside the segment
        vals = []
        for k, x in enumerate(seg):
            if k == 0:
                vals.append(float(np.interp(x, xs, ws, left=0, right=0)) if not np.any(np.isclose(xs, x)) else
                            float(ws[np.where(np.isclose(xs, x))[0][-1]]))
            elif k == len(seg) - 1:
                vals.append(float(np.interp(x, xs, ws)) if not np.any(np.isclose(xs, x)) else
                            float(ws[np.where(np.isclose(xs, x))[0][0]]))
            else:
                vals.append(float(np.interp(x, xs, ws)))
        out.append({**ld, "element": sb["id"], "relative": False, "parent": ld["element"],
                    "points": [[x - s0, v] for x, v in zip(seg, vals)]})
    return out


def merge_case(res: dict, meta: dict) -> dict:
    """Combine sub-element results under the parent member ids; nodal-average shell resultants."""
    split = meta["split"]
    els = res["elements"]
    for pid, info in split.items():
        parts = [els.pop(sb["id"]) for sb in info["subs"]]
        L = info["L"]
        m = {k: [] for k in ("x", "N", "Vy", "Vz", "T", "My", "Mz", "disp", "sigma_max", "sigma_min")}
        for k, (sb, st) in enumerate(zip(info["subs"], parts)):
            xs = [sb["s0"] + x for x in st["x"]]
            if k > 0:
                xs[0] += 1e-6 * L   # right side of the junction (a force may enter there)
            m["x"] += xs
            for c in ("N", "Vy", "Vz", "T", "My", "Mz", "disp", "sigma_max", "sigma_min"):
                m[c] += st[c]
        m["end_i"] = parts[0]["end_i"]
        m["end_j"] = parts[-1]["end_j"]
        m["end_check"] = max(p["end_check"] for p in parts)
        els[pid] = m

    # forces delivered by each panel to the members it is connected to (interior nodes of split members)
    fe = res.pop("_shell_fe", {})
    group_node: dict[str, dict[str, np.ndarray]] = {}
    for sid, f in fe.items():
        g = meta["shell_group"][sid]
        gn = group_node.setdefault(g, {})
        for a, n in enumerate(meta["shell_nodes"][sid]):
            gn[n] = gn.get(n, 0) - np.asarray(f[3 * a: 3 * a + 3])
    transfer = {}
    for pid, info in split.items():
        interior = [sb["j"] for sb in info["subs"][:-1]]
        for g, gn in group_node.items():
            tot = sum((gn[n] for n in interior if n in gn), np.zeros(3))
            if np.abs(tot).max() > 1e-9:
                transfer.setdefault(pid, {})[g] = tot.tolist()
    res["panel_transfer"] = transfer

    # nodal averaged resultants per panel
    shells = res.pop("shells", {})
    nodal = {}
    for g, info in meta["groups"].items():
        acc = np.zeros((len(info["nodes"]), 8))
        cnt = np.zeros(len(info["nodes"]))
        for q, sid in zip(info["quads"], [f"{g}:{k + 1}" for k in range(len(info["quads"]))]):
            r = shells.get(sid)
            if r is None:
                continue
            for a, ni in enumerate(q):
                acc[ni] += r["n"][a]
                cnt[ni] += 1
        nodal[g] = (acc / np.maximum(cnt, 1)[:, None]).tolist()
    res["panel_results"] = nodal
    # shell forces only at nodes of the user's model (for node balance in the load path)
    res["shell_node_force"] = {n: v for n, v in res.get("shell_node_force", {}).items() if n in meta["original_nodes"]}
    return res


def merge_element_info(info: dict, meta: dict) -> dict:
    for pid, sp in meta["split"].items():
        subs = [info.pop(sb["id"]) for sb in sp["subs"]]
        info[pid] = {**subs[0], "L": sp["L"]}
    return info
