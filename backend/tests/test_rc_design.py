"""RC design to EIT 1008-38 (ACI 318-95 strength design) against hand calculations in kgf, cm, ksc."""
import math

import pytest
from fastapi.testclient import TestClient

from structural.api import app
from structural.generator import generate
from structural.rc_design import (BARS, Interaction, as_required, beam_capacity, beta1, magnifier, rc_design,
                                  rho_balanced, rho_min, section_forces)

KGF = 101.971621


def test_material_constants():
    assert beta1(240) == 0.85 and beta1(280) == 0.85
    assert beta1(350) == pytest.approx(0.80) and beta1(700) == 0.65
    assert rho_balanced(240, 4000) == pytest.approx(0.0262, abs=5e-5)    # tabulated value for fc' 240 ksc, SD40
    assert rho_min(240, 4000) == pytest.approx(14 / 4000)


def test_singly_reinforced_section():
    b, d, fc, fy, Mu = 30.0, 54.1, 240.0, 4000.0, 2.0e6                  # Mu = 20 t·m
    Rn = Mu / (0.9 * b * d ** 2)
    rho = 0.85 * fc / fy * (1 - math.sqrt(1 - 2 * Rn / (0.85 * fc)))
    assert as_required(Mu, b, d, fc, fy) == pytest.approx(rho * b * d, rel=1e-12)
    As = 4 * BARS["DB20"][1]
    a = As * fy / (0.85 * fc * b)
    phiMn, c, _ = beam_capacity(b, 60.0, [(d, As)], [], fc, fy)
    assert phiMn == pytest.approx(0.9 * As * fy * (d - a / 2), rel=1e-6)
    assert c == pytest.approx(a / 0.85, rel=1e-6)


def test_strain_compatibility_point():
    # 40 x 40 cm, 3-DB20 at 6 cm and at 34 cm from the compression face, fc' 240, SD40, c = 15 cm
    As = 3 * BARS["DB20"][1]
    P, M, _ = section_forces(15.0, 40.0, 40.0, [(6.0, As), (34.0, As)], 240.0, 4000.0)
    a = 0.85 * 15
    Cc = 0.85 * 240 * a * 40
    fs_top = min(2.04e6 * 0.003 * (15 - 6) / 15, 4000) - 0.85 * 240
    fs_bot = -4000.0
    assert P == pytest.approx(Cc + As * (fs_top + fs_bot), rel=1e-9)
    assert M == pytest.approx(Cc * (20 - a / 2) + As * fs_top * (20 - 6) + As * fs_bot * (20 - 34), rel=1e-9)


def test_column_axial_limit_and_phi():
    As = BARS["DB16"][1]
    coords = [-14.0, -14.0, -14.0, 0.0, 0.0, 14.0, 14.0, 14.0]
    it = Interaction(40.0, 40.0, coords, As, 240.0, 4000.0)
    Ast = 8 * As
    assert it.Pmax == pytest.approx(0.7 * 0.8 * (0.85 * 240 * (1600 - Ast) + 4000 * Ast), rel=1e-12)
    assert it.phi(-1.0) == 0.9 and it.phi(1e7) == 0.7
    assert it.moment_at(it.Pmax * 1.01) is None
    m0, m1 = it.moment_at(0.0), it.moment_at(0.3 * it.Pmax)
    assert m1 > m0 > 0                                                    # moment capacity grows with compression below balance


def test_nonsway_magnifier():
    Pu, Lu, r, EI = 100e3, 400.0, 12.0, 4e10
    d, sl, lim, Pc = magnifier(Pu, M1=0.5, M2=1.0, Lu=Lu, r=r, k=1.0, EI=EI)
    assert sl == pytest.approx(Lu / r) and lim == pytest.approx(28.0)
    assert Pc == pytest.approx(math.pi ** 2 * EI / Lu ** 2)
    assert d == pytest.approx(max((0.6 + 0.4 * 0.5) / (1 - Pu / (0.75 * Pc)), 1.0))
    assert magnifier(Pu, 0.5, 1.0, 200.0, 12.0, 1.0, EI)[0] == 1.0         # kLu/r = 16.7 < 28: short column


def beam_model(w, L=6.0):
    return {"name": "rc", "settings": {"standard": "TH"}, "materials": {},
            "sections": {"B": {"shape": "rect", "b": 0.3, "h": 0.6, "material": "TH-fc240"},
                         "C": {"shape": "circle", "d": 0.4, "material": "TH-fc240"}},
            "nodes": [{"id": "A", "x": 0, "y": 0, "z": 0}, {"id": "B", "x": L, "y": 0, "z": 0},
                      {"id": "P", "x": 0, "y": 3, "z": 0}, {"id": "Q", "x": 0, "y": 3, "z": 3}],
            "elements": [{"id": "M", "type": "beam", "i": "A", "j": "B", "section": "B"},
                         {"id": "K", "type": "column", "i": "P", "j": "Q", "section": "C"}],
            "supports": [{"node": "A", "dofs": [1, 1, 1, 1, 0, 0]}, {"node": "B", "dofs": [0, 1, 1, 0, 0, 0]},
                         {"node": "P", "dofs": [1, 1, 1, 1, 1, 1]}],
            "load_cases": [{"id": "D", "name": "dead", "type": "dead", "self_weight": False}],
            "loads": [{"case": "D", "kind": "dist", "element": "M", "direction": [0, 0, -1], "points": [[0, w], [L, w]]},
                      {"case": "D", "kind": "nodal", "node": "Q", "values": [0, 0, -100, 0, 0, 0]}],
            "combinations": [{"id": "TH1", "name": "1.4D + 1.7L", "factors": {"D": 1.4}}], "slabs": []}


def test_simply_supported_beam_design():
    Mu = 2.0e6                                                            # kgf·cm
    w = Mu / KGF / 100 * 8 / (1.4 * 36)                                   # kN/m giving Mu = 1.4 w L^2 / 8
    r = rc_design(beam_model(w))
    m = r["members"]["M"]
    assert m["status"] == "ok"
    fc = round(240 * 0.0980665, 2) / 0.0980665                            # material TH-fc240 stores fck in MPa (2 decimals)
    d = 60 - 4 - 0.9 - 1.0
    As_req = as_required(Mu, 30, d, fc, 4000)
    assert m["rebar"]["bottom"] == "4-DB20"                               # As = 11.0 cm2; 6-DB16 would need two layers
    assert m["rebar"]["bottom_As_cm2"] >= As_req
    flex = next(c for c in m["checks"] if c["id"] == "flexure_bottom")
    assert flex["demand"] == pytest.approx(Mu / KGF / 100, rel=1e-4)
    # stirrups: Vc = 0.53 sqrt(fc') b d, s = min(d/2, Av fy / 3.5 b, Av fy d / Vs) rounded down to 2.5 cm
    Vu = 1.4 * w * 3 * KGF
    db = BARS[m["rebar"]["bottom"].split("-")[1].split()[0]][0]
    d = 60 - 4 - 0.9 - db / 2
    Vc = 0.53 * math.sqrt(fc) * 30 * d
    Vs = max(Vu / 0.85 - Vc, 0)
    Av = 2 * BARS["RB9"][1]
    s = math.floor(min(d / 2, Av * 2400 / (3.5 * 30), Av * 2400 * d / Vs if Vs else 1e9) / 2.5) * 2.5
    assert m["rebar"]["stirrups"] == f"RB9 @ {s / 100:.3f} m, 2 legs"
    shear = next(c for c in m["checks"] if c["id"] == "shear")
    assert shear["capacity"] == pytest.approx(0.85 * (Vc + Av * 2400 * d / s) / KGF, rel=1e-6)
    assert r["members"]["K"]["status"] == "not_covered"                   # circular column
    assert "rectangular" in r["members"]["K"]["reason"]


def test_oversized_moment_is_not_covered():
    r = rc_design(beam_model(400.0))
    assert r["members"]["M"]["status"] == "not_covered" and "rho_b" in r["members"]["M"]["reason"]


def test_thai_building_is_designed():
    m = generate({"standard": "TH"})
    r = rc_design(m)
    assert r["code"] == "EIT1008" and "THS" not in r["combinations"]
    assert r["summary"]["n_checked"] + r["summary"]["not_covered"] == len(m["elements"])
    for mem in r["members"].values():
        if mem.get("kind") == "column" and mem["status"] != "not_covered":
            assert 1.0 <= mem["rebar"]["rho_percent"] <= 8.0
        if mem["status"] in ("ok", "fail"):
            assert mem["util"] == pytest.approx(mem["checks"][0]["ratio"])


def test_steel_members_are_skipped_and_api():
    r = rc_design(generate({"type": "truss2d"}))
    assert r["summary"]["skipped"] == r["summary"]["skipped"] + r["summary"]["n_checked"] and r["summary"]["n_checked"] == 0
    c = TestClient(app)
    m = c.post("/api/generate", json={"standard": "TH"}).json()
    resp = c.post("/api/design/rc", json={"model": m, "options": {"main_grade": "SD30"}})
    assert resp.status_code == 200 and resp.json()["options"]["main_grade"] == "SD30"
    assert c.post("/api/design/rc", json={"model": m, "options": {"main_grade": "SD99"}}).status_code == 400
