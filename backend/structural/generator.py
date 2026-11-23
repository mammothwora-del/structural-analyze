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
}

COMBOS = {
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
                              "span_type": p["slab_span_type"], "level": lv,
                              "label": f"Slab L{lv} x[{a:g},{b:g}] y[{c:g},{d:g}]"})

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
        W = _level_weights(p, xs, ys, zs, sections, elements, slabs, nodes)
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
                     "stress_limit_steel": 355000.0},
        "grid": {"x": [{"name": n, "pos": v} for n, v in zip(xg, xs)],
                 "y": [{"name": n, "pos": v} for n, v in zip(yg, ys)],
                 "levels": [{"name": "Base" if k == 0 else f"L{k}", "z": z} for k, z in enumerate(zs)]},
        "materials": {k: v for k, v in MATERIALS.items()},
        "sections": sections,
        "nodes": nodes,
        "elements": elements,
        "slabs": slabs,
        "supports": supports,
        "load_cases": cases,
        "loads": loads,
        "combinations": default_combinations(p["standard"], case_ids),
        "generator": p,
    }
    return model


def _sec_name(s):
    if s.get("shape") == "rect":
        return f"{s['b'] * 1000:.0f}x{s['h'] * 1000:.0f} {s.get('material', '')}"
    if s.get("shape") == "I":
        return f"I {s['h'] * 1000:.0f}x{s['bf'] * 1000:.0f} {s.get('material', '')}"
    return s.get("name", "section")


def _level_weights(p, xs, ys, zs, sections, elements, slabs, nodes):
    nlev = len(zs) - 1
    W = [0.0] * (nlev + 1)
    area = (xs[-1]) * (ys[-1])
    for lv in range(1, nlev + 1):
        W[lv] += area * (p["slab_thickness"] * 25.0 + p["sdl"])
    zlev = {n["id"]: n["level"] for n in nodes}
    xyz = {n["id"]: (n["x"], n["y"], n["z"]) for n in nodes}
    for e in elements:
        s = sections[e["section"]]
        w = section_properties(s).A * MATERIALS[s["material"]]["density"]
        a, b = xyz[e["i"]], xyz[e["j"]]
        L = sum((u - v) ** 2 for u, v in zip(a, b)) ** 0.5
        if e["type"] == "column":
            for n in (e["i"], e["j"]):
                if zlev[n] > 0:
                    W[zlev[n]] += w * L / 2
        else:
            W[e["level"]] += w * L
    return W
