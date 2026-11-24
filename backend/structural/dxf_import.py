"""Import a structural wireframe from an ASCII DXF file.

Reads LINE, LWPOLYLINE and POLYLINE/VERTEX entities (model space, any layer) and turns every straight segment into a
member. No DXF library is needed: the file is read as group-code / value pairs.

* Coordinates are scaled to metres from ``options["units"]`` (mm, cm, m, in, ft) or, when that is "auto", from the
  $INSUNITS header (default mm, the usual drawing unit).
* End points closer than ``tol`` (m) are merged into one node; a member is split where another member's end node
  lies on it (T-junctions). Members that truly intersect in 3D (closest distance <= tol, inside both) are connected at
  a new node unless ``connect_crossings`` is false; lines that only cross in a 2D view never meet in 3D and stay apart.
* Member type from the layer name (COL..., BEAM/BM..., BRAC..., TRUSS...) or else from the direction: vertical =
  column, horizontal = beam, inclined = brace.
* Supports at every node on the lowest level (fixed or pinned); one load case DL with self-weight; no other loads.
"""
from __future__ import annotations

import math

import numpy as np

from .generator import STEEL_BY_STD, default_combinations
from .sections import MATERIALS

UNIT_SCALE = {"mm": 0.001, "cm": 0.01, "m": 1.0, "in": 0.0254, "ft": 0.3048}
INSUNITS = {1: "in", 2: "ft", 4: "mm", 5: "cm", 6: "m"}
DXF_DEFAULTS = {"units": "auto", "tol": 0.005, "material": "steel", "support": "fixed", "standard": "EN1990",
                "name": "Imported DXF", "connect_crossings": True}

SECTIONS = {
    "steel": {
        "column": {"shape": "I", "h": 0.3, "bf": 0.3, "tf": 0.019, "tw": 0.011, "name": "I 300x300 (default)"},
        "beam": {"shape": "I", "h": 0.4, "bf": 0.2, "tf": 0.013, "tw": 0.008, "name": "I 400x200 (default)"},
        "brace": {"shape": "pipe", "d": 0.1143, "t": 0.006, "name": "CHS 114.3x6.0 (default)"},
        "truss": {"shape": "pipe", "d": 0.0889, "t": 0.005, "name": "CHS 88.9x5.0 (default)"},
    },
    "concrete": {
        "column": {"shape": "rect", "b": 0.4, "h": 0.4, "name": "400x400 (default)"},
        "beam": {"shape": "rect", "b": 0.3, "h": 0.6, "name": "300x600 (default)"},
        "brace": {"shape": "rect", "b": 0.3, "h": 0.3, "name": "300x300 (default)"},
        "truss": {"shape": "rect", "b": 0.25, "h": 0.25, "name": "250x250 (default)"},
    },
}
ELEM_PREFIX = {"column": "C", "beam": "B", "brace": "BR", "truss": "T"}
CONCRETE_BY_STD = {"TH": "TH-fc240", "EN1990": "C30/37", "ASCE7": "C30/37"}


class DXFError(ValueError):
    pass


def _pairs(text: str):
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if len(lines) < 2:
        raise DXFError("empty file")
    out = []
    for k in range(0, len(lines) - 1, 2):
        code = lines[k].strip()
        if not code:
            continue
        try:
            out.append((int(code), lines[k + 1].strip()))
        except ValueError as exc:
            raise DXFError(f"not an ASCII DXF file (line {k + 1}: {code[:20]!r}); binary DXF / DWG are not supported") from exc
    return out


def parse_dxf(text: str) -> tuple[list[tuple[str, tuple, tuple]], dict]:
    """Return (segments [(layer, p0, p1)] in drawing units, header info)."""
    pairs = _pairs(text)
    header, segs = {}, []
    section = None
    k = 0
    n = len(pairs)
    while k < n:
        code, val = pairs[k]
        if code == 0 and val == "SECTION" and k + 1 < n and pairs[k + 1][0] == 2:
            section = pairs[k + 1][1]
            k += 2
            continue
        if code == 0 and val == "ENDSEC":
            section = None
            k += 1
            continue
        if section == "HEADER" and code == 9 and val == "$INSUNITS" and k + 1 < n:
            try:
                header["insunits"] = int(pairs[k + 1][1])
            except ValueError:
                pass
            k += 2
            continue
        if section in ("ENTITIES", "BLOCKS") and code == 0 and val in ("LINE", "LWPOLYLINE", "POLYLINE"):
            if section == "BLOCKS":       # block definitions are not exploded
                header["skipped_blocks"] = header.get("skipped_blocks", 0) + 1
                k += 1
                continue
            ent, k = _read_entity(pairs, k + 1)
            layer = ent.get(8, ["0"])[0]
            if val == "LINE":
                p0 = tuple(float(ent.get(c, ["0"])[0]) for c in (10, 20, 30))
                p1 = tuple(float(ent.get(c, ["0"])[0]) for c in (11, 21, 31))
                segs.append((layer, p0, p1))
            elif val == "LWPOLYLINE":
                xs, ys = ent.get(10, []), ent.get(20, [])
                z = float(ent.get(38, ["0"])[0])
                pts = [(float(x), float(y), z) for x, y in zip(xs, ys)]
                closed = int(ent.get(70, ["0"])[0]) & 1
                if any(float(b) != 0 for b in ent.get(42, [])):
                    header["arcs_straightened"] = True
                segs += _poly_segments(layer, pts, closed)
            else:   # POLYLINE followed by VERTEX ... SEQEND
                closed = int(ent.get(70, ["0"])[0]) & 1
                pts = []
                while k < n and pairs[k] == (0, "VERTEX"):
                    v, k = _read_entity(pairs, k + 1)
                    pts.append(tuple(float(v.get(c, ["0"])[0]) for c in (10, 20, 30)))
                if k < n and pairs[k] == (0, "SEQEND"):
                    k += 1
                    _, k = _read_entity(pairs, k)
                segs += _poly_segments(layer, pts, closed)
            continue
        if section == "ENTITIES" and code == 0 and val in ("ARC", "CIRCLE", "SPLINE", "INSERT", "3DFACE", "TEXT", "MTEXT", "DIMENSION"):
            header.setdefault("ignored", {})
            header["ignored"][val] = header["ignored"].get(val, 0) + 1
        k += 1
    return segs, header


def _read_entity(pairs, k):
    ent = {}
    while k < len(pairs) and pairs[k][0] != 0:
        ent.setdefault(pairs[k][0], []).append(pairs[k][1])
        k += 1
    return ent, k


def _poly_segments(layer, pts, closed):
    out = [(layer, pts[i], pts[i + 1]) for i in range(len(pts) - 1)]
    if closed and len(pts) > 2:
        out.append((layer, pts[-1], pts[0]))
    return out


def _type_from_layer(layer: str):
    u = layer.upper()
    if "COL" in u:
        return "column"
    if "BRAC" in u:
        return "brace"
    if "TRUSS" in u or "CHORD" in u or "WEB" in u:
        return "truss"
    if "BEAM" in u or u.startswith("BM") or "GIRDER" in u or "PURLIN" in u or "RAFTER" in u:
        return "beam"
    return None


def import_dxf(text: str, options: dict | None = None) -> dict:
    opt = {**DXF_DEFAULTS, **(options or {})}
    segs, header = parse_dxf(text)
    if not segs:
        raise DXFError("no LINE, LWPOLYLINE or POLYLINE entities found in model space")
    units = opt["units"]
    if units == "auto":
        units = INSUNITS.get(header.get("insunits", 4), "mm")
    if units not in UNIT_SCALE:
        raise DXFError(f"unknown units {units!r}")
    sc = UNIT_SCALE[units]
    tol = float(opt["tol"])
    # merge end points on a grid of size tol
    nodes, key_of = [], {}

    def node(p):
        q = np.array(p, dtype=float) * sc
        key = tuple(np.round(q / tol).astype(int))
        for dk in _neighbours(key):
            if dk in key_of:
                j = key_of[dk]
                if np.linalg.norm(nodes[j] - q) <= tol:
                    return j
        nodes.append(q)
        key_of[key] = len(nodes) - 1
        return len(nodes) - 1

    raw = []
    for layer, p0, p1 in segs:
        a, b = node(p0), node(p1)
        if a != b:
            raw.append((layer, a, b))
    if not raw:
        raise DXFError("every segment is shorter than the merge tolerance")
    n_cross = 0
    if opt["connect_crossings"]:
        for q in _crossings(np.array(nodes), raw, tol):
            before = len(nodes)
            node(q / sc)
            n_cross += len(nodes) > before
    P = np.array(nodes)
    # split members at nodes lying on them (T-junctions)
    members, seen = [], set()
    for layer, a, b in raw:
        pa, pb = P[a], P[b]
        d = pb - pa
        L = float(np.linalg.norm(d))
        t = (P - pa) @ d / L ** 2
        dist = np.linalg.norm(P - (pa + np.outer(t, d)), axis=1)
        on = [(float(t[i]), i) for i in np.nonzero((dist <= tol) & (t * L > tol) & ((1 - t) * L > tol))[0]]
        chain = [a] + [i for _, i in sorted(on)] + [b]
        for i, j in zip(chain[:-1], chain[1:]):
            key = frozenset((i, j))
            if key in seen:
                continue
            seen.add(key)
            members.append((layer, i, j, i == a, j == b))     # flags: end is an end of the drawn line
    used = sorted({i for _, a, b, *_ in members for i in (a, b)})
    zmin = float(P[used, 2].min())
    zmax = float(P[used, 2].max())
    if zmax - zmin < tol:
        raise DXFError("the drawing is flat in Z (a plan): draw the frame in 3D or in an elevation plane (X-Z)")
    nid = {i: f"N{k + 1}" for k, i in enumerate(used)}
    out_nodes = [{"id": nid[i], "x": round(float(P[i, 0]), 6), "y": round(float(P[i, 1]), 6), "z": round(float(P[i, 2]), 6)} for i in used]
    std = opt["standard"] if opt["standard"] in ("TH", "EN1990", "ASCE7") else "EN1990"
    mat = STEEL_BY_STD.get(std, "S355") if opt["material"] == "steel" else CONCRETE_BY_STD.get(std, "C30/37")
    lib = SECTIONS["steel" if opt["material"] == "steel" else "concrete"]
    sec_id = {"column": "COL", "beam": "BM", "brace": "BR", "truss": "TR"}
    elements, counts, used_types, by_layer = [], {}, set(), {}
    for layer, i, j, end_i, end_j in members:
        d = P[j] - P[i]
        L = float(np.linalg.norm(d))
        t = _type_from_layer(layer)
        if t is None:
            vert = abs(d[2]) / L
            t = "column" if vert > 0.999 else ("beam" if vert < 0.02 else "brace")
        if t == "column" and P[i, 2] > P[j, 2]:
            i, j, end_i, end_j = j, i, end_j, end_i     # columns drawn bottom to top
        counts[t] = counts.get(t, 0) + 1
        used_types.add(t)
        by_layer[layer] = by_layer.get(layer, 0) + 1
        e = {"id": f"{ELEM_PREFIX[t]}{counts[t]}", "type": "truss" if t == "truss" else t,
             "role": t, "i": nid[i], "j": nid[j], "section": sec_id[t], "label": f"layer {layer}"}
        if t == "truss":
            e["truss"] = True
            e["role"] = "chord"
        if t == "brace":
            # pinned at the ends of the drawn line, continuous through crossings and junctions along it
            ri = [0, 0, 0, 0, 1, 1] if end_i else [0] * 6
            rj = [0, 0, 0, 1, 1, 1] if end_j else [0] * 6
            if not end_i and end_j:
                rj = [0, 0, 0, 0, 1, 1]                 # keep torsion restrained by one end of each segment
            if any(ri + rj):
                e["releases"] = {"i": ri, "j": rj}
        elements.append(e)
    sections = {sec_id[t]: {**lib[t], "material": mat, "name": f"{lib[t]['name']} {mat}"} for t in used_types}
    base = [nid[i] for i in used if abs(P[i, 2] - zmin) <= tol]
    supports = [{"node": n, "type": "fixed" if opt["support"] == "fixed" else "pinned"} for n in base]
    # make the unsupported pin joints well posed: nothing else to do, the solver fixes free rotations and reports them
    cases = [{"id": "DL", "name": "Dead load (self weight)", "type": "dead", "self_weight": True}]
    notes = [f"Imported from DXF: {len(segs)} segments in {units} -> {len(elements)} members, {len(out_nodes)} nodes "
             f"(merge tolerance {tol * 1000:.0f} mm).",
             "Member types from layer names or direction; sections are DEFAULTS, assign the real ones before using results.",
             f"Supports ({opt['support']}) assumed at the {len(base)} lowest nodes (z = {zmin:.3f} m).",
             "Only self-weight is loaded: add the load cases and loads of the project."]
    loose = _unsupported(elements, set(base))
    if loose:
        notes.append(f"{len(loose)} member(s) are not connected to any supported part ({', '.join(loose[:8])}"
                     f"{', ...' if len(loose) > 8 else ''}): connect or delete them before the analysis.")
    if n_cross:
        notes.append(f"{n_cross} point(s) where members cross in 3D were connected with a new node "
                     "(turn 'connect crossings' off to keep crossing members separate).")
    if header.get("ignored"):
        notes.append("Ignored entities: " + ", ".join(f"{v} {k}" for k, v in header["ignored"].items()) + ".")
    if header.get("skipped_blocks"):
        notes.append("Lines inside block definitions (INSERT) were not imported: explode blocks before exporting.")
    if header.get("arcs_straightened"):
        notes.append("Polyline arc segments (bulges) were imported as straight members.")
    return {
        "name": opt["name"], "units": {"force": "kN", "length": "m"},
        "settings": {"standard": std, "allowable_bearing": 250.0, "stress_limit_concrete": 18000.0,
                     "stress_limit_steel": 1000.0 * MATERIALS[STEEL_BY_STD.get(std, "S355")]["fy"], "slab_model": "tributary"},
        "materials": {k: v for k, v in MATERIALS.items()}, "sections": sections,
        "nodes": out_nodes, "elements": elements, "slabs": [], "walls": [], "supports": supports,
        "load_cases": cases, "loads": [], "combinations": default_combinations(std, {"DL"}),
        "generator": {"type": "dxf", "units": units, "layers": by_layer}, "notes": notes,
    }


def _crossings(P: np.ndarray, raw, tol: float) -> list[np.ndarray]:
    """Points where two segments truly intersect in 3D (closest distance <= tol) inside both of them."""
    A = P[[a for _, a, _ in raw]]
    D = P[[b for _, _, b in raw]] - A
    L = np.linalg.norm(D, axis=1)
    lo, hi = np.minimum(A, A + D) - tol, np.maximum(A, A + D) + tol
    out = []
    for i in range(len(raw) - 1):
        j = np.arange(i + 1, len(raw))
        j = j[np.all((lo[j] <= hi[i]) & (hi[j] >= lo[i]), axis=1)]          # bounding boxes overlap
        if not j.size:
            continue
        d1, d2, r = D[i], D[j], A[i] - A[j]
        a, b, c = d1 @ d1, d2 @ d1, np.einsum("ij,ij->i", d2, d2)
        dd, e = r @ d1, np.einsum("ij,ij->i", d2, r)
        den = a * c - b * b
        ok = den > 1e-12 * a * c                                            # not parallel
        if not ok.any():
            continue
        j, b, c, dd, e, den = j[ok], b[ok], c[ok], dd[ok], e[ok], den[ok]
        s = (b * e - c * dd) / den
        t = (a * e - b * dd) / den
        p1 = A[i] + np.outer(s, d1)
        p2 = A[j] + t[:, None] * D[j]
        inside = (s * L[i] > tol) & ((1 - s) * L[i] > tol) & (t * L[j] > tol) & ((1 - t) * L[j] > tol)
        hit = inside & (np.linalg.norm(p1 - p2, axis=1) <= tol)
        out += [(p1[k] + p2[k]) / 2 for k in np.nonzero(hit)[0]]
    return out


def _unsupported(elements, supported: set) -> list[str]:
    """Ids of members in connected groups that contain no supported node."""
    parent = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for e in elements:
        parent[find(e["i"])] = find(e["j"])
    ok = {find(n) for n in supported if n in parent}
    return [e["id"] for e in elements if find(e["i"]) not in ok]


def _neighbours(key):
    x, y, z = key
    return [(x + a, y + b, z + c) for a in (-1, 0, 1) for b in (-1, 0, 1) for c in (-1, 0, 1)]


__all__ = ["import_dxf", "parse_dxf", "DXFError"]
