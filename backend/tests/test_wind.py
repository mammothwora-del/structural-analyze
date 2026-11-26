"""DPT 1311-50 low-rise wind loads (wind.py) against hand calculations."""
import math

import pytest
from fastapi.testclient import TestClient

from structural.analysis import analyze
from structural.api import app
from structural.generator import generate
from structural.serviceability import sls_combinations
from structural.structures import generate_warehouse
from structural.wind import cpcg, exposure_factor, generate_wind, wind_parameters


def test_code_values():
    # q = 1/2 rho V^2, rho = 1.25: zone 1 (25 m/s) -> 390.6 N/m2
    w = wind_parameters(generate_warehouse({"roof": "portal", "standard": "TH"}), {"zone": "1"})
    assert w["q"] == pytest.approx(0.5 * 1.25 * 25**2 / 1000)
    w4 = wind_parameters(generate_warehouse({"roof": "portal", "standard": "TH"}), {"zone": "4A"})
    assert w4["V"] == pytest.approx(30.0) and w4["q"] == pytest.approx(0.5 * 1.25 * 30**2 / 1000)
    assert w4["sls_factor"] == pytest.approx(0.75 / 1.2**2)
    # Ce, Table 2-3 values
    assert exposure_factor(6, "A") == pytest.approx(0.90, abs=5e-3) and exposure_factor(20, "A") == pytest.approx(1.149, abs=1e-3)
    assert exposure_factor(6, "B") == pytest.approx(0.7) and exposure_factor(30, "B") == pytest.approx(0.92, abs=5e-3)
    # Figure 1 (case 1) and interpolation, case 2
    assert cpcg(1, "2E", 3) == -2.0 and cpcg(1, "1", 20) == 1.0 and cpcg(1, "2", 40) == 0.4
    assert cpcg(1, "1", 12.5) == pytest.approx((0.75 + 1.0) / 2)
    assert cpcg(2, "5E", 30) == 1.15 and cpcg(2, "6", 0) == -0.55
    assert w["Iw"] == 1.0 and wind_parameters(generate_warehouse({"roof": "portal"}), {"importance": "high"})["Iw"] == 1.15


def test_portal_warehouse_resultants_match_hand_calculation():
    m = generate_warehouse({"roof": "portal", "standard": "TH", "span": 20, "bay": 6, "n_bays": 5, "eave_height": 6, "rise": 2})
    r = generate_wind(m, {"zone": "1", "exposure": "A", "internal": "1"})
    s = r["summary"]
    W, L, He, rise = 20.0, 30.0, 6.0, 2.0
    th = math.degrees(math.atan(rise / (W / 2)))
    assert s["slope"] == pytest.approx(th, abs=1e-6) and s["ridge"] == "y"
    h = He + rise / 2                                   # mid-height of the roof (slope >= 7 deg)
    assert s["h"] == pytest.approx(h)
    base = 1.0 * 0.5 * 1.25 * 25**2 / 1000 * (h / 10) ** 0.2
    yE = s["y_end"]
    assert yE == pytest.approx(6.0)                     # max(6, 2z), z = min(0.1*20, 0.4*7) = 2
    c1 = next(c for c in s["cases"] if c["case"] == 1 and c["cpi"] == 0.0 and "+" in c["name"])
    P = lambda z: base * cpcg(1, z, th)                 # noqa: E731
    strip = lambda z: P(z) * (L - yE) + P(z + "E") * yE  # noqa: E731  (per unit height or depth)
    fx = strip("1") * He - strip("4") * He + strip("2") * rise - strip("3") * rise
    fz = -(strip("2") + strip("3")) * W / 2
    assert c1["resultant"][0] == pytest.approx(fx, abs=2e-3)
    assert c1["resultant"][2] == pytest.approx(fz, abs=2e-3)
    # internal pressure adds an outward push on the roof only (walls cancel)
    c1i = next(c for c in s["cases"] if c["case"] == 1 and c["cpi"] == -0.15 and "+" in c["name"])
    assert c1i["resultant"][0] == pytest.approx(fx, abs=2e-3)
    assert c1i["resultant"][2] == pytest.approx(fz - 2.0 * 0.15 * base * W * L, abs=2e-3)
    # the loads in the model add up to the reported resultant (vertical): analyse and compare reactions
    res = analyze(r["model"])
    reac = sum(v[2] for v in res["cases"][c1["id"]]["reactions"].values())
    assert reac == pytest.approx(-fz, rel=1e-4)


def test_cases_combinations_and_replacement():
    m = generate_warehouse({"roof": "pitched", "standard": "TH"})
    assert any(c["id"] == "WX" for c in m["load_cases"])
    r = generate_wind(m, {"internal": "3"})
    mm = r["model"]
    ids = [c["id"] for c in mm["load_cases"] if c["type"] == "wind"]
    assert "WX" not in ids and len(ids) == 8              # 4 directions x 2 internal pressures
    assert not any(l["case"] == "WX" for l in mm["loads"])
    assert all(c["sls_factor"] == pytest.approx(0.75) for c in mm["load_cases"] if c["type"] == "wind")
    combos = {c["id"]: c for c in mm["combinations"]}
    assert "TH1" in combos and "THS" in combos and "TH2" not in combos
    assert combos["TH2-W1"]["factors"]["W1"] == pytest.approx(1.275) and combos["TH3-W8"]["factors"]["W8"] == 1.3
    assert {c["cpi"] for c in r["summary"]["cases"]} == {-0.7, 0.7}
    assert len(generate_wind(m, {"all_corners": True})["summary"]["cases"]) == 16
    # deflection check uses the serviceability factor of each wind case
    sls = {c["id"]: c for c in sls_combinations(mm)}
    assert sls["SLS-W1"]["factors"] == {"W1": 0.75}
    assert sls_combinations(mm, wind_factor=1.0)[-1]["factors"]["W8"] == 1.0
    # the model analyses
    assert analyze(mm)["ok"]


def test_scope_flat_building_and_api():
    tall = generate({"n_levels": 3, "standard": "TH"})
    with pytest.raises(ValueError, match="does not apply"):
        generate_wind(tall)
    flat = generate({"n_levels": 1, "x_spans": [6, 6, 6], "y_spans": [6, 6], "story_heights": [4], "standard": "TH"})
    r = generate_wind(flat, {"exposure": "B"})
    s = r["summary"]
    assert s["h"] == pytest.approx(6.0) and s["Ce"] == pytest.approx(0.7)      # h at least 6 m; B minimum 0.7
    assert any(l["kind"] == "area" for l in r["model"]["loads"] if l["case"].startswith("W"))
    assert analyze(r["model"])["ok"]
    with TestClient(app) as c:
        out = c.post("/api/loads/wind", json={"model": flat, "params": {"zone": "2"}}).json()
        assert out["summary"]["V"] == 27.0 and out["model"]["load_cases"]
        assert c.post("/api/loads/wind", json={"model": tall}).status_code == 400
        assert c.post("/api/loads/wind", json={"model": flat, "params": {"zone": "9"}}).status_code == 400


def test_report_lists_the_wind_parameters():
    import io

    import pypdf

    from structural.report import build_report
    m = generate_wind(generate_warehouse({"roof": "portal", "standard": "TH"}), {"zone": "2"})["model"]
    pdf = build_report(m, {"steel": False, "rc": False, "deflection": False, "members": False})
    txt = "".join(p.extract_text() for p in pypdf.PdfReader(io.BytesIO(pdf)).pages)
    assert "DPT 1311-50" in txt and "V = 27.0 m/s" in txt
