"""Material library and cross-section property calculation.

Internal unit system: kN, m. Material input is in engineering units
(E, G in MPa, density in kN/m^3) and converted here.

Section local axes (see solver.local_axes):
  * local y : section width direction  (dimension ``b``)
  * local z : section depth direction  (dimension ``h``)
  * Iy      : second moment about local y  (bending in the x-z plane, "major")
  * Iz      : second moment about local z  (bending in the x-y plane, "minor")
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .steel_tables import table_props

MPA_TO_KN_M2 = 1000.0

# Default material library. Values are typical nominal values; the user can
# override any of them in the model file.
MATERIALS: dict[str, dict] = {
    "C25/30": {"name": "Concrete C25/30", "kind": "concrete", "E": 31000.0, "nu": 0.2, "density": 25.0, "fck": 25.0},
    "C30/37": {"name": "Concrete C30/37", "kind": "concrete", "E": 33000.0, "nu": 0.2, "density": 25.0, "fck": 30.0},
    "C40/50": {"name": "Concrete C40/50", "kind": "concrete", "E": 35000.0, "nu": 0.2, "density": 25.0, "fck": 40.0},
    "S275": {"name": "Steel S275", "kind": "steel", "E": 210000.0, "nu": 0.3, "density": 78.5, "fy": 275.0},
    "S355": {"name": "Steel S355", "kind": "steel", "E": 210000.0, "nu": 0.3, "density": 78.5, "fy": 355.0},
    "A992": {"name": "Steel ASTM A992", "kind": "steel", "E": 200000.0, "nu": 0.3, "density": 77.0, "fy": 345.0},
}

KSC_TO_MPA = 0.0980665


def _thai_concrete(fc_ksc: float) -> dict:
    """Thai practice (EIT 1008 / ACI 318): Ec = 15100 sqrt(fc') in ksc, fc' = cylinder strength."""
    E_ksc = 15100.0 * math.sqrt(fc_ksc)
    return {"name": f"Concrete fc'={fc_ksc:.0f} ksc (TH)", "kind": "concrete", "E": round(E_ksc * KSC_TO_MPA, 1),
            "nu": 0.2, "density": 23.5, "fck": round(fc_ksc * KSC_TO_MPA, 2), "standard": "TH"}


for _fc in (180, 210, 240, 280, 320):
    MATERIALS[f"TH-fc{_fc}"] = _thai_concrete(_fc)
MATERIALS["SS400"] = {"name": "Steel SS400 (TIS 1227)", "kind": "steel", "E": 200000.0, "nu": 0.3, "density": 77.0, "fy": 245.0, "standard": "TH"}
MATERIALS["SM520"] = {"name": "Steel SM520 (TIS 1227)", "kind": "steel", "E": 200000.0, "nu": 0.3, "density": 77.0, "fy": 355.0, "standard": "TH"}


@dataclass
class SectionProps:
    A: float   # m^2
    Iy: float  # m^4  (major, about local y)
    Iz: float  # m^4  (minor, about local z)
    J: float   # m^4  (St. Venant torsion constant)
    Sy: float  # m^3  elastic modulus for My  (Iy / (h/2))
    Sz: float  # m^3  elastic modulus for Mz  (Iz / (b/2))
    b: float   # m   overall width (local y)
    h: float   # m   overall depth (local z)

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def rect_torsion_constant(b: float, h: float) -> float:
    """St. Venant torsion constant of a solid rectangle (Roark approximation)."""
    a, c = max(b, h), min(b, h)
    return a * c**3 * (1.0 / 3.0 - 0.21 * (c / a) * (1.0 - c**4 / (12.0 * a**4)))


def shape_rects(sec: dict) -> list[tuple[float, float, float, float]]:
    """Open thin-walled shapes as rectangles (y0, y1, z0, z1) in the section plane: y across the width (b), z along
    the depth (h). Corners are square (no fillets). Channel and lip channel: web at y = 0..t, flanges towards +y.
    Angle: legs along +y and +z from the heel at the origin."""
    shape = sec.get("shape")
    if shape == "channel":
        h, b, tw, tf = (float(sec[k]) for k in ("h", "b", "tw", "tf"))
        if 2 * tf >= h or tw >= b:
            raise ValueError("Channel flanges or web too thick for its size")
        return [(0, tw, -h / 2, h / 2), (tw, b, h / 2 - tf, h / 2), (tw, b, -h / 2, -h / 2 + tf)]
    if shape == "angle":
        b, t = float(sec["b"]), float(sec["t"])
        if t >= b:
            raise ValueError("Angle leg thickness larger than the leg")
        return [(0, b, 0, t), (0, t, t, b)]
    if shape == "lipchannel":
        h, b, c, t = (float(sec[k]) for k in ("h", "b", "c", "t"))
        if 2 * t >= min(b, c) or 2 * c >= h:
            raise ValueError("Lip channel dimensions are not consistent (h > 2c, b and c > 2t)")
        return [(0, t, -h / 2, h / 2), (t, b, h / 2 - t, h / 2), (t, b, -h / 2, -h / 2 + t),
                (b - t, b, h / 2 - c, h / 2 - t), (b - t, b, -h / 2 + t, -h / 2 + c)]
    raise ValueError(f"No rectangle model for shape '{shape}'")


def rect_props(rects) -> dict:
    """Area, centroid (yc, zc) and centroidal second moments of a set of non-overlapping rectangles.
    Iyy = about the axis along y (bending in the depth direction), Izz = about the axis along z, Iyz = product."""
    A = sum((y1 - y0) * (z1 - z0) for y0, y1, z0, z1 in rects)
    yc = sum((y1 - y0) * (z1 - z0) * (y0 + y1) / 2 for y0, y1, z0, z1 in rects) / A
    zc = sum((y1 - y0) * (z1 - z0) * (z0 + z1) / 2 for y0, y1, z0, z1 in rects) / A
    Iyy = Izz = Iyz = 0.0
    for y0, y1, z0, z1 in rects:
        w, d = y1 - y0, z1 - z0
        dy, dz = (y0 + y1) / 2 - yc, (z0 + z1) / 2 - zc
        Iyy += w * d ** 3 / 12 + w * d * dz ** 2
        Izz += d * w ** 3 / 12 + w * d * dy ** 2
        Iyz += w * d * dy * dz
    return {"A": A, "yc": yc, "zc": zc, "Iyy": Iyy, "Izz": Izz, "Iyz": Iyz}


def plastic_modulus(rects, axis: str) -> float:
    """Plastic modulus of rectangles for bending about a line along y (axis 'y') or along z (axis 'z')."""
    k = (2, 3) if axis == "y" else (0, 1)
    A = sum((r[1] - r[0]) * (r[3] - r[2]) for r in rects)

    def above(c):
        return sum((r[1] - r[0]) * (r[3] - r[2]) * max(0.0, min(1.0, (r[k[1]] - c) / (r[k[1]] - r[k[0]]))) for r in rects)

    lo, hi = min(r[k[0]] for r in rects), max(r[k[1]] for r in rects)
    for _ in range(80):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if above(mid) > A / 2 else (lo, mid)
    c = (lo + hi) / 2
    Z = 0.0
    for r in rects:
        other = (r[1] - r[0]) if axis == "y" else (r[3] - r[2])
        a0, a1 = r[k[0]], r[k[1]]
        for s0, s1 in ((a0, min(a1, c)), (max(a0, c), a1)):
            if s1 > s0:
                Z += other * (s1 - s0) * abs((s0 + s1) / 2 - c)
    return Z


def open_shape_props(sec: dict) -> dict:
    """Channel / angle / lip channel from their dimensions, in the model axes (y = major, z = minor): extra keys
    xc (centroid from the web back or the heel), c_y and c_z (extreme fibre distances for Sy and Sz)."""
    shape = sec["shape"]
    rects = shape_rects(sec)
    rp = rect_props(rects)
    if shape == "angle":
        b, t = float(sec["b"]), float(sec["t"])
        c = rp["yc"]
        Iu = rp["Iyy"] + abs(rp["Iyz"])          # major principal axis: the axis of symmetry (through the heel)
        Iv = rp["Iyy"] - abs(rp["Iyz"])
        cu, cv = b / math.sqrt(2), max(math.sqrt(2) * c, (b + t) / math.sqrt(2) - math.sqrt(2) * c)
        J = (2 * b - t) * t ** 3 / 3
        return {"A": rp["A"], "Iy": Iu, "Iz": Iv, "J": J, "Sy": Iu / cu, "Sz": Iv / cv, "b": b, "h": b, "xc": c,
                "c_y": cu, "c_z": cv}
    h, b = float(sec["h"]), float(sec["b"])
    if shape == "channel":
        tw, tf = float(sec["tw"]), float(sec["tf"])
        J = (2 * (b - tw / 2) * tf ** 3 + (h - tf) * tw ** 3) / 3
    else:
        t = float(sec["t"])
        J = sum(max(r[1] - r[0], r[3] - r[2]) * t ** 3 for r in rects) / 3
    xc = rp["yc"]
    return {"A": rp["A"], "Iy": rp["Iyy"], "Iz": rp["Izz"], "J": J, "Sy": rp["Iyy"] / (h / 2),
            "Sz": rp["Izz"] / (b - xc), "b": b, "h": h, "xc": xc, "c_y": h / 2, "c_z": b - xc}


def section_properties(sec: dict) -> SectionProps:
    """Properties of a section. A size picked from the supplier tables (``catalog`` set and the dimensions unchanged)
    uses the table's A, I and elastic moduli (they include the fillets); J is always calculated from the dimensions."""
    p = _section_properties(sec)
    t = table_props(sec)
    if t:
        p = SectionProps(t["A"], t["Iy"], t["Iz"], p.J, t["Sy"], t["Sz"], p.b, p.h)
    return p


def _section_properties(sec: dict) -> SectionProps:
    """Compute properties for a section definition.

    Supported shapes (dimensions in metres):
      * ``rect``:    b, h
      * ``I``:       h (overall depth), bf (flange width), tf, tw  (doubly symmetric)
      * ``circle``:  d (solid)
      * ``pipe``:    d (outside diameter), t (wall)      - circular hollow section (CHS)
      * ``box``:     b, h, t (wall)                      - rectangular hollow section (RHS/SHS)
      * ``channel``: h, b (flange width), tw, tf         - hot-rolled channel (C)
      * ``angle``:   b (leg), t                          - equal-leg angle (L), in its principal axes: Iy = Iu
                     (major, about the axis of symmetry), Iz = Iv (minor)
      * ``lipchannel``: h, b, c (lip), t                 - cold-formed lip channel (LC)
      * ``general``: A, Iy, Iz, J, b, h given directly
    """
    shape = sec.get("shape", "rect")
    if shape == "rect":
        b, h = float(sec["b"]), float(sec["h"])
        A = b * h
        Iy = b * h**3 / 12.0
        Iz = h * b**3 / 12.0
        J = rect_torsion_constant(b, h)
        return SectionProps(A, Iy, Iz, J, Iy / (h / 2), Iz / (b / 2), b, h)
    if shape == "I":
        h, bf, tf, tw = (float(sec[k]) for k in ("h", "bf", "tf", "tw"))
        hw = h - 2 * tf
        A = 2 * bf * tf + hw * tw
        Iy = (bf * h**3 - (bf - tw) * hw**3) / 12.0
        Iz = 2 * tf * bf**3 / 12.0 + hw * tw**3 / 12.0
        J = (2 * bf * tf**3 + (h - tf) * tw**3) / 3.0
        return SectionProps(A, Iy, Iz, J, Iy / (h / 2), Iz / (bf / 2), bf, h)
    if shape == "circle":
        d = float(sec["d"])
        A = math.pi * d**2 / 4
        I = math.pi * d**4 / 64
        return SectionProps(A, I, I, 2 * I, I / (d / 2), I / (d / 2), d, d)
    if shape == "pipe":
        d, t = float(sec["d"]), float(sec["t"])
        di = d - 2 * t
        if di < 0:
            raise ValueError("Pipe wall thickness larger than radius")
        A = math.pi * (d**2 - di**2) / 4
        I = math.pi * (d**4 - di**4) / 64
        return SectionProps(A, I, I, 2 * I, I / (d / 2), I / (d / 2), d, d)
    if shape == "box":
        b, h, t = float(sec["b"]), float(sec["h"]), float(sec["t"])
        bi, hi = b - 2 * t, h - 2 * t
        if bi < 0 or hi < 0:
            raise ValueError("Box wall thickness too large")
        A = b * h - bi * hi
        Iy = (b * h**3 - bi * hi**3) / 12.0
        Iz = (h * b**3 - hi * bi**3) / 12.0
        # thin-walled closed section (Bredt): J = 4 Am^2 t / perimeter (mid-line)
        bm, hm = b - t, h - t
        J = 4 * (bm * hm) ** 2 * t / (2 * (bm + hm))
        return SectionProps(A, Iy, Iz, J, Iy / (h / 2), Iz / (b / 2), b, h)
    if shape in ("channel", "angle", "lipchannel"):
        o = open_shape_props(sec)
        return SectionProps(o["A"], o["Iy"], o["Iz"], o["J"], o["Sy"], o["Sz"], o["b"], o["h"])
    if shape == "general":
        b, h = float(sec.get("b", 0.3)), float(sec.get("h", 0.3))
        Iy, Iz = float(sec["Iy"]), float(sec["Iz"])
        return SectionProps(float(sec["A"]), Iy, Iz, float(sec["J"]), Iy / (h / 2), Iz / (b / 2), b, h)
    raise ValueError(f"Unknown section shape '{shape}'")


def material_props(mat: dict) -> dict:
    """Return material constants in internal units (kN, m)."""
    E = float(mat["E"]) * MPA_TO_KN_M2
    nu = float(mat.get("nu", 0.2))
    G = float(mat["G"]) * MPA_TO_KN_M2 if "G" in mat else E / (2 * (1 + nu))
    return {"E": E, "G": G, "density": float(mat.get("density", 0.0))}
