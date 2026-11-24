"""Standard hot-rolled and hollow steel section sizes, by nominal dimensions.

H sections: TIS 1227 / JIS G 3192 (h x b x tw x tf, mm). SHS / RHS: JIS G 3466 (h x b x t, mm).
CHS: JIS G 3444 (d x t, mm). Only the nominal dimensions are listed. Area, inertia and moduli are calculated
from them by structural.sections, without root or corner radii, so they come out slightly below the
manufacturers' tables (conservative). Check availability with the supplier.
"""
from __future__ import annotations

from .sections import section_properties

H = [  # narrow flange (beams)
    (100, 50, 5, 7), (125, 60, 6, 8), (150, 75, 5, 7), (175, 90, 5, 8), (200, 100, 5.5, 8), (250, 125, 6, 9),
    (300, 150, 6.5, 9), (350, 175, 7, 11), (400, 200, 8, 13), (450, 200, 9, 14), (500, 200, 10, 16),
    (600, 200, 11, 17), (700, 300, 13, 24), (800, 300, 14, 26), (900, 300, 16, 28),
    # medium flange
    (148, 100, 6, 9), (194, 150, 6, 9), (244, 175, 7, 11), (294, 200, 8, 12), (340, 250, 9, 14), (390, 300, 10, 16),
    (440, 300, 11, 18), (488, 300, 11, 18), (588, 300, 12, 20),
    # wide flange (columns)
    (100, 100, 6, 8), (125, 125, 6.5, 9), (150, 150, 7, 10), (175, 175, 7.5, 11), (200, 200, 8, 12),
    (250, 250, 9, 14), (300, 300, 10, 15), (350, 350, 12, 19), (400, 400, 13, 21),
]
SHS = [
    (50, 2.3), (50, 3.2), (60, 2.3), (60, 3.2), (75, 2.3), (75, 3.2), (75, 4.5), (100, 2.3), (100, 3.2), (100, 4.5),
    (100, 6.0), (125, 3.2), (125, 4.5), (125, 6.0), (150, 4.5), (150, 6.0), (150, 9.0), (175, 6.0), (200, 6.0),
    (200, 9.0), (200, 12.0), (250, 6.0), (250, 9.0), (250, 12.0), (300, 9.0), (300, 12.0),
]
RHS = [  # h x b x t, h along the strong axis
    (75, 45, 2.3), (100, 50, 2.3), (100, 50, 3.2), (100, 50, 4.5), (125, 75, 3.2), (125, 75, 4.5), (150, 100, 3.2),
    (150, 100, 4.5), (150, 100, 6.0), (200, 100, 4.5), (200, 100, 6.0), (250, 150, 6.0), (250, 150, 9.0),
    (300, 200, 9.0), (300, 200, 12.0),
]
CHS = [
    (34.0, 2.3), (42.7, 2.3), (48.6, 2.3), (48.6, 3.2), (60.5, 2.3), (60.5, 3.2), (76.3, 2.8), (76.3, 3.2),
    (76.3, 4.0), (89.1, 2.8), (89.1, 3.2), (89.1, 4.0), (101.6, 3.2), (101.6, 4.0), (114.3, 3.2), (114.3, 4.5),
    (114.3, 6.0), (139.8, 4.0), (139.8, 4.5), (139.8, 6.0), (165.2, 4.5), (165.2, 5.0), (165.2, 6.0), (165.2, 7.1),
    (190.7, 5.3), (190.7, 6.0), (216.3, 4.5), (216.3, 6.0), (216.3, 8.2), (267.4, 6.0), (267.4, 9.3), (318.5, 6.0),
    (318.5, 9.0),
]

FAMILIES = {
    "H": "H sections (TIS 1227 / JIS G 3192)",
    "SHS": "Square hollow sections (JIS G 3466)",
    "RHS": "Rectangular hollow sections (JIS G 3466)",
    "CHS": "Circular hollow sections (JIS G 3444)",
}
# the families a section of a given shape may change to when "keep the shape" is asked
SHAPE_FAMILIES = {"I": ("H",), "box": ("SHS", "RHS"), "pipe": ("CHS",)}


def _g(v):
    return f"{v:g}"


def _entries():
    out = []
    for h, b, tw, tf in H:
        out.append({"family": "H", "name": f"H {_g(h)}x{_g(b)}x{_g(tw)}x{_g(tf)}", "shape": "I", "fab": "rolled",
                    "h": h / 1000, "bf": b / 1000, "tw": tw / 1000, "tf": tf / 1000})
    for a, t in SHS:
        out.append({"family": "SHS", "name": f"SHS {_g(a)}x{_g(a)}x{_g(t)}", "shape": "box", "fab": "cold",
                    "h": a / 1000, "b": a / 1000, "t": t / 1000})
    for h, b, t in RHS:
        out.append({"family": "RHS", "name": f"RHS {_g(h)}x{_g(b)}x{_g(t)}", "shape": "box", "fab": "cold",
                    "h": h / 1000, "b": b / 1000, "t": t / 1000})
    for d, t in CHS:
        out.append({"family": "CHS", "name": f"CHS {_g(d)}x{_g(t)}", "shape": "pipe", "fab": "cold",
                    "d": d / 1000, "t": t / 1000})
    for e in out:
        e["A"] = section_properties(e).A
        e["mass"] = e["A"] * 7850.0                    # kg/m, from the nominal area
    return sorted(out, key=lambda e: (e["family"], e["A"]))


CATALOG = _entries()


def family(name: str) -> list[dict]:
    """Sections of one family, lightest first."""
    if name not in FAMILIES:
        raise ValueError(f"Unknown section family '{name}'. Available: {', '.join(FAMILIES)}")
    return [e for e in CATALOG if e["family"] == name]


def as_section(entry: dict, material: str) -> dict:
    """A model section from a catalogue entry."""
    keys = ("shape", "fab", "h", "bf", "tw", "tf", "b", "t", "d")
    return {**{k: entry[k] for k in keys if k in entry}, "material": material, "name": f"{entry['name']} {material}",
            "catalog": entry["name"]}


__all__ = ["CATALOG", "FAMILIES", "SHAPE_FAMILIES", "family", "as_section"]
