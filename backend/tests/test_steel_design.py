"""Steel member design checks against hand calculations.

Each expected value is worked out here directly from the code equations (AISC 360-16, EN 1993-1-1 / 1-5) and the
section dimensions, independently of structural.steel_design, plus published table values where they exist.
"""
import math

import pytest
from fastapi.testclient import TestClient

from structural.api import app
from structural.generator import generate
from structural.steel_design import aisc_fcr, design_combinations, ec3_chi, steel_design

E = 200000e3   # kN/m2 (A992, SS400)
E_EU = 210000e3   # S355
FY_A992 = 345e3


def I_section(h, bf, tf, tw, mat):
    return {"shape": "I", "h": h, "bf": bf, "tf": tf, "tw": tw, "material": mat}


def member_model(sec, L, supports, loads, combos, design=None, axis="x"):
    j = {"x": [L, 0, 0], "z": [0, 0, L]}[axis]
    return {"name": "t", "settings": {"standard": "ASCE7"}, "materials": {}, "sections": {"S": sec},
            "nodes": [{"id": "A", "x": 0, "y": 0, "z": 0}, {"id": "B", "x": j[0], "y": j[1], "z": j[2]}],
            "elements": [{"id": "M", "type": "beam" if axis == "x" else "column", "i": "A", "j": "B", "section": "S",
                          **({"design": design} if design else {})}],
            "supports": supports, "load_cases": [{"id": "D", "name": "dead", "type": "dead", "self_weight": False}],
            "loads": [dict(case="D", **ld) for ld in loads], "combinations": combos, "slabs": []}


SIMPLE = [{"node": "A", "dofs": [1, 1, 1, 1, 0, 0]}, {"node": "B", "dofs": [0, 1, 1, 0, 0, 0]}]
PINNED_COL = [{"node": "A", "dofs": [1, 1, 1, 1, 0, 0]}, {"node": "B", "dofs": [1, 1, 0, 0, 0, 0]}]
ULS = [{"id": "U1", "name": "1.4D", "factors": {"D": 1.4}}, {"id": "S1", "name": "D (service)", "factors": {"D": 1.0}}]


def check(r, cid):
    return next(c for c in r["members"]["M"]["checks"] if c["id"] == cid)


# ------------------------------------------------------------------ published / closed-form values
@pytest.mark.parametrize("curve,alpha,chi", [("a", 0.21, 0.6656), ("b", 0.34, 0.5970), ("c", 0.49, 0.5399), ("d", 0.76, 0.4671)])
def test_ec3_buckling_curve_values_at_unit_slenderness(curve, alpha, chi):
    assert ec3_chi(1.0, alpha) == pytest.approx(chi, abs=1e-4)   # EN 1993-1-1 Figure 6.4 / tabulated values
    assert ec3_chi(0.2, alpha) == 1.0


def test_aisc_column_curve_is_continuous():
    Fy = 345e3
    assert aisc_fcr(Fy, Fy / 2.25) == pytest.approx(0.877 * Fy / 2.25, rel=1e-3)   # E3-2 meets E3-3


# ------------------------------------------------------------------ AISC 360-16 beam
H, BF, TF, TW = 0.4, 0.2, 0.013, 0.008
L, W = 6.0, 20.0
ZX = BF * TF * (H - TF) + TW * (H - 2 * TF) ** 2 / 4
SX = (BF * H ** 3 - (BF - TW) * (H - 2 * TF) ** 3) / 12 / (H / 2)
UDL = [{"kind": "dist", "element": "M", "direction": [0, 0, -1], "points": [[0, W], [L, W]]}]


def test_aisc_braced_compact_beam_reaches_the_plastic_moment():
    m = member_model(I_section(H, BF, TF, TW, "A992"), L, SIMPLE, UDL, ULS, design={"Lb": 0.5})
    r = steel_design(m, "AISC360")
    assert r["combinations"] == ["U1"]                       # the service combination is not a design combination
    Mu = 1.4 * W * L ** 2 / 8
    c = check(r, "flexure_y")
    assert abs(c["demand"]) == pytest.approx(Mu, rel=1e-4)
    assert c["capacity"] == pytest.approx(0.9 * FY_A992 * ZX, rel=1e-9)   # F2-1 with Lb < Lp
    v = check(r, "shear_z")                                  # G2.1(a): h/tw = 46.8 < 2.24 sqrt(E/Fy) -> phi = 1.0
    assert abs(v["demand"]) == pytest.approx(1.4 * W * L / 2, rel=1e-4)
    assert v["capacity"] == pytest.approx(0.6 * FY_A992 * H * TW, rel=1e-9)
    assert r["members"]["M"]["status"] == "ok"


@pytest.mark.parametrize("Lb", [4.0, 8.0])
def test_aisc_lateral_torsional_buckling_of_an_unbraced_beam(Lb):
    udl = [{"kind": "dist", "element": "M", "direction": [0, 0, -1], "points": [[0, W], [Lb, W]]}]
    m = member_model(I_section(H, BF, TF, TW, "A992"), Lb, SIMPLE, udl, ULS)
    c = check(steel_design(m, "AISC360"), "flexure_y")
    Fy, rE = FY_A992, math.sqrt(E / FY_A992)
    Iz = 2 * TF * BF ** 3 / 12 + (H - 2 * TF) * TW ** 3 / 12
    A = 2 * BF * TF + (H - 2 * TF) * TW
    J = (2 * BF * TF ** 3 + (H - TF) * TW ** 3) / 3
    ho = H - TF
    Cw = Iz * ho ** 2 / 4 - (H - 2 * TF) * TW ** 3 / 12 * ho ** 2 / 4    # flanges only: Iz_flanges h0^2 / 4
    rts = math.sqrt(math.sqrt(Iz * Cw) / SX)
    Lp = 1.76 * math.sqrt(Iz / A) * rE
    jc = J / (SX * ho)
    Lr = 1.95 * rts * E / (0.7 * Fy) * math.sqrt(jc + math.sqrt(jc ** 2 + 6.76 * (0.7 * Fy / E) ** 2))
    Cb = 12.5 / (2.5 + 3 * 0.75 + 4 + 3 * 0.75)              # uniform load, Cb = 1.136
    Mp = Fy * ZX
    if Lb <= Lr:
        assert Lp < Lb                                        # inelastic LTB, F2-2
        Mn = min(Cb * (Mp - (Mp - 0.7 * Fy * SX) * (Lb - Lp) / (Lr - Lp)), Mp)
    else:                                                     # elastic LTB, F2-3 / F2-4
        Fcr = Cb * math.pi ** 2 * E / (Lb / rts) ** 2 * math.sqrt(1 + 0.078 * jc * (Lb / rts) ** 2)
        Mn = min(Fcr * SX, Mp)
    assert c["detail"]["Cb"] == pytest.approx(Cb, rel=2e-3)   # from the computed moment diagram
    assert c["capacity"] == pytest.approx(0.9 * Mn, rel=2e-3)


# ------------------------------------------------------------------ AISC 360-16 column and tie
def test_aisc_pinned_column_flexural_buckling():
    tw, Lc, P = 0.012, 4.0, 500.0                            # web h/tw = 31 < 1.49 sqrt(E/Fy): not slender
    m = member_model(I_section(H, BF, TF, tw, "A992"), Lc, PINNED_COL,
                     [{"kind": "nodal", "node": "B", "values": [0, 0, -P, 0, 0, 0]}], ULS, axis="z")
    r = steel_design(m, "AISC360")
    A = 2 * BF * TF + (H - 2 * TF) * tw
    Iz = 2 * TF * BF ** 3 / 12 + (H - 2 * TF) * tw ** 3 / 12
    Fe = math.pi ** 2 * E / (Lc / math.sqrt(Iz / A)) ** 2
    Fcr = 0.658 ** (FY_A992 / Fe) * FY_A992
    c = check(r, "compression")
    assert c["demand"] == pytest.approx(1.4 * P, rel=1e-6)
    assert c["capacity"] == pytest.approx(0.9 * Fcr * A, rel=1e-6)
    h1 = check(r, "interaction")                             # pure compression, Pr/Pc >= 0.2: H1-1a
    assert h1["ratio"] == pytest.approx(1.4 * P / (0.9 * Fcr * A), rel=1e-4)


def test_aisc_and_thai_eit_tension_member():
    sec = {"shape": "pipe", "d": 0.1143, "t": 0.006, "material": "SS400"}
    T = 150.0
    m = member_model(sec, 3.0, PINNED_COL, [{"kind": "nodal", "node": "B", "values": [0, 0, T, 0, 0, 0]}], ULS, axis="z")
    A = math.pi * (0.1143 ** 2 - (0.1143 - 0.012) ** 2) / 4
    for code in ("AISC360", "EIT"):
        r = steel_design(m, code)
        c = check(r, "tension")
        assert c["capacity"] == pytest.approx(0.9 * 245e3 * A, rel=1e-9)
        assert c["ratio"] == pytest.approx(1.4 * T / (0.9 * 245e3 * A), rel=1e-5)
    assert steel_design(m, "EIT")["members"]["M"]["util"] == steel_design(m, "AISC360")["members"]["M"]["util"]


# ------------------------------------------------------------------ EN 1993-1-1
def test_ec3_pinned_column_buckling_curve_b():
    tw, Lc, P = 0.012, 4.0, 500.0
    m = member_model(I_section(H, BF, TF, tw, "S355"), Lc, PINNED_COL,
                     [{"kind": "nodal", "node": "B", "values": [0, 0, -P, 0, 0, 0]}], ULS, axis="z")
    r = steel_design(m, "EC3")
    fy = 355e3
    A = 2 * BF * TF + (H - 2 * TF) * tw
    Iz = 2 * TF * BF ** 3 / 12 + (H - 2 * TF) * tw ** 3 / 12
    lam = math.sqrt(A * fy / (math.pi ** 2 * E_EU * Iz / Lc ** 2))
    phi = 0.5 * (1 + 0.34 * (lam - 0.2) + lam ** 2)          # rolled I, h/b = 2 > 1.2, tf < 40 mm: z-z curve b
    chi = 1 / (phi + math.sqrt(phi ** 2 - lam ** 2))
    c = check(r, "buckling")
    assert c["detail"]["curves"] == "a/b"
    assert c["capacity"] == pytest.approx(chi * A * fy, rel=1e-6)
    assert r["members"]["M"]["props"]["class"] == 3          # web c/t = 31.2: 30.9 eps < c/t <= 34.2 eps


def test_ec3_class4_box_uses_the_effective_area():
    sec = {"shape": "box", "b": 0.3, "h": 0.3, "t": 0.005, "material": "S355"}
    m = member_model(sec, 2.0, PINNED_COL, [{"kind": "nodal", "node": "B", "values": [0, 0, -300.0, 0, 0, 0]}], ULS, axis="z")
    r = steel_design(m, "EC3")
    eps = math.sqrt(235 / 355)
    c = 0.3 - 0.015
    lam_p = (c / 0.005) / (28.4 * eps * 2)                  # EN 1993-1-5 4.4, internal part, k_sigma = 4
    rho = (lam_p - 0.22) / lam_p ** 2
    A = 0.3 ** 2 - 0.29 ** 2
    Aeff = A - 4 * (1 - rho) * c * 0.005
    assert r["members"]["M"]["props"]["class"] == 4
    assert check(r, "compression")["capacity"] == pytest.approx(Aeff * 355e3, rel=1e-9)


def test_ec3_braced_beam_plastic_moment_and_shear():
    m = member_model(I_section(H, BF, TF, TW, "S355"), L, SIMPLE, UDL, ULS, design={"Lb": 0.5})
    r = steel_design(m, "EC3")
    assert check(r, "bending_y")["capacity"] == pytest.approx(ZX * 355e3, rel=1e-9)   # class 1/2: W_pl fy
    Av = max(2 * BF * TF + (H - 2 * TF) * TW - 2 * BF * TF + TW * TF, (H - 2 * TF) * TW)
    assert check(r, "shear_z")["capacity"] == pytest.approx(Av * 355e3 / math.sqrt(3), rel=1e-9)
    assert check(r, "ltb")["detail"]["chi_LT"] == 1.0         # short unbraced length: no LTB reduction


def test_slender_tube_is_reported_not_covered():
    sec = {"shape": "pipe", "d": 0.5, "t": 0.004, "material": "S355"}    # d/t = 125 > 90 eps^2: class 4 CHS
    m = member_model(sec, 3.0, PINNED_COL, [{"kind": "nodal", "node": "B", "values": [0, 0, -100.0, 0, 0, 0]}], ULS, axis="z")
    mem = steel_design(m, "EC3")["members"]["M"]
    assert mem["status"] == "not_covered" and mem["util"] is None and "1993-1-6" in mem["reason"]


# ------------------------------------------------------------------ driver
def test_service_combinations_are_excluded():
    m = generate({"type": "warehouse"})
    ids, _ = zip(*design_combinations(m)[0])
    assert "SLS1" not in ids and "ULS2" in ids


def test_concrete_members_are_skipped():
    r = steel_design(generate({}))
    assert r["summary"]["skipped"] == len(generate({})["elements"]) and r["summary"]["n_checked"] == 0


@pytest.mark.parametrize("params", [{"type": "warehouse"}, {"type": "warehouse", "roof": "portal", "standard": "ASCE7"},
                                    {"type": "truss2d", "standard": "TH"}, {"type": "space_truss"}, {"type": "lattice_roof"}])
def test_every_steel_generator_is_checked(params):
    m = generate(params)
    r = steel_design(m)
    assert r["code"] == {"ASCE7": "AISC360", "TH": "EIT"}.get(params.get("standard"), "EC3")
    for mem in r["members"].values():
        assert mem["status"] in ("ok", "fail", "not_covered")
        if mem["status"] != "not_covered":
            assert mem["util"] == pytest.approx(mem["checks"][0]["ratio"]) and mem["checks"][0]["combo"] in r["combinations"]


def test_api_endpoint():
    c = TestClient(app)
    m = c.post("/api/generate", json={"type": "truss2d"}).json()
    r = c.post("/api/design/steel", json={"model": m, "code": "AISC360"})
    assert r.status_code == 200 and r.json()["code"] == "AISC360"
    assert c.post("/api/design/steel", json={"model": m, "code": "banana"}).status_code == 400
