"""Supplier steel tables, the channel / angle / lip channel shapes and their AISC (EIT) checks."""
import math

import numpy as np
import pytest

from structural import steel_tables as T
from structural.sections import MATERIALS, _section_properties, open_shape_props, rect_props, section_properties, shape_rects
from structural.steel_catalog import ANALYSIS_ONLY, CATALOG, as_section, family
from structural.steel_design import (Forces, NotCovered, Params, aisc_compression, aisc_flexure, check_member, geometry,
                                     steel_design)
from structural.steel_sizing import suggest_sections
from structural.structures import generate_truss2d

E, G, FY = 200e6, 200e6 / 2.6, 245e3          # kN/m2 (SS400)

# how far the table may be from the plain plate model (fillets, corner radii, sloped flanges of I-beams and channels)
TOL = {"H": (0.06, 0.07, 0.05), "I": (0.05, 0.05, 0.30), "C": (0.04, 0.04, 0.25), "L": (0.04, 0.07, 0.07),
       "LC": (0.10, 0.10, 0.20), "SHS": (0.15, 0.30, 0.30), "RHS": (0.15, 0.30, 0.30), "CHS": (0.01, 0.01, 0.01)}


def _cat(name):
    return next(e for e in CATALOG if e["name"] == name)


def _sec(e):
    return {"shape": e["shape"], **e["dims"]}


def test_every_row_agrees_with_its_dimensions():
    """Catches misprints (a digit off gives tens of %), not the small effect of fillets and corner radii."""
    assert len(T.TABLE) == len(T.H) + len(T.I) + len(T.C) + len(T.L) + len(T.LC) + len(T.SHS) + len(T.RHS) + len(T.CHS) == 293
    for name, e in T.TABLE.items():
        p = _section_properties(_sec(e))
        ta, ti, tz = TOL[e["family"]]
        assert p.A == pytest.approx(e["A"], rel=ta), name
        assert p.Iy == pytest.approx(e["Iy"], rel=ti), name
        assert p.Iz == pytest.approx(e["Iz"], rel=tz), name
        assert e["Iy"] >= e["Iz"] * 0.999, name
        if e["family"] == "L":
            continue
        # the printed elastic moduli agree with the printed inertia
        h = e["dims"].get("h", e["dims"].get("d"))
        b = e["dims"].get("bf", e["dims"].get("b", h))
        cz = b - e["xc"] if "xc" in e else b / 2
        assert e["Sy"] == pytest.approx(e["Iy"] / (h / 2), rel=0.035), name
        assert e["Sz"] == pytest.approx(e["Iz"] / cz, rel=0.035), name


def test_angle_rows():
    for b, t, r1, r2, A, W, c, Ix, Iu, Iv, Zx in T.L:
        assert Iu + Iv == pytest.approx(2 * Ix, rel=0.01)
        assert Zx == pytest.approx(Ix / (b / 10 - c), rel=0.03)
        assert W == pytest.approx(A * 0.785, rel=0.02)


def test_corrected_misprints():
    t = T.TABLE
    assert "H 434x299x10x15" in t and "H 434x299x10x17" not in t
    assert t["H 350x357x19x19"]["Iz"] == pytest.approx(14400e-8)
    assert t["C 180x75x7x10.5"]["Sy"] == pytest.approx(153e-6)
    assert t["C 380x100x10.5x16"]["A"] == pytest.approx(69.43e-4)


def test_table_properties_are_used_only_while_the_dimensions_are_the_tables():
    e = T.TABLE["H 400x200x8x13"]
    sec = {"shape": "I", "h": 0.4, "bf": 0.2, "tw": 0.008, "tf": 0.013, "catalog": "H 400x200x8x13", "material": "SS400"}
    p = section_properties(sec)
    assert (p.A, p.Iy, p.Iz, p.Sy, p.Sz) == (e["A"], e["Iy"], e["Iz"], e["Sy"], e["Sz"])
    assert p.J == pytest.approx(_section_properties(sec).J)          # J from the dimensions
    edited = {**sec, "tf": 0.016}                                    # the user changed a dimension: plate model again
    assert section_properties(edited).A == pytest.approx(_section_properties(edited).A)
    assert section_properties({**sec, "catalog": "H 999"}).A == pytest.approx(_section_properties(sec).A)
    # plastic moduli scaled by S_table / S_dims, so the shape factor of the plate model is kept
    g, gd = geometry(sec), geometry({k: v for k, v in sec.items() if k != "catalog"})
    assert g.Zy / g.Sy == pytest.approx(gd.Zy / gd.Sy)


def test_angle_principal_axes():
    sec = {"shape": "angle", "b": 0.1, "t": 0.01}
    rp = rect_props(shape_rects(sec))
    o = open_shape_props(sec)
    # centroid of two plates: (100*10*50 + 90*10*5) / 1900 = 28.68 mm
    assert o["xc"] == pytest.approx((100 * 10 * 50 + 90 * 10 * 5) / 1900 * 1e-3)
    assert rp["Iyy"] == pytest.approx(rp["Izz"])                     # equal legs: Ix = Iy
    assert o["Iy"] + o["Iz"] == pytest.approx(2 * rp["Iyy"])
    assert o["Iy"] > rp["Iyy"] > o["Iz"]
    # Ix by hand: 100x10 leg about its own centroid shifted by (28.68 - 5), 10x90 leg by (55 - 28.68)
    c = o["xc"] * 1000
    Ix = 100 * 10 ** 3 / 12 + 1000 * (c - 5) ** 2 + 10 * 90 ** 3 / 12 + 900 * (55 - c) ** 2
    assert rp["Iyy"] == pytest.approx(Ix * 1e-12)
    # the table (with root and toe radii) is within a few %
    e = T.TABLE["L 100x100x10"]
    assert o["Iy"] == pytest.approx(e["Iy"], rel=0.04) and o["Iz"] == pytest.approx(e["Iz"], rel=0.03)
    # Su to the leg tips b/sqrt(2); Sv to the farther of the heel and the tips along the axis of symmetry
    assert e["Sy"] == pytest.approx(e["Iy"] / (0.1 / math.sqrt(2)))


def _forces(N=0.0, My=0.0, Mz=0.0, L=3.0):
    x = np.linspace(0, L, 9)
    z = np.zeros_like(x)
    return [("c", Forces(x, N + z, z, z, z, My + z, Mz + z))]


def test_channel_compression_by_hand():
    """C 150x75x6.5x10, SS400, L = 1.5 m: flexural-torsional buckling (E4) by hand."""
    sec = as_section(_cat("C 150x75x6.5x10"), "SS400")
    g = geometry(sec)
    L = 1.5
    A, Ix, Iy = 23.71e-4, 861e-8, 117e-8                               # table (Ix major, Iy minor)
    assert (g.A, g.Iy, g.Iz) == pytest.approx((A, Ix, Iy))
    b, h, tw, tf = 0.075, 0.150, 0.0065, 0.010
    bp, hp = b - tw / 2, h - tf
    e = 3 * bp ** 2 * tf / (6 * bp * tf + hp * tw)
    x0 = 0.0228 - tw / 2 + e                                           # table Cy = 2.28 cm
    Cw = tf * bp ** 3 * hp ** 2 / 12 * (3 * bp * tf + 2 * hp * tw) / (6 * bp * tf + hp * tw)
    J = (2 * bp * tf ** 3 + hp * tw ** 3) / 3
    assert (g.x0, g.Cw, g.J) == pytest.approx((x0, Cw, J))
    ro2 = x0 ** 2 + (Ix + Iy) / A
    H = 1 - x0 ** 2 / ro2
    Fex = math.pi ** 2 * E / (L / math.sqrt(Ix / A)) ** 2
    Fey = math.pi ** 2 * E / (L / math.sqrt(Iy / A)) ** 2
    Fez = (math.pi ** 2 * E * Cw / L ** 2 + G * J) / (A * ro2)
    Fft = (Fex + Fez) / (2 * H) * (1 - math.sqrt(1 - 4 * Fex * Fez * H / (Fex + Fez) ** 2))
    Fe = min(Fey, Fft)
    Fcr = 0.658 ** (FY / Fe) * FY
    # flange b/t = 7.5 and web (150 - 20) / 6.5 = 20 are not slender (12.8 and 42.6): Ae = A
    c = aisc_compression(g, FY, E, G, Params(L=L))
    assert c["Fe"] == pytest.approx(Fe) and c["phiPn"] == pytest.approx(0.9 * Fcr * A) and not c["slender"]
    assert ("flexural-torsional" in c["mode"]) == (Fft < Fey)


def test_channel_bending_by_hand():
    """C 200x80x7.5x11: compact (b/t = 7.3 <= 0.38 sqrt(E/Fy) = 10.9). F2 with c = (h0/2) sqrt(Iy/Cw)."""
    sec = as_section(_cat("C 200x80x7.5x11"), "SS400")
    g = geometry(sec)
    rE = math.sqrt(E / FY)
    Lb = 2.5
    ho = 0.2 - 0.011
    rts = math.sqrt(math.sqrt(g.Iz * g.Cw) / g.Sy)
    Lp = 1.76 * g.rz * rE
    c = ho / 2 * math.sqrt(g.Iz / g.Cw)
    jc = g.J * c / (g.Sy * ho)
    Lr = 1.95 * rts * E / (0.7 * FY) * math.sqrt(jc + math.sqrt(jc ** 2 + 6.76 * (0.7 * FY / E) ** 2))
    Mp = FY * g.Zy
    assert Lp < Lb < Lr
    Mn = min(Mp - (Mp - 0.7 * FY * g.Sy) * (Lb - Lp) / (Lr - Lp), Mp)
    f = aisc_flexure(g, FY, E, "y", Params(L=Lb), 1.0)
    assert f["phiMn"] == pytest.approx(0.9 * Mn) and f["clause"] == "F2"
    # plastic modulus of the plate model: flanges 80x11 at +-94.5 mm, web 7.5 x 178 -> 2*80*11*94.5 + 7.5*178^2/4
    Zd = 2 * 80 * 11 * 94.5 + 7.5 * 178 ** 2 / 4
    assert g.Zy / (g.Sy / geometry({k: v for k, v in sec.items() if k != "catalog"}).Sy) == pytest.approx(Zd * 1e-9, rel=1e-6)


def test_angle_bending_and_compression_by_hand():
    """L 100x100x10, SS400. F10 about the major principal axis, E3 about the minor one."""
    sec = as_section(_cat("L 100x100x10"), "SS400")
    g = geometry(sec)
    A, Iu, Iv = 19.0e-4, 278e-8, 72e-8
    assert (g.A, g.Iy, g.Iz) == pytest.approx((A, Iu, Iv))
    rz, t, Lb = math.sqrt(Iv / A), 0.01, 3.0
    My = FY * Iu / (0.1 / math.sqrt(2))
    Mcr = 9 * E * A * rz * t * 1.0 / (8 * Lb)
    Mn = min((1.92 - 1.17 * math.sqrt(My / Mcr)) * My, 1.5 * My)        # My / Mcr < 1 here
    assert My / Mcr < 1
    # leg b/t = 10 <= 0.54 sqrt(E/Fy) = 15.4: compact, no leg local buckling
    f = aisc_flexure(g, FY, E, "y", Params(L=Lb), 1.0)
    assert f["phiMn"] == pytest.approx(0.9 * Mn) and f["clause"] == "F10"
    fz = aisc_flexure(g, FY, E, "z", Params(L=Lb), 1.0)
    assert fz["phiMn"] == pytest.approx(0.9 * 1.5 * FY * g.Sz)
    # KL/r = 3 / 0.01947 = 154: elastic buckling about v governs (E3-3); b/t = 10 < 0.45 sqrt(E/Fy) = 12.9
    c = aisc_compression(g, FY, E, G, Params(L=Lb))
    Fe = math.pi ** 2 * E / (Lb / rz) ** 2
    assert c["mode"].startswith("flexural, minor") and c["phiPn"] == pytest.approx(0.9 * 0.877 * Fe * A)


def test_slender_angle_leg_reduces_compression():
    sec = as_section(_cat("L 120x120x8"), "SS400")   # b/t = 15 > 0.45 sqrt(E/Fy) = 12.9
    c = aisc_compression(geometry(sec), FY, E, G, Params(L=0.5))
    assert c["slender"] == ["legs"] and c["Ae"] < geometry(sec).A


def test_codes_and_shapes_not_covered():
    mat = MATERIALS["SS400"]
    ch = as_section(family("C")[3], "SS400")
    r = check_member(ch, mat, Params(L=3.0), _forces(N=-50, My=5), "EIT")
    assert r["checks"] and any("shear centre" in n for n in r["notes"])
    with pytest.raises(NotCovered, match="EN 1993-1-1"):
        check_member(ch, mat, Params(L=3.0), _forces(N=-50), "EC3")
    lc = as_section(family("LC")[10], "SS400")
    with pytest.raises(NotCovered, match="cold-formed"):
        check_member(lc, mat, Params(L=3.0), _forces(N=-5), "AISC360")
    assert ANALYSIS_ONLY == {"LC"}


def test_truss_with_angles_and_lip_channels():
    m = generate_truss2d({"standard": "TH"})
    m["sections"]["WEB"] = as_section(_cat("L 50x50x6"), "SS400")
    m["sections"]["CH"] = as_section(_cat("LC 150x65x20x3.2"), "SS400")
    d = steel_design(m)
    web = [d["members"][e["id"]] for e in m["elements"] if e["section"] == "WEB"]
    cho = [d["members"][e["id"]] for e in m["elements"] if e["section"] == "CH"]
    assert web and all(x["status"] in ("ok", "fail") for x in web)
    assert cho and all(x["status"] == "not_covered" and "cold-formed" in x["reason"] for x in cho)
    # suggest angle sizes for the web members; lip channels cannot be suggested
    r = suggest_sections(m, groups={"WEB": "L", "CH": "H"})
    assert r["sections"]["WEB"]["catalog"].startswith("L ") and r["sections"]["WEB"]["shape"] == "angle"
    rows = {g["section"]: g for g in r["groups"]}
    assert rows["WEB"]["max_util"] <= 1.0
    with pytest.raises(ValueError, match="no design checks"):
        suggest_sections(m, groups={"CH": "LC"})
    # "keep the shape" leaves a lip channel group alone, with a note
    r2 = suggest_sections(m, groups={"WEB": "L"})
    assert r2["sections"]["CH"] == m["sections"]["CH"]
    assert any("CH" in n and "no design-checked standard sizes" in n for n in r2["notes"])
