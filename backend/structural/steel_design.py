"""Steel member design checks.

Codes:
  * ``AISC360``: AISC 360-16, LRFD (chapters D, E, F, G, H).
  * ``EC3``:     EN 1993-1-1:2005 (sections 5.5, 6.2, 6.3 and Annex B), recommended gamma_M0 = gamma_M1 = 1.0.
  * ``EIT``:     Thai practice. The EIT steel design standard follows AISC; this check uses the AISC 360-16 LRFD
                 resistance equations with the model's load combinations and TIS steel grades. Confirm against the
                 edition in force for the project.

Internal units: kN, m (stresses kN/m2). Section axes as in sections.py: y = major (My, Vz), z = minor (Mz, Vy).
Sign convention of the analysis: N > 0 tension.

What is NOT checked (reported as notes): connections and net-section rupture, web crippling / local loads,
torsion of open sections, second-order effects unless the forces come from a P-Delta analysis, the AISC direct
analysis method (notional loads, reduced stiffness), seismic detailing.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from .sections import MATERIALS, material_props, section_properties

CODES = {
    "AISC360": "AISC 360-16 (LRFD)",
    "EC3": "EN 1993-1-1 (Eurocode 3)",
    "EIT": "Thai EIT (AISC 360-16 LRFD equations)",
}
CODE_FOR_STANDARD = {"ASCE7": "AISC360", "EN1990": "EC3", "TH": "EIT"}
SLS_WORDS = ("sls", "serv", "service", "characteristic", "ths")
G_M0 = G_M1 = 1.0   # EN 1993-1-1 recommended values (national annexes may differ)
CURVE_ALPHA = {"a0": 0.13, "a": 0.21, "b": 0.34, "c": 0.49, "d": 0.76}


@dataclass
class Geo:
    shape: str
    A: float
    Iy: float
    Iz: float
    J: float
    Cw: float
    Sy: float
    Sz: float
    Zy: float
    Zz: float
    h: float
    b: float
    tf: float = 0.0
    tw: float = 0.0
    t: float = 0.0
    fab: str = "rolled"     # rolled | welded (I) ; hot | cold (hollow)

    @property
    def ry(self):           # radius of gyration for buckling about the major axis
        return math.sqrt(self.Iy / self.A)

    @property
    def rz(self):
        return math.sqrt(self.Iz / self.A)

    @property
    def hw(self):           # clear web depth (fillets / corner radii ignored)
        return self.h - 2 * self.tf


def geometry(sec: dict) -> Geo:
    """Section properties for design, including plastic moduli and the warping constant."""
    p = section_properties(sec)
    shape = sec.get("shape", "rect")
    if shape == "I":
        h, bf, tf, tw = (float(sec[k]) for k in ("h", "bf", "tf", "tw"))
        hw = h - 2 * tf
        Zy = bf * tf * (h - tf) + tw * hw ** 2 / 4
        Zz = tf * bf ** 2 / 2 + hw * tw ** 2 / 4
        Cw = (tf * bf ** 3 / 12) * (h - tf) ** 2 / 2      # = I_flange,z * h0^2 / 2 = Iz_flanges * h0^2 / 4
        return Geo("I", p.A, p.Iy, p.Iz, p.J, Cw, p.Sy, p.Sz, Zy, Zz, h, bf, tf, tw, fab=sec.get("fab", "rolled"))
    if shape == "box":
        b, h, t = float(sec["b"]), float(sec["h"]), float(sec["t"])
        bi, hi = b - 2 * t, h - 2 * t
        Zy = b * h ** 2 / 4 - bi * hi ** 2 / 4
        Zz = h * b ** 2 / 4 - hi * bi ** 2 / 4
        return Geo("box", p.A, p.Iy, p.Iz, p.J, 0.0, p.Sy, p.Sz, Zy, Zz, h, b, t=t, fab=sec.get("fab", "cold"))
    if shape == "pipe":
        d, t = float(sec["d"]), float(sec["t"])
        Z = (d ** 3 - (d - 2 * t) ** 3) / 6
        return Geo("pipe", p.A, p.Iy, p.Iz, p.J, 0.0, p.Sy, p.Sz, Z, Z, d, d, t=t, fab=sec.get("fab", "cold"))
    if shape == "rect":
        b, h = float(sec["b"]), float(sec["h"])
        return Geo("rect", p.A, p.Iy, p.Iz, p.J, 0.0, p.Sy, p.Sz, b * h ** 2 / 4, h * b ** 2 / 4, h, b)
    if shape == "circle":
        d = float(sec["d"])
        return Geo("circle", p.A, p.Iy, p.Iz, p.J, 0.0, p.Sy, p.Sz, d ** 3 / 6, d ** 3 / 6, d, d)
    raise NotCovered(f"section shape '{shape}' has no design rules here (give the section as I, box, pipe, rect or circle)")


class NotCovered(Exception):
    """The code clause needed for this member is outside what is implemented."""


@dataclass
class Forces:
    """Internal forces of one member for one combination, at stations x (kN, kN*m)."""
    x: np.ndarray
    N: np.ndarray
    Vy: np.ndarray
    Vz: np.ndarray
    T: np.ndarray
    My: np.ndarray
    Mz: np.ndarray


@dataclass
class Params:
    L: float
    Ky: float = 1.0
    Kz: float = 1.0
    Kt: float = 1.0
    Lb: float | None = None       # laterally unbraced length for LTB (default L)
    Cb: float | None = None       # user moment-gradient factor (default from the moment diagram)
    notes: list = field(default_factory=list)

    @property
    def Llt(self):
        return self.L if self.Lb is None else self.Lb


def _chk(cid, name, clause, demand, capacity, unit, extra=None, ratio=None):
    r = ratio if ratio is not None else (abs(demand) / capacity if capacity > 0 else math.inf)
    return {"id": cid, "name": name, "clause": clause, "demand": float(demand), "capacity": float(capacity),
            "unit": unit, "ratio": float(r), "detail": extra or {}}


def _interp_quadratic(x0: float, xs: np.ndarray, ys: np.ndarray) -> float:
    """Value at x0 from the parabola through the three nearest stations (exact for a uniformly loaded span)."""
    if len(xs) < 3:
        return float(np.interp(x0, xs, ys))
    k = int(np.clip(np.searchsorted(xs, x0), 1, len(xs) - 2))
    if abs(xs[k - 1] - x0) < abs(xs[k] - x0) and k > 1:
        k -= 1
    xa, xb, xc = xs[k - 1], xs[k], xs[k + 1]
    ya, yb, yc = ys[k - 1], ys[k], ys[k + 1]
    return float(ya * (x0 - xb) * (x0 - xc) / ((xa - xb) * (xa - xc)) + yb * (x0 - xa) * (x0 - xc) / ((xb - xa) * (xb - xc))
                 + yc * (x0 - xa) * (x0 - xb) / ((xc - xa) * (xc - xb)))


def moment_gradient(f: Forces, comp: str, L: float) -> float:
    """C_b = 12.5 Mmax / (2.5 Mmax + 3 MA + 4 MB + 3 MC) from the moment diagram over the member (AISC F1-1)."""
    Ms = getattr(f, comp)
    mmax = float(np.abs(Ms).max())
    if mmax <= 1e-12:
        return 1.0
    q = [abs(_interp_quadratic(L * k / 4, f.x, Ms)) for k in (1, 2, 3)]
    return min(12.5 * mmax / (2.5 * mmax + 3 * q[0] + 4 * q[1] + 3 * q[2]), 3.0)


def equivalent_moment_factor(f: Forces, comp: str) -> tuple[float, str]:
    """C_m for EN 1993-1-1 Annex B (Table B.3).

    Linear moment between the ends (max at an end): C_m = 0.6 + 0.4 psi >= 0.4. When the largest moment is in the
    span (transverse load), C_m = 1.0 is used (conservative upper bound of Table B.3)."""
    M = getattr(f, comp)
    a = np.abs(M)
    mmax = float(a.max())
    if mmax <= 1e-12:
        return 1.0, "no moment"
    ends = (float(M[0]), float(M[-1]))
    big, small = (ends[0], ends[1]) if abs(ends[0]) >= abs(ends[1]) else (ends[1], ends[0])
    if abs(big) >= 0.98 * mmax:
        psi = small / big if abs(big) > 1e-12 else 1.0
        return max(0.6 + 0.4 * psi, 0.4), f"psi = {psi:.2f}"
    return 1.0, "span moment governs: 1.0 (conservative)"


# ---------------------------------------------------------------------------------------------------------------
# AISC 360-16 LRFD
# ---------------------------------------------------------------------------------------------------------------
def aisc_fcr(Fy: float, Fe: float) -> float:
    """E3-2 / E3-3."""
    return (0.658 ** (Fy / Fe)) * Fy if Fy / Fe <= 2.25 else 0.877 * Fe


def aisc_cv2(lam, kv, E, Fy):
    """G2-9 to G2-11."""
    s = math.sqrt(kv * E / Fy)
    if lam <= 1.10 * s:
        return 1.0
    if lam <= 1.37 * s:
        return 1.10 * s / lam
    return 1.51 * kv * E / (lam ** 2 * Fy)


def aisc_compression(g: Geo, Fy, E, G, p: Params) -> dict:
    Fe_y = math.pi ** 2 * E / (p.Ky * p.L / g.ry) ** 2
    Fe_z = math.pi ** 2 * E / (p.Kz * p.L / g.rz) ** 2
    Fe, mode = (Fe_y, "flexural, major axis (E3)") if Fe_y <= Fe_z else (Fe_z, "flexural, minor axis (E3)")
    if g.shape == "I":
        Fe_t = (math.pi ** 2 * E * g.Cw / (p.Kt * p.L) ** 2 + G * g.J) / (g.Iy + g.Iz)   # E4-2
        if Fe_t < Fe:
            Fe, mode = Fe_t, "torsional (E4)"
    Fcr = aisc_fcr(Fy, Fe)
    Ae, slender = g.A, []
    rE = math.sqrt(E / Fy)

    def reduce(lam, lam_r, c1, c2, width, thick, count, name):
        nonlocal Ae
        if lam > lam_r * math.sqrt(Fy / Fcr):                    # E7-2 / E7-3
            Fel = (c2 * lam_r / lam) ** 2 * Fy
            be = width * (1 - c1 * math.sqrt(Fel / Fcr)) * math.sqrt(Fel / Fcr)
            Ae -= count * (width - min(be, width)) * thick
            slender.append(name)

    if g.shape == "I":
        reduce(g.b / (2 * g.tf), 0.56 * rE, 0.22, 1.49, g.b / 2, g.tf, 4, "flange")
        reduce(g.hw / g.tw, 1.49 * rE, 0.18, 1.31, g.hw, g.tw, 1, "web")
    elif g.shape == "box":
        for w, name in ((g.b - 3 * g.t, "wall b"), (g.h - 3 * g.t, "wall h")):
            reduce(w / g.t, 1.40 * rE, 0.20, 1.38, w, g.t, 2, name)
    elif g.shape == "pipe":
        Dt = g.h / g.t
        if Dt > 0.45 * E / Fy:
            raise NotCovered(f"round HSS with D/t = {Dt:.0f} > 0.45E/Fy (outside AISC 360 E7.2)")
        if Dt > 0.11 * E / Fy:                                   # E7-7
            Ae = g.A * (0.038 * E / (Fy * Dt) + 2 / 3)
            slender.append("wall")
    Pn = Fcr * Ae
    return {"phiPn": 0.9 * Pn, "Fcr": Fcr, "Fe": Fe, "mode": mode, "Ae": Ae, "slender": slender,
            "KL_r": max(p.Ky * p.L / g.ry, p.Kz * p.L / g.rz)}


def aisc_flexure(g: Geo, Fy, E, axis: str, p: Params, Cb: float) -> dict:
    rE = math.sqrt(E / Fy)
    if g.shape == "I":
        lf, lpf, lrf = g.b / (2 * g.tf), 0.38 * rE, 1.0 * rE
        if axis == "y":
            lw = g.hw / g.tw
            if lw > 3.76 * rE:
                raise NotCovered(f"I-section web h/tw = {lw:.0f} > 3.76 sqrt(E/Fy): noncompact/slender web (AISC F4/F5) not implemented")
            Mp, S = Fy * g.Zy, g.Sy
            ho = g.h - g.tf
            rts = math.sqrt(math.sqrt(g.Iz * g.Cw) / S)
            Lp = 1.76 * g.rz * rE                                                       # F2-5
            jc = g.J / (S * ho)
            Lr = 1.95 * rts * E / (0.7 * Fy) * math.sqrt(jc + math.sqrt(jc ** 2 + 6.76 * (0.7 * Fy / E) ** 2))   # F2-6
            Lb = p.Llt
            if Lb <= Lp:
                Mltb = Mp
            elif Lb <= Lr:
                Mltb = min(Cb * (Mp - (Mp - 0.7 * Fy * S) * (Lb - Lp) / (Lr - Lp)), Mp)    # F2-2
            else:
                Fcr = Cb * math.pi ** 2 * E / (Lb / rts) ** 2 * math.sqrt(1 + 0.078 * jc * (Lb / rts) ** 2)   # F2-4
                Mltb = min(Fcr * S, Mp)
            if lf <= lpf:
                Mflb = Mp
            elif lf <= lrf:
                Mflb = Mp - (Mp - 0.7 * Fy * S) * (lf - lpf) / (lrf - lpf)               # F3-1
            else:
                kc = min(max(4 / math.sqrt(g.hw / g.tw), 0.35), 0.76)
                Mflb = 0.9 * E * kc * S / lf ** 2                                       # F3-2
            Mn = min(Mltb, Mflb)
            return {"phiMn": 0.9 * Mn, "Mp": Mp, "Lp": Lp, "Lr": Lr, "Lb": Lb, "Cb": Cb, "M_ltb": Mltb, "M_flb": Mflb,
                    "clause": "F2/F3", "limit": "lateral-torsional buckling" if Mltb < Mflb else ("yielding" if Mflb >= Mp else "flange local buckling")}
        Mp, S = min(Fy * g.Zz, 1.6 * Fy * g.Sz), g.Sz                                   # F6-1
        if lf <= lpf:
            Mn = Mp
        elif lf <= lrf:
            Mn = Mp - (Mp - 0.7 * Fy * S) * (lf - lpf) / (lrf - lpf)                    # F6-2
        else:
            Mn = 0.69 * E / lf ** 2 * S                                                 # F6-3/4
        return {"phiMn": 0.9 * Mn, "Mp": Mp, "clause": "F6", "limit": "yielding" if Mn >= Mp else "flange local buckling"}
    if g.shape == "box":
        bf, hw = (g.b, g.h) if axis == "y" else (g.h, g.b)
        Z, S = (g.Zy, g.Sy) if axis == "y" else (g.Zz, g.Sz)
        Mp = Fy * Z
        lf, lw = (bf - 3 * g.t) / g.t, (hw - 3 * g.t) / g.t
        if lw > 5.70 * rE:
            raise NotCovered(f"HSS web h/t = {lw:.0f} > 5.70 sqrt(E/Fy): slender web (F7.3(c)) not implemented")
        if lf > 1.40 * rE:
            be = min(1.92 * g.t * rE * (1 - 0.38 / lf * rE), bf - 3 * g.t)                                 # F7-4
            Mflb = Fy * box_effective_modulus(bf, hw, g.t, be)                                              # F7-3
        else:
            Mflb = Mp if lf <= 1.12 * rE else min(Mp - (Mp - Fy * S) * (3.57 * lf / rE - 4.0), Mp)        # F7-2
        Mwlb = Mp if lw <= 2.42 * rE else min(Mp - (Mp - Fy * S) * (0.305 * lw / rE - 0.738), Mp)          # F7-5
        Mn = min(Mflb, Mwlb)
        return {"phiMn": 0.9 * Mn, "Mp": Mp, "clause": "F7", "limit": "yielding" if Mn >= Mp else "local buckling"}
    if g.shape == "pipe":
        Dt = g.h / g.t
        Mp = Fy * g.Zy
        if Dt <= 0.07 * E / Fy:
            Mn = Mp
        elif Dt <= 0.31 * E / Fy:
            Mn = (0.021 * E / Dt + Fy) * g.Sy                                           # F8-2
        elif Dt <= 0.45 * E / Fy:
            Mn = 0.33 * E / Dt * g.Sy                                                   # F8-3/4
        else:
            raise NotCovered(f"round HSS D/t = {Dt:.0f} > 0.45E/Fy (outside AISC F8)")
        return {"phiMn": 0.9 * min(Mn, Mp), "Mp": Mp, "clause": "F8", "limit": "yielding" if Mn >= Mp else "local buckling"}
    if g.shape == "rect":
        Z, S, d, t = (g.Zy, g.Sy, g.h, g.b) if axis == "y" else (g.Zz, g.Sz, g.b, g.h)
        Mp, My = min(Fy * Z, 1.6 * Fy * S), Fy * S                                      # F11-1
        if axis == "y" and d > t:
            q = p.Llt * d / t ** 2
            if q > 1.9 * E / Fy:
                Mn = min(1.9 * E * Cb / q * S, Mp)                                      # F11-3/4
            elif q > 0.08 * E / Fy:
                Mn = min(Cb * (1.52 - 0.274 * q * Fy / E) * My, Mp)                      # F11-2
            else:
                Mn = Mp
        else:
            Mn = Mp
        return {"phiMn": 0.9 * Mn, "Mp": Mp, "clause": "F11", "limit": "yielding" if Mn >= Mp else "lateral-torsional buckling"}
    Mp = min(Fy * g.Zy, 1.6 * Fy * g.Sy)                                                # circle, F11-1
    return {"phiMn": 0.9 * Mp, "Mp": Mp, "clause": "F11", "limit": "yielding"}


def box_effective_modulus(bf: float, hw: float, t: float, be: float) -> float:
    """Elastic modulus of a box whose compression flange has the effective flat width be (plus 3t of corners)."""
    parts = [(be + 3 * t, t, hw - t / 2), (bf, t, t / 2), (2 * t, hw - 2 * t, hw / 2)]   # (width, height, centroid)
    A = sum(w * h for w, h, _ in parts)
    yb = sum(w * h * y for w, h, y in parts) / A
    I = sum(w * h ** 3 / 12 + w * h * (y - yb) ** 2 for w, h, y in parts)
    return min(I / (hw - yb), I / yb)


def aisc_shear(g: Geo, Fy, E, axis: str, L: float) -> dict:
    """axis 'z' = shear Vz (major-axis bending), 'y' = shear Vy."""
    rE = math.sqrt(E / Fy)
    if g.shape == "I":
        if axis == "z":
            Aw, lam = g.h * g.tw, g.hw / g.tw
            if lam <= 2.24 * rE:                                                        # G2.1(a)
                return {"phiVn": 1.0 * 0.6 * Fy * Aw, "Aw": Aw, "Cv": 1.0, "phi": 1.0, "clause": "G2.1"}
            kv = 5.34
            Cv1 = 1.0 if lam <= 1.10 * math.sqrt(kv * E / Fy) else 1.10 * math.sqrt(kv * E / Fy) / lam   # G2-3/4
            return {"phiVn": 0.9 * 0.6 * Fy * Aw * Cv1, "Aw": Aw, "Cv": Cv1, "phi": 0.9, "clause": "G2.1"}
        Aw = 2 * g.b * g.tf
        Cv2 = aisc_cv2(g.b / (2 * g.tf), 1.2, E, Fy)
        return {"phiVn": 0.9 * 0.6 * Fy * Aw * Cv2, "Aw": Aw, "Cv": Cv2, "phi": 0.9, "clause": "G6"}
    if g.shape == "box":
        hh = (g.h if axis == "z" else g.b) - 3 * g.t
        Aw = 2 * hh * g.t
        Cv2 = aisc_cv2(hh / g.t, 5.0, E, Fy)
        return {"phiVn": 0.9 * 0.6 * Fy * Aw * Cv2, "Aw": Aw, "Cv": Cv2, "phi": 0.9, "clause": "G4"}
    if g.shape == "pipe":
        Dt, D = g.h / g.t, g.h
        Lv = max(L / 2, 1e-6)    # distance from max to zero shear: L/2 assumed
        Fcr = min(max(1.60 * E / (math.sqrt(Lv / D) * Dt ** 1.25), 0.78 * E / Dt ** 1.5), 0.6 * Fy)   # G5-2
        return {"phiVn": 0.9 * Fcr * g.A / 2, "Fcr": Fcr, "phi": 0.9, "clause": "G5"}
    raise NotCovered("AISC 360 chapter G has no shear provisions for solid bars")


def aisc_torsion_capacity(g: Geo, Fy, E):
    """H3.1 for HSS (Fcr limited to the yield value 0.6Fy; the HSS is assumed not slender in torsion)."""
    if g.shape == "box":
        C = 2 * (g.b - g.t) * (g.h - g.t) * g.t - 4.5 * (4 - math.pi) * g.t ** 3
        return 0.9 * 0.6 * Fy * C
    if g.shape == "pipe":
        C = math.pi * (g.h - g.t) ** 2 * g.t / 2
        return 0.9 * 0.6 * Fy * C
    return None


def aisc_member(g: Geo, Fy, E, G, p: Params, forces: list[tuple[str, Forces]], code_name: str) -> dict:
    checks, info = {}, {}

    def keep(c, combo, x):
        c["combo"], c["x"] = combo, float(x)
        if c["id"] not in checks or c["ratio"] > checks[c["id"]]["ratio"]:
            checks[c["id"]] = c

    phiTn = 0.9 * Fy * g.A                                                              # D2-1 (gross yielding)
    comp = aisc_compression(g, Fy, E, G, p)
    shear_z = shear_y = None
    try:
        shear_z, shear_y = aisc_shear(g, Fy, E, "z", p.L), aisc_shear(g, Fy, E, "y", p.L)
    except NotCovered as exc:
        info["shear"] = str(exc)
    Tc = aisc_torsion_capacity(g, Fy, E)
    skip = []

    def flexure_or_skip(axis, Cb, comp_name, S):
        """A bending check outside the implemented clauses is skipped only when that moment is negligible."""
        try:
            return aisc_flexure(g, Fy, E, axis, p, Cb)
        except NotCovered as exc:
            if max(float(np.abs(getattr(f, comp_name)).max()) for _, f in forces) <= 0.01 * Fy * S:
                skip.append(f"{exc} (that moment is negligible here, so this check is skipped)")
                return None
            raise

    NONE = {"phiMn": math.inf, "limit": "", "clause": ""}
    flex_z = flexure_or_skip("z", 1.0, "Mz", g.Sz) or NONE
    flex_y0 = flexure_or_skip("y", 1.0, "My", g.Sy)
    for combo, f in forces:
        Cb = p.Cb if p.Cb is not None else (moment_gradient(f, "My", p.L) if p.Lb is None or p.Lb >= p.L else 1.0)
        flex_y = aisc_flexure(g, Fy, E, "y", p, Cb) if flex_y0 else NONE
        k = int(np.argmax(f.N))
        if f.N[k] > 0:
            keep(_chk("tension", "Tension (gross yielding)", "D2(a)", f.N[k], phiTn, "force"), combo, f.x[k])
        k = int(np.argmin(f.N))
        if f.N[k] < 0:
            keep(_chk("compression", f"Compression, {comp['mode']}", "E3/E4" + ("/E7" if comp["slender"] else ""), -f.N[k], comp["phiPn"], "force",
                      {"Fcr": comp["Fcr"], "Fe": comp["Fe"], "Ae/A": comp["Ae"] / g.A, "KL/r": comp["KL_r"]}), combo, f.x[k])
        k = int(np.argmax(np.abs(f.My)))
        if flex_y is not NONE:
            keep(_chk("flexure_y", f"Major-axis bending ({flex_y['limit']})", flex_y["clause"], f.My[k], flex_y["phiMn"], "moment",
                      {kk: flex_y[kk] for kk in ("Mp", "Lp", "Lr", "Lb", "Cb") if kk in flex_y}), combo, f.x[k])
        k = int(np.argmax(np.abs(f.Mz)))
        if flex_z is not NONE:
            keep(_chk("flexure_z", f"Minor-axis bending ({flex_z['limit']})", flex_z["clause"], f.Mz[k], flex_z["phiMn"], "moment"), combo, f.x[k])
        if shear_z:
            k = int(np.argmax(np.abs(f.Vz)))
            keep(_chk("shear_z", "Shear Vz", shear_z["clause"], f.Vz[k], shear_z["phiVn"], "force"), combo, f.x[k])
            k = int(np.argmax(np.abs(f.Vy)))
            keep(_chk("shear_y", "Shear Vy", shear_y["clause"], f.Vy[k], shear_y["phiVn"], "force"), combo, f.x[k])
        # H1-1 at every station
        Pc = np.where(f.N < 0, comp["phiPn"], phiTn)
        pr = np.abs(f.N) / Pc
        mr = np.abs(f.My) / flex_y["phiMn"] + np.abs(f.Mz) / flex_z["phiMn"]
        h1 = np.where(pr >= 0.2, pr + 8 / 9 * mr, pr / 2 + mr)
        if Tc:
            tr = np.abs(f.T) / Tc
            vr = np.maximum(np.abs(f.Vz) / shear_z["phiVn"], np.abs(f.Vy) / shear_y["phiVn"]) if shear_z else 0
            h3 = (pr + mr) + (vr + tr) ** 2                                                 # H3-6
            h1 = np.where(tr > 0.2, np.maximum(h1, h3), h1)
            k = int(np.argmax(np.abs(f.T)))
            if abs(f.T[k]) > 1e-9:
                keep(_chk("torsion", "Torsion (HSS)", "H3.1", f.T[k], Tc, "moment"), combo, f.x[k])
        k = int(np.argmax(h1))
        keep(_chk("interaction", "Axial + bending interaction", "H1-1a" if pr[k] >= 0.2 else "H1-1b", h1[k], 1.0, "ratio",
                  {"Pr/Pc": float(pr[k]), "Mry/Mcy": float(abs(f.My[k]) / flex_y["phiMn"]), "Mrz/Mcz": float(abs(f.Mz[k]) / flex_z["phiMn"])},
                  ratio=float(h1[k])), combo, f.x[k])
    notes = list(p.notes) + skip
    if comp["KL_r"] > 200 and "compression" in checks:
        notes.append(f"KL/r = {comp['KL_r']:.0f} > 200 (AISC E2 user note recommends at most 200 for compression members).")
    if comp["slender"]:
        notes.append("Slender elements in compression (" + ", ".join(comp["slender"]) + "): effective area by E7.")
    if g.shape == "I" and any(np.abs(f.T).max() > 1e-3 * Fy * g.Zy for _, f in forces):
        notes.append("Torsion in an open section is not checked.")
    if "shear" in info:
        notes.append(info["shear"])
    if Tc is None and g.shape != "I":
        notes.append("Torsion not checked for this section.")
    return {"checks": list(checks.values()), "notes": notes,
            "props": {"phiPn": comp["phiPn"], "phiTn": phiTn, "phiMny": flex_y0["phiMn"] if flex_y0 else None,
                      "phiMnz": flex_z["phiMn"] if flex_z is not NONE else None, "KL_r": comp["KL_r"], "buckling_mode": comp["mode"]}}


# ---------------------------------------------------------------------------------------------------------------
# EN 1993-1-1
# ---------------------------------------------------------------------------------------------------------------
def ec3_chi(lam: float, alpha: float, lam0: float = 0.2) -> float:
    """Reduction factor, 6.3.1.2 (6.49) / 6.3.2.2 (6.56)."""
    if lam <= lam0:
        return 1.0
    phi = 0.5 * (1 + alpha * (lam - 0.2) + lam ** 2)
    return min(1.0, 1 / (phi + math.sqrt(max(phi ** 2 - lam ** 2, 0.0))))


def ec3_curves(g: Geo, fy_mpa: float) -> tuple[str, str]:
    """Buckling curves (Table 6.2) for y-y and z-z, S235 to S420."""
    if g.shape == "I":
        if g.fab == "welded":
            return ("b", "c") if g.tf <= 0.040 else ("c", "d")
        if g.h / g.b > 1.2:
            return ("a", "b") if g.tf <= 0.040 else ("b", "c")
        return ("b", "c") if g.tf <= 0.100 else ("d", "d")
    if g.shape in ("box", "pipe"):
        return ("a", "a") if g.fab == "hot" else ("c", "c")
    return ("c", "c")


def ec3_class(g: Geo, fy: float, eps: float, Nc: float, My: float, Mz: float) -> tuple[int, str]:
    """Cross-section class (Table 5.2) under compression Nc (> 0 compression, kN) and moments (kN*m). fy in kN/m2."""
    def internal(c, t, sig_n, M, I, uniform):
        ct = c / t
        if uniform:
            lims = (33 * eps, 38 * eps, 42 * eps)
        else:
            alpha = min(max(0.5 + sig_n * 1.0 / (2 * c * t * fy), 0.01), 1.0)
            l1 = 396 * eps / (13 * alpha - 1) if alpha > 0.5 else 36 * eps / alpha
            l2 = 456 * eps / (13 * alpha - 1) if alpha > 0.5 else 41.5 * eps / alpha
            s1 = sig_n / g.A + abs(M) * (c / 2) / I
            s2 = sig_n / g.A - abs(M) * (c / 2) / I
            if s1 <= 0:
                return 1, ct
            psi = s2 / s1
            l3 = 42 * eps / (0.67 + 0.33 * psi) if psi > -1 else 62 * eps * (1 - psi) * math.sqrt(-psi)
            lims = (l1, l2, l3)
        return next((k + 1 for k, lim in enumerate(lims) if ct <= lim), 4), ct

    if g.shape == "I":
        c_f = (g.b - g.tw) / 2 / g.tf
        cf = next((k + 1 for k, lim in enumerate((9 * eps, 10 * eps, 14 * eps)) if c_f <= lim), 4)
        if Nc <= 0 and abs(My) < 1e-9 and abs(Mz) < 1e-9:
            return 1, "no compression"
        if Nc > 0 and abs(My) < 1e-9:
            cw, ctw = internal(g.hw, g.tw, Nc, 0, g.Iy, True)
        else:
            cw, ctw = internal(g.hw, g.tw, Nc, My, g.Iy, False)
        if Nc <= 0 and abs(My) < 1e-9:     # minor-axis bending only: web at the neutral axis
            cw = 1
        return max(cf, cw), f"flange c/t = {c_f:.1f} (class {cf}), web c/t = {ctw:.1f} (class {cw})"
    if g.shape == "box":
        out = []
        for w, M_flange, M_web, I_web in ((g.b, My, Mz, g.Iz), (g.h, Mz, My, g.Iy)):
            c = w - 3 * g.t
            uniform = Nc > 0 and abs(M_web) < 1e-9 or abs(M_flange) > 1e-9
            cl, ct = internal(c, g.t, Nc, M_web, I_web, uniform) if (Nc > 0 or abs(M_web) > 1e-9 or abs(M_flange) > 1e-9) else (1, (w - 3 * g.t) / g.t)
            out.append((cl, ct))
        cls = max(o[0] for o in out)
        return cls, f"walls c/t = {out[0][1]:.1f} / {out[1][1]:.1f}"
    if g.shape == "pipe":
        dt = g.h / g.t
        cls = next((k + 1 for k, lim in enumerate((50 * eps ** 2, 70 * eps ** 2, 90 * eps ** 2)) if dt <= lim), 4)
        return cls, f"d/t = {dt:.1f}"
    return 1, "solid section"


def ec3_rho(ct: float, eps: float, outstand: bool) -> float:
    """Plate reduction factor, EN 1993-1-5 4.4(2), uniform compression (psi = 1)."""
    ks = 0.43 if outstand else 4.0
    lam = ct / (28.4 * eps * math.sqrt(ks))
    if outstand:
        return 1.0 if lam <= 0.748 else min(1.0, (lam - 0.188) / lam ** 2)
    return 1.0 if lam <= 0.673 else min(1.0, (lam - 0.22) / lam ** 2)


def ec3_effective_area(g: Geo, eps: float) -> float:
    if g.shape == "I":
        c = (g.b - g.tw) / 2
        return (g.A - 4 * (1 - ec3_rho(c / g.tf, eps, True)) * c * g.tf
                - (1 - ec3_rho(g.hw / g.tw, eps, False)) * g.hw * g.tw)
    if g.shape == "box":
        cb, ch = g.b - 3 * g.t, g.h - 3 * g.t
        return g.A - 2 * (1 - ec3_rho(cb / g.t, eps, False)) * cb * g.t - 2 * (1 - ec3_rho(ch / g.t, eps, False)) * ch * g.t
    raise NotCovered("class 4 circular hollow section (EN 1993-1-6) not implemented")


def ec3_bending_class3(g: Geo, eps: float, axis: str) -> bool:
    """True when every plate is class 3 or better in pure bending about this axis (then W_eff = W_el)."""
    if g.shape == "I":
        flange = (g.b - g.tw) / 2 / g.tf <= 14 * eps
        return flange and (g.hw / g.tw <= 124 * eps if axis == "y" else True)
    if g.shape == "box":
        fl, wb = (g.b, g.h) if axis == "y" else (g.h, g.b)
        return (fl - 3 * g.t) / g.t <= 42 * eps and (wb - 3 * g.t) / g.t <= 124 * eps
    return False


def ec3_shear_areas(g: Geo) -> tuple[float, float]:
    """(Av for Vz, Av for Vy), 6.2.6(3), fillet radii ignored, eta = 1.0."""
    if g.shape == "I":
        return max(g.A - 2 * g.b * g.tf + g.tw * g.tf, g.hw * g.tw), g.A - g.hw * g.tw
    if g.shape == "box":
        return g.A * g.h / (g.b + g.h), g.A * g.b / (g.b + g.h)
    if g.shape == "pipe":
        return 2 * g.A / math.pi, 2 * g.A / math.pi
    return g.A, g.A


def ec3_mcr(g: Geo, E, G, L, C1):
    """Elastic critical moment of a doubly symmetric I-section, load at the shear centre, k = kw = 1."""
    return C1 * math.pi ** 2 * E * g.Iz / L ** 2 * math.sqrt(g.Cw / g.Iz + L ** 2 * G * g.J / (math.pi ** 2 * E * g.Iz))


def ec3_member(g: Geo, fy, E, G, p: Params, forces: list[tuple[str, Forces]]) -> dict:
    fy_mpa = fy / 1000
    eps = math.sqrt(235 / fy_mpa)
    if fy_mpa > 460:
        raise NotCovered("steel grade above S460 (EN 1993-1-12)")
    # member class = worst over every station of every combination (actions below 1 % of the resistance ignored)
    cls, cls_txt = 1, ""
    n_sig, my_sig, mz_sig = 0.01 * g.A * fy, 0.01 * g.Sy * fy, 0.01 * g.Sz * fy
    for _, f in forces:
        for k in range(len(f.x)):
            Nc = -f.N[k] if -f.N[k] > n_sig else 0.0
            c, txt = ec3_class(g, fy, eps, Nc, f.My[k] if abs(f.My[k]) > my_sig else 0.0, f.Mz[k] if abs(f.Mz[k]) > mz_sig else 0.0)
            if c > cls or not cls_txt:
                cls, cls_txt = max(c, cls), txt
    notes = list(p.notes)
    Aeff = g.A
    if cls == 4:
        Aeff = ec3_effective_area(g, eps)
        for axis, comp, sig in (("y", "My", my_sig), ("z", "Mz", mz_sig)):
            if any(np.abs(getattr(f, comp)).max() > sig for _, f in forces) and not ec3_bending_class3(g, eps, axis):
                raise NotCovered(f"class 4 cross-section in bending about {axis} ({cls_txt}): effective modulus Weff "
                                 "(EN 1993-1-5) not implemented")
        notes.append(f"Class 4 ({cls_txt}): A_eff = {Aeff / g.A:.3f} A from EN 1993-1-5 4.4 with every plate in uniform "
                     "compression (conservative); W_eff = W_el because the plates are class 3 or better in pure bending; "
                     "e_N = 0 (doubly symmetric).")
    Wy, Wz = (g.Zy, g.Zz) if cls <= 2 else (g.Sy, g.Sz)
    Npl = g.A * fy / G_M0
    Nc_Rd = Aeff * fy / G_M0
    Avz, Avy = ec3_shear_areas(g)
    Vplz, Vply = Avz * fy / math.sqrt(3) / G_M0, Avy * fy / math.sqrt(3) / G_M0
    if g.shape == "I" and g.hw / g.tw > 72 * eps or g.shape == "box" and (g.h - 3 * g.t) / g.t > 72 * eps:
        raise NotCovered("web slenderness above 72 eps / eta: shear buckling (EN 1993-1-5) not implemented")
    # flexural (and torsional) buckling
    cy, cz = ec3_curves(g, fy_mpa)
    Ncr_y = math.pi ** 2 * E * g.Iy / (p.Ky * p.L) ** 2
    Ncr_z = math.pi ** 2 * E * g.Iz / (p.Kz * p.L) ** 2
    lam_y, lam_z = math.sqrt(Aeff * fy / Ncr_y), math.sqrt(Aeff * fy / Ncr_z)
    chi_y, chi_z = ec3_chi(lam_y, CURVE_ALPHA[cy]), ec3_chi(lam_z, CURVE_ALPHA[cz])
    chi_T, lam_T = 1.0, 0.0
    if g.shape == "I":
        i0 = (g.Iy + g.Iz) / g.A
        Ncr_T = (G * g.J + math.pi ** 2 * E * g.Cw / (p.Kt * p.L) ** 2) / i0                # torsional, 6.3.1.4
        lam_T = math.sqrt(Aeff * fy / Ncr_T)
        chi_T = ec3_chi(lam_T, CURVE_ALPHA[cz])
    chi_min = min(chi_y, chi_z, chi_T)
    Nb = chi_min * Aeff * fy / G_M1
    mode = "major axis" if chi_min == chi_y else ("minor axis" if chi_min == chi_z else "torsional")
    checks = {}

    def keep(c, combo, x):
        c["combo"], c["x"] = combo, float(x)
        if c["id"] not in checks or c["ratio"] > checks[c["id"]]["ratio"]:
            checks[c["id"]] = c

    clause_m = "6.2.5" + (" (plastic)" if cls <= 2 else " (elastic)")
    for combo, f in forces:
        k = int(np.argmax(f.N))
        if f.N[k] > 0:
            keep(_chk("tension", "Tension (gross section)", "6.2.3 (6.6)", f.N[k], Npl, "force"), combo, f.x[k])
        k = int(np.argmin(f.N))
        if f.N[k] < 0:
            keep(_chk("compression", "Compression resistance", "6.2.4", -f.N[k], Nc_Rd, "force"), combo, f.x[k])
            keep(_chk("buckling", f"Flexural buckling, {mode}", "6.3.1", -f.N[k], Nb, "force",
                      {"chi_y": chi_y, "chi_z": chi_z, "chi_T": chi_T, "lambda_y": lam_y, "lambda_z": lam_z, "curves": f"{cy}/{cz}"}), combo, f.x[k])
        k = int(np.argmax(np.abs(f.Vz)))
        keep(_chk("shear_z", "Shear Vz", "6.2.6", f.Vz[k], Vplz, "force", {"Av": Avz}), combo, f.x[k])
        k = int(np.argmax(np.abs(f.Vy)))
        keep(_chk("shear_y", "Shear Vy", "6.2.6", f.Vy[k], Vply, "force", {"Av": Avy}), combo, f.x[k])
        # cross-section resistance at every station (6.2.8 shear reduction, 6.2.9 bending + axial)
        n = np.abs(f.N) / np.where(f.N < 0, Nc_Rd, Npl)
        rho_z = np.where(np.abs(f.Vz) > 0.5 * Vplz, (2 * np.abs(f.Vz) / Vplz - 1) ** 2, 0.0)
        rho_y = np.where(np.abs(f.Vy) > 0.5 * Vply, (2 * np.abs(f.Vy) / Vply - 1) ** 2, 0.0)
        if g.shape == "I" and cls <= 2:
            Aw = g.hw * g.tw
            Mply = np.maximum((Wy - rho_z * Aw ** 2 / (4 * g.tw)) * fy / G_M0, 1e-12)              # (6.30)
        else:
            Mply = (1 - rho_z) * Wy * fy / G_M0
        Mplz = (1 - rho_y) * Wz * fy / G_M0
        if cls <= 2 and g.shape in ("I", "box", "pipe"):
            nn = np.minimum(n, 0.999999)
            if g.shape == "I":
                a = min((g.A - 2 * g.b * g.tf) / g.A, 0.5)
                MNy = np.minimum(Mply * (1 - nn) / (1 - 0.5 * a), Mply)                             # (6.36)
                MNz = np.where(nn <= a, Mplz, Mplz * (1 - ((nn - a) / (1 - a)) ** 2))               # (6.37/6.38)
                al, be = 2.0, np.maximum(5 * nn, 1.0)
            elif g.shape == "box":
                aw = min((g.A - 2 * g.b * g.t) / g.A, 0.5)
                af = min((g.A - 2 * g.h * g.t) / g.A, 0.5)
                MNy = np.minimum(Mply * (1 - nn) / (1 - 0.5 * aw), Mply)                            # (6.39)
                MNz = np.minimum(Mplz * (1 - nn) / (1 - 0.5 * af), Mplz)                            # (6.40)
                al = be = np.minimum(1.66 / (1 - 1.13 * nn ** 2), 6.0)
            else:
                MNy = Mply * (1 - nn ** 1.7)
                MNz = Mplz * (1 - nn ** 1.7)
                al = be = 2.0
            cs = (np.abs(f.My) / MNy) ** al + (np.abs(f.Mz) / MNz) ** be                          # (6.41)
            cs = np.where(n >= 1, n, np.maximum(cs, n))
            clause = "6.2.9.1 (6.41)"
        else:
            cs = n + np.abs(f.My) / Mply + np.abs(f.Mz) / Mplz                                     # (6.2) / 6.2.9.2-3
            clause = "6.2.1(7) / 6.2.9.2"
        k = int(np.argmax(cs))
        keep(_chk("section", "Cross-section: bending + axial + shear", clause, cs[k], 1.0, "ratio",
                  {"n": float(n[k]), "rho_z": float(rho_z[k])}, ratio=float(cs[k])), combo, f.x[k])
        k = int(np.argmax(np.abs(f.My)))
        keep(_chk("bending_y", "Major-axis bending", clause_m, f.My[k], Wy * fy / G_M0, "moment"), combo, f.x[k])
        k = int(np.argmax(np.abs(f.Mz)))
        keep(_chk("bending_z", "Minor-axis bending", clause_m, f.Mz[k], Wz * fy / G_M0, "moment"), combo, f.x[k])

        # lateral-torsional buckling (I-sections, general case 6.3.2.2)
        My_max, Mz_max = float(np.abs(f.My).max()), float(np.abs(f.Mz).max())
        chi_lt, lam_lt, C1 = 1.0, 0.0, 1.0
        if g.shape == "I":
            C1 = p.Cb if p.Cb is not None else (min(moment_gradient(f, "My", p.L), 2.7) if p.Lb is None or p.Lb >= p.L else 1.0)
            Mcr = ec3_mcr(g, E, G, p.Llt, C1)
            lam_lt = math.sqrt(Wy * fy / Mcr)
            a_lt = (0.21 if g.h / g.b <= 2 else 0.34) if g.fab != "welded" else (0.49 if g.h / g.b <= 2 else 0.76)
            chi_lt = ec3_chi(lam_lt, a_lt)
            if My_max > 1e-9:
                keep(_chk("ltb", "Lateral-torsional buckling", "6.3.2.2", My_max, chi_lt * Wy * fy / G_M1, "moment",
                          {"Mcr": Mcr, "lambda_LT": lam_lt, "chi_LT": chi_lt, "C1": C1, "L_LT": p.Llt}),
                     combo, f.x[int(np.argmax(np.abs(f.My)))])
        MyRk, MzRk = Wy * fy, Wz * fy
        NEd = float(max(-f.N.min(), 0.0))
        if NEd > 0:
            Cmy, ty = equivalent_moment_factor(f, "My")
            Cmz, tz = equivalent_moment_factor(f, "Mz")
            CmLT = Cmy
            ny, nz = NEd / (chi_y * Nc_Rd / G_M1), NEd / (chi_z * Nc_Rd / G_M1)
            susceptible = g.shape == "I" and chi_lt < 1.0
            if cls <= 2:
                kyy = Cmy * min(1 + (lam_y - 0.2) * ny, 1 + 0.8 * ny)
                kzz = Cmz * min(1 + (2 * lam_z - 0.6) * nz, 1 + 1.4 * nz) if g.shape == "I" else Cmz * min(1 + (lam_z - 0.2) * nz, 1 + 0.8 * nz)
                kyz = 0.6 * kzz
                if susceptible:
                    kzy = (max(1 - 0.1 * lam_z / (CmLT - 0.25) * nz, 1 - 0.1 / (CmLT - 0.25) * nz) if lam_z >= 0.4
                           else min(0.6 + lam_z, 1 - 0.1 * lam_z / (CmLT - 0.25) * nz))
                else:
                    kzy = 0.6 * kyy
            else:
                kyy = Cmy * min(1 + 0.6 * lam_y * ny, 1 + 0.6 * ny)
                kzz = Cmz * min(1 + 0.6 * lam_z * nz, 1 + 0.6 * nz)
                kyz = kzz
                kzy = max(1 - 0.05 * lam_z / (CmLT - 0.25) * nz, 1 - 0.05 / (CmLT - 0.25) * nz) if susceptible else 0.8 * kyy
            r61 = ny + kyy * My_max / (chi_lt * MyRk / G_M1) + kyz * Mz_max / (MzRk / G_M1)
            r62 = nz + kzy * My_max / (chi_lt * MyRk / G_M1) + kzz * Mz_max / (MzRk / G_M1)
            r = max(r61, r62)
            keep(_chk("interaction", "Buckling interaction (Annex B)", "6.3.3 (6.61)" if r61 >= r62 else "6.3.3 (6.62)", r, 1.0, "ratio",
                      {"kyy": kyy, "kyz": kyz, "kzy": kzy, "kzz": kzz, "Cmy": Cmy, "Cmz": Cmz, "Cm note": f"{ty}; {tz}"}, ratio=r), combo, 0.0)
        elif My_max > 1e-9 or Mz_max > 1e-9:
            r = My_max / (chi_lt * MyRk / G_M1) + Mz_max / (MzRk / G_M1)
            keep(_chk("interaction", "Biaxial bending with LTB (axial tension neglected)", "6.3.2 / 6.3.3", r, 1.0, "ratio", ratio=r), combo, 0.0)
    if g.shape in ("box", "pipe"):
        notes.append(f"Hollow section: buckling curve {cy} ({'hot-finished' if g.fab == 'hot' else 'cold-formed, assumed'}); not susceptible to LTB.")
    if g.shape == "I":
        notes.append(f"C1 for M_cr from the moment diagram (quarter-point formula, approximation); load applied at the shear centre.")
    if g.shape == "rect":
        notes.append("Solid rectangular bar: lateral-torsional buckling not checked.")
    if any(np.abs(f.T).max() > 1e-3 * max(Wy * fy, 1e-9) for _, f in forces):
        notes.append("Torsion is not checked.")
    return {"checks": list(checks.values()), "notes": notes,
            "props": {"class": cls, "class_detail": cls_txt, "Npl_Rd": Npl, "Aeff/A": Aeff / g.A, "Nb_Rd": Nb, "chi_y": chi_y, "chi_z": chi_z,
                      "chi_T": chi_T, "curves": f"{cy}/{cz}", "Wy": Wy, "Wz": Wz}}


# ---------------------------------------------------------------------------------------------------------------
# driver
# ---------------------------------------------------------------------------------------------------------------
def design_combinations(model: dict) -> tuple[list[tuple[str, dict]], list[str]]:
    cases = {c["id"] for c in model.get("load_cases", [])}
    out = []
    for c in model.get("combinations", []):
        text = f"{c['id']} {c.get('name', '')}".lower()
        if any(w in text for w in SLS_WORDS):
            continue
        out.append((c["id"], {k: float(v) for k, v in c["factors"].items() if k in cases}))
    notes = []
    if not out:
        out = [(c, {c: 1.0}) for c in sorted(cases)]
        notes.append("No ultimate (ULS) load combinations in the model: each load case is checked unfactored.")
    return out, notes


def combine_member(cases: dict, eid: str, factors: dict) -> Forces | None:
    base = None
    acc = {k: None for k in ("N", "Vy", "Vz", "T", "My", "Mz")}
    for c, fac in factors.items():
        st = cases.get(c, {}).get("elements", {}).get(eid)
        if st is None:
            continue
        base = st
        for k in acc:
            v = fac * np.asarray(st[k], dtype=float)
            acc[k] = v if acc[k] is None else acc[k] + v
    if base is None:
        return None
    return Forces(np.asarray(base["x"], dtype=float), **acc)


def member_params(e: dict, L: float) -> Params:
    d = e.get("design", {}) or {}
    p = Params(L=L, Ky=float(d.get("Ky", 1.0)), Kz=float(d.get("Kz", 1.0)), Kt=float(d.get("Kt", d.get("Kz", 1.0))))
    if d.get("Lb") not in (None, ""):
        p.Lb = float(d["Lb"])
    if d.get("Cb") not in (None, ""):
        p.Cb = float(d["Cb"])
    if not d.get("Ky") and not d.get("Kz"):
        p.notes.append("Effective length factors K = 1.0 assumed (member braced against sway at both ends). "
                       "Set K in the member's design settings for sway frames or other end conditions.")
    return p


def steel_design(model: dict, code: str | None = None, results: dict | None = None) -> dict:
    """Check every steel member of the model for all ultimate combinations."""
    from .analysis import analyze
    std = model.get("settings", {}).get("standard", "EN1990")
    code = code or model.get("settings", {}).get("steel_code") or CODE_FOR_STANDARD.get(std, "EC3")
    if code not in CODES:
        raise ValueError(f"Unknown steel design code '{code}'")
    res = results or analyze(model)
    combos, gnotes = design_combinations(model)
    mats = {**MATERIALS, **model.get("materials", {})}
    xyz = {n["id"]: np.array([n["x"], n["y"], n["z"]], dtype=float) for n in model["nodes"]}
    members, counts = {}, {"ok": 0, "fail": 0, "not_covered": 0, "skipped": 0}
    for e in model["elements"]:
        sec = model["sections"].get(e["section"], {})
        mat = mats.get(sec.get("material", ""), {})
        out = {"id": e["id"], "section": sec.get("name", e["section"]), "material": sec.get("material", "")}
        if mat.get("kind") != "steel":
            out.update(status="skipped", util=None, reason=f"not steel ({mat.get('kind', 'unknown material')})")
            counts["skipped"] += 1
            members[e["id"]] = out
            continue
        L = float(np.linalg.norm(xyz[e["j"]] - xyz[e["i"]]))
        forces = [(cid, f) for cid, fac in combos if (f := combine_member(res["cases"], e["id"], fac)) is not None]
        fy = float(mat["fy"]) * 1000
        mp = material_props(mat)
        p = member_params(e, L)
        out["params"] = {"L": L, "Ky": p.Ky, "Kz": p.Kz, "Lb": p.Llt, "Cb": p.Cb, "fy": fy / 1000}
        try:
            if not forces:
                raise NotCovered("no results for this member")
            g = geometry(sec)
            r = aisc_member(g, fy, mp["E"], mp["G"], p, forces, code) if code in ("AISC360", "EIT") else ec3_member(g, fy, mp["E"], mp["G"], p, forces)
        except NotCovered as exc:
            out.update(status="not_covered", util=None, reason=str(exc), checks=[], notes=list(p.notes))
            counts["not_covered"] += 1
            members[e["id"]] = out
            continue
        checks = sorted(r["checks"], key=lambda c: -c["ratio"])
        util = checks[0]["ratio"] if checks else 0.0
        status = "ok" if util <= 1.0 + 1e-9 else "fail"
        counts[status] += 1
        out.update(status=status, util=util, governing=checks[0] if checks else None, checks=checks, notes=r["notes"], props=r["props"])
        members[e["id"]] = out
    utils = [m["util"] for m in members.values() if m.get("util") is not None]
    gnotes += [
        "Member forces from the linear (first-order) analysis. " + (
            "Where alpha_cr < 10 (EN 1993-1-1 5.2.1) second-order effects and imperfections must be included: "
            "not done here." if code == "EC3" else
            "AISC 360 chapter C asks for second-order effects (direct analysis method with notional loads and "
            "reduced stiffness): not included here."),
        "Connections, net-section rupture, bolt holes, web crippling under concentrated loads and seismic detailing are not checked.",
        "Fillet / corner radii are ignored in the section properties (slightly conservative).",
    ]
    if code == "EC3":
        gnotes.append("gamma_M0 = gamma_M1 = 1.0 (recommended values); check the National Annex.")
    if code == "EIT":
        gnotes.append("Thai EIT: AISC 360-16 LRFD equations with the model's load combinations. Confirm against the EIT "
                      "steel design standard in force for the project.")
    return {"code": code, "code_name": CODES[code], "combinations": [c for c, _ in combos], "members": members,
            "summary": {**counts, "max_util": max(utils) if utils else None, "n_checked": len(utils)}, "notes": gnotes}


__all__ = ["steel_design", "CODES", "geometry", "aisc_fcr", "ec3_chi", "ec3_mcr", "aisc_flexure", "aisc_compression"]
