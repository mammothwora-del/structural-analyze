"""Wind loads on low-rise buildings to DPT 1311-50 (มยผ. 1311-50), simplified procedure, Appendix ข.1.

Pressure on a surface (positive = towards the surface):
    p = Iw · q · Ce · (CpCg − Cgi · Cpi)
  * q = ½ ρ V² with ρ = 1.25 kg/m³ (N/m², eq. 2-4). V = TF · V50 for strength, V = V50 for serviceability (App. ก).
  * V50 and TF by wind zone (App. ก): 1: 25 m/s, 1.0; 2: 27, 1.0; 3: 29, 1.0; 4A: 25, 1.2; 4B: 25, 1.08.
    The standard applies TF to very-high-importance buildings and leaves it to the designer otherwise; here it is
    applied when "use_tf" is on (default on, so zones 4A / 4B are not under-estimated).
  * Iw (Table 2-2): strength 0.8 low, 1.0 normal, 1.15 high and very high; serviceability 0.75.
  * Ce (eq. 2-5, 2-6) at the reference height h (mid-height of the roof, at least 6 m; the eave height when the roof
    slope is below 7°): exposure A (open) (h/10)^0.2 ≥ 0.9; exposure B (suburban, small city centre) 0.7 (h/12)^0.3 ≥ 0.7.
  * CpCg: Figure ข.1, combined external peak values for the main structure of low-rise buildings (mean roof height
    ≤ 23 m and H/Ds < 1). They include Cg; they are not multiplied by Cg again. Load case 1: wind roughly perpendicular
    to the ridge; load case 2: wind roughly parallel to the ridge. Linear interpolation between the listed slopes.
  * Internal pressure (2.6.2): Cgi = 2.0, Cpi by category: 1: −0.15 to 0; 2: −0.45 to +0.3; 3: −0.7 to +0.7. Each
    external case is combined with the largest and the smallest Cpi (one load case each).
  * End zones (notes 7, 8): z = min(10 % of the least plan dimension, 40 % of H), at least 4 % of it and 1 m;
    y = max(6 m, 2z).

How the pressures reach the frame model (ASSUMED, stated in the notes):
  * Walls are carried by the columns in the wall plane, each over its tributary width along the wall (the wall
    between column lines spans horizontally to them), as a uniform line load up to the eave. Above the eave, the
    gable triangle of an end wall is lumped at the roof nodes of the end frame.
  * The roof is carried by the purlins (one-way sheeting), each over half the distance to its neighbours measured
    along the slope, as a line load normal to the roof. A flat roof with slab panels gets area loads on the panels.
  * Zone values are integrated over each tributary strip, so a strip across a zone boundary gets the average.
"""
from __future__ import annotations

import math

import numpy as np

ZONES = {"1": (25.0, 1.0), "2": (27.0, 1.0), "3": (29.0, 1.0), "4A": (25.0, 1.2), "4B": (25.0, 1.08)}
ZONE_NAMES = {"1": "Zone 1: central region (e.g. Bangkok)", "2": "Zone 2: lower north, east-west border",
              "3": "Zone 3: upper north", "4A": "Zone 4A: east coast of the southern peninsula",
              "4B": "Zone 4B: Phetchaburi and west coast of the southern peninsula"}
IW = {"low": 0.8, "normal": 1.0, "high": 1.15, "very_high": 1.15}
IW_SLS = 0.75
CPI = {"1": (-0.15, 0.0), "2": (-0.45, 0.3), "3": (-0.7, 0.7)}
CGI = 2.0
RHO = 1.25

# Figure ข.1, load case 1 (wind perpendicular to the ridge): slope (deg) -> CpCg per zone
_C1_SLOPES = (0.0, 5.0, 20.0, 30.0, 45.0, 90.0)
_C1 = {
    "1": (0.75, 0.75, 1.0, 1.05, 1.05, 1.05), "1E": (1.15, 1.15, 1.5, 1.3, 1.3, 1.3),
    "2": (-1.3, -1.3, -1.3, 0.4, 0.4, 1.05), "2E": (-2.0, -2.0, -2.0, 0.5, 0.5, 1.3),
    "3": (-0.7, -0.7, -0.9, -0.8, -0.8, -0.7), "3E": (-1.0, -1.0, -1.3, -1.0, -1.0, -0.9),
    "4": (-0.55, -0.55, -0.8, -0.7, -0.7, -0.7), "4E": (-0.8, -0.8, -1.2, -0.9, -0.9, -0.9),
}
# load case 2 (wind parallel to the ridge), all slopes
_C2 = {"1": -0.85, "1E": -0.9, "2": -1.3, "2E": -2.0, "3": -0.7, "3E": -1.0, "4": -0.85, "4E": -0.9,
       "5": 0.75, "5E": 1.15, "6": -0.55, "6E": -0.8}

DEFAULTS = {"zone": "1", "importance": "normal", "exposure": "A", "internal": "1", "use_tf": True,
            "ridge": "auto", "roof_slope": None, "all_corners": False, "replace": True}


def cpcg(case: int, zone: str, slope: float) -> float:
    if case == 2:
        return _C2[zone]
    return float(np.interp(min(max(slope, 0.0), 90.0), _C1_SLOPES, _C1[zone]))


def exposure_factor(h: float, exposure: str) -> float:
    if exposure == "A":
        return max((h / 10.0) ** 0.2, 0.9)
    if exposure == "B":
        return max(0.7 * (h / 12.0) ** 0.3, 0.7)
    raise ValueError("Exposure must be A (open terrain) or B (suburban / small city centre)")


def _intervals(pos: list[float], lo: float, hi: float) -> list[tuple[float, float]]:
    """Tributary interval of each sorted position, clipped to [lo, hi]."""
    out = []
    for k, x in enumerate(pos):
        a = lo if k == 0 else (pos[k - 1] + x) / 2
        b = hi if k == len(pos) - 1 else (x + pos[k + 1]) / 2
        out.append((a, b))
    return out


def _integrate(a: float, b: float, f, cuts: list[float]) -> float:
    """Integral of a piecewise-constant f over [a, b] (f changes only at the cut positions)."""
    pts = [a] + sorted(c for c in cuts if a < c < b) + [b]
    return sum(f((p + q) / 2) * (q - p) for p, q in zip(pts[:-1], pts[1:]))


def _geometry(model: dict, ridge: str, roof_slope):
    xyz = {n["id"]: np.array([n["x"], n["y"], n["z"]], dtype=float) for n in model["nodes"]}
    used = {n for e in model["elements"] for n in (e["i"], e["j"])}
    P = np.array([xyz[n] for n in used])
    lo, hi = P.min(axis=0), P.max(axis=0)
    z0 = float(lo[2])
    cols = [e for e in model["elements"] if e["type"] == "column"]
    if not cols:
        raise ValueError("The model has no columns, so the walls and the eave height cannot be found")
    eave = max(max(xyz[e["i"]][2], xyz[e["j"]][2]) for e in cols)
    top = float(hi[2])
    roof_roles = {"purlin"}
    purl = [e for e in model["elements"] if e["type"] == "beam" and e.get("role") in roof_roles]
    if not purl:
        purl = [e for e in model["elements"] if e["type"] == "beam" and e.get("role") == "eave"]
    if ridge == "auto":
        if purl:
            d = np.sum([np.abs(xyz[e["j"]] - xyz[e["i"]]) for e in purl], axis=0)
            ridge = "y" if d[1] >= d[0] else "x"
        else:
            ridge = "y" if (hi[1] - lo[1]) >= (hi[0] - lo[0]) else "x"
    if ridge not in ("x", "y"):
        raise ValueError("ridge must be 'auto', 'x' or 'y'")
    ui, vi = (0, 1) if ridge == "y" else (1, 0)        # u: across the ridge, v: along the ridge
    # roof profile across the ridge: highest purlin line at each u
    prof: dict[float, float] = {}
    for e in purl:
        for n in (e["i"], e["j"]):
            u, z = round(float(xyz[n][ui]), 6), float(xyz[n][2])
            prof[u] = max(prof.get(u, -1e9), z)
    us = sorted(prof)
    if roof_slope is None:
        angles = [math.degrees(math.atan2(abs(prof[b] - prof[a]), b - a)) for a, b in zip(us[:-1], us[1:]) if b - a > 1e-6]
        if angles:
            slope = float(np.median(angles))
        else:
            width = hi[ui] - lo[ui]
            slope = math.degrees(math.atan2(top - eave, width / 2)) if width > 0 else 0.0
    else:
        slope = float(roof_slope)
    # ridges: local maxima of the profile (the windward roof runs from the windward eave to the first ridge)
    ridges = []
    for k in range(1, len(us) - 1):
        a, b, c = prof[us[k - 1]], prof[us[k]], prof[us[k + 1]]
        if b >= a - 1e-6 and b >= c - 1e-6 and (b > a + 1e-6 or b > c + 1e-6):
            ridges.append(us[k])
    return {"xyz": xyz, "lo": lo, "hi": hi, "z0": z0, "eave": eave, "top": top, "ridge": ridge, "ui": ui, "vi": vi,
            "purlins": purl, "profile": prof, "slope": slope, "ridges": ridges}


def wind_parameters(model: dict, params: dict | None = None) -> dict:
    p = {**DEFAULTS, **(params or {})}
    if p["zone"] not in ZONES:
        raise ValueError(f"Unknown wind zone '{p['zone']}'. Use one of {', '.join(ZONES)}")
    if p["importance"] not in IW:
        raise ValueError(f"Unknown importance '{p['importance']}'. Use low, normal, high or very_high")
    if str(p["internal"]) not in CPI:
        raise ValueError("Internal pressure category must be 1, 2 or 3")
    g = _geometry(model, p["ridge"], p.get("roof_slope"))
    V50, TF = ZONES[p["zone"]]
    tf = TF if p["use_tf"] else 1.0
    V = tf * V50
    q = 0.5 * RHO * V ** 2 / 1000.0                     # kN/m2
    He = g["eave"] - g["z0"]
    H = g["top"] - g["z0"]
    h = He if g["slope"] < 7.0 else (He + H) / 2
    h = max(h, 6.0)
    Ce = exposure_factor(h, p["exposure"])
    Iw = IW[p["importance"]]
    ui, vi = g["ui"], g["vi"]
    B_u = float(g["hi"][ui] - g["lo"][ui])              # across the ridge
    B_v = float(g["hi"][vi] - g["lo"][vi])              # along the ridge
    Ds = min(B_u, B_v)
    z_edge = max(min(0.1 * Ds, 0.4 * H), 0.04 * Ds, 1.0)
    y_end = max(6.0, 2 * z_edge)
    scope = []
    if h > 23.0:
        scope.append(f"The reference height h = {h:.1f} m is over 23 m: Figure ข.1 (low-rise) does not apply. Use the "
                     "detailed procedure of DPT 1311-50.")
    if Ds > 0 and h / Ds >= 1.0:
        scope.append(f"h / Ds = {h / Ds:.2f} is not below 1: Figure ข.1 (low-rise) does not apply.")
    # serviceability pressure / strength pressure: (Iw_SLS · V50²) / (Iw · (TF V50)²)
    sls = IW_SLS / Iw / tf ** 2
    return {"params": p, "V50": V50, "TF": TF, "tf_used": tf, "V": V, "q": q, "Iw": Iw, "Iw_sls": IW_SLS, "h": h, "He": He,
            "H": H, "Ce": Ce, "slope": g["slope"], "ridge": g["ridge"], "Ds": Ds, "z_edge": z_edge, "y_end": y_end,
            "B_across": B_u, "B_along": B_v, "cpi": CPI[str(p["internal"])], "sls_factor": sls, "scope": scope,
            "_g": g}


def _cases(w: dict) -> list[dict]:
    """External load cases: (id, case 1/2, wind sign along u or v, reference corner)."""
    out = [{"id": "W1", "case": 1, "dir": +1, "end": 0, "corner": 0, "name": "across the ridge, towards +u"},
           {"id": "W2", "case": 1, "dir": -1, "end": 1, "corner": 1, "name": "across the ridge, towards −u"},
           {"id": "W3", "case": 2, "dir": +1, "end": 0, "corner": 0, "name": "along the ridge, towards +v"},
           {"id": "W4", "case": 2, "dir": -1, "end": 1, "corner": 1, "name": "along the ridge, towards −v"}]
    if w["params"]["all_corners"]:
        out += [{"id": "W5", "other": True, "case": 1, "dir": +1, "end": 1, "corner": 0, "name": "across the ridge, towards +u (other end)"},
                {"id": "W6", "other": True, "case": 1, "dir": -1, "end": 0, "corner": 1, "name": "across the ridge, towards −u (other end)"},
                {"id": "W7", "other": True, "case": 2, "dir": +1, "end": 0, "corner": 1, "name": "along the ridge, towards +v (other side)"},
                {"id": "W8", "other": True, "case": 2, "dir": -1, "end": 1, "corner": 0, "name": "along the ridge, towards −v (other side)"}]
    return out


def generate_wind(model: dict, params: dict | None = None) -> dict:
    """Return {"model": model with the wind load cases, loads and combinations, "summary": ...}."""
    import copy

    from .generator import COMBOS

    w = wind_parameters(model, params)
    if w["scope"]:
        raise ValueError(" ".join(w["scope"]))
    g = w.pop("_g")
    m = copy.deepcopy(model)
    xyz, ui, vi = g["xyz"], g["ui"], g["vi"]
    lo, hi = g["lo"], g["hi"]
    u0, u1, v0, v1 = float(lo[ui]), float(hi[ui]), float(lo[vi]), float(hi[vi])
    tol = 1e-3
    base = w["Iw"] * w["q"] * w["Ce"]
    slope, y_end, z_edge, H = w["slope"], w["y_end"], w["z_edge"], w["H"]
    axis = {"x": np.array([1.0, 0, 0]), "y": np.array([0, 1.0, 0])}
    eu = np.eye(3)[ui]
    ev = np.eye(3)[vi]

    old_wind = {c["id"] for c in m["load_cases"] if c.get("type") == "wind"}
    if w["params"]["replace"]:
        m["load_cases"] = [c for c in m["load_cases"] if c["id"] not in old_wind]
        m["loads"] = [l for l in m["loads"] if l["case"] not in old_wind]
        m["combinations"] = [c for c in m.get("combinations", []) if not set(c["factors"]) & old_wind]
    taken = {c["id"] for c in m["load_cases"]}

    cols = [e for e in m["elements"] if e["type"] == "column"]
    # columns standing in each outer wall plane, grouped by position along the wall
    walls = {}
    for name, ax, val, along in (("u0", ui, u0, vi), ("u1", ui, u1, vi), ("v0", vi, v0, ui), ("v1", vi, v1, ui)):
        lines: dict[float, list[dict]] = {}
        for e in cols:
            a, b = xyz[e["i"]], xyz[e["j"]]
            if abs(a[ax] - val) < tol and abs(b[ax] - val) < tol:
                lines.setdefault(round(float(a[along]), 6), []).append(e)
        walls[name] = lines
    # roof strips: purlin positions across the ridge
    prof, us = g["profile"], sorted(g["profile"])
    roof_slabs = [s for s in m.get("slabs", []) if not g["purlins"] and _slab_top(s, xyz) >= g["top"] - tol]

    cases_out, summary_cases, all_loads = [], [], []
    cpi_lo, cpi_hi = w["cpi"]
    cpis = [cpi_hi, cpi_lo] if cpi_hi != cpi_lo else [cpi_hi]
    k_id = 1
    for ex in _cases(w):
        c = ex["case"]
        # end zone along the ridge (case 1: at the reference end; case 2: at the windward gable)
        if c == 1:
            in_end = (lambda v: v <= v0 + y_end) if ex["end"] == 0 else (lambda v: v >= v1 - y_end)
            ww_wall, lw_wall = ("u0", "u1") if ex["dir"] > 0 else ("u1", "u0")
        else:
            in_end = (lambda v: v <= v0 + y_end) if ex["dir"] > 0 else (lambda v: v >= v1 - y_end)
            ref_side, far_side = ("u0", "u1") if ex["corner"] == 0 else ("u1", "u0")
            ww_end, lw_end = ("v0", "v1") if ex["dir"] > 0 else ("v1", "v0")
        v_cut = [v0 + y_end, v1 - y_end]
        for cpi in cpis:
            cid = f"W{k_id}"
            while cid in taken:
                k_id += 1
                cid = f"W{k_id}"
            k_id += 1
            label_dir = ("+" if ex["dir"] > 0 else "−") + (w["ridge"] if c == 2 else ("x" if w["ridge"] == "y" else "y"))
            name = f"Wind {label_dir} (DPT 1311 case {c}{', other corner' if ex.get('other') else ''}), Cpi {cpi:+.2f}"
            cases_out.append({"id": cid, "name": name, "type": "wind", "sls_factor": round(w["sls_factor"], 6),
                              "wind": {"standard": "DPT 1311-50", "case": c, "dir": label_dir, "cpi": cpi}})
            loads, zones_used = [], {}

            def p_of(zone):
                val = cpcg(c, zone, slope) - CGI * cpi
                zones_used[zone] = (float(cpcg(c, zone, slope)), float(base * val))
                return base * val

            def wall_load(wall, zone_of_v, inward):
                """Uniform line load on each column line of a wall: integral of p over its tributary strip."""
                lines = walls[wall]
                if not lines:
                    return 0.0
                pos = sorted(lines)
                along = vi if wall in ("u0", "u1") else ui
                lo_a, hi_a = (v0, v1) if along == vi else (u0, u1)
                cuts = v_cut if along == vi else [u0 + z_edge, u1 - z_edge]
                total = 0.0
                for (a, b), x in zip(_intervals(pos, lo_a, hi_a), pos):
                    f = _integrate(a, b, lambda t: p_of(zone_of_v(t)), cuts)     # kN/m (per m height)
                    if abs(f) < 1e-12:
                        continue
                    for e in lines[x]:
                        loads.append({"case": cid, "kind": "dist", "element": e["id"], "direction": list(inward),
                                      "points": [[0, f], [1, f]], "relative": True,
                                      "label": f"Wind wall {wall}: {f:.3f} kN/m over {b - a:.2f} m"})
                    He_line = max(max(xyz[e["i"]][2], xyz[e["j"]][2]) for e in lines[x]) - g["z0"]
                    total += f * He_line
                return total

            F_total = np.zeros(3)
            if c == 1:
                for wall, zz in ((ww_wall, "1"), (lw_wall, "4")):
                    inward = eu if wall == "u0" else -eu
                    t = wall_load(wall, lambda v, zz=zz: zz + "E" if in_end(v) else zz, inward)
                    F_total += t * inward
            else:
                for wall, zz in ((ref_side, "1"), (far_side, "4")):
                    inward = eu if wall == "u0" else -eu
                    t = wall_load(wall, lambda v, zz=zz: zz + "E" if in_end(v) else zz, inward)
                    F_total += t * inward
                ref_u = u0 if ref_side == "u0" else u1
                for wall, zz in ((ww_end, "5"), (lw_end, "6")):
                    inward = ev if wall == "v0" else -ev
                    t = wall_load(wall, lambda u, zz=zz: zz + "E" if abs(u - ref_u) <= z_edge else zz, inward)
                    F_total += t * inward
                    # gable triangle above the eave, lumped at the roof nodes of the end frame
                    vv = v0 if wall == "v0" else v1
                    gn = sorted({n for e in m["elements"] for n in (e["i"], e["j"])
                                 if abs(xyz[n][vi] - vv) < tol and xyz[n][2] > g["eave"] + tol},
                                key=lambda n: xyz[n][ui])
                    gn_top: dict[float, str] = {}
                    for n in gn:
                        key = round(float(xyz[n][ui]), 6)
                        if key not in gn_top or xyz[n][2] > xyz[gn_top[key]][2]:
                            gn_top[key] = n
                    pos = sorted(gn_top)
                    for (a, b), x in zip(_intervals(pos, u0, u1), pos):
                        n = gn_top[x]
                        hgt = float(xyz[n][2] - g["eave"])
                        Fn = _integrate(a, b, lambda u, zz=zz: p_of(zz + "E" if abs(u - ref_u) <= z_edge else zz),
                                        [u0 + z_edge, u1 - z_edge]) * hgt
                        if abs(Fn) > 1e-9:
                            vec = Fn * inward
                            loads.append({"case": cid, "kind": "nodal", "node": n, "values": [*map(float, vec), 0, 0, 0],
                                          "label": f"Wind gable wall {wall} above the eave ({hgt:.2f} m high strip)"})
                            F_total += vec

            # roof
            def roof_zone(u_mid, v):
                if c == 1:
                    first_ridge = (min([r for r in g["ridges"]], default=(u0 + u1) / 2) if ex["dir"] > 0
                                   else max([r for r in g["ridges"]], default=(u0 + u1) / 2))
                    windward = u_mid <= first_ridge if ex["dir"] > 0 else u_mid >= first_ridge
                    dist = (u_mid - u0) if ex["dir"] > 0 else (u1 - u_mid)
                    zz = "2" if windward else "3"
                    # note 9: negative zone 2 values only within 2.5 H of the windward edge
                    if zz == "2" and dist > 2.5 * H and cpcg(1, "2", slope) < 0:
                        zz = "3"
                else:
                    mid = (u0 + u1) / 2
                    near_ref = u_mid <= mid if ex["corner"] == 0 else u_mid >= mid
                    zz = "2" if near_ref else "3"
                return zz + "E" if in_end(v) else zz

            if us and g["purlins"]:
                lines_at: dict[float, list[dict]] = {}
                for e in g["purlins"]:
                    a, b = xyz[e["i"]], xyz[e["j"]]
                    if abs(a[ui] - b[ui]) > tol:
                        continue                      # not along the ridge
                    key = round(float(a[ui]), 6)
                    if abs(a[2] - prof.get(key, a[2])) > tol:
                        continue                      # below the roof surface (e.g. an eave strut under a truss end)
                    lines_at.setdefault(key, []).append(e)
                pos = [u for u in us if u in lines_at]
                for k, u in enumerate(pos):
                    halves = []
                    if k > 0:
                        halves.append(pos[k - 1])
                    if k < len(pos) - 1:
                        halves.append(pos[k + 1])
                    els = lines_at[u]
                    # several purlins at one position (two trusses meeting at a valley) share the strip
                    n_par = max(1, round(sum(_len_v(e, xyz, vi) for e in els) / max(v1 - v0, 1e-9)))
                    for nb_u in halves:
                        du, dz = nb_u - u, prof[nb_u] - prof[u]
                        seg = math.hypot(du, dz)
                        half = seg / 2
                        # outward normal of the roof strip (upwards)
                        t_vec = du * eu + dz * np.array([0, 0, 1.0])
                        nrm = np.cross(t_vec, ev)
                        if nrm[2] < 0:
                            nrm = -nrm
                        nrm = nrm / np.linalg.norm(nrm)
                        u_mid = u + du / 4
                        for e in els:
                            va, vb = sorted((float(xyz[e["i"]][vi]), float(xyz[e["j"]][vi])))
                            if vb - va < 1e-6:
                                continue
                            pavg = _integrate(va, vb, lambda v: p_of(roof_zone(u_mid, v)), v_cut) / (vb - va)
                            f = pavg * half / n_par
                            if abs(f) < 1e-12:
                                continue
                            loads.append({"case": cid, "kind": "dist", "element": e["id"], "direction": [*map(float, -nrm)],
                                          "points": [[0, f], [1, f]], "relative": True,
                                          "label": f"Wind roof: {pavg:.3f} kN/m² × {half:.2f} m (half strip, along the slope)"})
                            F_total += -nrm * f * (vb - va)
            elif roof_slabs:
                for s in roof_slabs:
                    cen = np.mean([xyz[n] for n in s["corners"]], axis=0) if s.get("corners") else None
                    if cen is None:
                        continue
                    pz = p_of(roof_zone(float(cen[ui]), float(cen[vi])))
                    loads.append({"case": cid, "kind": "area", "slabs": [s["id"]], "q": pz,
                                  "label": f"Wind roof panel {s['id']} (zone at its centre)"})
            all_loads += loads
            summary_cases.append({"id": cid, "name": name, "case": c, "cpi": cpi,
                                  "zones": {z: {"cpcg": round(v[0], 4), "p": round(v[1], 4)} for z, v in sorted(zones_used.items())},
                                  "resultant": [round(float(x), 3) for x in F_total], "n_loads": len(loads)})
    m["load_cases"] += cases_out
    m["loads"] += all_loads
    # combinations: every standard combination with wind, once per wind case
    std = m.get("settings", {}).get("standard", "EN1990")
    present = {c["id"] for c in m["load_cases"]}
    for tid, tname, fac in COMBOS.get(std, COMBOS["EN1990"]):
        if "WX" not in fac:
            continue
        for wc in cases_out:
            f = {k: v for k, v in fac.items() if k in present and k != "WX"}
            f[wc["id"]] = fac["WX"]
            m["combinations"].append({"id": f"{tid}-{wc['id']}", "name": f"{tname} [W = {wc['id']}]", "factors": f})
    notes = [
        f"DPT 1311-50 simplified procedure, low-rise buildings (Appendix ข.1, Figure ข.1). q = ½·1.25·V² with V = "
        f"{'TF·' if w['tf_used'] != 1 else ''}V50 = {w['V']:.1f} m/s → q = {w['q']:.3f} kN/m².",
        f"Iw = {w['Iw']} (strength). Serviceability uses V50 and Iw = 0.75: the deflection check takes {w['sls_factor']:.3f} × "
        "each wind case.",
        f"Ce = {w['Ce']:.3f} (exposure {w['params']['exposure']}) at h = {w['h']:.2f} m"
        f"{' (eave height, roof slope below 7°)' if w['slope'] < 7 else ' (mid-height of the roof, at least 6 m)'}.",
        f"Roof slope {w['slope']:.1f}° ({'from the model' if w['params'].get('roof_slope') is None else 'given'}); ridge along "
        f"{w['ridge']}. End zones y = {w['y_end']:.2f} m, edge strips z = {w['z_edge']:.2f} m.",
        f"Internal pressure category {w['params']['internal']}: Cpi {cpi_lo:+.2f} and {cpi_hi:+.2f}, Cgi = 2.0; each external "
        "case is made once with each.",
        "ASSUMED load path: walls span horizontally to the columns in the wall plane (tributary width), roof sheeting "
        "spans to the purlins (half the distance to the neighbours along the slope); the gable triangle above the eave "
        "is lumped at the end-frame roof nodes. Zone values are averaged over each tributary strip.",
        "Load cases cover the four main wind directions with one reference corner each"
        + ("" if w["params"]["all_corners"] else " (a non-symmetric structure should also be checked with 'all corners')")
        + ". Zone 5E / 6E (end walls) taken as strips of width z at the reference corner side (interpretation of Figure ข.1).",
        "Not included: cladding and secondary member pressures (Figures ข.2, ข.3, Cg = 2.5), topography (hills), dynamic "
        "effects, open or partly open structures (canopies), and multi-span roof coefficients: for a multi-span roof the "
        "windward roof zone is taken from the windward eave to the first ridge and zone 3 elsewhere.",
    ]
    m.setdefault("notes", [])
    m["notes"] = [n for n in m["notes"] if not n.startswith("Wind:")] + [
        f"Wind: DPT 1311-50 low-rise method, zone {w['params']['zone']}, exposure {w['params']['exposure']}, "
        f"{len(cases_out)} load cases (see the wind summary)."]
    summary = {k: v for k, v in w.items()}
    summary.update({"cases": summary_cases, "notes": notes, "zone_name": ZONE_NAMES[w["params"]["zone"]],
                    "removed_cases": sorted(old_wind) if w["params"]["replace"] else []})
    m["wind"] = {k: summary[k] for k in ("params", "V50", "TF", "tf_used", "V", "q", "Iw", "h", "Ce", "slope", "ridge",
                                          "y_end", "z_edge", "cpi", "sls_factor")}
    return {"model": m, "summary": summary}


def _len_v(e, xyz, vi):
    return abs(float(xyz[e["j"]][vi] - xyz[e["i"]][vi]))


def _slab_top(s, xyz):
    ns = s.get("corners") or []
    return min((float(xyz[n][2]) for n in ns if n in xyz), default=-1e9)


__all__ = ["generate_wind", "wind_parameters", "cpcg", "exposure_factor", "ZONES", "IW", "CPI", "DEFAULTS"]
