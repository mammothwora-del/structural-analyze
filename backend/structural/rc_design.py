"""Reinforced concrete beam and column design to the Thai strength design standard EIT 1008-38.

EIT 1008-38 follows ACI 318-95 (strength design): U = 1.4D + 1.7L etc., phi = 0.90 flexure, 0.85 shear,
0.70 tied columns, rectangular stress block 0.85 fc' over beta1 c, eps_cu = 0.003, Es = 2.04e6 ksc.
The equations are written in the Thai practice units kgf, cm, ksc (kgf/cm2); results are returned in kN and m.

Designed:
  * beams (rectangular): bottom and top longitudinal bars for the largest positive / negative moments, rho limits,
    bar fit in one or two layers, vertical stirrups for the largest shear;
  * columns (tied, rectangular): bars around the perimeter by strain compatibility (P-M interaction about each
    axis), biaxial bending by the linear load contour, nonsway slenderness magnification, ties and shear.

Not designed (reported): torsion above the threshold, deflection and crack control, development / lap lengths,
beam-column joints, seismic detailing, slabs and walls, circular or spiral columns.
"""
from __future__ import annotations

import math

import numpy as np

from .sections import MATERIALS
from .steel_design import design_combinations

KGF_PER_KN = 101.971621
KSC_PER_MPA = 1 / 0.0980665
ES = 2.04e6            # ksc
EPS_CU = 0.003
PHI_B, PHI_V, PHI_C = 0.90, 0.85, 0.70

BARS = {   # name: (diameter cm, area cm2)
    "RB6": (0.6, 0.283), "RB9": (0.9, 0.636), "DB10": (1.0, 0.785), "DB12": (1.2, 1.131), "DB16": (1.6, 2.011),
    "DB20": (2.0, 3.142), "DB25": (2.5, 4.909), "DB28": (2.8, 6.158), "DB32": (3.2, 8.042),
}
GRADES = {"SR24": 2400.0, "SD30": 3000.0, "SD40": 4000.0, "SD50": 5000.0}
DEFAULTS = {"main_grade": "SD40", "tie_grade": "SR24", "cover": 0.04, "beam_bars": ["DB16", "DB20", "DB25"],
            "column_bars": ["DB16", "DB20", "DB25", "DB28"], "stirrup": "RB9", "stirrup_legs": 2}


class NotCovered(Exception):
    pass


def beta1(fc: float) -> float:
    """ACI 318-95 10.2.7.3 in ksc: 0.85 up to 280 ksc, less 0.05 per 70 ksc, at least 0.65."""
    return min(0.85, max(0.65, 0.85 - 0.05 * (fc - 280) / 70))


def rho_balanced(fc: float, fy: float) -> float:
    return 0.85 * beta1(fc) * fc / fy * 6120 / (6120 + fy)


def rho_min(fc: float, fy: float) -> float:
    """ACI 318-95 10.5.1 in ksc: max(14 / fy, 0.8 sqrt(fc') / fy)."""
    return max(14 / fy, 0.8 * math.sqrt(fc) / fy)


def as_required(Mu: float, b: float, d: float, fc: float, fy: float) -> float:
    """Tension steel of a singly reinforced section (kgf*cm, cm, ksc -> cm2); inf when the section is too small."""
    Rn = Mu / (PHI_B * b * d ** 2)
    disc = 1 - 2 * Rn / (0.85 * fc)
    if disc < 0:
        return math.inf
    return 0.85 * fc / fy * (1 - math.sqrt(disc)) * b * d


def section_forces(c: float, b: float, h: float, layers: list[tuple[float, float]], fc: float, fy: float):
    """Nominal (P, M about mid-depth) for neutral axis depth c measured from the compression face.

    layers: (depth from compression face, area). Compression positive. Units kgf, cm."""
    b1 = beta1(fc)
    a = min(b1 * c, h)
    Cc = 0.85 * fc * a * b
    P, M = Cc, Cc * (h / 2 - a / 2)
    eps_t = 0.0
    for di, As in layers:
        eps = EPS_CU * (c - di) / c
        fs = max(-fy, min(fy, ES * eps))
        if di < a:
            fs -= 0.85 * fc                     # concrete displaced by the bar
        P += As * fs
        M += As * fs * (h / 2 - di)
        eps_t = min(eps_t, eps)
    return P, M, -eps_t


def beam_capacity(b, h, bottom, top, fc, fy):
    """phi Mn of a rectangular section with bottom (tension) and top layers [(depth, area)], strain compatibility."""
    layers = list(bottom) + list(top)
    lo, hi = 1e-3, h
    for _ in range(80):                           # P(c) increases with c: find P = 0
        c = 0.5 * (lo + hi)
        P, _, _ = section_forces(c, b, h, layers, fc, fy)
        lo, hi = (c, hi) if P < 0 else (lo, c)
    P, M, eps_t = section_forces(c, b, h, layers, fc, fy)
    return PHI_B * abs(M), c, eps_t


# ---------------------------------------------------------------------------------------------------------------
# beams
# ---------------------------------------------------------------------------------------------------------------
def _fit(n: int, db: float, b: float, cover: float, ds: float) -> int:
    """Bars per layer with clear spacing >= max(db, 2.5 cm) (ACI 7.6.1)."""
    s = max(db, 2.5)
    return max(int((b - 2 * (cover + ds) + s) // (db + s)), 0)


def choose_bars(As_req: float, b: float, cover: float, ds: float, names: list[str], min_n: int = 2):
    """Set of one bar size giving As_req in at most two layers -> (name, n, layers, centroid offset).

    A single layer is preferred; among those, the least steel."""
    best, best_key = None, None
    for name in names:
        db, ab = BARS[name]
        n = max(min_n, math.ceil(As_req / ab - 1e-9))
        per = _fit(n, db, b, cover, ds)
        if per < 2:
            continue
        if n <= per:
            cand = (name, n, 1, cover + ds + db / 2)
        elif n <= 2 * per:
            n1, n2 = per, n - per
            y1, y2 = cover + ds + db / 2, cover + ds + db + 2.5 + db / 2        # 2.5 cm clear between layers
            cand = (name, n, 2, (n1 * y1 + n2 * y2) / n)
        else:
            continue
        key = (cand[2], n * ab)                       # one layer preferred, then the least steel
        if best is None or key < best_key:
            best, best_key = cand, key
    return best


def design_beam(b, h, Mpos, Mneg, Vu, Tu, Nmax, Mlat, fc, fy, fyt, opt, L):
    """All forces in kgf, cm. Returns (checks, rebar, notes)."""
    cover = opt["cover"] * 100
    st_name = opt["stirrup"]
    ds, ast = BARS[st_name]
    legs = int(opt["stirrup_legs"])
    notes, checks = [], []
    if Nmax > 0.1 * fc * b * h:
        raise NotCovered(f"axial force {Nmax / KGF_PER_KN:.0f} kN exceeds 0.1 fc' Ag: design this member as a column")
    Acp, pcp = b * h, 2 * (b + h)
    Tth = PHI_V * 0.266 * math.sqrt(fc) * Acp ** 2 / pcp                    # 11.6.1 threshold torsion
    rb, rmin = rho_balanced(fc, fy), rho_min(fc, fy)
    # torsion (ACI 318-95 11.6, theta = 45 deg, closed stirrups): transverse At/s and longitudinal Al
    torsion = Tu > Tth
    x1, y1 = b - 2 * cover - ds, h - 2 * cover - ds                           # centreline of the closed stirrup
    Aoh, ph = x1 * y1, 2 * (x1 + y1)
    Ao = 0.85 * Aoh
    At_s, Al, Al_tb, side = 0.0, 0.0, 0.0, None
    if torsion:
        if legs != 2:
            notes.append("Torsion: the two outer legs are the closed stirrup; inner legs count for shear only.")
        At_s = Tu / (PHI_V * 2 * Ao * fyt)                                      # 11-21
        Al = max(At_s * ph * fyt / fy,                                         # 11-22
                 1.33 * math.sqrt(fc) * Acp / fy - max(At_s, 1.76 * b / fyt) * ph * fyt / fy)   # 11-24
        n_side = max(math.ceil((h - 2 * (cover + ds)) / 30) - 1, 0)           # longitudinal bars at <= 30 cm (11.6.6.2)
        if n_side:
            Al_side = Al * 2 * y1 / ph
            Al_tb = (Al - Al_side) / 2
            need = Al_side / (2 * n_side)
            sb = next((nm for nm in ("DB12", "DB16", "DB20", "DB25") if BARS[nm][1] >= need), None)
            if sb is None:
                raise NotCovered("torsion side bars larger than DB25 needed: increase the section")
            side = (n_side, sb)
        else:
            Al_tb = Al / 2
    out = {}
    for face, Mu in (("bottom", Mpos), ("top", Mneg)):
        name0 = opt["beam_bars"][0]
        d = h - cover - ds - BARS[name0][0] / 2
        for _ in range(3):                                   # iterate d with the chosen layer arrangement
            As = as_required(Mu, b, d, fc, fy) if Mu > 0 else 0.0
            if As > 0.75 * rb * b * d or math.isinf(As):
                raise NotCovered(f"{face} steel for {Mu / KGF_PER_KN / 100:.0f} kN·m needs more than 0.75 rho_b "
                                 "(compression reinforcement): increase the beam depth or width")
            As_flex = max(As, min(rmin * b * d, 4 / 3 * As)) if Mu > 0 else 0.0     # 10.5.1 / 10.5.3
            As_req = As_flex + Al_tb
            pick = choose_bars(As_req, b, cover, ds, opt["beam_bars"])
            if pick is None:
                raise NotCovered(f"{face} bars for As = {As_req:.1f} cm2 do not fit in two layers of {', '.join(opt['beam_bars'])}")
            d_new = h - pick[3]
            if abs(d_new - d) < 1e-6:
                break
            d = d_new
        out[face] = {"As_req": As_req, "As_flex": As_flex, "As_calc": As, "bars": pick, "d": d, "Mu": Mu}
    # capacities with the bars actually provided (strain compatibility, both faces)
    for face, Mu in (("bottom", Mpos), ("top", Mneg)):
        tens = [(h - out[face]["bars"][3], out[face]["bars"][1] * BARS[out[face]["bars"][0]][1])]
        other = "top" if face == "bottom" else "bottom"
        comp = [(out[other]["bars"][3], out[other]["bars"][1] * BARS[out[other]["bars"][0]][1])]
        phiMn, c, eps_t = beam_capacity(b, h, tens, comp, fc, fy)
        name, n, nl, _ = out[face]["bars"]
        As_prov = n * BARS[name][1]
        rho = (As_prov - Al_tb) / (b * out[face]["d"])                          # flexural share of the bars
        out[face].update(phiMn=phiMn, rho=rho, c=c, As_prov=As_prov)
        label = "positive (bottom bars)" if face == "bottom" else "negative (top bars)"
        if Mu > 0:
            checks.append(_c(f"flexure_{face}", f"Flexure, {label}", "EIT 1008-38 / ACI 318-95 10.2-10.3", Mu / 1e2 / KGF_PER_KN,
                             phiMn / 1e2 / KGF_PER_KN, "moment", {"As req (cm2)": out[face]["As_req"], "As prov (cm2)": As_prov,
                                                                  "d (cm)": out[face]["d"], "c (cm)": c}))
            checks.append(_c(f"rho_max_{face}", f"Steel ratio {label} <= 0.75 rho_b", "10.3.3", rho, 0.75 * rb, "ratio_raw",
                             {"rho": rho, "0.75 rho_b": 0.75 * rb}))
    # shear (+ torsion)
    d = min(out["bottom"]["d"], out["top"]["d"])
    Vc = 0.53 * math.sqrt(fc) * b * d                                        # 11-3
    Vs_lim = 2.1 * math.sqrt(fc) * b * d                                     # 11.5.6.8
    Vs_req = max(Vu / PHI_V - Vc, 0.0)
    if Vs_req > Vs_lim:
        raise NotCovered(f"shear {Vu / KGF_PER_KN:.0f} kN needs Vs > 2.1 sqrt(fc') bw d: increase the section")
    Av_s = Vs_req / (fyt * d)                                                # total stirrup area per cm for shear
    s_max = min(d / 2, 60.0) if Vs_req <= 1.1 * math.sqrt(fc) * b * d else min(d / 4, 30.0)   # 11.5.4
    if torsion:
        s_max = min(s_max, ph / 8, 30.0)                                     # 11.6.6.1
    s_min_steel = legs * ast * fyt / (3.5 * b)                                # 11.5.5.3 / 11.6.5.2: Av + 2At >= 3.5 bw s / fy
    need_leg = Av_s / legs + At_s                                            # per outer leg, per cm
    s = min(s_max, s_min_steel, ast / need_leg if need_leg > 0 else math.inf)
    s = math.floor(s / 2.5) * 2.5
    if s < 5.0:
        raise NotCovered(f"stirrup spacing below 5 cm with {legs} legs of {st_name}: use more legs or a larger section")
    Vs_prov = legs * max(ast / s - At_s, 0.0) * fyt * d
    phiVn = PHI_V * (Vc + Vs_prov)
    checks.append(_c("shear", "Shear (vertical stirrups)", "11.3 / 11.5", Vu / KGF_PER_KN, phiVn / KGF_PER_KN, "force",
                     {"Vc (kN)": Vc / KGF_PER_KN, "s (cm)": s, "Av (cm2)": legs * ast, "d (cm)": d}))
    if torsion:
        At_prov = max(ast / s - Av_s / legs, 0.0)
        checks.append(_c("torsion", "Torsion (closed stirrups)", "11.6.3", Tu / 1e2 / KGF_PER_KN,
                         PHI_V * 2 * Ao * At_prov * fyt / 1e2 / KGF_PER_KN, "moment",
                         {"At/s req (cm2/cm)": At_s, "Ao (cm2)": Ao, "threshold (kN·m)": Tth / 1e2 / KGF_PER_KN}))
        lhs = math.sqrt((Vu / (b * d)) ** 2 + (Tu * ph / (1.7 * Aoh ** 2)) ** 2)   # 11-18
        rhs = PHI_V * (Vc / (b * d) + 2.12 * math.sqrt(fc))
        checks.append(_c("vt_section", "Shear + torsion: section size", "11.6.3.1 (11-18)", lhs, rhs, "ratio_raw",
                         {"stress (ksc)": lhs, "limit (ksc)": rhs}))
        Al_prov = sum(max(out[f]["As_prov"] - out[f]["As_flex"], 0.0) for f in ("top", "bottom"))
        if side:
            Al_prov += 2 * side[0] * BARS[side[1]][1]
        checks.append(_c("torsion_long", "Torsion longitudinal steel Al", "11.6.3.7 / 11.6.5.3", Al, max(Al_prov, 1e-9), "ratio_raw",
                         {"Al req (cm2)": Al, "Al prov (cm2)": Al_prov}))
        notes.append("Torsion designed for the largest torsion of all combinations together with the largest shear "
                     "(equilibrium torsion assumed, conservative); longitudinal steel shared between top, bottom and side bars.")
    elif Tu > 1e-6:
        notes.append(f"Torsion {Tu / 1e2 / KGF_PER_KN:.1f} kN·m is below the threshold {Tth / 1e2 / KGF_PER_KN:.1f} kN·m "
                     "of ACI 318-95 11.6.1: neglected.")
    if Vu <= PHI_V * Vc / 2 and not torsion:
        notes.append("Vu <= phi Vc / 2: stirrups are not required by 11.5.5.1; minimum stirrups at the maximum spacing are given.")
    if Mlat > 0.05 * min(out["bottom"]["phiMn"], out["top"]["phiMn"]):
        notes.append(f"Lateral moment Mz up to {Mlat / 1e2 / KGF_PER_KN:.1f} kN·m is not included in the beam design.")
    notes.append("Top bars sized for the largest negative moment along the beam and bottom bars for the largest positive "
                 "moment (constant over the length; curtailment and anchorage not designed).")
    rebar = {}
    for face in ("bottom", "top"):
        name, n, nl, yc = out[face]["bars"]
        rebar[face] = f"{n}-{name}" + (" (2 layers)" if nl == 2 else "")
        rebar[f"{face}_As_cm2"] = n * BARS[name][1]
        rebar[f"{face}_layers"] = nl
        if out[face]["Mu"] <= 0 and not torsion:
            rebar[face] += " (constructive)"
    rebar["stirrups"] = f"{st_name} @ {s / 100:.3f} m, {legs} legs" + (" (closed)" if torsion else "")
    if side:
        rebar["side"] = f"{side[0]}-{side[1]} each side (torsion)"
    rebar["d"] = d / 100
    rebar["sketch"] = _beam_sketch(b, h, cover, ds, out, side)
    return checks, rebar, notes


def _beam_sketch(b, h, cover, ds, out, side=None):
    """Bar centres (y, z in m from the section centre, z up) for drawing the section."""
    pts = []
    for face, sgn in (("bottom", -1), ("top", 1)):
        name, n, nl, _ = out[face]["bars"]
        db = BARS[name][0]
        per = _fit(n, db, b, cover, ds)
        rows = [min(n, per), n - min(n, per)]
        for r, cnt in enumerate(rows):
            if cnt <= 0:
                continue
            z = h / 2 - (cover + ds + db / 2 + r * (db + 2.5))
            y0 = b / 2 - cover - ds - db / 2
            ys = [0.0] if cnt == 1 else [-y0 + 2 * y0 * k / (cnt - 1) for k in range(cnt)]
            pts += [[y / 100, sgn * z / 100, db / 100] for y in ys]
    if side:
        n, nm = side
        db = BARS[nm][0]
        y = b / 2 - cover - ds - db / 2
        top = h / 2 - cover - ds
        for k in range(1, n + 1):
            z = top - 2 * top * k / (n + 1)
            pts += [[y / 100, z / 100, db / 100], [-y / 100, z / 100, db / 100]]
    return pts


# ---------------------------------------------------------------------------------------------------------------
# columns
# ---------------------------------------------------------------------------------------------------------------
def column_layouts():
    """(bars along each b face, bars along each h face) including corners, by total count."""
    out = []
    for nb in range(2, 7):
        for nh in range(2, 7):
            out.append((nb, nh))
    return sorted(out, key=lambda p: (2 * p[0] + 2 * p[1] - 4, abs(p[0] - p[1])))


def bar_positions(b, h, nb, nh, edge):
    """Bar centres (y across b, z across h) from the centre; edge = cover + tie + db/2."""
    yb, zh = b / 2 - edge, h / 2 - edge
    pts = set()
    for k in range(nb):
        y = -yb + 2 * yb * k / (nb - 1)
        pts.add((round(y, 6), round(zh, 6)))
        pts.add((round(y, 6), round(-zh, 6)))
    for k in range(nh):
        z = -zh + 2 * zh * k / (nh - 1)
        pts.add((round(yb, 6), round(z, 6)))
        pts.add((round(-yb, 6), round(z, 6)))
    return sorted(pts)


class Interaction:
    """phi Pn - phi Mn of a tied rectangular column about one axis (depth = dimension along the bending plane)."""

    def __init__(self, width, depth, coords, area, fc, fy):
        self.w, self.h, self.fc, self.fy = width, depth, fc, fy
        self.layers = [(depth / 2 - z, area) for z in coords]             # depth from the compression face
        Ast = area * len(coords)
        Ag = width * depth
        self.P0 = 0.85 * fc * (Ag - Ast) + fy * Ast
        self.Pmax = PHI_C * 0.80 * self.P0                                 # 10.3.5.2
        self.Pt_tension = 0.9 * fy * Ast
        dt = max(d for d, _ in self.layers)
        cb = 6120 * dt / (6120 + fy)
        Pb, _, _ = section_forces(cb, width, depth, self.layers, fc, fy)
        self.Pswitch = min(0.1 * fc * Ag, PHI_C * Pb)

    def phi(self, Pn):
        """9.3.2.2: 0.70 for tied columns, increased linearly to 0.90 as phi Pn falls from min(0.1 fc' Ag, phi Pb) to 0."""
        if Pn <= 0:
            return 0.9
        p = PHI_C * Pn
        return PHI_C if p >= self.Pswitch else 0.9 - 0.2 * p / self.Pswitch

    def point(self, c):
        Pn, Mn, _ = section_forces(c, self.w, self.h, self.layers, self.fc, self.fy)
        f = self.phi(Pn)
        return f * Pn, f * abs(Mn)

    def moment_at(self, Pu):
        """phi Mn at the factored axial load Pu (compression positive); None when Pu is outside the diagram."""
        if Pu > self.Pmax + 1e-9 or Pu < -self.Pt_tension - 1e-9:
            return None
        lo, hi = 1e-4 * self.h, 20 * self.h
        if self.point(lo)[0] > Pu:
            return self.point(lo)[1] * max(0.0, (Pu + self.Pt_tension) / (self.point(lo)[0] + self.Pt_tension))
        for _ in range(80):
            c = 0.5 * (lo + hi)
            lo, hi = (c, hi) if self.point(c)[0] < Pu else (lo, c)
        return self.point(c)[1]


def magnifier(Pu, M1, M2, Lu, r, k, EI, kind="nonsway"):
    """ACI 318-95 10.12 (nonsway): returns (delta, kLu/r, limit, Pc)."""
    slender = k * Lu / r
    ratio = M1 / M2 if abs(M2) > 1e-9 else 1.0
    limit = min(34 - 12 * ratio, 40)
    Pc = math.pi ** 2 * EI / (k * Lu) ** 2
    if slender <= limit or Pu <= 0:
        return 1.0, slender, limit, Pc
    Cm = max(0.6 + 0.4 * ratio, 0.4)
    if Pu >= 0.75 * Pc:
        return math.inf, slender, limit, Pc
    return max(Cm / (1 - Pu / (0.75 * Pc)), 1.0), slender, limit, Pc


def design_column(b, h, forces, fc, fy, fyt, opt, Lu):
    """forces: list of (combo, Pu, My_i, My_j, Mz_i, Mz_j, Vy, Vz, beta_d) in kgf, kgf*cm (Pu compression > 0).

    b along local y, h along local z; My bends about y (depth h), Mz about z (depth b)."""
    cover = opt["cover"] * 100
    Ag = b * h
    Ec = 15100 * math.sqrt(fc)
    notes = []
    k = 1.0
    for axis_depth in (h, b):
        if k * Lu / (0.3 * axis_depth) > 100:
            raise NotCovered(f"kLu/r = {k * Lu / (0.3 * axis_depth):.0f} > 100: a second-order analysis is required (ACI 318-95 10.11.5)")
    best = None
    for name in opt["column_bars"]:
        db, ab = BARS[name]
        tie = "RB9" if db <= 2.8 else "DB12"
        dt = BARS[tie][0]
        edge = cover + dt + db / 2
        for nb, nh in column_layouts():
            pts = bar_positions(b, h, nb, nh, edge)
            n = len(pts)
            rho = n * ab / Ag
            if rho < 0.01 - 1e-12:
                continue
            if rho > 0.08:
                break
            if (b - 2 * edge) / max(nb - 1, 1) - db < max(1.5 * db, 4.0) or (h - 2 * edge) / max(nh - 1, 1) - db < max(1.5 * db, 4.0):
                continue                                                       # 7.6.3 clear spacing
            iy = Interaction(b, h, [p[1] for p in pts], ab, fc, fy)            # bending about y: depth h
            iz = Interaction(h, b, [p[0] for p in pts], ab, fc, fy)
            worst, rows = 0.0, []
            for combo, Pu, Myi, Myj, Mzi, Mzj, Vy, Vz, bd in forces:
                res = []
                for (Mi, Mj, depth, I_) in ((Myi, Myj, h, iy), (Mzi, Mzj, b, iz)):
                    M2, M1 = (Mj, Mi) if abs(Mj) >= abs(Mi) else (Mi, Mj)
                    M1s = abs(M1) * (1 if M1 * M2 >= 0 else -1)              # positive for single curvature
                    EI = 0.4 * Ec * (b * h ** 3 / 12 if depth == h else h * b ** 3 / 12) / (1 + bd)
                    dl, sl, lim, Pc = magnifier(Pu, M1s, abs(M2), Lu, 0.3 * depth, k, EI)
                    M2min = max(Pu, 0) * (1.5 + 0.03 * depth)                  # 10.12.3.2
                    Mc = dl * max(abs(M2), M2min if dl > 1 else 0)
                    res.append((Mc, dl, sl, lim))
                if any(math.isinf(r_[0]) for r_ in res):
                    ratio, Mx, My_ = math.inf, 0, 0
                else:
                    Mx, My_ = iy.moment_at(Pu), iz.moment_at(Pu)
                    if Mx is None or My_ is None:
                        ratio = (Pu / iy.Pmax) if Pu > 0 else (-Pu / iy.Pt_tension)
                        ratio = max(ratio, 1.0 + 1e-6)
                    else:
                        ratio = res[0][0] / max(Mx, 1e-9) + res[1][0] / max(My_, 1e-9)
                        ratio = max(ratio, Pu / iy.Pmax if Pu > 0 else 0)
                rows.append((ratio, combo, Pu, res, Mx, My_))
                worst = max(worst, ratio)
            cand = (worst, name, nb, nh, pts, iy, iz, rows, tie, rho)
            if worst <= 1.0:
                if best is None or best[0] > 1.0 or n * ab < len(best[4]) * BARS[best[1]][1] - 1e-9:
                    best = cand
                break                                                          # smallest passing layout for this bar size
            if best is None or (best[0] > 1.0 and worst < best[0]):
                best = cand
    if best is None:
        raise NotCovered("no bar layout with 1 % to 8 % steel fits this section")
    worst, name, nb, nh, pts, iy, iz, rows, tie, rho = best
    db, ab = BARS[name]
    checks = []
    r0 = max(rows, key=lambda r_: r_[0])
    ratio, combo, Pu, res, Mx, My_ = r0
    checks.append(_c("pm", "Axial + biaxial bending (P-M, load contour)", "10.3 / 10.12", ratio, 1.0, "ratio",
                     {"Pu (kN)": Pu / KGF_PER_KN, "Mcy (kN·m)": res[0][0] / 1e2 / KGF_PER_KN, "Mcz (kN·m)": res[1][0] / 1e2 / KGF_PER_KN,
                      "phiMny at Pu (kN·m)": (Mx or 0) / 1e2 / KGF_PER_KN, "phiMnz at Pu (kN·m)": (My_ or 0) / 1e2 / KGF_PER_KN,
                      "delta_y": res[0][1], "delta_z": res[1][1], "kLu/r y": res[0][2], "kLu/r z": res[1][2]}, ratio=ratio, combo=combo))
    Pmax_row = max(rows, key=lambda r_: r_[2])
    checks.append(_c("axial", "Axial compression", "10.3.5.2 (0.80 P0)", max(Pmax_row[2], 0) / KGF_PER_KN, iy.Pmax / KGF_PER_KN, "force",
                     {"rho_g": rho}, combo=Pmax_row[1]))
    # ties: 7.10.5 spacing, shear 11.3.1.2 with axial compression
    dt, at = BARS[tie]
    s = min(16 * db, 48 * dt, min(b, h))
    Vsh = []
    for combo, Pu, *_m, Vy, Vz, bd in forces:
        for V, width, depth in ((abs(Vz), b, h), (abs(Vy), h, b)):
            d = depth - cover - dt - db / 2
            Vc = 0.53 * (1 + max(Pu, 0) / (140 * Ag)) * math.sqrt(fc) * width * d
            if Pu < 0:
                Vc = max(0.53 * (1 + Pu / (35 * Ag)) * math.sqrt(fc) * width * d, 0.0)   # 11-8 (tension)
            Vs_req = max(V / PHI_V - Vc, 0.0)
            if Vs_req > 2.1 * math.sqrt(fc) * width * d:
                raise NotCovered("column shear needs Vs > 2.1 sqrt(fc') bw d: increase the section")
            if Vs_req > 0:
                s = min(s, 2 * at * fyt * d / Vs_req, d / 2)
            Vsh.append((V, Vc, d, width, combo))
    s = math.floor(s / 2.5) * 2.5
    if s < 5.0:
        raise NotCovered("tie spacing below 5 cm needed for shear: increase the section")
    gov = max(Vsh, key=lambda v: v[0] / (PHI_V * (v[1] + 2 * at * fyt * v[2] / s)))
    V, Vc, d, width, vcombo = gov
    checks.append(_c("shear", "Shear (ties, 2 legs)", "11.3.1.2 / 11.5", V / KGF_PER_KN, PHI_V * (Vc + 2 * at * fyt * d / s) / KGF_PER_KN,
                     "force", {"Vc (kN)": Vc / KGF_PER_KN, "s (cm)": s}, combo=vcombo))
    if any(r_[3][i][1] > 1.0 for r_ in rows for i in (0, 1)):
        notes.append("Slenderness: moments magnified for a nonsway (braced) column, k = 1.0 assumed, Lu = member length, "
                     "EI = 0.4 Ec Ig / (1 + beta_d) (ACI 318-95 10.12).")
    else:
        notes.append("Slenderness effects may be neglected (kLu/r <= 34 - 12 M1/M2) for a nonsway column with k = 1.0 assumed.")
    notes.append("Biaxial bending: linear load contour Mux/phiMnx + Muy/phiMny <= 1 at the factored axial load (conservative).")
    rebar = {"bars": f"{len(pts)}-{name}", "layout": f"{nb} per b-face × {nh} per h-face", "rho_percent": 100 * rho,
             "As_cm2": len(pts) * ab, "ties": f"{tie} @ {s / 100:.3f} m",
             "sketch": [[y / 100, z / 100, db / 100] for y, z in pts]}
    return checks, rebar, notes


# ---------------------------------------------------------------------------------------------------------------
def _c(cid, name, clause, demand, capacity, unit, extra=None, ratio=None, combo=None):
    if unit == "ratio_raw":
        unit, r = "ratio", demand / capacity
        return {"id": cid, "name": name, "clause": clause, "demand": float(demand), "capacity": float(capacity), "unit": "ratio",
                "ratio": float(r), "detail": extra or {}, "combo": combo or "", "x": 0.0}
    r = ratio if ratio is not None else (abs(demand) / capacity if capacity > 0 else math.inf)
    return {"id": cid, "name": name, "clause": clause, "demand": float(demand), "capacity": float(capacity), "unit": unit,
            "ratio": float(r), "detail": extra or {}, "combo": combo or "", "x": 0.0}


def rc_design(model: dict, options: dict | None = None, results: dict | None = None) -> dict:
    from .analysis import analyze
    opt = {**DEFAULTS, **(options or {})}
    fy, fyt = GRADES[opt["main_grade"]], GRADES[opt["tie_grade"]]
    res = results or analyze(model)
    combos, gnotes = design_combinations(model)
    mats = {**MATERIALS, **model.get("materials", {})}
    xyz = {n["id"]: np.array([n["x"], n["y"], n["z"]], dtype=float) for n in model["nodes"]}
    dead = {c["id"] for c in model.get("load_cases", []) if c.get("type") in ("dead", "sdl")}
    members, counts = {}, {"ok": 0, "fail": 0, "not_covered": 0, "skipped": 0}
    for e in model["elements"]:
        sec = model["sections"].get(e["section"], {})
        mat = mats.get(sec.get("material", ""), {})
        out = {"id": e["id"], "section": sec.get("name", e["section"]), "material": sec.get("material", "")}
        if mat.get("kind") != "concrete":
            out.update(status="skipped", util=None, reason=f"not concrete ({mat.get('kind', 'unknown')})")
            counts["skipped"] += 1
            members[e["id"]] = out
            continue
        fc = float(mat["fck"]) * KSC_PER_MPA
        L = float(np.linalg.norm(xyz[e["j"]] - xyz[e["i"]])) * 100
        out["kind"] = "column" if e["type"] == "column" else "beam"
        out["params"] = {"fc_ksc": fc, "fy_ksc": fy, "fyt_ksc": fyt, "L": L / 100}
        try:
            if sec.get("shape", "rect") != "rect":
                raise NotCovered(f"section shape '{sec.get('shape')}': only rectangular RC sections are designed")
            if e["type"] not in ("column", "beam"):
                raise NotCovered(f"{e['type']} members in concrete are not designed")
            b, h = float(sec["b"]) * 100, float(sec["h"]) * 100
            per = []
            for cid, fac in combos:
                st = None
                acc = {}
                bd_num = bd_den = 0.0
                for case, f in fac.items():
                    s_ = res["cases"].get(case, {}).get("elements", {}).get(e["id"])
                    if s_ is None:
                        continue
                    st = s_
                    for k_ in ("N", "Vy", "Vz", "T", "My", "Mz"):
                        acc[k_] = acc.get(k_, 0) + f * np.asarray(s_[k_], dtype=float)
                    n_ = -float(np.mean(s_["N"])) * f
                    bd_den += n_
                    if case in dead:
                        bd_num += n_
                if st is None:
                    continue
                per.append((cid, acc, min(max(bd_num / bd_den, 0.0), 1.0) if bd_den > 1e-9 else 0.6))
            if not per:
                raise NotCovered("no results for this member")
            K = KGF_PER_KN
            if out["kind"] == "beam":
                Mpos = max(float(np.max(-a["My"])) for _, a, _ in per) * K * 100
                Mneg = max(float(np.max(a["My"])) for _, a, _ in per) * K * 100
                Vu = max(float(np.max(np.abs(a["Vz"]))) for _, a, _ in per) * K
                Tu = max(float(np.max(np.abs(a["T"]))) for _, a, _ in per) * K * 100
                Nmax = max(float(np.max(np.abs(a["N"]))) for _, a, _ in per) * K
                Mlat = max(float(np.max(np.abs(a["Mz"]))) for _, a, _ in per) * K * 100
                checks, rebar, notes = design_beam(b, h, max(Mpos, 0), max(Mneg, 0), Vu, Tu, Nmax, Mlat, fc, fy, fyt, opt, L)
                for c_ in checks:
                    gov = _governing_combo(per, c_["id"])
                    c_["combo"] = gov
            else:
                forces = [(cid, P * K,   # largest and smallest axial compression of the combination
                           float(a["My"][0]) * K * 100, float(a["My"][-1]) * K * 100, float(a["Mz"][0]) * K * 100, float(a["Mz"][-1]) * K * 100,
                           float(np.max(np.abs(a["Vy"]))) * K, float(np.max(np.abs(a["Vz"]))) * K, bd)
                          for cid, a, bd in per for P in sorted({float(np.max(-a["N"])), float(np.min(-a["N"]))})]
                checks, rebar, notes = design_column(b, h, forces, fc, fy, fyt, opt, L)
        except NotCovered as exc:
            out.update(status="not_covered", util=None, reason=str(exc), checks=[], notes=[])
            counts["not_covered"] += 1
            members[e["id"]] = out
            continue
        checks.sort(key=lambda c_: -c_["ratio"])
        util = checks[0]["ratio"]
        status = "ok" if util <= 1 + 1e-9 else "fail"
        counts[status] += 1
        out.update(status=status, util=util, governing=checks[0], checks=checks, notes=notes, rebar=rebar)
        members[e["id"]] = out
    utils = [m["util"] for m in members.values() if m.get("util") is not None]
    std = model.get("settings", {}).get("standard")
    if std != "TH":
        gnotes.append("The model's load combinations are not the Thai ones (1.4D + 1.7L ...). EIT 1008-38 strength reduction "
                      "factors are meant for its own load factors: switch the standard to Thai for a consistent design.")
    gnotes += [
        f"Main bars {opt['main_grade']} (fy = {fy:.0f} ksc), stirrups/ties {opt['tie_grade']} (fy = {fyt:.0f} ksc), "
        f"clear cover {opt['cover'] * 100:.1f} cm. Concrete fc' from each member's material.",
        "Forces from the linear analysis (uncracked stiffness); shear taken at its maximum, not at d from the support (conservative).",
        "The smallest bar set that passes is chosen, so utilisations close to 1.0 are expected: they show the provided "
        "bars are just enough, not that the member is overloaded.",
        "Not designed: deflection and crack control, bar anchorage / laps / curtailment, beam-column joints, seismic detailing "
        "(DPT 1301/1302), slabs, walls and footings.",
    ]
    return {"code": "EIT1008", "code_name": "EIT 1008-38 (strength design, ACI 318-95 based)", "combinations": [c for c, _ in combos],
            "members": members, "options": opt,
            "summary": {**counts, "max_util": max(utils) if utils else None, "n_checked": len(utils)}, "notes": gnotes}


def _governing_combo(per, cid):
    key = {"flexure_bottom": lambda a: np.max(-a["My"]), "flexure_top": lambda a: np.max(a["My"]),
           "rho_max_bottom": lambda a: np.max(-a["My"]), "rho_max_top": lambda a: np.max(a["My"]),
           "shear": lambda a: np.max(np.abs(a["Vz"])), "torsion": lambda a: np.max(np.abs(a["T"])),
           "torsion_long": lambda a: np.max(np.abs(a["T"])),
           "vt_section": lambda a: np.max(np.abs(a["T"])) + np.max(np.abs(a["Vz"]))}[cid]
    return max(per, key=lambda p: key(p[1]))[0]


__all__ = ["rc_design", "beta1", "rho_balanced", "rho_min", "as_required", "Interaction", "beam_capacity", "BARS", "GRADES"]
