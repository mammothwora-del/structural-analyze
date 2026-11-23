"""Integration tests: generated building, slab distribution, equilibrium, API."""
import numpy as np
import pytest
from fastapi.testclient import TestClient

from structural.analysis import analyze
from structural.api import app
from structural.generator import generate_building
from structural.slabs import distribute, expand_area_loads


@pytest.fixture(scope="module")
def building():
    return generate_building({"x_spans": [6, 6], "y_spans": [5, 5], "story_heights": [4, 3.5, 3.5]})


@pytest.fixture(scope="module")
def results(building):
    return analyze(building)


def test_generator_counts(building):
    # 3x3 grid columns per storey * 3 storeys
    cols = [e for e in building["elements"] if e["type"] == "column"]
    assert len(cols) == 27
    assert len(building["supports"]) == 9
    assert any(e["role"] == "secondary" for e in building["elements"])


def test_two_way_tributary_areas_sum_to_panel_area(building):
    trib, warns = distribute(building)
    assert not warns
    for t in trib.values():
        assert abs(sum(e["tributary_area"] for e in t["edges"]) - t["area"]) < 1e-9


def test_one_way_panel():
    model = generate_building({"x_spans": [9], "y_spans": [3], "story_heights": [3], "secondary_beams": "none"})
    trib, _ = distribute(model)
    t = next(iter(trib.values()))
    assert t["mode"] == "one-way"
    # only the two long (9 m) edges carry load, half each
    fr = sorted(e["fraction"] for e in t["edges"])
    assert fr == pytest.approx([0, 0, 0.5, 0.5])


def test_area_load_total_preserved(building):
    m, trib, _ = expand_area_loads(building)
    total_area = sum(t["area"] for t in trib.values())
    sdl = [l for l in m["loads"] if l["case"] == "SDL"]
    tot = 0.0
    for l in sdl:
        pts = l["points"]
        tot += sum(0.5 * (a[1] + b[1]) * (b[0] - a[0]) for a, b in zip(pts[:-1], pts[1:]))
    assert tot == pytest.approx(1.5 * total_area, rel=1e-9)


def test_all_cases_in_equilibrium(results):
    assert results["ok"], results["warnings"]
    for cid, r in results["cases"].items():
        assert r["equilibrium"]["ok"], cid
        # applied + reactions = 0 for each component
        app_ = np.array(r["equilibrium"]["applied"])
        rea = np.array(r["equilibrium"]["reactions"])
        assert np.allclose(app_, -rea, atol=1e-3)


def test_sdl_total_reaction_equals_area_load(building, results):
    area = 12 * 10 * 3
    assert sum(r[2] for r in results["cases"]["SDL"]["reactions"].values()) == pytest.approx(1.5 * area, rel=1e-5)


def test_node_force_balance(building, results):
    """At every free node, element end forces + applied loads balance (exact statics)."""
    r = results["cases"]["DL"]
    info = results["elements"]
    sums = {}
    for e in building["elements"]:
        R = np.array(info[e["id"]]["axes"])
        st = r["elements"][e["id"]]
        for end, n in (("end_i", e["i"]), ("end_j", e["j"])):
            fg = R.T @ np.array(st[end][:3])
            sums[n] = sums.get(n, np.zeros(3)) - fg   # force from member on node
    sup = {s["node"] for s in building["supports"]}
    for n, s in sums.items():
        if n in sup:
            s = s + np.array(r["reactions"][n][:3])
        assert np.allclose(s, 0, atol=1e-3), n


def test_api_roundtrip():
    c = TestClient(app)
    m = c.post("/api/generate", json={"x_spans": [5], "y_spans": [4], "story_heights": [3]}).json()
    res = c.post("/api/analyze", json=m)
    assert res.status_code == 200
    assert res.json()["ok"]


def test_api_reports_unstable():
    c = TestClient(app)
    m = c.post("/api/generate", json={"x_spans": [5], "y_spans": [4], "story_heights": [3], "support": "pinned",
                                       "secondary_beams": "none"}).json()
    # remove all beams -> pinned-base cantilever columns become mechanisms
    m["elements"] = [e for e in m["elements"] if e["type"] == "column"]
    m["slabs"] = []
    m["loads"] = [l for l in m["loads"] if l["kind"] != "area"]
    res = c.post("/api/analyze", json=m).json()
    assert not res["ok"]
    assert any(w["code"] == "mechanism" for w in res["warnings"])


def test_stations_identical_across_cases(results):
    cases = list(results["cases"].values())
    for eid in cases[0]["elements"]:
        xs = [c["elements"][eid]["x"] for c in cases]
        assert all(x == xs[0] for x in xs), eid
