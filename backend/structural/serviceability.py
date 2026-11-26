"""Serviceability: deflection of beams, roof members and trusses, and column drift.

Members are grouped into spans, because a beam is often several elements in the analysis model:
  * Beam spans: beam elements (not columns, braces or truss members) joined end to end where they continue in nearly
    the same direction (< 35 deg, so a pitched rafter runs eave to eave) with the same role. A span stops at a support,
    at a node where a column or a truss member connects, or where the beam does not simply continue. Deflection is
    measured from the straight line between the span's end points (end displacements subtracted), perpendicular
    to it. A span with a free end is a cantilever: tip deflection relative to the root, against 2L.
  * Trusses: each connected set of truss members that lies in one vertical plane. Vertical deflection of every truss
    node relative to the two supports (nodes shared with a column or a support) on either side of it, over that span.
    Space trusses and lattice shells are not checked.
  * Column drift: collinear column elements stacked end to end, split into storeys at the highest node of each
    level (the whole height when the nodes carry no levels). Relative horizontal displacement of the two ends of a
    storey over its height.

Serviceability combinations (unfactored):
  * total: the model's SLS combinations (names or ids with SLS, service, characteristic), or D + L when there are none;
  * live: the live load cases alone;
  * wind: each wind case alone, times a factor: the one given, else the case's own "sls_factor" (set by the DPT 1311
    wind generator: serviceability pressure / strength pressure), else 1.0 (0.6 for ASCE 7, whose wind loads are
    strength level).
Beams and trusses: the total limit for "total", the live limit for "live" (and for "wind" on roof members). Drift:
every serviceability combination.

Default limits (ASSUMED, editable): IBC 2018 Table 1604.3 for floors (L/360 live, L/240 total) and for roof members
supporting a non-plaster ceiling (L/240 live or wind, L/180 total); drift H/400 for buildings with more than one
level and H/200 for single-storey frames (common practice; AISC Design Guide 3). Seismic drift (Cd x elastic
drift to DPT 1301/1302 or ASCE 7) is not checked.
"""
from __future__ import annotations

import math

import numpy as np

from .analysis import analyze
from .steel_design import SLS_WORDS

DEFAULT_LIMITS = {"floor_live": 360.0, "floor_total": 240.0, "roof_live": 240.0, "roof_total": 180.0,
                  "drift_multi": 400.0, "drift_single": 200.0}
ROOF_ROLES = {"purlin", "eave", "rafter", "girt", "roof beam"}
NO_SPAN_ROLES = {"rib", "ring", "arch", "longitudinal", "diagonal", "lattice"}
MAX_TURN = math.radians(35.0)


def sls_combinations(model: dict, wind_factor: float | None = None) -> list[dict]:
    cases = {c["id"]: c.get("type", "") for c in model.get("load_cases", [])}
    std = model.get("settings", {}).get("standard", "EN1990")
    user_factor = wind_factor is not None
    if wind_factor is None:
        wind_factor = 0.6 if std == "ASCE7" else 1.0
    out = []
    for c in model.get("combinations", []):
        text = f"{c['id']} {c.get('name', '')}".lower()
        if any(w in text for w in SLS_WORDS):
            f = {k: float(v) for k, v in c["factors"].items() if k in cases}
            if f:
                out.append({"id": c["id"], "name": c.get("name", c["id"]), "factors": f, "kind": "total"})
    if not out:
        f = {k: 1.0 for k, t in cases.items() if t in ("dead", "sdl", "live")}
        if f:
            out.append({"id": "SLS-DL", "name": "D + L (unfactored, added for the check)", "factors": f, "kind": "total"})
    live = {k: 1.0 for k, t in cases.items() if t == "live"}
    if live:
        out.append({"id": "SLS-L", "name": "L alone", "factors": live, "kind": "live"})
    sls_f = {c["id"]: c.get("sls_factor") for c in model.get("load_cases", [])}
    for k, t in cases.items():
        if t == "wind":
            f = wind_factor if user_factor or sls_f.get(k) is None else float(sls_f[k])
            out.append({"id": f"SLS-{k}", "name": f"{f:g} × {k} alone", "factors": {k: f}, "kind": "wind"})
    return out


def _combine_disp(res: dict, factors: dict) -> tuple[dict, dict]:
    """Node translations and element station displacements (global) for a combination."""
    nodes, els = {}, {}
    for c, fac in factors.items():
        case = res["cases"].get(c)
        if not case:
            continue
        for nid, d in case["displacements"].items():
            v = fac * np.asarray(d[:3], dtype=float)
            nodes[nid] = v if nid not in nodes else nodes[nid] + v
        for eid, st in case["elements"].items():
            v = fac * np.asarray(st["disp"], dtype=float)
            els[eid] = v if eid not in els else els[eid] + v
    return nodes, els


def _unit(v):
    n = np.linalg.norm(v)
    return v / n if n > 0 else v


def build_spans(model: dict) -> dict:
    """Beam spans, trusses and column stacks of the model (geometry only)."""
    xyz = {n["id"]: np.array([n["x"], n["y"], n["z"]], dtype=float) for n in model["nodes"]}
    # supports that hold the node vertically (lateral restraints and sliding guides do not end a span)
    from .solver import SUPPORT_TYPES
    supported = {s["node"] for s in model.get("supports", []) if not s.get("lateral")
                 and int((s.get("dofs") or SUPPORT_TYPES.get(s.get("type", "fixed"), [1] * 6))[2])}
    at: dict[str, list[dict]] = {}
    for e in model["elements"]:
        at.setdefault(e["i"], []).append(e)
        at.setdefault(e["j"], []).append(e)

    def is_beam(e):
        return e["type"] == "beam" and e.get("role") not in NO_SPAN_ROLES

    def other(e, n):
        return e["j"] if e["i"] == n else e["i"]

    def direction(e, frm):
        return _unit(xyz[other(e, frm)] - xyz[frm])

    def stops(n):
        return n in supported or any(x["type"] in ("column", "truss") for x in at[n])

    # beam spans
    spans, used = [], set()
    for e in model["elements"]:
        if not is_beam(e) or e["id"] in used:
            continue
        chain, ends = [e], []
        used.add(e["id"])
        for start in (e["i"], e["j"]):
            cur, n = e, start
            while True:
                if stops(n):
                    break
                d_in = direction(cur, n) * -1           # direction of travel arriving at n
                nxt = [x for x in at[n] if x is not cur and is_beam(x) and x.get("role") == cur.get("role")
                       and math.acos(max(-1.0, min(1.0, float(direction(x, n) @ d_in)))) < MAX_TURN]
                if len(nxt) != 1 or nxt[0]["id"] in used:
                    break
                cur = nxt[0]
                used.add(cur["id"])
                chain.append(cur)
                n = other(cur, n)
            ends.append(n)
        a, b = ends
        free = [n for n in (a, b) if len(at[n]) == 1 and n not in supported]
        roof = any(x.get("role") in ROOF_ROLES for x in chain)
        spans.append({"kind": "cantilever" if len(free) == 1 else "beam", "roof": roof, "elements": [x["id"] for x in chain],
                      "ends": [a, b], "free": free[0] if len(free) == 1 else None,
                      "role": chain[0].get("role") or chain[0]["type"]})

    # trusses: connected sets of truss members
    tr = [e for e in model["elements"] if e["type"] == "truss"]
    adj: dict[str, set] = {}
    for e in tr:
        adj.setdefault(e["i"], set()).add(e["id"])
        adj.setdefault(e["j"], set()).add(e["id"])
    by_id = {e["id"]: e for e in tr}
    seen, trusses = set(), []
    for e in tr:
        if e["id"] in seen:
            continue
        stack, comp = [e["id"]], []
        seen.add(e["id"])
        while stack:
            x = by_id[stack.pop()]
            comp.append(x["id"])
            for n in (x["i"], x["j"]):
                for y in adj[n]:
                    if y not in seen:
                        seen.add(y)
                        stack.append(y)
        nodes = sorted({n for x in comp for n in (by_id[x]["i"], by_id[x]["j"])})
        sup = [n for n in nodes if n in supported or any(x["type"] == "column" for x in at[n])]
        P = np.array([xyz[n][:2] for n in nodes])
        c = P.mean(axis=0)
        w, v = np.linalg.eigh(np.cov((P - c).T) if len(P) > 2 else np.eye(2))
        ax = v[:, -1]
        s = {n: float((xyz[n][:2] - c) @ ax) for n in nodes}
        off = max(abs(float((xyz[n][:2] - c) @ v[:, 0])) for n in nodes)
        length = max(s.values()) - min(s.values())
        planar = off <= max(0.05 * length, 0.3)
        trusses.append({"kind": "truss", "roof": True, "elements": comp, "nodes": nodes, "supports": sup, "s": s,
                        "planar": planar, "role": "truss"})

    # column stacks: collinear column elements from end to end, then one drift item per storey (between the
    # highest nodes of consecutive levels; the whole height when the nodes carry no levels)
    level = {n["id"]: n.get("level") for n in model["nodes"]}
    cols, used = [], set()
    for e in model["elements"]:
        if e["type"] != "column" or e["id"] in used:
            continue
        chain = [e]
        used.add(e["id"])
        for start in (e["i"], e["j"]):
            cur, n = e, start
            while n not in supported:
                d_in = direction(cur, n) * -1
                nxt = [x for x in at[n] if x is not cur and x["type"] == "column" and x["id"] not in used
                       and math.acos(max(-1.0, min(1.0, float(direction(x, n) @ d_in)))) < math.radians(10)]
                if len(nxt) != 1:
                    break
                cur = nxt[0]
                used.add(cur["id"])
                chain.append(cur)
                n = other(cur, n)
        nodes = sorted({n for x in chain for n in (x["i"], x["j"])}, key=lambda n: xyz[n][2])
        if all(level[n] is None for n in nodes):
            stops_ = [nodes[0], nodes[-1]]
        else:
            top: dict = {}
            for n in nodes:
                top[level[n]] = n                      # nodes sorted by z: the last one is the highest
            stops_ = [nodes[0]] + [top[k] for k in sorted(top, key=lambda k: xyz[top[k]][2]) if top[k] != nodes[0]]
        for a_, b_ in zip(stops_[:-1], stops_[1:]):
            za, zb = xyz[a_][2], xyz[b_][2]
            seg = [x["id"] for x in chain if min(xyz[x["i"]][2], xyz[x["j"]][2]) >= za - 1e-6
                   and max(xyz[x["i"]][2], xyz[x["j"]][2]) <= zb + 1e-6]
            if seg:
                cols.append({"kind": "drift", "elements": seg, "ends": [a_, b_], "role": "column"})
    return {"spans": spans, "trusses": trusses, "columns": cols, "xyz": xyz}


def deflection_checks(model: dict, results: dict | None = None, limits: dict | None = None,
                      wind_factor: float | None = None) -> dict:
    lim = {**DEFAULT_LIMITS, **{k: float(v) for k, v in (limits or {}).items() if v}}
    res = results or analyze(model)
    if not res.get("ok", True):
        raise ValueError("The analysis failed, so deflections cannot be checked")
    combos = sls_combinations(model, wind_factor)
    geo = build_spans(model)
    xyz = geo["xyz"]
    axes = {eid: np.asarray(info["axes"], dtype=float) for eid, info in res["elements"].items()}
    els = {e["id"]: e for e in model["elements"]}
    multi = any(e["type"] == "column" and (e.get("level") or 0) >= 2 for e in model["elements"])
    drift_lim = lim["drift_multi"] if multi else lim["drift_single"]
    disp = {c["id"]: _combine_disp(res, c["factors"]) for c in combos}
    items, notes = [], []

    def limit_for(item, kind):
        if kind == "total":
            return lim["roof_total"] if item["roof"] else lim["floor_total"], "total"
        if kind == "live" or (kind == "wind" and item["roof"]):
            return lim["roof_live"] if item["roof"] else lim["floor_live"], kind
        return None, None

    # beam spans
    for sp in geo["spans"]:
        a, b = sp["ends"]
        A, B = xyz[a], xyz[b]
        chord = B - A
        L = float(np.linalg.norm(chord))
        if L < 1e-6:
            continue
        e_ch = chord / L
        best = None
        for c in combos:
            n_lim, which = limit_for(sp, c["kind"])
            if not n_lim:
                continue
            nd, ed = disp[c["id"]]
            dA, dB = nd.get(a, np.zeros(3)), nd.get(b, np.zeros(3))
            worst = (0.0, None, "y", None)
            for eid in sp["elements"]:
                if eid not in ed:
                    continue
                e = els[eid]
                Pi, Pj = xyz[e["i"]], xyz[e["j"]]
                xs = np.asarray(res["cases"][next(iter(c["factors"]))]["elements"][eid]["x"], dtype=float)
                Le = float(np.linalg.norm(Pj - Pi))
                for k, x in enumerate(xs):
                    P = Pi + (Pj - Pi) * (x / Le)
                    if sp["kind"] == "cantilever":
                        root = dA if sp["free"] == b else dB
                        rel = ed[eid][k] - root
                    else:
                        t = float((P - A) @ e_ch) / L
                        rel = ed[eid][k] - ((1 - t) * dA + t * dB)
                    rel = rel - (rel @ e_ch) * e_ch
                    m = float(np.linalg.norm(rel))
                    if m > worst[0]:
                        R = axes[eid]
                        worst = (m, eid, "y" if abs(rel @ R[2]) >= abs(rel @ R[1]) else "z", float(x))
            Leff = 2 * L if sp["kind"] == "cantilever" else L
            allow = Leff / n_lim
            u = worst[0] / allow
            if best is None or u > best["util"]:
                best = {"util": u, "delta": worst[0], "allow": allow, "limit": f"L/{n_lim:g}" + (" (2L, cantilever)" if sp["kind"] == "cantilever" else ""),
                        "which": which, "combo": c["id"], "axis": worst[2], "at": worst[1]}
        if best:
            items.append({**{k: sp[k] for k in ("kind", "roof", "elements", "role")}, "L": L, **best})

    # trusses
    for tr in geo["trusses"]:
        if not tr["planar"]:
            notes.append(f"A truss of {len(tr['elements'])} members is not in one vertical plane (space truss): deflection not checked.")
            continue
        sup = sorted(tr["supports"], key=lambda n: tr["s"][n])
        if len(sup) < 2:
            notes.append(f"A truss of {len(tr['elements'])} members has fewer than two supports: deflection not checked.")
            continue
        best = None
        for c in combos:
            n_lim, which = limit_for(tr, c["kind"])
            if not n_lim:
                continue
            nd, _ = disp[c["id"]]
            for n in tr["nodes"]:
                s = tr["s"][n]
                lo = [x for x in sup if tr["s"][x] <= s + 1e-9]
                hi = [x for x in sup if tr["s"][x] >= s - 1e-9]
                if not lo or not hi:
                    continue
                pa, pb = lo[-1], hi[0]
                span = tr["s"][pb] - tr["s"][pa]
                if span < 1e-6:
                    continue
                t = (s - tr["s"][pa]) / span
                dz = nd.get(n, np.zeros(3))[2] - ((1 - t) * nd.get(pa, np.zeros(3))[2] + t * nd.get(pb, np.zeros(3))[2])
                allow = span / n_lim
                u = abs(float(dz)) / allow
                if best is None or u > best["util"]:
                    best = {"util": u, "delta": abs(float(dz)), "allow": allow, "limit": f"L/{n_lim:g}", "which": which,
                            "combo": c["id"], "axis": "A", "at": n, "L": span}
        if best:
            items.append({"kind": "truss", "roof": True, "elements": tr["elements"], "role": "truss", **best})

    # column drift
    for col in geo["columns"]:
        a, b = col["ends"]
        H = float(xyz[b][2] - xyz[a][2])
        if H < 1e-6:
            continue
        best = None
        R = axes.get(col["elements"][0])
        for c in combos:
            nd, _ = disp[c["id"]]
            rel = nd.get(b, np.zeros(3)) - nd.get(a, np.zeros(3))
            rel[2] = 0.0
            m = float(np.linalg.norm(rel))
            allow = H / drift_lim
            u = m / allow
            if best is None or u > best["util"]:
                axis = "y" if R is None or abs(rel @ R[2]) >= abs(rel @ R[1]) else "z"
                best = {"util": u, "delta": m, "allow": allow, "limit": f"H/{drift_lim:g}", "which": "drift",
                        "combo": c["id"], "axis": axis, "at": b}
        if best:
            items.append({"kind": "drift", "roof": False, "elements": col["elements"], "role": "column", "L": H, **best})

    for k, it in enumerate(sorted(items, key=lambda x: -x["util"])):
        it["id"] = f"S{k + 1}"
        it["status"] = "ok" if it["util"] <= 1.0 + 1e-9 else "fail"
    items.sort(key=lambda x: -x["util"])
    members = {}
    for it in items:
        for eid in it["elements"]:
            m = members.get(eid)
            if m is None or it["util"] > m["util"]:
                members[eid] = {"id": eid, "util": it["util"], "status": it["status"], "span": it["id"], "kind": it["kind"]}
    if not combos:
        notes.append("No load cases for a serviceability combination.")
    notes += [
        "Deflections from the linear elastic analysis with gross (uncracked) section properties. Concrete members: "
        "cracking and creep increase long-term deflection and are not included.",
        "Limits are the defaults shown (IBC 2018 Table 1604.3 for members; common practice for drift) unless changed. "
        "Check them against the project's requirements.",
        "Seismic drift (Cd x elastic drift, DPT 1301/1302 or ASCE 7) and vibration are not checked.",
    ]
    return {"combinations": [{k: c[k] for k in ("id", "name", "kind")} for c in combos], "limits": lim,
            "drift_limit": drift_lim, "items": items, "members": members,
            "summary": {"n": len(items), "ok": sum(1 for i in items if i["status"] == "ok"),
                        "fail": sum(1 for i in items if i["status"] == "fail"),
                        "max_util": max((i["util"] for i in items), default=None)},
            "notes": notes}


__all__ = ["deflection_checks", "sls_combinations", "build_spans", "DEFAULT_LIMITS"]
