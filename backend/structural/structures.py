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
def truss_geometry(kind: str, span: float, height: float, panels: int, eave_depth: float = 0.0):
    """Nodes (x, z) and members of a planar truss in the x-z plane.

    Returns (points: dict name->(x, z), members: list of (a, b, role), roof: list of node names
    on the top chord from left to right, supports: (left, right)).
    kind: 'pratt' | 'howe' | 'warren' | 'pitched' (Pratt-type gable truss; eave_depth > 0 gives
    vertical end posts, i.e. a truss with depth at the supports).
    """
    n = max(2, int(panels))
    if kind != "warren" and n % 2:
        n += 1
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
    else:
        raise ValueError(f"Unknown truss type '{kind}'")
    # de-duplicate
    seen, uniq = set(), []
    for a_, b_, r in M:
        key = tuple(sorted((a_, b_)))
        if key not in seen:
            seen.add(key)
            uniq.append((a_, b_, r))
    return P, uniq, roof, ("B0", f"B{n}")


TRUSS_DEFAULTS = {
    "type": "truss2d", "truss_type": "pratt", "span": 18.0, "height": 2.0, "panels": 6, "eave_depth": 0.0,
    "spacing": 6.0, "sdl": 0.5, "live_load": 0.5, "standard": "EN1990",
    "chord": {"shape": "box", "b": 0.15, "h": 0.15, "t": 0.008}, "web": {"shape": "pipe", "d": 0.0889, "t": 0.005},
}


def generate_truss2d(params: dict | None = None) -> dict:
    p = {**TRUSS_DEFAULTS, **(params or {})}
    p["steel"] = p.get("material") or STEEL.get(p["standard"], "S355")
    P, M, roof, (left, right) = truss_geometry(p["truss_type"], float(p["span"]), float(p["height"]), int(p["panels"]),
                                               float(p.get("eave_depth", 0.0)))
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
WAREHOUSE_DEFAULTS = {
    "type": "warehouse", "span": 20.0, "bay": 6.0, "n_bays": 5, "eave_height": 6.0, "rise": 2.0, "eave_depth": 1.0,
    "panels": 8, "support": "fixed", "sdl": 0.3, "live_load": 0.5, "wind_pressure": 0.8, "standard": "EN1990",
    "roof_bracing": True, "wall_bracing": True,
    "column": {"shape": "I", "h": 0.4, "bf": 0.2, "tf": 0.013, "tw": 0.008},
    "chord": {"shape": "box", "b": 0.15, "h": 0.15, "t": 0.006}, "web": {"shape": "pipe", "d": 0.0761, "t": 0.004},
    "purlin": {"shape": "box", "b": 0.1, "h": 0.15, "t": 0.004}, "brace": {"shape": "pipe", "d": 0.0603, "t": 0.004},
    "footing": {"B": 1.5, "L": 1.5, "t": 0.5}, "allowable_bearing": 200.0,
}


def generate_warehouse(params: dict | None = None) -> dict:
    p = {**WAREHOUSE_DEFAULTS, **(params or {})}
    p["steel"] = p.get("material") or STEEL.get(p["standard"], "S355")
    span, bay, nb, H = float(p["span"]), float(p["bay"]), int(p["n_bays"]), float(p["eave_height"])
    P, M, roof, _ = truss_geometry("pitched", span, float(p["rise"]), int(p["panels"]), float(p["eave_depth"]))
    st = p["steel"]
    sections = {k.upper()[:3]: {**p[k], "material": st, "name": _name(p[k], st)} for k in ("column", "chord", "web", "purlin", "brace")}
    S = {"column": "COL", "chord": "CHO", "web": "WEB", "purlin": "PUR", "brace": "BRA"}
    b = _Builder()
    ys = [j * bay for j in range(nb + 1)]
    frames = []
    for j, y in enumerate(ys):
        ids = {k: b.node(x, y, H + z, 1, f"F{j + 1}") for k, (x, z) in P.items()}
        frames.append(ids)
        n = int(p["panels"]) + (int(p["panels"]) % 2)
        for a_, b_, role in M:
            if {a_, b_} in ({"B0", "T0"}, {f"B{n}", f"T{n}"}):
                continue   # end posts are the column heads

            b.el("T", ids[a_], ids[b_], S["chord"] if role == "chord" else S["web"], "truss", role, 1,
                 f"Truss F{j + 1} {role} {a_}-{b_}", truss=True)
        for side, k in (("L", 0), ("R", n)):
            x = k * span / n
            base = b.node(x, y, 0.0, 0, f"F{j + 1}{side}")
            b.el("C", base, ids[f"B{k}"], S["column"], "column", "column", 1, f"Column F{j + 1} {side}")
            if f"T{k}" in ids:   # column continues to the top chord (truss with depth at the eaves)
                b.el("C", ids[f"B{k}"], ids[f"T{k}"], S["column"], "column", "column", 1, f"Column head F{j + 1} {side}")
            # pinned base: free to rotate about the horizontal axes; twist about the column axis is held by the base plate
            b.support(base, dofs=[1, 1, 1, 0, 0, 1] if p["support"] == "pinned" else None,
                      kind=p["support"], footing={**p["footing"], "type": "isolated", "label": f"Footing F{j + 1}{side}"})
    # purlins along every top-chord node line, eave struts along the bottom-chord ends
    xs_roof = [P[r][0] for r in roof]
    trib = _tributary(xs_roof)
    for r, w in zip(roof, trib):
        for j in range(nb):
            eid = b.el("P", frames[j][r], frames[j + 1][r], S["purlin"], "beam", "purlin", 1, f"Purlin {r} F{j + 1}-F{j + 2}", pinned=True)
            for case, q in (("SDL", p["sdl"]), ("LL", p["live_load"])):
                if q:
                    b.loads.append({"case": case, "kind": "dist", "element": eid, "direction": [0, 0, -1],
                                    "points": [[0, q * w], [1, q * w]], "relative": True,
                                    "label": f"Roof {q} kN/m² × {w:.2f} m tributary width (one-way sheeting, assumed)"})
    n = int(p["panels"]) + (int(p["panels"]) % 2)
    for k in (0, n):
        if f"T{k}" in P:   # eave struts at the bottom-chord level as well
            for j in range(nb):
                b.el("P", frames[j][f"B{k}"], frames[j + 1][f"B{k}"], S["purlin"], "beam", "eave", 1, f"Eave strut F{j + 1}-F{j + 2}", pinned=True)
    # bottom-chord ties along the building (out-of-plane restraint of the bottom chords), anchored by
    # vertical cross-bracing between the trusses in the end bays
    end_bays = sorted({0, nb - 1})
    bottom_inner = [f"B{k}" for k in range(1, n)]
    for bk in bottom_inner:
        for j in range(nb):
            b.el("X", frames[j][bk], frames[j + 1][bk], S["brace"], "brace", "tie", 1, f"Bottom-chord tie {bk} F{j + 1}-F{j + 2}", truss=True)
        tk = f"T{bk[1:]}"
        if tk in P:
            for j in end_bays:
                b.el("X", frames[j][bk], frames[j + 1][tk], S["brace"], "brace", "vertical brace", 1, f"Vertical brace bay {j + 1}", truss=True)
                b.el("X", frames[j + 1][bk], frames[j][tk], S["brace"], "brace", "vertical brace", 1, f"Vertical brace bay {j + 1}", truss=True)
    # bracing in the end bays
    if p.get("roof_bracing"):
        for j in end_bays:
            for k in range(len(roof) - 1):
                a1, a2 = roof[k], roof[k + 1]
                b.el("X", frames[j][a1], frames[j + 1][a2], S["brace"], "brace", "roof brace", 1, f"Roof brace bay {j + 1}", truss=True)
                b.el("X", frames[j][a2], frames[j + 1][a1], S["brace"], "brace", "roof brace", 1, f"Roof brace bay {j + 1}", truss=True)
    if p.get("wall_bracing"):
        for j in end_bays:
            for k in (0, n):
                x = k * span / n
                b0, b1 = b.node(x, ys[j], 0.0, 0), b.node(x, ys[j + 1], 0.0, 0)
                b.el("X", b0, frames[j + 1][f"B{k}"], S["brace"], "brace", "wall brace", 1, f"Wall brace bay {j + 1}", truss=True)
                b.el("X", b1, frames[j][f"B{k}"], S["brace"], "brace", "wall brace", 1, f"Wall brace bay {j + 1}", truss=True)
    cases = _gravity_cases()
    if p.get("wind_pressure"):
        cases.append({"id": "WX", "name": "Wind +X (simplified net pressure on the long wall)", "type": "wind"})
        trib_y = _tributary(ys)
        for j, w in enumerate(trib_y):
            F = p["wind_pressure"] * w * H / 2
            b.loads.append({"case": "WX", "kind": "nodal", "node": frames[j]["B0"], "values": [F, 0, 0, 0, 0, 0],
                            "label": "Wind lumped at column head (half wall height)"})
    grid = {"x": [{"name": "A", "pos": 0.0}, {"name": "B", "pos": span}],
            "y": [{"name": str(j + 1), "pos": y} for j, y in enumerate(ys)],
            "levels": [{"name": "Base", "z": 0.0}, {"name": "Eave", "z": H}]}
    m = b.model(f"Warehouse {span:g} × {nb * bay:g} m", p, sections, cases, grid)
    m["notes"] = ["Roof sheeting assumed to span one way between purlins (tributary width per purlin).",
                  "Purlins and eave struts are simply supported between trusses (pinned ends).",
                  "Bottom chords are restrained out of plane by longitudinal ties anchored by vertical bracing in the end bays.",
                  "Truss members and bracing are pin-ended (axial only under nodal loads); bracing acts in tension and compression.",
                  "Wind: simplified net pressure on the long wall lumped at the windward column heads; not a code calculation."]
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


__all__ = ["generate_truss2d", "generate_warehouse", "generate_space_truss", "truss_geometry", "COMBOS"]
