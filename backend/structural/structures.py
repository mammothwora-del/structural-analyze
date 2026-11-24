"""Generators for truss structures: planar trusses, a truss-roof steel warehouse and a
double-layer space truss.

All member forces come from the 3D FEM. Roof loads are given per plan area (kN/m²) and are
brought to the structure by explicit, labelled assumptions:

* planar truss and space truss: lumped at the top-chord nodes by tributary plan area
  (loads assumed to reach the truss through purlins / deck supports at the nodes);
* warehouse: roof sheeting spans one way between purlins, so each purlin carries the roof
  load over its tributary width (line load on the purlin); purlins are FE members and
  deliver their reactions to the trusses at the nodes.

Bracing rods are modelled as linear truss members acting in tension and compression (no
tension-only behaviour, no buckling).
"""
from __future__ import annotations

from .generator import COMBOS, default_combinations
from .sections import MATERIALS

STEEL = {"TH": "SS400", "EN1990": "S355", "ASCE7": "A992"}


class _Builder:
    def __init__(self):
        self.nodes, self.node_at, self.elements, self.supports, self.loads = [], {}, [], [], []
        self.counts = {}

    def node(self, x, y, z, level=0, grid=""):
        key = (round(x, 6), round(y, 6), round(z, 6))
        if key not in self.node_at:
            nid = f"N{len(self.nodes) + 1}"
            self.node_at[key] = nid
            self.nodes.append({"id": nid, "x": float(x), "y": float(y), "z": float(z), "level": level, "grid": grid})
        return self.node_at[key]

    def el(self, prefix, i, j, section, etype, role, level=1, label="", truss=False, pinned=False):
        if i == j:
            return None
        self.counts[prefix] = self.counts.get(prefix, 0) + 1
        e = {"id": f"{prefix}{self.counts[prefix]}", "type": etype, "role": role, "i": i, "j": j,
             "section": section, "level": level, "label": label}
        if truss:
            e["truss"] = True
        if pinned:   # simply supported member: moments released at both ends, torsion at end j
            e["releases"] = {"i": [0, 0, 0, 0, 1, 1], "j": [0, 0, 0, 1, 1, 1]}
        self.elements.append(e)
        return e["id"]

    def support(self, n, dofs=None, kind=None, footing=None, lateral=False):
        s = {"node": n}
        if dofs is not None:
            s["dofs"] = dofs
        if kind:
            s["type"] = kind
        if footing:
            s["footing"] = footing
        if lateral:
            s["lateral"] = True
        self.supports.append(s)

    def model(self, name, p, sections, cases, grid, settings=None):
        cids = {c["id"] for c in cases}
        return {
            "name": name, "units": {"force": "kN", "length": "m"},
            "settings": {"standard": p["standard"], "allowable_bearing": p.get("allowable_bearing", 250.0),
                         "stress_limit_concrete": 18000.0, "stress_limit_steel": 1000.0 * MATERIALS[p["steel"]]["fy"],
                         "slab_model": "tributary", **(settings or {})},
            "grid": grid, "materials": {k: v for k, v in MATERIALS.items()}, "sections": sections,
            "nodes": self.nodes, "elements": self.elements, "slabs": [], "walls": [], "supports": self.supports,
            "load_cases": cases, "loads": self.loads,
            "combinations": default_combinations(p["standard"], cids), "generator": p,
        }


def _gravity_cases():
    return [{"id": "DL", "name": "Dead load (self weight)", "type": "dead", "self_weight": True},
            {"id": "SDL", "name": "Superimposed dead load (roof)", "type": "sdl"},
            {"id": "LL", "name": "Roof live load", "type": "live"}]


def _tributary(xs):
    """Tributary lengths of sorted positions xs on [xs[0], xs[-1]]."""
    out = []
    for k, x in enumerate(xs):
        lo = (x - xs[k - 1]) / 2 if k > 0 else 0.0
        hi = (xs[k + 1] - x) / 2 if k < len(xs) - 1 else 0.0
        out.append(lo + hi)
    return out


# ------------------------------------------------------------------ planar truss geometry
TRUSS_TYPES = ("pratt", "howe", "warren", "warren_v", "k", "pitched", "howe_roof", "fink", "fan", "scissors",
               "mono", "bowstring")
FLAT_TYPES = ("pratt", "howe", "warren", "warren_v", "k")


def _posts_and_diagonals(n, a, top_z, bot_z, pattern):
    """Truss with a post at every panel point between a top and a bottom chord profile.

    top_z(k), bot_z(k): chord heights at panel point k (0..n). Where both coincide (e.g. at the supports
    of a truss without end depth) the top and bottom nodes merge. pattern 'pratt': diagonals slope down
    towards midspan (tension under gravity); 'howe': up towards midspan.
    """
    P, M = {}, []
    for k in range(n + 1):
        P[f"B{k}"] = (k * a, bot_z(k))
        if top_z(k) - bot_z(k) > 1e-9:
            P[f"T{k}"] = (k * a, top_z(k))
    top = [f"T{k}" if f"T{k}" in P else f"B{k}" for k in range(n + 1)]
    M += [(f"B{k}", f"B{k + 1}", "chord") for k in range(n)]
    M += [(top[k], top[k + 1], "chord") for k in range(n)]
    M += [(f"B{k}", top[k], "web") for k in range(n + 1) if top[k] != f"B{k}"]
    h = n / 2
    for k in range(n):
        left = k + 0.5 < h
        down_to_centre = (top[k], f"B{k + 1}") if left else (f"B{k}", top[k + 1])
        up_to_centre = (f"B{k}", top[k + 1]) if left else (top[k], f"B{k + 1}")
        M.append((*(down_to_centre if pattern == "pratt" else up_to_centre), "web"))
    return P, M, top


def truss_geometry(kind: str, span: float, height: float, panels: int, eave_depth: float = 0.0, bottom_rise: float = 0.0):
    """Nodes (x, z) and members of a planar truss in the x-z plane.

    Returns (points: dict name->(x, z), members: list of (a, b, role), roof: list of node names
    on the top chord from left to right, supports: (left, right)).

    Parallel chords: 'pratt', 'howe', 'warren' (no verticals), 'warren_v' (Warren with verticals),
    'k' (K-truss). Roof trusses (height = rise at the ridge, eave_depth = depth at the supports):
    'pitched' (Pratt web), 'howe_roof', 'fink' (W web, 4 top-chord panels), 'fan', 'scissors'
    (bottom chord pitched up to bottom_rise, default rise/2), 'mono' (mono-pitch, high end on the right),
    'bowstring' (parabolic top chord).
    """
    if kind not in TRUSS_TYPES:
        raise ValueError(f"Unknown truss type '{kind}'. Available: {', '.join(TRUSS_TYPES)}")
    n = max(2, int(panels))
    if kind not in ("warren", "mono") and n % 2:
        n += 1
    if kind == "k" and n < 4:
        n = 4
    a = span / n
    P, M = {}, []
    for k in range(n + 1):
        P[f"B{k}"] = (k * a, 0.0)
    if kind in ("pratt", "howe"):
        for k in range(1, n):
            P[f"T{k}"] = (k * a, height)
        M += [(f"B{k}", f"B{k + 1}", "chord") for k in range(n)]
        M += [(f"T{k}", f"T{k + 1}", "chord") for k in range(1, n - 1)]
        M += [("B0", "T1", "web"), (f"B{n}", f"T{n - 1}", "web")]
        M += [(f"B{k}", f"T{k}", "web") for k in range(1, n)]
        h = n // 2
        for k in range(1, h):
            M.append((f"T{k}", f"B{k + 1}", "web") if kind == "pratt" else (f"B{k}", f"T{k + 1}", "web"))
        for k in range(h + 1, n):
            M.append((f"T{k}", f"B{k - 1}", "web") if kind == "pratt" else (f"B{k}", f"T{k - 1}", "web"))
        roof = ["B0"] + [f"T{k}" for k in range(1, n)] + [f"B{n}"]
    elif kind == "warren":
        for k in range(n):
            P[f"T{k}"] = ((k + 0.5) * a, height)
        M += [(f"B{k}", f"B{k + 1}", "chord") for k in range(n)]
        M += [(f"T{k}", f"T{k + 1}", "chord") for k in range(n - 1)]
        for k in range(n):
            M += [(f"B{k}", f"T{k}", "web"), (f"T{k}", f"B{k + 1}", "web")]
        roof = ["B0"] + [f"T{k}" for k in range(n)] + [f"B{n}"]
    elif kind == "warren_v":
        # zig-zag diagonals with a vertical at every inner panel point
        for k in range(1, n):
            P[f"T{k}"] = (k * a, height)
        M += [(f"B{k}", f"B{k + 1}", "chord") for k in range(n)]
        M += [(f"T{k}", f"T{k + 1}", "chord") for k in range(1, n - 1)]
        M += [(f"B{k}", f"T{k}", "web") for k in range(1, n)]
        M += [("B0", "T1", "web"), (f"T{n - 1}", f"B{n}", "web")]
        for k in range(1, n - 1):
            M.append((f"T{k}", f"B{k + 1}", "web") if k % 2 else (f"B{k}", f"T{k + 1}", "web"))
        roof = ["B0"] + [f"T{k}" for k in range(1, n)] + [f"B{n}"]
    elif kind == "k":
        # verticals split at mid-height; the two diagonals of each K meet there and point to midspan
        h = n // 2
        for k in range(1, n):
            P[f"T{k}"] = (k * a, height)
            if k != h:
                P[f"M{k}"] = (k * a, height / 2)
        M += [(f"B{k}", f"B{k + 1}", "chord") for k in range(n)]
        M += [(f"T{k}", f"T{k + 1}", "chord") for k in range(1, n - 1)]
        M += [("B0", "T1", "web"), (f"B{n}", f"T{n - 1}", "web"), (f"B{h}", f"T{h}", "web")]
        for k in range(1, n):
            if k == h:
                continue
            M += [(f"B{k}", f"M{k}", "web"), (f"M{k}", f"T{k}", "web")]
            nxt = k + 1 if k < h else k - 1
            M += [(f"M{k}", f"T{nxt}", "web"), (f"M{k}", f"B{nxt}", "web")]
        roof = ["B0"] + [f"T{k}" for k in range(1, n)] + [f"B{n}"]
    elif kind == "pitched":
        h = n // 2
        for k in range(n + 1):
            z = eave_depth + height * (1 - abs(2 * k / n - 1))
            if z > 1e-9:
                P[f"T{k}"] = (k * a, z)
        top = [f"T{k}" if f"T{k}" in P else f"B{k}" for k in range(n + 1)]
        M += [(f"B{k}", f"B{k + 1}", "chord") for k in range(n)]
        M += [(top[k], top[k + 1], "chord") for k in range(n)]
        M += [(f"B{k}", top[k], "web") for k in range(n + 1) if top[k] != f"B{k}"]
        for k in range(0, h):
            if top[k] != f"B{k + 1}":
                M.append((top[k], f"B{k + 1}", "web"))
        for k in range(h + 1, n + 1):
            M.append((top[k], f"B{k - 1}", "web"))
        M = [m for m in M if m[0] != m[1]]
        roof = top
    elif kind in ("howe_roof", "scissors", "mono", "bowstring"):
        if kind == "howe_roof":
            tz, bz, pat = (lambda k: eave_depth + height * (1 - abs(2 * k / n - 1))), (lambda k: 0.0), "howe"
        elif kind == "scissors":
            br = bottom_rise if bottom_rise > 0 else height / 2
            br = min(br, 0.8 * (eave_depth + height))
            tz, bz, pat = (lambda k: eave_depth + height * (1 - abs(2 * k / n - 1))), (lambda k: br * (1 - abs(2 * k / n - 1))), "pratt"
        elif kind == "mono":
            tz, bz, pat = (lambda k: eave_depth + height * k / n), (lambda k: 0.0), "pratt"
        else:
            tz, bz, pat = (lambda k: eave_depth + height * (1 - (2 * k / n - 1) ** 2)), (lambda k: 0.0), "pratt"
        P, M, roof = _posts_and_diagonals(n, a, tz, bz, pat)
    elif kind in ("fink", "fan"):
        # classic gable trusses with 4 top-chord panels (panels input is not used)
        H = eave_depth + height
        if kind == "fink":
            # W web: top chord at quarter points, bottom chord at third points
            P = {"B0": (0.0, 0.0), "B1": (span / 3, 0.0), "B2": (2 * span / 3, 0.0), "B3": (span, 0.0),
                 "T1": (span / 4, eave_depth + height / 2), "T2": (span / 2, H), "T3": (3 * span / 4, eave_depth + height / 2)}
            M = [("B0", "B1", "chord"), ("B1", "B2", "chord"), ("B2", "B3", "chord"),
                 ("T1", "T2", "chord"), ("T2", "T3", "chord"),
                 ("T1", "B1", "web"), ("B1", "T2", "web"), ("T2", "B2", "web"), ("B2", "T3", "web")]
            right = "B3"
        else:
            # fan: two struts fan out from each bottom-chord third point to the top chord
            P = {"B0": (0.0, 0.0), "B1": (span / 3, 0.0), "B2": (2 * span / 3, 0.0), "B3": (span, 0.0)}
            for k in range(1, 6):
                x = k * span / 6
                P[f"T{k}"] = (x, eave_depth + height * (1 - abs(2 * x / span - 1)))
            M = [("B0", "B1", "chord"), ("B1", "B2", "chord"), ("B2", "B3", "chord")]
            M += [(f"T{k}", f"T{k + 1}", "chord") for k in range(1, 5)]
            M += [("B1", "T1", "web"), ("B1", "T2", "web"), ("B1", "T3", "web"),
                  ("B2", "T3", "web"), ("B2", "T4", "web"), ("B2", "T5", "web")]
            right = "B3"
        if eave_depth > 1e-9:
            P["T0"], P["T4" if kind == "fink" else "T6"] = (0.0, eave_depth), (span, eave_depth)
            last = "T4" if kind == "fink" else "T6"
            M += [("B0", "T0", "web"), (right, last, "web"), ("T0", "T1", "chord"),
                  ("T3" if kind == "fink" else "T5", last, "chord"), ("T0", "B1", "web"), (last, "B2", "web")]
            tops = ["T0"] + [f"T{k}" for k in range(1, 4 if kind == "fink" else 6)] + [last]
        else:
            M += [("B0", "T1", "chord"), ("T3" if kind == "fink" else "T5", right, "chord")]
            tops = ["B0"] + [f"T{k}" for k in range(1, 4 if kind == "fink" else 6)] + [right]
        roof = tops
        return P, _dedupe(M), roof, ("B0", right)
    return P, _dedupe(M), roof, ("B0", f"B{n}")


def _dedupe(M):
    seen, uniq = set(), []
    for a_, b_, r in M:
        key = tuple(sorted((a_, b_)))
        if a_ != b_ and key not in seen:
            seen.add(key)
            uniq.append((a_, b_, r))
    return uniq


TRUSS_DEFAULTS = {
    "type": "truss2d", "truss_type": "pratt", "span": 18.0, "height": 2.0, "panels": 6, "eave_depth": 0.0,
    "spacing": 6.0, "sdl": 0.5, "live_load": 0.5, "standard": "EN1990",
    "chord": {"shape": "box", "b": 0.15, "h": 0.15, "t": 0.008}, "web": {"shape": "pipe", "d": 0.0889, "t": 0.005},
}


def generate_truss2d(params: dict | None = None) -> dict:
    p = {**TRUSS_DEFAULTS, **(params or {})}
    p["steel"] = p.get("material") or STEEL.get(p["standard"], "S355")
    P, M, roof, (left, right) = truss_geometry(p["truss_type"], float(p["span"]), float(p["height"]), int(p["panels"]),
                                               float(p.get("eave_depth", 0.0)), float(p.get("bottom_rise", 0.0)))
    b = _Builder()
    ids = {k: b.node(x, 0.0, z, 1, k) for k, (x, z) in P.items()}
    sections = {"CH": {**p["chord"], "material": p["steel"], "name": _name(p["chord"], p["steel"])},
                "WEB": {**p["web"], "material": p["steel"], "name": _name(p["web"], p["steel"])}}
    for a_, b_, role in M:
        b.el("T", ids[a_], ids[b_], "CH" if role == "chord" else "WEB", "truss", role, 1, f"{role} {a_}-{b_}", truss=True)
    b.support(ids[left], [1, 1, 1, 0, 0, 0], footing=None)
    b.support(ids[right], [0, 1, 1, 0, 0, 0])
    for k, nid in ids.items():
        if nid not in (ids[left], ids[right]):
            b.support(nid, [0, 1, 0, 0, 0, 0], lateral=True)   # out-of-plane restraint (purlins / bracing)
    xs = [P[r][0] for r in roof]
    trib = _tributary(xs)
    for case, q in (("SDL", p["sdl"]), ("LL", p["live_load"])):
        if q:
            for r, w in zip(roof, trib):
                b.loads.append({"case": case, "kind": "nodal", "node": ids[r], "values": [0, 0, -q * p["spacing"] * w, 0, 0, 0],
                                "label": f"Roof load {q} kN/m² × {p['spacing']} m spacing × {w:.2f} m tributary (panel point)"})
    grid = {"x": [{"name": "1", "pos": 0.0}, {"name": "2", "pos": float(p["span"])}], "y": [{"name": "A", "pos": 0.0}],
            "levels": [{"name": "Support", "z": 0.0}, {"name": "Top", "z": max(z for _, z in P.values())}]}
    m = b.model(f"{p['truss_type'].capitalize()} truss {p['span']:g} m", p, sections, _gravity_cases(), grid)
    m["notes"] = ["Planar truss: all nodes restrained out of plane (lateral restraint by purlins/bracing assumed).",
                  "Roof load lumped at top-chord panel points by tributary length (assumed)."]
    return m


# ------------------------------------------------------------------ warehouse
WAREHOUSE_ROOFS = ("pitched", "howe_roof", "fink", "fan", "scissors", "bowstring", "mono", "portal")
WAREHOUSE_DEFAULTS = {
    "type": "warehouse", "roof": "pitched", "span": 20.0, "n_spans": 1, "bay": 6.0, "n_bays": 5, "eave_height": 6.0,
    "rise": 2.0, "eave_depth": 1.0, "panels": 8, "support": "fixed", "sdl": 0.3, "live_load": 0.5, "wind_pressure": 0.8,
    "standard": "EN1990", "roof_bracing": True, "wall_bracing": True,
    "column": {"shape": "I", "h": 0.4, "bf": 0.2, "tf": 0.013, "tw": 0.008},
    "rafter": {"shape": "I", "h": 0.45, "bf": 0.2, "tf": 0.014, "tw": 0.0094},
    "chord": {"shape": "box", "b": 0.15, "h": 0.15, "t": 0.006}, "web": {"shape": "pipe", "d": 0.0761, "t": 0.004},
    "purlin": {"shape": "box", "b": 0.1, "h": 0.15, "t": 0.004}, "brace": {"shape": "pipe", "d": 0.0603, "t": 0.004},
    "footing": {"B": 1.5, "L": 1.5, "t": 0.5}, "allowable_bearing": 200.0,
}


def _portal_geometry(span, rise, panels, mono=False):
    """Rafter line of a portal frame: points (x, z) at purlin positions, eaves at z = 0."""
    n = max(2, int(panels))
    if not mono and n % 2:
        n += 1
    P = {}
    for k in range(n + 1):
        x = k * span / n
        P[f"R{k}"] = (x, rise * k / n if mono else rise * (1 - abs(2 * k / n - 1)))
    M = [(f"R{k}", f"R{k + 1}", "rafter") for k in range(n)]
    return P, M, [f"R{k}" for k in range(n + 1)], ("R0", f"R{n}")


def generate_warehouse(params: dict | None = None) -> dict:
    p = {**WAREHOUSE_DEFAULTS, **(params or {})}
    p["steel"] = p.get("material") or STEEL.get(p["standard"], "S355")
    roof_kind = p.get("roof", "pitched")
    if roof_kind not in WAREHOUSE_ROOFS:
        raise ValueError(f"Unknown warehouse roof '{roof_kind}'. Available: {', '.join(WAREHOUSE_ROOFS)}")
    span, bay, nb, H = float(p["span"]), float(p["bay"]), int(p["n_bays"]), float(p["eave_height"])
    ns = max(1, int(p.get("n_spans", 1)))
    portal = roof_kind in ("portal",)
    if portal:
        P, M, roof, (left, right) = _portal_geometry(span, float(p["rise"]), int(p["panels"]))
    else:
        P, M, roof, (left, right) = truss_geometry(roof_kind, span, float(p["rise"]), int(p["panels"]), float(p["eave_depth"]))
    st = p["steel"]
    keys = ("column", "rafter", "purlin", "brace") if portal else ("column", "chord", "web", "purlin", "brace")
    sections = {k.upper()[:3]: {**p[k], "material": st, "name": _name(p[k], st)} for k in keys}
    S = {"column": "COL", "chord": "CHO", "web": "WEB", "purlin": "PUR", "brace": "BRA", "rafter": "RAF"}
    b = _Builder()
    ys = [j * bay for j in range(nb + 1)]
    xs_col = [s_ * span for s_ in range(ns + 1)]
    lx, rx = P[left][0], P[right][0]
    # nodes at the column lines (x of the truss supports) carry the column; everything above is chained
    frames, span_nodes = [], []   # frames[j][(s, name)] -> node id
    for j, y in enumerate(ys):
        ids = {}
        col_heads = {x: set() for x in xs_col}
        for s_ in range(ns):
            x0 = s_ * span
            for k, (x, z) in P.items():
                nid = b.node(x0 + x, y, H + z, 1, f"F{j + 1}")
                ids[(s_, k)] = nid
                for xc in xs_col:
                    if abs(x0 + x - xc) < 1e-6:
                        col_heads[xc].add((H + z, nid))
            for a_, b_, role in M:
                xa, xb = P[a_][0], P[b_][0]
                at_col = abs(xa - xb) < 1e-9 and (abs(xa - lx) < 1e-9 or abs(xa - rx) < 1e-9)
                if at_col:
                    continue   # end posts are part of the column
                if portal:
                    b.el("R", ids[(s_, a_)], ids[(s_, b_)], S["rafter"], "beam", "rafter", 1, f"Rafter F{j + 1} span {s_ + 1}")
                else:
                    b.el("T", ids[(s_, a_)], ids[(s_, b_)], S["chord"] if role == "chord" else S["web"], "truss", role, 1,
                         f"Truss F{j + 1}.{s_ + 1} {role} {a_}-{b_}", truss=True)
        for c, xc in enumerate(xs_col):
            base = b.node(xc, y, 0.0, 0, f"F{j + 1}/{c + 1}")
            chain = [base] + [nid for _, nid in sorted(col_heads[xc])]
            for lo, hi in zip(chain, chain[1:]):
                b.el("C", lo, hi, S["column"], "column", "column", 1, f"Column F{j + 1} line {c + 1}")
            # pinned base: free to rotate about the horizontal axes; twist about the column axis is held by the base plate
            b.support(base, dofs=[1, 1, 1, 0, 0, 1] if p["support"] == "pinned" else None,
                      kind=p["support"], footing={**p["footing"], "type": "isolated", "label": f"Footing F{j + 1}/{c + 1}"})
            ids[("col", c)] = base
            ids[("head", c)] = chain[1] if len(chain) > 1 else base
        frames.append(ids)
    # purlins along every roof node line (one line per unique node), loaded by one-way sheeting
    roof_line = []
    for s_ in range(ns):
        for r in roof:
            nid = frames[0][(s_, r)]
            if nid not in [q[1] for q in roof_line]:
                roof_line.append(((s_, r), nid))
    xs_roof = [b.nodes[int(nid[1:]) - 1]["x"] for _, nid in roof_line]
    order = sorted(range(len(xs_roof)), key=lambda i: xs_roof[i])
    trib = dict(zip(order, _tributary([xs_roof[i] for i in order])))
    for idx, (key, _) in enumerate(roof_line):
        w = trib[idx]
        for j in range(nb):
            eid = b.el("P", frames[j][key], frames[j + 1][key], S["purlin"], "beam", "purlin", 1, f"Purlin {key[1]} F{j + 1}-F{j + 2}", pinned=True)
            for case, q in (("SDL", p["sdl"]), ("LL", p["live_load"])):
                if q and eid and w > 0:
                    b.loads.append({"case": case, "kind": "dist", "element": eid, "direction": [0, 0, -1],
                                    "points": [[0, q * w], [1, q * w]], "relative": True,
                                    "label": f"Roof {q} kN/m² × {w:.2f} m tributary width (one-way sheeting, assumed)"})
    # eave struts at every column head below a roof node (truss bottom chord at the column)
    roof_ids = {nid for _, nid in roof_line}
    for c in range(len(xs_col)):
        if frames[0][("head", c)] not in roof_ids:
            for j in range(nb):
                b.el("P", frames[j][("head", c)], frames[j + 1][("head", c)], S["purlin"], "beam", "eave", 1, f"Eave strut F{j + 1}-F{j + 2}", pinned=True)
    end_bays = sorted({0, nb - 1})
    if not portal:
        # bottom-chord ties along the building (out-of-plane restraint of the bottom chords), anchored by
        # vertical cross-bracing between the trusses in the end bays
        bottoms = [k for k in P if k.startswith("B") and k not in (left, right)]
        tops = [k for k in P if not k.startswith("B")]
        for s_ in range(ns):
            for bk in bottoms:
                if frames[0][(s_, bk)] in roof_ids:
                    continue
                for j in range(nb):
                    b.el("X", frames[j][(s_, bk)], frames[j + 1][(s_, bk)], S["brace"], "brace", "tie", 1, f"Bottom-chord tie {bk} F{j + 1}-F{j + 2}", truss=True)
                cand = [t for t in tops if abs(P[t][0] - P[bk][0]) < 1e-9] or sorted(tops, key=lambda t: abs(P[t][0] - P[bk][0]))[:1]
                for tk in cand[:1]:
                    for j in end_bays:
                        b.el("X", frames[j][(s_, bk)], frames[j + 1][(s_, tk)], S["brace"], "brace", "vertical brace", 1, f"Vertical brace bay {j + 1}", truss=True)
                        b.el("X", frames[j + 1][(s_, bk)], frames[j][(s_, tk)], S["brace"], "brace", "vertical brace", 1, f"Vertical brace bay {j + 1}", truss=True)
    if p.get("roof_bracing"):
        for s_ in range(ns):
            for j in end_bays:
                for k in range(len(roof) - 1):
                    a1, a2 = (s_, roof[k]), (s_, roof[k + 1])
                    b.el("X", frames[j][a1], frames[j + 1][a2], S["brace"], "brace", "roof brace", 1, f"Roof brace bay {j + 1}", truss=True)
                    b.el("X", frames[j][a2], frames[j + 1][a1], S["brace"], "brace", "roof brace", 1, f"Roof brace bay {j + 1}", truss=True)
    if p.get("wall_bracing"):
        for j in end_bays:
            for c in (0, len(xs_col) - 1):
                b.el("X", frames[j][("col", c)], frames[j + 1][("head", c)], S["brace"], "brace", "wall brace", 1, f"Wall brace bay {j + 1}", truss=True)
                b.el("X", frames[j + 1][("col", c)], frames[j][("head", c)], S["brace"], "brace", "wall brace", 1, f"Wall brace bay {j + 1}", truss=True)
    cases = _gravity_cases()
    if p.get("wind_pressure"):
        cases.append({"id": "WX", "name": "Wind +X (simplified net pressure on the long wall)", "type": "wind"})
        trib_y = _tributary(ys)
        for j, w in enumerate(trib_y):
            F = p["wind_pressure"] * w * H / 2
            b.loads.append({"case": "WX", "kind": "nodal", "node": frames[j][("head", 0)], "values": [F, 0, 0, 0, 0, 0],
                            "label": "Wind lumped at column head (half wall height)"})
    grid = {"x": [{"name": chr(65 + c), "pos": x} for c, x in enumerate(xs_col)],
            "y": [{"name": str(j + 1), "pos": y} for j, y in enumerate(ys)],
            "levels": [{"name": "Base", "z": 0.0}, {"name": "Eave", "z": H}]}
    label = "portal frame" if portal else f"{roof_kind.replace('_', ' ')} trusses"
    m = b.model(f"Warehouse {ns * span:g} × {nb * bay:g} m ({label})", p, sections, cases, grid)
    m["notes"] = ["Roof sheeting assumed to span one way between purlins (tributary width per purlin).",
                  "Purlins and eave struts are simply supported between frames (pinned ends).",
                  "Bracing is pin-ended and acts in tension and compression (no tension-only behaviour; buckling in Stability mode).",
                  "Wind: simplified net pressure on the long wall lumped at the windward column heads; not a code calculation."]
    if portal:
        m["notes"].insert(2, "Portal frame: rafters rigidly connected to the columns and at the ridge (no haunches modelled).")
    else:
        m["notes"].insert(2, "Truss members are pin-ended (axial only under nodal loads). Bottom chords are restrained out of plane "
                             "by longitudinal ties anchored by vertical bracing in the end bays.")
    if ns > 1:
        m["notes"].append(f"{ns} spans share the internal column lines; roof drainage/valley details are not modelled.")
    return m


# ------------------------------------------------------------------ space truss
SPACE_DEFAULTS = {
    "type": "space_truss", "nx": 8, "ny": 6, "module": 2.0, "depth": 1.5, "column_height": 5.0, "supports": "perimeter",
    "sdl": 0.5, "live_load": 0.75, "standard": "EN1990",
    "member": {"shape": "pipe", "d": 0.0889, "t": 0.005}, "column": {"shape": "pipe", "d": 0.3239, "t": 0.01},
    "footing": {"B": 1.5, "L": 1.5, "t": 0.5}, "allowable_bearing": 200.0,
}


def generate_space_truss(params: dict | None = None) -> dict:
    p = {**SPACE_DEFAULTS, **(params or {})}
    p["steel"] = p.get("material") or STEEL.get(p["standard"], "S355")
    nx, ny, a, d, Hc = int(p["nx"]), int(p["ny"]), float(p["module"]), float(p["depth"]), float(p["column_height"])
    st = p["steel"]
    sections = {"ST": {**p["member"], "material": st, "name": _name(p["member"], st)},
                "COL": {**p["column"], "material": st, "name": _name(p["column"], st)}}
    b = _Builder()
    ztop = Hc + d
    T = {(i, j): b.node(i * a, j * a, ztop, 1, f"T{i},{j}") for i in range(nx + 1) for j in range(ny + 1)}
    B = {(i, j): b.node((i + 0.5) * a, (j + 0.5) * a, Hc, 1, f"B{i},{j}") for i in range(nx) for j in range(ny)}
    for (i, j), n in T.items():
        if i < nx:
            b.el("T", n, T[(i + 1, j)], "ST", "truss", "chord", 1, "Top chord", truss=True)
        if j < ny:
            b.el("T", n, T[(i, j + 1)], "ST", "truss", "chord", 1, "Top chord", truss=True)
    for (i, j), n in B.items():
        if i < nx - 1:
            b.el("T", n, B[(i + 1, j)], "ST", "truss", "chord", 1, "Bottom chord", truss=True)
        if j < ny - 1:
            b.el("T", n, B[(i, j + 1)], "ST", "truss", "chord", 1, "Bottom chord", truss=True)
        for di, dj in ((0, 0), (1, 0), (1, 1), (0, 1)):
            b.el("T", n, T[(i + di, j + dj)], "ST", "truss", "web", 1, "Diagonal", truss=True)
    # supports at top perimeter nodes (every 2nd module) or corners
    if p["supports"] == "corners":
        sup = [(0, 0), (nx, 0), (nx, ny), (0, ny)]
    else:
        sup = sorted({(i, j) for i in range(0, nx + 1, 2) for j in (0, ny)} | {(i, j) for j in range(0, ny + 1, 2) for i in (0, nx)}
                     | {(nx, 0), (nx, ny), (0, ny)})
    for (i, j) in sup:
        top = T[(i, j)]
        if Hc > 0:
            base = b.node(i * a, j * a, 0.0, 0, f"C{i},{j}")
            b.el("C", base, top, "COL", "column", "column", 1, f"Column {i},{j}")
            b.support(base, kind="fixed", footing={**p["footing"], "type": "isolated", "label": f"Footing {i},{j}"})
        else:
            b.support(top, [1, 1, 1, 0, 0, 0])
    tx, ty = _tributary([i * a for i in range(nx + 1)]), _tributary([j * a for j in range(ny + 1)])
    for case, q in (("SDL", p["sdl"]), ("LL", p["live_load"])):
        if q:
            for (i, j), n in T.items():
                b.loads.append({"case": case, "kind": "nodal", "node": n, "values": [0, 0, -q * tx[i] * ty[j], 0, 0, 0],
                                "label": f"Roof {q} kN/m² × {tx[i] * ty[j]:.2f} m² tributary (lumped at node)"})
    grid = {"x": [{"name": str(i + 1), "pos": i * a} for i in range(0, nx + 1, 2)],
            "y": [{"name": chr(65 + k), "pos": j * a} for k, j in enumerate(range(0, ny + 1, 2))],
            "levels": [{"name": "Base", "z": 0.0}, {"name": "Roof", "z": ztop}]}
    m = b.model(f"Space truss {nx * a:g} × {ny * a:g} m", p, sections, _gravity_cases(), grid)
    m["notes"] = ["Square-on-square double-layer grid, pin-jointed members.",
                  "Roof load lumped at the top nodes by tributary plan area (deck assumed to span between nodes)."]
    return m


# ------------------------------------------------------------------ lattice roofs (barrel vault, dome)
LATTICE_DEFAULTS = {
    "type": "lattice_roof", "shape": "barrel", "pattern": "braced",
    "span": 24.0, "rise": 6.0, "length": 36.0, "n_arc": 12, "n_long": 12,          # barrel vault
    "diameter": 30.0, "dome_rise": 7.5, "n_rings": 6, "n_sectors": 16,             # dome
    "support_height": 0.0, "sdl": 0.3, "live_load": 0.5, "standard": "EN1990",
    "member": {"shape": "pipe", "d": 0.1397, "t": 0.0063},
    "allowable_bearing": 200.0,
}
LATTICE_PATTERNS = {"barrel": ("braced", "cross", "ribbed"), "dome": ("schwedler", "lamella", "ribbed")}


def _arc(span, rise):
    """Circular arc through (0, 0), (span/2, rise), (span, 0): radius and centre height."""
    R = (span ** 2 / 4 + rise ** 2) / (2 * rise)
    return R, rise - R


def generate_lattice_roof(params: dict | None = None) -> dict:
    import math
    p = {**LATTICE_DEFAULTS, **(params or {})}
    p["steel"] = p.get("material") or STEEL.get(p["standard"], "S355")
    shape = p["shape"]
    if shape not in LATTICE_PATTERNS:
        raise ValueError(f"Unknown lattice roof shape '{shape}'. Available: barrel, dome")
    pattern = p["pattern"] if p["pattern"] in LATTICE_PATTERNS[shape] else LATTICE_PATTERNS[shape][0]
    st = p["steel"]
    sections = {"LAT": {**p["member"], "material": st, "name": _name(p["member"], st)}}
    b = _Builder()
    z0 = float(p["support_height"])
    loads_at = {}   # node -> tributary plan area

    def mem(i, j, role, label):
        return b.el("L", i, j, "LAT", "beam", role, 1, label)

    if shape == "barrel":
        L, f, Ly = float(p["span"]), float(p["rise"]), float(p["length"])
        na, nl = max(2, int(p["n_arc"])), max(1, int(p["n_long"]))
        R, zc = _arc(L, f)
        half = math.asin(min(1.0, (L / 2) / R))
        xs = [L / 2 - R * math.sin(half * (1 - 2 * i / na)) for i in range(na + 1)]
        zs = [zc + R * math.cos(half * (1 - 2 * i / na)) for i in range(na + 1)]
        ys = [j * Ly / nl for j in range(nl + 1)]
        N = {(i, j): b.node(xs[i], ys[j], z0 + zs[i], 1, f"V{i},{j}") for i in range(na + 1) for j in range(nl + 1)}
        tx, ty = _tributary(xs), _tributary(ys)
        for (i, j), n in N.items():
            loads_at[n] = tx[i] * ty[j]
            if i < na:
                mem(n, N[(i + 1, j)], "arch", "Arch member")
            if j < nl and 0 < i < na:
                mem(n, N[(i, j + 1)], "longitudinal", "Longitudinal member")
            if i < na and j < nl and pattern != "ribbed":
                # herringbone: diagonals change direction at the crown so the vault is symmetric
                if pattern == "cross" or i < na / 2:
                    mem(n, N[(i + 1, j + 1)], "diagonal", "Diagonal")
                if pattern == "cross" or i >= na / 2:
                    mem(N[(i + 1, j)], N[(i, j + 1)], "diagonal", "Diagonal")
        for j in range(nl + 1):
            for i in (0, na):
                b.support(N[(i, j)], [1, 1, 1, 0, 0, 0])
        # edge members along the springing lines (on the supports)
        for i in (0, na):
            for j in range(nl):
                mem(N[(i, j)], N[(i, j + 1)], "longitudinal", "Edge member")
        grid = {"x": [{"name": "A", "pos": 0.0}, {"name": "B", "pos": L}],
                "y": [{"name": str(k + 1), "pos": ys[j]} for k, j in enumerate(range(0, nl + 1, max(1, nl // 6)))],
                "levels": [{"name": "Springing", "z": z0}, {"name": "Crown", "z": z0 + f}]}
        name = f"Barrel vault {L:g} × {Ly:g} m ({pattern})"
        plan = L * Ly
    else:
        D, f = float(p["diameter"]), float(p["dome_rise"])
        nr, ns = max(2, int(p["n_rings"])), max(6, int(p["n_sectors"]))
        R = (D ** 2 / 4 + f ** 2) / (2 * f)
        th0 = math.asin(min(1.0, (D / 2) / R))
        c = D / 2
        apex = b.node(c, c, z0 + f, 1, "Apex")
        rho = [R * math.sin(th0 * r / nr) for r in range(nr + 1)]
        zr = [R * math.cos(th0 * r / nr) - (R - f) for r in range(nr + 1)]
        ring = {}
        for r in range(1, nr + 1):
            off = 0.5 * (r % 2) if pattern == "lamella" else 0.0
            for k in range(ns):
                ang = 2 * math.pi * (k + off) / ns
                ring[(r, k)] = b.node(c + rho[r] * math.cos(ang), c + rho[r] * math.sin(ang), z0 + zr[r], 1, f"D{r},{k}")
        bounds = [0.0] + [(rho[r] + rho[r + 1]) / 2 for r in range(nr)] + [rho[nr]]
        loads_at[apex] = math.pi * bounds[1] ** 2
        for r in range(1, nr + 1):
            area = math.pi * (bounds[r + 1] ** 2 - bounds[r] ** 2) / ns
            for k in range(ns):
                loads_at[ring[(r, k)]] = area
                mem(ring[(r, k)], ring[(r, (k + 1) % ns)], "ring", "Ring member")
        for k in range(ns):
            mem(apex, ring[(1, k)], "rib", "Rib (meridian)")
        for r in range(1, nr):
            for k in range(ns):
                if pattern == "lamella":
                    # triangulated: each node joins the two nearest nodes of the next ring
                    if r % 2:   # this ring is rotated by half a step
                        mem(ring[(r, k)], ring[(r + 1, k)], "diagonal", "Lamella member")
                        mem(ring[(r, k)], ring[(r + 1, (k + 1) % ns)], "diagonal", "Lamella member")
                    else:
                        mem(ring[(r, k)], ring[(r + 1, k)], "diagonal", "Lamella member")
                        mem(ring[(r, k)], ring[(r + 1, (k - 1) % ns)], "diagonal", "Lamella member")
                else:
                    mem(ring[(r, k)], ring[(r + 1, k)], "rib", "Rib (meridian)")
                    if pattern == "schwedler":
                        mem(ring[(r, k)], ring[(r + 1, (k + 1) % ns)], "diagonal", "Diagonal")
        for k in range(ns):
            b.support(ring[(nr, k)], [1, 1, 1, 0, 0, 0])
        grid = {"x": [{"name": "A", "pos": 0.0}, {"name": "B", "pos": D}], "y": [{"name": "1", "pos": 0.0}, {"name": "2", "pos": D}],
                "levels": [{"name": "Springing", "z": z0}, {"name": "Apex", "z": z0 + f}]}
        name = f"Dome Ø{D:g} m ({pattern})"
        plan = math.pi * rho[nr] ** 2
    for case, q in (("SDL", p["sdl"]), ("LL", p["live_load"])):
        if q:
            for n, A in loads_at.items():
                b.loads.append({"case": case, "kind": "nodal", "node": n, "values": [0, 0, -q * A, 0, 0, 0],
                                "label": f"Roof {q} kN/m² × {A:.2f} m² tributary plan area (lumped at node)"})
    m = b.model(name, p, sections, _gravity_cases(), grid)
    m["notes"] = ["Single-layer lattice with rigid (moment) joints; members are beam elements.",
                  "Roof load lumped at the nodes by tributary plan area (cladding assumed to span between nodes).",
                  "Supported by pins along the springing line (ring beam / walls assumed rigid).",
                  "Single-layer lattice roofs are sensitive to buckling, snap-through and imperfections. Run the "
                  "Stability mode for elastic buckling factors; snap-through and imperfection sensitivity are NOT checked.",
                  f"Plan area {plan:.1f} m²."]
    return m


def _name(s, mat):
    sh = s.get("shape")
    if sh == "pipe":
        return f"CHS {s['d'] * 1000:.1f}x{s['t'] * 1000:.1f} {mat}"
    if sh == "box":
        return f"RHS {s['h'] * 1000:.0f}x{s['b'] * 1000:.0f}x{s['t'] * 1000:.1f} {mat}"
    if sh == "I":
        return f"I {s['h'] * 1000:.0f}x{s['bf'] * 1000:.0f} {mat}"
    if sh == "rect":
        return f"{s['b'] * 1000:.0f}x{s['h'] * 1000:.0f} {mat}"
    return s.get("name", "section")


__all__ = ["generate_truss2d", "generate_warehouse", "generate_space_truss", "generate_lattice_roof", "truss_geometry", "COMBOS"]
