"""Deflection and drift checks (serviceability.py) against hand calculations, and sizing for deflection."""
import numpy as np
import pytest
from fastapi.testclient import TestClient

from structural.analysis import analyze
from structural.api import app
from structural.generator import generate
from structural.serviceability import DEFAULT_LIMITS, build_spans, deflection_checks, sls_combinations
from structural.steel_sizing import suggest_sections
from structural.structures import generate_truss2d, generate_warehouse

E_MPA = 200000.0
E = E_MPA * 1000.0  # kN/m2
B, H = 0.2, 0.4
IY = B * H**3 / 12
IZ = H * B**3 / 12


def frame(nodes, elements, supports, loads, cases=(("D", "dead"), ("L", "live"))):
    return {
        "materials": {"M": {"E": E_MPA, "nu": 0.3, "density": 0.0}},
        "sections": {"S": {"shape": "rect", "b": B, "h": H, "material": "M"}},
        "nodes": [{"id": n, "x": x, "y": y, "z": z} for n, (x, y, z) in nodes.items()],
        "elements": [{"id": e, "i": i, "j": j, "section": "S", "type": t, **({"level": 1} if t == "column" else {})}
                     for e, (i, j, t) in elements.items()],
        "supports": supports,
        "load_cases": [{"id": c, "name": c, "type": t, "self_weight": False} for c, t in cases],
        "combinations": [],
        "loads": loads,
    }


def simple_beam(L=8.0, n=4, wd=10.0, wl=5.0):
    nodes = {f"N{k}": (L * k / n, 0.0, 3.0) for k in range(n + 1)}
    els = {f"E{k}": (f"N{k}", f"N{k + 1}", "beam") for k in range(n)}
    sup = [{"node": "N0", "dofs": [1, 1, 1, 1, 0, 0]}, {"node": f"N{n}", "dofs": [0, 1, 1, 0, 0, 0]}]
    loads = [{"case": c, "kind": "dist", "element": e, "direction": [0, 0, -1], "points": [[0, w], [L / n, w]]}
             for e in els for c, w in (("D", wd), ("L", wl))]
    return frame(nodes, els, sup, loads)


def test_simply_supported_beam_is_one_span_with_the_textbook_deflection():
    L, wd, wl = 8.0, 10.0, 5.0
    m = simple_beam(L, 4, wd, wl)
    geo = build_spans(m)
    assert len(geo["spans"]) == 1 and geo["spans"][0]["kind"] == "beam"
    assert sorted(geo["spans"][0]["elements"]) == ["E0", "E1", "E2", "E3"]
    r = deflection_checks(m)
    combos = {c["id"]: c for c in r["combinations"]}
    assert set(combos) == {"SLS-DL", "SLS-L"}          # no SLS combination in the model: D + L added, and L alone
    (it,) = r["items"]
    d_total = 5 * (wd + wl) * L**4 / (384 * E * IY)
    d_live = 5 * wl * L**4 / (384 * E * IY)
    # total governs: (d_total / (L/240)) > (d_live / (L/360))
    assert it["combo"] == "SLS-DL" and it["which"] == "total" and it["limit"] == "L/240"
    assert it["delta"] == pytest.approx(d_total, rel=1e-6)
    assert it["allow"] == pytest.approx(L / 240)
    assert it["util"] == pytest.approx(d_total / (L / 240), rel=1e-6)
    assert it["axis"] == "y" and it["L"] == pytest.approx(L)
    assert it["status"] == ("ok" if it["util"] <= 1 else "fail")
    assert set(r["members"]) == {"E0", "E1", "E2", "E3"}
    # with a tighter live limit, live governs
    r2 = deflection_checks(m, limits={"floor_live": 2000})
    assert r2["items"][0]["which"] == "live" and r2["items"][0]["delta"] == pytest.approx(d_live, rel=1e-6)
    assert r2["limits"]["floor_live"] == 2000 and r2["limits"]["floor_total"] == DEFAULT_LIMITS["floor_total"]


def test_end_displacements_are_subtracted():
    """A beam on two equal springs that settle uniformly has no relative deflection from the settlement."""
    L, n, P = 6.0, 2, 30.0
    nodes = {"A": (0, 0, 3), "M": (L / 2, 0, 3), "B": (L, 0, 3), "A0": (0, 0, 0), "B0": (L, 0, 0)}
    els = {"E1": ("A", "M", "beam"), "E2": ("M", "B", "beam"), "C1": ("A0", "A", "column"), "C2": ("B0", "B", "column")}
    sup = [{"node": "A0", "type": "fixed"}, {"node": "B0", "type": "fixed"}]
    loads = [{"case": "L", "kind": "nodal", "node": "M", "values": [0, 0, -P, 0, 0, 0]}]
    m = frame(nodes, els, sup, loads)
    res = analyze(m)
    r = deflection_checks(m, res)
    beam = next(i for i in r["items"] if i["kind"] == "beam")
    d = {k: np.array(res["cases"]["L"]["displacements"][k][:3]) for k in ("A", "M", "B")}
    expected = abs((d["M"] - (d["A"] + d["B"]) / 2)[2])
    assert d["A"][2] < 0 and beam["delta"] == pytest.approx(expected, rel=1e-6)


def test_cantilever_uses_tip_deflection_against_2L():
    L, P = 3.0, 20.0
    nodes = {"N0": (0, 0, 3), "N1": (L / 2, 0, 3), "N2": (L, 0, 3)}
    els = {"E0": ("N0", "N1", "beam"), "E1": ("N1", "N2", "beam")}
    loads = [{"case": "L", "kind": "nodal", "node": "N2", "values": [0, 0, -P, 0, 0, 0]}]
    m = frame(nodes, els, [{"node": "N0", "type": "fixed"}], loads)
    (it,) = deflection_checks(m)["items"]
    assert it["kind"] == "cantilever"
    assert it["delta"] == pytest.approx(P * L**3 / (3 * E * IY), rel=1e-6)
    assert it["which"] == "live" and it["allow"] == pytest.approx(2 * L / 360)
    assert "2L" in it["limit"]


def test_single_storey_drift_from_wind():
    Hc, Lb, F = 4.0, 6.0, 15.0
    nodes = {"A": (0, 0, 0), "B": (0, 0, Hc), "C": (Lb, 0, Hc), "D": (Lb, 0, 0)}
    els = {"C1": ("A", "B", "column"), "BM": ("B", "C", "beam"), "C2": ("D", "C", "column")}
    sup = [{"node": "A", "type": "fixed"}, {"node": "D", "type": "fixed"}]
    loads = [{"case": "W", "kind": "nodal", "node": "B", "values": [F, 0, 0, 0, 0, 0]}]
    m = frame(nodes, els, sup, loads, cases=(("D", "dead"), ("W", "wind")))
    res = analyze(m)
    r = deflection_checks(m, res)
    drift = [i for i in r["items"] if i["kind"] == "drift"]
    assert len(drift) == 2 and r["drift_limit"] == DEFAULT_LIMITS["drift_single"]
    ux = res["cases"]["W"]["displacements"]["B"][0]
    c1 = next(i for i in drift if i["elements"] == ["C1"])
    assert c1["combo"] == "SLS-W" and c1["delta"] == pytest.approx(abs(ux), rel=1e-9)
    assert c1["allow"] == pytest.approx(Hc / 200) and c1["limit"] == "H/200"
    # ASCE 7 wind is strength level: 0.6 W by default, or a factor given
    assert sls_combinations({**m, "settings": {"standard": "ASCE7"}})[-1]["factors"] == {"W": 0.6}
    r6 = deflection_checks(m, res, wind_factor=0.5)
    assert next(i for i in r6["items"] if i["elements"] == ["C1"])["delta"] == pytest.approx(0.5 * abs(ux), rel=1e-9)


def test_multi_storey_building_uses_storey_drift_and_beam_spans():
    m = generate({"n_x": 2, "n_y": 2, "n_levels": 3})
    r = deflection_checks(m)
    assert r["drift_limit"] == DEFAULT_LIMITS["drift_multi"]
    drift = [i for i in r["items"] if i["kind"] == "drift"]
    heights = {round(i["L"], 3) for i in drift}
    lv = {round(lv["height"], 3) for lv in m.get("levels", [])} if m.get("levels") else None
    assert all(h > 2.0 for h in heights)              # storey heights, not bits of a column
    if lv:
        assert heights <= lv
    assert any(i["kind"] == "beam" for i in r["items"])
    assert r["summary"]["n"] == len(r["items"]) and r["summary"]["ok"] + r["summary"]["fail"] == len(r["items"])


def test_planar_truss_vertical_deflection_relative_to_supports():
    m = generate_truss2d({})
    res = analyze(m)
    r = deflection_checks(m, res)
    trusses = [i for i in r["items"] if i["kind"] == "truss"]
    assert len(trusses) == 1
    t = trusses[0]
    nd = {}
    for cid, f in next(c for c in sls_combinations(m) if c["id"] == t["combo"])["factors"].items():
        for nid, d in res["cases"][cid]["displacements"].items():
            nd[nid] = nd.get(nid, 0.0) + f * d[2]
    sup = {s["node"] for s in m["supports"] if not s.get("lateral")}
    assert all(abs(nd[s]) < 1e-12 for s in sup)
    assert t["delta"] == pytest.approx(abs(nd[t["at"]]), rel=1e-9)
    assert t["delta"] == pytest.approx(max(abs(v) for k, v in nd.items() if k in {n for e in m["elements"] for n in (e["i"], e["j"])}), rel=1e-9)


def test_warehouse_purlins_rafters_and_drift_are_found():
    m = generate_warehouse({"roof": "pitched", "n_bays": 3, "standard": "TH"})
    r = deflection_checks(m)
    kinds = {i["kind"] for i in r["items"]}
    assert {"beam", "truss", "drift"} <= kinds
    pur = [i for i in r["items"] if i["role"] == "purlin"]
    assert pur and all(i["roof"] for i in pur)
    assert all(i["limit"].startswith("L/180") or i["limit"].startswith("L/240") for i in pur)
    assert r["notes"]


def test_api_endpoint():
    m = simple_beam()
    with TestClient(app) as c:
        out = c.post("/api/design/deflection", json={"model": m, "limits": {"floor_total": 300}}).json()
        assert out["items"][0]["limit"] == "L/300"
        assert c.post("/api/design/deflection", json={}).status_code == 400


def test_suggest_sizes_can_meet_deflection_limits():
    m = generate_warehouse({"roof": "mono", "n_spans": 1, "n_bays": 3, "standard": "TH"})
    tight = {"roof_total": 600, "roof_live": 800}
    plain = suggest_sections(m)
    stiff = suggest_sections(m, check_deflection=True, deflection_limits=tight)
    assert stiff["deflection"]["summary"]["fail"] == 0
    assert stiff["design"]["summary"]["fail"] == 0
    # the check of the plain sizes against the same limits fails, so the sizing had to make something stiffer
    assert deflection_checks({**m, "sections": plain["sections"]}, limits=tight)["summary"]["fail"] > 0
    mass = lambda r: sum(g["mass_after"] or 0 for g in r["groups"])  # noqa: E731
    assert mass(stiff) > mass(plain)
    assert any(g["defl_util"] is not None for g in stiff["groups"])
    assert plain["deflection"] is None


def test_report_has_the_deflection_section():
    import io

    import pypdf

    from structural.report import build_report
    m = generate_warehouse({"roof": "pitched", "n_bays": 3, "standard": "TH"})
    d = deflection_checks(m, limits={"roof_total": 200})
    for lang, head in (("en", "Deflection and drift"), ("th", "การแอ่นตัวและการเค")):
        pdf = build_report(m, {"steel": False, "rc": False}, lang=lang, deflection={"limits": {"roof_total": 200}})
        txt = "".join(p.extract_text() for p in pypdf.PdfReader(io.BytesIO(pdf)).pages)
        assert head in txt
        assert f"{d['summary']['max_util']:.2f}" in txt and "L/200" in txt
    pdf = build_report(m, {"steel": False, "rc": False, "deflection": False})
    assert "Deflection and drift" not in "".join(p.extract_text() for p in pypdf.PdfReader(io.BytesIO(pdf)).pages)
