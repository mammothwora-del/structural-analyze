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


def section_properties(sec: dict) -> SectionProps:
    """Compute properties for a section definition.

    Supported shapes (dimensions in metres):
      * ``rect``:    b, h
      * ``I``:       h (overall depth), bf (flange width), tf, tw  (doubly symmetric)
      * ``circle``:  d
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
