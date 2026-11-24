"""Parametric multi-storey building generator.

Creates a regular grid frame with columns, main beams, optional secondary beams,
slab panels, footings/supports, load cases, loads and load combinations. The
result is a plain model dict (see docs/model-format.md) that the user can edit.

Lateral load generators here are deliberately simple and are labelled as such:
* Wind: a uniform net pressure (kN/m2, windward + leeward combined) on the
  facade, lumped to the windward column nodes by tributary width and height.
* Seismic: equivalent lateral force with a user coefficient Cs; storey forces
  F_k = Cs W W_k h_k / sum(W_i h_i) shared equally by the column nodes of a level.
They are NOT code calculations of wind/seismic actions.
"""
from __future__ import annotations

import string

from .sections import MATERIALS, section_properties

DEFAULTS = {
    "x_spans": [6.0, 6.0, 6.0],
    "y_spans": [5.0, 5.0],
    "story_heights": [4.0, 3.5, 3.5, 3.5],
    "column": {"shape": "rect", "b": 0.4, "h": 0.4, "material": "C30/37"},
    "main_beam": {"shape": "rect", "b": 0.3, "h": 0.6, "material": "C30/37"},
    "secondary_beam": {"shape": "rect", "b": 0.25, "h": 0.45, "material": "C30/37"},
    "secondary_beams": "y",          # 'none' | 'x' | 'y'  (direction the secondary beams run)
    "secondary_per_bay": 1,
    "slab_thickness": 0.18,
    "slab_span_type": "auto",
    "sdl": 1.5,                      # kN/m2
    "live_load": 3.0,                # kN/m2 (floors)
    "roof_live_load": 1.0,           # kN/m2
    "support": "fixed",
    "footing": {"B": 2.0, "L": 2.0, "t": 0.6},
    "allowable_bearing": 250.0,      # kN/m2 (user input, used for a pressure ratio only)
    "wind_pressure": 1.0,            # kN/m2 net, 0 = no wind case
    "seismic_cs": 0.08,              # 0 = no seismic case
    "standard": "EN1990",
    "slab_model": "shell",           # 'shell' (FEM plate/shell) | 'tributary' (45-degree assumption)
    "mesh_size": 1.0,                # m, target shell element size
    "walls": "none",                 # 'none' | 'x' (walls in the XZ plane on the two outer Y lines) | 'xy'
    "wall_thickness": 0.2,
    "bracing": "none",               # 'none' | 'x' | 'diagonal'  (steel braces in the end bays of the outer frames)
    "brace": {"shape": "box", "b": 0.15, "h": 0.15, "t": 0.008},
}

STEEL_BY_STD = {"TH": "SS400", "EN1990": "S355", "ASCE7": "A992"}


def generate(params: dict | None = None) -> dict:
    """Dispatch to the generator for params['type'] (building | truss2d | warehouse | space_truss)."""
    from .structures import generate_space_truss, generate_truss2d, generate_warehouse
    t = (params or {}).get("type", "building")
    if t == "building":
        return generate_building(params)
    if t == "truss2d":
        return generate_truss2d(params)
    if t == "warehouse":
        return generate_warehouse(params)
    if t == "space_truss":
        return generate_space_truss(params)
    raise ValueError(f"Unknown structure type '{t}'")

COMBOS = {
    # Thai practice, strength design (EIT 1008-38 / Ministerial Regulation load factors based on ACI 318-95):
    # U = 1.4D + 1.7L ; U = 0.75(1.4D + 1.7L + 1.7W) ; U = 0.9D + 1.3W.
    # Seismic (DPT 1301/1302-61 style, strength-level E): 1.2D + 1.0L + 1.0E ; 0.9D + 1.0E
    # (the vertical term 0.2 S_DS D is not included). Verify against the edition in force for the project.
    "TH": [
        ("TH1", "1.4D + 1.7L", {"DL": 1.4, "SDL": 1.4, "LL": 1.7}),
        ("TH2", "0.75(1.4D + 1.7L + 1.7W)", {"DL": 1.05, "SDL": 1.05, "LL": 1.275, "WX": 1.275}),
        ("TH3", "0.9D + 1.3W", {"DL": 0.9, "SDL": 0.9, "WX": 1.3}),
        ("TH4", "1.2D + 1.0L + 1.0E (DPT 1301/1302)", {"DL": 1.2, "SDL": 1.2, "LL": 1.0, "EX": 1.0}),
        ("TH5", "0.9D + 1.0E (DPT 1301/1302)", {"DL": 0.9, "SDL": 0.9, "EX": 1.0}),
        ("THS", "D + L (service)", {"DL": 1.0, "SDL": 1.0, "LL": 1.0}),
    ],
    "EN1990": [
        ("ULS1", "1.35G", {"DL": 1.35, "SDL": 1.35}),
        ("ULS2", "1.35G + 1.5Q", {"DL": 1.35, "SDL": 1.35, "LL": 1.5}),
        ("ULS3", "1.35G + 1.5Q + 0.9Wx", {"DL": 1.35, "SDL": 1.35, "LL": 1.5, "WX": 0.9}),
        ("ULS4", "1.35G + 1.05Q + 1.5Wx", {"DL": 1.35, "SDL": 1.35, "LL": 1.05, "WX": 1.5}),
        ("ULS5", "1.0G + 1.5Wx", {"DL": 1.0, "SDL": 1.0, "WX": 1.5}),
        ("SEIS1", "G + 0.3Q + Ex", {"DL": 1.0, "SDL": 1.0, "LL": 0.3, "EX": 1.0}),
        ("SLS1", "G + Q (characteristic)", {"DL": 1.0, "SDL": 1.0, "LL": 1.0}),
    ],
    "ASCE7": [
        ("LRFD1", "1.4D", {"DL": 1.4, "SDL": 1.4}),
        ("LRFD2", "1.2D + 1.6L", {"DL": 1.2, "SDL": 1.2, "LL": 1.6}),
        ("LRFD4", "1.2D + 1.0W + L", {"DL": 1.2, "SDL": 1.2, "LL": 1.0, "WX": 1.0}),
        ("LRFD5", "1.2D + 1.0E + L", {"DL": 1.2, "SDL": 1.2, "LL": 1.0, "EX": 1.0}),
        ("LRFD6", "0.9D + 1.0W", {"DL": 0.9, "SDL": 0.9, "WX": 1.0}),
        ("LRFD7", "0.9D + 1.0E", {"DL": 0.9, "SDL": 0.9, "EX": 1.0}),
        ("SERV", "D + L (service)", {"DL": 1.0, "SDL": 1.0, "LL": 1.0}),
    ],
}


def default_combinations(standard: str, cases: set[str]):
    out = []
    for cid, name, factors in COMBOS.get(standard, COMBOS["EN1990"]):
        f = {k: v for k, v in factors.items() if k in cases}
        if any(k not in cases for k in factors if k in ("WX", "EX")):
            continue
        out.append({"id": cid, "name": name, "factors": f})
    return out


def _cum(spans):
    out = [0.0]
    for s in spans:
        out.append(round(out[-1] + float(s), 9))
    return out


def generate_building(params: dict | None = None) -> dict:
    p = {**DEFAULTS, **(params or {})}
    xs, ys = _cum(p["x_spans"]), _cum(p["y_spans"])
    zs = _cum(p["story_heights"])
    nlev = len(zs) - 1
    xg = [str(i + 1) for i in range(len(xs))]
    yg = list(string.ascii_uppercase[: len(ys)])

    # secondary lines (positions inside bays)
    sec_dir = p["secondary_beams"]
    nsec = int(p["secondary_per_bay"]) if sec_dir in ("x", "y") else 0
    sec_x, sec_y = [], []
    if sec_dir == "y":   # beams run along Y, located at intermediate x positions
        for a, b in zip(xs[:-1], xs[1:]):
            sec_x += [a + (b - a) * (k + 1) / (nsec + 1) for k in range(nsec)]
    elif sec_dir == "x":
        for a, b in zip(ys[:-1], ys[1:]):
            sec_y += [a + (b - a) * (k + 1) / (nsec + 1) for k in range(nsec)]
    all_x = sorted(xs + sec_x)
    all_y = sorted(ys + sec_y)

    nodes, node_at = [], {}

    def node(x, y, z, level, tag):
        key = (round(x, 6), round(y, 6), level)
        if key not in node_at:
            nid = f"N{len(nodes) + 1}"
            node_at[key] = nid
            nodes.append({"id": nid, "x": x, "y": y, "z": z, "level": level, "grid": tag})
        return node_at[key]

    def gname(x, y):
        gx = xg[xs.index(x)] if x in xs else f"{x:g}"
        gy = yg[ys.index(y)] if y in ys else f"{y:g}"
        return f"{gy}{gx}" if (x in xs and y in ys) else f"{gy}/{gx}"

    for lv, z in enumerate(zs):
        for x in xs:
            for y in ys:
                node(x, y, z, lv, gname(x, y))
        if lv > 0:
            for x in sec_x:
                for y in ys:
                    node(x, y, z, lv, gname(x, y))
            for y in sec_y:
                for x in xs:
                    node(x, y, z, lv, gname(x, y))

    sections = {
        "COL": {**p["column"], "name": _sec_name(p["column"])},
        "MB": {**p["main_beam"], "name": _sec_name(p["main_beam"])},
    }
    if nsec:
        sections["SB"] = {**p["secondary_beam"], "name": _sec_name(p["secondary_beam"])}

    elements = []

    def add(kind, role, i, j, sec, lv, label):
        elements.append({"id": f"{kind}{len([e for e in elements if e['id'][0] == kind]) + 1}",
                         "type": "column" if kind == "C" else "beam", "role": role,
                         "i": i, "j": j, "section": sec, "level": lv, "label": label})

    for lv in range(1, nlev + 1):
        for x in xs:
            for y in ys:
                add("C", "column", node_at[(round(x, 6), round(y, 6), lv - 1)], node_at[(round(x, 6), round(y, 6), lv)],
                    "COL", lv, f"Column {gname(x, y)} storey {lv}")
    for lv in range(1, nlev + 1):
        # beams along X on main y-lines (split at secondary x positions)
        for y in ys:
            for a, b in zip(all_x[:-1], all_x[1:]):
                add("B", "main", node_at[(round(a, 6), round(y, 6), lv)], node_at[(round(b, 6), round(y, 6), lv)],
                    "MB", lv, f"Main beam {gname(a, y)}-{gname(b, y)} L{lv}")
        # beams along Y on main x-lines
        for x in xs:
            for a, b in zip(all_y[:-1], all_y[1:]):
                add("B", "main", node_at[(round(x, 6), round(a, 6), lv)], node_at[(round(x, 6), round(b, 6), lv)],
                    "MB", lv, f"Main beam {gname(x, a)}-{gname(x, b)} L{lv}")
        for x in sec_x:
            for a, b in zip(ys[:-1], ys[1:]):
                add("B", "secondary", node_at[(round(x, 6), round(a, 6), lv)], node_at[(round(x, 6), round(b, 6), lv)],
                    "SB", lv, f"Secondary beam x={x:g} {yg[ys.index(a)]}-{yg[ys.index(b)]} L{lv}")
        for y in sec_y:
            for a, b in zip(xs[:-1], xs[1:]):
                add("B", "secondary", node_at[(round(a, 6), round(y, 6), lv)], node_at[(round(b, 6), round(y, 6), lv)],
                    "SB", lv, f"Secondary beam y={y:g} {xg[xs.index(a)]}-{xg[xs.index(b)]} L{lv}")

    slabs = []
    for lv in range(1, nlev + 1):
        for a, b in zip(all_x[:-1], all_x[1:]):
            for c, d in zip(all_y[:-1], all_y[1:]):
                corners = [node_at[(round(a, 6), round(c, 6), lv)], node_at[(round(b, 6), round(c, 6), lv)],
                           node_at[(round(b, 6), round(d, 6), lv)], node_at[(round(a, 6), round(d, 6), lv)]]
                slabs.append({"id": f"S{len(slabs) + 1}", "corners": corners, "thickness": p["slab_thickness"],
                              "density": MATERIALS.get(p["column"].get("material", ""), {}).get("density", 25.0),
                              "material": p["column"].get("material", "C30/37"),
                              "span_type": p["slab_span_type"], "level": lv,
                              "label": f"Slab L{lv} x[{a:g},{b:g}] y[{c:g},{d:g}]"})

    # Shear walls (shell elements): in the middle bay of the outer frames, full height.
    walls = []
    wmode = p.get("walls", "none")
    wmat = p["column"].get("material", "C30/37")
    wdens = MATERIALS.get(wmat, {}).get("density", 25.0)

    def wall(c4, lv, label):
        walls.append({"id": f"W{len(walls) + 1}", "corners": c4, "thickness": p["wall_thickness"], "material": wmat,
                      "density": wdens, "level": lv, "base_support": p["support"] if lv == 1 else None, "label": label})

    if wmode in ("x", "xy") and len(xs) > 1:
        k = (len(xs) - 2) // 2
        a, b = xs[k], xs[k + 1]
        for y in (ys[0], ys[-1]):
            for lv in range(1, nlev + 1):
                n = lambda x, l: node_at[(round(x, 6), round(y, 6), l)]
                wall([n(a, lv - 1), n(b, lv - 1), n(b, lv), n(a, lv)], lv, f"Wall y={y:g} x[{a:g},{b:g}] storey {lv}")
    if wmode == "xy" and len(ys) > 1:
        k = (len(ys) - 2) // 2
        a, b = ys[k], ys[k + 1]
        for x in (xs[0], xs[-1]):
            for lv in range(1, nlev + 1):
                n = lambda y, l: node_at[(round(x, 6), round(y, 6), l)]
                wall([n(a, lv - 1), n(b, lv - 1), n(b, lv), n(a, lv)], lv, f"Wall x={x:g} y[{a:g},{b:g}] storey {lv}")

    # Steel bracing (pin-ended truss members) in the end bays of the outer frames.
    bmode = p.get("bracing", "none")
    if bmode in ("x", "diagonal"):
        steel = STEEL_BY_STD.get(p["standard"], "S355")
        sections["BR"] = {**p["brace"], "material": steel, "name": f"Brace {_sec_name({**p['brace'], 'material': steel})}"}
        bays = []
        for y in (ys[0], ys[-1]):
            for a, b in sorted({(xs[0], xs[1]), (xs[-2], xs[-1])}):
                bays.append(((a, y), (b, y)))
        if len(ys) > 1:
            for x in (xs[0], xs[-1]):
                for a, b in sorted({(ys[0], ys[1]), (ys[-2], ys[-1])}):
                    bays.append(((x, a), (x, b)))
        for (p1, p2) in bays:
            for lv in range(1, nlev + 1):
                n1b, n2b = node_at[(round(p1[0], 6), round(p1[1], 6), lv - 1)], node_at[(round(p2[0], 6), round(p2[1], 6), lv - 1)]
                n1t, n2t = node_at[(round(p1[0], 6), round(p1[1], 6), lv)], node_at[(round(p2[0], 6), round(p2[1], 6), lv)]
                pairs = [(n1b, n2t)] + ([(n2b, n1t)] if bmode == "x" else [])
                for i, j in pairs:
                    elements.append({"id": f"X{len([e for e in elements if e['id'][0] == 'X']) + 1}", "type": "brace", "role": "brace",
                                     "i": i, "j": j, "section": "BR", "level": lv, "truss": True,
                                     "label": f"Brace storey {lv} ({gname(*p1)}-{gname(*p2)})"})

    supports = []
    for x in xs:
        for y in ys:
            supports.append({"node": node_at[(round(x, 6), round(y, 6), 0)], "type": p["support"],
                             "footing": {**p["footing"], "type": "isolated", "label": f"Footing {gname(x, y)}"}})

    cases = [
        {"id": "DL", "name": "Dead load (self weight)", "type": "dead", "self_weight": True},
        {"id": "SDL", "name": "Superimposed dead load", "type": "sdl"},
        {"id": "LL", "name": "Live load", "type": "live"},
    ]
    loads = []
    roof_slabs = [s["id"] for s in slabs if s["level"] == nlev]
    floor_slabs = [s["id"] for s in slabs if s["level"] < nlev]
    if p["sdl"]:
        loads.append({"case": "SDL", "kind": "area", "slabs": [s["id"] for s in slabs], "q": p["sdl"], "label": "SDL all floors"})
    if p["live_load"] and floor_slabs:
        loads.append({"case": "LL", "kind": "area", "slabs": floor_slabs, "q": p["live_load"], "label": "Floor live load"})
    if p["roof_live_load"] and roof_slabs:
        loads.append({"case": "LL", "kind": "area", "slabs": roof_slabs, "q": p["roof_live_load"], "label": "Roof live load"})

    width_y = ys[-1]
    if p["wind_pressure"]:
        cases.append({"id": "WX", "name": "Wind +X (simplified net pressure)", "type": "wind"})
        for lv in range(1, nlev + 1):
            h_trib = (zs[lv] - zs[lv - 1]) / 2 + ((zs[lv + 1] - zs[lv]) / 2 if lv < nlev else 0.0)
            for k, y in enumerate(ys):
                w_trib = ((ys[k] - ys[k - 1]) / 2 if k > 0 else 0) + ((ys[k + 1] - ys[k]) / 2 if k < len(ys) - 1 else 0)
                F = p["wind_pressure"] * h_trib * w_trib
                loads.append({"case": "WX", "kind": "nodal", "node": node_at[(0.0, round(y, 6), lv)],
                              "values": [F, 0, 0, 0, 0, 0], "label": "Wind lumped facade load"})
    if p["seismic_cs"]:
        cases.append({"id": "EX", "name": f"Seismic +X (ELF, Cs={p['seismic_cs']})", "type": "seismic"})
        # seismic weight per level: slabs (self + SDL) + beams + half columns above/below
        W = _level_weights(p, xs, ys, zs, sections, elements, slabs, nodes, walls)
        sum_wh = sum(W[lv] * zs[lv] for lv in range(1, nlev + 1))
        V = p["seismic_cs"] * sum(W[1:])
        ncol = len(xs) * len(ys)
        for lv in range(1, nlev + 1):
            Fk = V * W[lv] * zs[lv] / sum_wh
            for x in xs:
                for y in ys:
                    loads.append({"case": "EX", "kind": "nodal", "node": node_at[(round(x, 6), round(y, 6), lv)],
                                  "values": [Fk / ncol, 0, 0, 0, 0, 0], "label": f"ELF storey force L{lv}"})

    case_ids = {c["id"] for c in cases}
    model = {
        "name": "Generated building",
        "units": {"force": "kN", "length": "m"},
        "settings": {"standard": p["standard"], "allowable_bearing": p["allowable_bearing"],
                     "stress_limit_concrete": 0.6 * MATERIALS.get(p["column"].get("material", "C30/37"), {}).get("fck", 30) * 1000,
                     "slab_model": p.get("slab_model", "shell"), "mesh_size": float(p.get("mesh_size", 1.0)),
                     "stress_limit_steel": 355000.0},
        "grid": {"x": [{"name": n, "pos": v} for n, v in zip(xg, xs)],
                 "y": [{"name": n, "pos": v} for n, v in zip(yg, ys)],
                 "levels": [{"name": "Base" if k == 0 else f"L{k}", "z": z} for k, z in enumerate(zs)]},
        "materials": {k: v for k, v in MATERIALS.items()},
        "sections": sections,
        "nodes": nodes,
        "elements": elements,
        "slabs": slabs,
        "walls": walls,
        "supports": supports,
        "load_cases": cases,
        "loads": loads,
        "combinations": default_combinations(p["standard"], case_ids),
        "generator": p,
    }
    return model


def _sec_name(s):
    if s.get("shape") == "box":
        return f"RHS {s['h'] * 1000:.0f}x{s['b'] * 1000:.0f}x{s['t'] * 1000:.1f} {s.get('material', '')}"
    if s.get("shape") == "pipe":
        return f"CHS {s['d'] * 1000:.1f}x{s['t'] * 1000:.1f} {s.get('material', '')}"
    if s.get("shape") == "rect":
        return f"{s['b'] * 1000:.0f}x{s['h'] * 1000:.0f} {s.get('material', '')}"
    if s.get("shape") == "I":
        return f"I {s['h'] * 1000:.0f}x{s['bf'] * 1000:.0f} {s.get('material', '')}"
    return s.get("name", "section")


def _level_weights(p, xs, ys, zs, sections, elements, slabs, nodes, walls=()):
    nlev = len(zs) - 1
    W = [0.0] * (nlev + 1)
    area = (xs[-1]) * (ys[-1])
    for lv in range(1, nlev + 1):
        W[lv] += area * (p["slab_thickness"] * MATERIALS.get(p["column"].get("material", ""), {}).get("density", 25.0) + p["sdl"])
    zlev = {n["id"]: n["level"] for n in nodes}
    xyz = {n["id"]: (n["x"], n["y"], n["z"]) for n in nodes}
    for e in elements:
        s = sections[e["section"]]
        w = section_properties(s).A * MATERIALS.get(s["material"], {"density": 25.0})["density"]
        a, b = xyz[e["i"]], xyz[e["j"]]
        L = sum((u - v) ** 2 for u, v in zip(a, b)) ** 0.5
        if e["type"] == "column":
            for n in (e["i"], e["j"]):
                if zlev[n] > 0:
                    W[zlev[n]] += w * L / 2
        else:
            W[e["level"]] += w * L
    for wl in walls:
        c = [xyz[n] for n in wl["corners"]]
        width = sum((u - v) ** 2 for u, v in zip(c[0], c[1])) ** 0.5
        height = abs(c[2][2] - c[1][2])
        wt = width * height * wl["thickness"] * wl["density"]
        lv = wl["level"]
        W[lv] += wt / 2
        if lv - 1 > 0:
            W[lv - 1] += wt / 2
    return W
