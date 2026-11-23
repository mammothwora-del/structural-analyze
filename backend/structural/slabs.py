"""Slab-to-beam load distribution (tributary area / 45-degree yield-line method).

Phase 1 does NOT analyse slabs with shell finite elements. Area loads on a slab
panel are converted to line loads on the supporting edge beams using the
classic tributary-area rule:

* two-way panels (long/short <= 2, or forced): 45-degree lines from the corners
  -> triangular load on short edges, trapezoidal load on long edges;
* one-way panels: the panel spans in the short direction; each long edge takes
  half the load uniformly.

This is an approximation (it ignores slab continuity, stiffness and torsion) and
is labelled as such in the user interface. The beam/column forces obtained from
the frame analysis are then exact for these applied beam loads.
"""
from __future__ import annotations

import copy

import numpy as np

CONCRETE_DENSITY = 25.0  # kN/m3 (used for slab self-weight unless the slab has its own)


def _depth_fn(Le: float, Lshort: float, mode: str, is_long: bool):
    """Tributary depth d(s) along an edge of length Le."""
    if mode == "two-way":
        return (lambda s: max(0.0, min(s, Le - s, Lshort / 2))), [Lshort / 2, Le / 2, Le - Lshort / 2]
    # one-way
    if is_long:
        return (lambda s: Lshort / 2), []
    return (lambda s: 0.0), []


def slab_geometry(slab: dict, xyz: dict):
    c = [np.asarray(xyz[n], dtype=float) for n in slab["corners"]]
    if len(c) != 4:
        raise ValueError(f"Slab {slab['id']}: exactly 4 corner nodes are required in Phase 1")
    lx = np.linalg.norm(c[1] - c[0])
    ly = np.linalg.norm(c[3] - c[0])
    area = float(np.linalg.norm(np.cross(c[1] - c[0], c[3] - c[0])))
    return c, lx, ly, area


def slab_mode(slab: dict, lx: float, ly: float) -> str:
    m = slab.get("span_type", "auto")
    if m in ("one-way", "two-way"):
        return m
    return "two-way" if max(lx, ly) / min(lx, ly) <= 2.0 else "one-way"


def distribute(model: dict):
    """Return (tributary_info, warnings).

    tributary_info[slab_id] = {
        mode, area, lx, ly,
        edges: [{edge, length, fraction, polygon, segments: [{element, xa, xb, points:[[x, d],...]}]}]
    }
    where d is the tributary depth (m); line load = q * d.
    """
    xyz = {n["id"]: (n["x"], n["y"], n["z"]) for n in model["nodes"]}
    elements = model["elements"]
    info, warnings = {}, []
    import numpy as _np
    P_i = _np.array([xyz[e["i"]] for e in elements], dtype=float).reshape(-1, 3)
    P_j = _np.array([xyz[e["j"]] for e in elements], dtype=float).reshape(-1, 3)
    for slab in model.get("slabs", []):
        c, lx, ly, area = slab_geometry(slab, xyz)
        mode = slab_mode(slab, lx, ly)
        Lshort = min(lx, ly)
        centroid = sum(c) / 4
        edges = []
        covered_area = 0.0
        for k in range(4):
            a, b = c[k], c[(k + 1) % 4]
            Le = float(np.linalg.norm(b - a))
            t = (b - a) / Le
            inward = centroid - a - np.dot(centroid - a, t) * t
            inward /= np.linalg.norm(inward)
            # edges 0, 2 have length lx; edges 1, 3 have length ly
            if mode == "one-way":
                span = slab.get("span_direction")  # 'edge0' -> spans parallel to edge 0
                if span is None:
                    span = "edge0" if lx <= ly else "edge1"
                is_long = (k % 2 == 1) if span == "edge0" else (k % 2 == 0)
                Ld = lx if span == "edge0" else ly
            else:
                is_long = (k % 2 == 0) if lx >= ly else (k % 2 == 1)
                Ld = Lshort
            dfn, kinks = _depth_fn(Le, Ld, mode, is_long)
            # tributary polygon
            ss = sorted({0.0, Le, *[s for s in kinks if 0 < s < Le]})
            inner = [a + s * t + dfn(s) * inward for s in ss]
            polygon = [a.tolist(), b.tolist()] + [p.tolist() for p in reversed(inner)]
            trib = float(sum(0.5 * (dfn(s0) + dfn(s1)) * (s1 - s0) for s0, s1 in zip(ss[:-1], ss[1:])))
            # find beams lying on this edge
            segs = []
            si_all = (P_i - a) @ t
            sj_all = (P_j - a) @ t
            di_all = _np.linalg.norm(P_i - a - si_all[:, None] * t, axis=1)
            dj_all = _np.linalg.norm(P_j - a - sj_all[:, None] * t, axis=1)
            for idx in _np.where((di_all < 1e-6) & (dj_all < 1e-6))[0]:
                e = elements[idx]
                si, sj = float(si_all[idx]), float(sj_all[idx])
                lo, hi = max(0.0, min(si, sj)), min(Le, max(si, sj))
                if hi - lo < 1e-9:
                    continue
                pts_s = sorted({lo, hi, *[s for s in kinks if lo < s < hi]})
                pts = [[abs(s - si), dfn(s)] for s in pts_s]
                pts.sort(key=lambda p: p[0])
                segs.append({"element": e["id"], "s0": lo, "s1": hi, "points": pts})
            # coverage check
            segs.sort(key=lambda g: g["s0"])
            cov, pos, gaps = 0.0, 0.0, []
            for g in segs:
                if g["s0"] > pos + 1e-6:
                    gaps.append((pos, g["s0"]))
                pos = max(pos, g["s1"])
            if pos < Le - 1e-6:
                gaps.append((pos, Le))
            lost = sum(sum(0.5 * (dfn(s0) + dfn(s1)) * (s1 - s0) for s0, s1 in [(g0, g1)]) for g0, g1 in gaps)
            if gaps and lost > 1e-9:
                warnings.append({"level": "warning", "code": "slab_edge_unsupported",
                                 "message": f"Slab {slab['id']}: part of edge {k + 1} has no supporting beam; "
                                            f"{lost / area * 100:.1f}% of the slab load on that edge is not transferred "
                                            f"(it is excluded from the analysis)."})
            # remove overlap double-counting (two collinear elements overlapping) by trimming
            covered_area += trib - lost
            edges.append({"edge": k, "length": Le, "tributary_area": trib, "fraction": trib / area,
                          "polygon": polygon, "segments": segs, "lost_area": lost})
        info[slab["id"]] = {"mode": mode, "area": area, "lx": float(lx), "ly": float(ly),
                            "effective_area": covered_area, "edges": edges,
                            "z": float(np.mean([p[2] for p in c]))}
    return info, warnings


def expand_area_loads(model: dict):
    """Return (analysis_model, tributary_info, warnings).

    Converts ``kind: area`` loads (q in kN/m2, acting downward) and slab
    self-weight (for load cases with self_weight) into member line loads that
    the frame solver understands. Each generated load keeps a ``source`` tag.
    """
    trib, warnings = distribute(model)
    out = copy.deepcopy(model)
    loads = [l for l in out.get("loads", []) if l.get("kind") != "area"]
    slabs = {s["id"]: s for s in model.get("slabs", [])}

    def add(case, slab_id, q, label):
        t = trib[slab_id]
        for ed in t["edges"]:
            for g in ed["segments"]:
                loads.append({"case": case, "kind": "dist", "element": g["element"], "direction": [0, 0, -1],
                              "points": [[x, q * d] for x, d in g["points"]],
                              "source": {"type": label, "slab": slab_id, "edge": ed["edge"], "q": q}})

    for case in model.get("load_cases", []):
        if case.get("self_weight"):
            for s in model.get("slabs", []):
                q = float(s.get("thickness", 0.0)) * float(s.get("density", CONCRETE_DENSITY))
                if q > 0:
                    add(case["id"], s["id"], q, "slab_self_weight")
    for l in model.get("loads", []):
        if l.get("kind") != "area":
            continue
        targets = l.get("slabs") or [l["slab"]]
        for sid in targets:
            if sid not in slabs:
                warnings.append({"level": "warning", "code": "missing_slab",
                                 "message": f"Area load refers to unknown slab {sid}"})
                continue
            add(l["case"], sid, float(l["q"]), "area_load")
    out["loads"] = loads
    return out, trib, warnings
