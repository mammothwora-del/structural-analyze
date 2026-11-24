"""Phase 3 generators: planar trusses, warehouse, space truss, braced building."""
import pytest
from fastapi.testclient import TestClient

from structural.analysis import analyze
from structural.api import app
from structural.generator import generate


def _check(res):
    assert res["ok"], [w for w in res["warnings"] if w["level"] == "error"]
    for c in res["cases"].values():
        assert c["equilibrium"]["ok"]


@pytest.mark.parametrize("kind", ["pratt", "howe", "warren", "pitched"])
def test_planar_trusses_are_stable_and_carry_the_roof_load(kind):
    p = {"type": "truss2d", "truss_type": kind, "span": 16.0, "height": 2.0, "panels": 8, "spacing": 5.0, "sdl": 1.0}
    m = generate(p)
    res = analyze(m)
    _check(res)
    r = res["cases"]["SDL"]
    assert sum(v[2] for v in r["reactions"].values()) == pytest.approx(1.0 * 5.0 * 16.0, rel=1e-5)
    # members carry axial force only (nodal loads, pin-ended)
    for st in r["elements"].values():
        assert max(abs(v) for v in st["My"] + st["Mz"]) < 1e-6


def test_pratt_top_chord_force_equals_midspan_moment_over_depth():
    L, h, w = 16.0, 2.0, 1.0 * 5.0   # kN/m along the span
    m = generate({"type": "truss2d", "truss_type": "pratt", "span": L, "height": h, "panels": 8, "spacing": 5.0, "sdl": 1.0})
    r = analyze(m)["cases"]["SDL"]
    xyz = {n["id"]: (n["x"], n["z"]) for n in m["nodes"]}
    # top chord members touching midspan
    mids = [e["id"] for e in m["elements"] if e["role"] == "chord" and all(xyz[n][1] > 0 for n in (e["i"], e["j"]))
            and L / 2 in (xyz[e["i"]][0], xyz[e["j"]][0])]
    assert mids
    for eid in mids:
        assert r["elements"][eid]["N"][0] == pytest.approx(-w * L**2 / 8 / h, rel=1e-5)


def test_warehouse_is_stable_and_in_equilibrium():
    p = {"type": "warehouse", "span": 20.0, "bay": 6.0, "n_bays": 4, "sdl": 0.3, "live_load": 0.5}
    res = analyze(generate(p))
    _check(res)
    assert sum(v[2] for v in res["cases"]["LL"]["reactions"].values()) == pytest.approx(0.5 * 20 * 24, rel=1e-5)
    wx = res["cases"]["WX"]
    assert sum(v[0] for v in wx["reactions"].values()) == pytest.approx(-wx["equilibrium"]["applied"][0], rel=1e-5)
    assert any(w["code"] == "pin_joint_rotations" for w in res["warnings"])


def test_warehouse_without_roof_bracing_is_reported_unstable():
    res = analyze(generate({"type": "warehouse", "roof_bracing": False}))
    assert not res["ok"]
    assert any(w["code"] == "mechanism" for w in res["warnings"])


@pytest.mark.parametrize("supports,hc", [("perimeter", 5.0), ("corners", 0.0)])
def test_space_truss(supports, hc):
    m = generate({"type": "space_truss", "nx": 6, "ny": 4, "module": 2.0, "depth": 1.5, "supports": supports,
                  "column_height": hc, "sdl": 1.0})
    res = analyze(m)
    _check(res)
    r = res["cases"]["SDL"]
    assert sum(v[2] for v in r["reactions"].values()) == pytest.approx(12 * 8 * 1.0, rel=1e-5)
    if supports == "corners":
        rz = sorted(v[2] for v in r["reactions"].values())
        assert rz[0] == pytest.approx(rz[-1], rel=1e-6)   # doubly symmetric -> equal corner reactions


def test_bracing_stiffens_the_building():
    base = {"type": "building", "x_spans": [6, 6, 6], "y_spans": [5, 5], "story_heights": [3.5, 3.5, 3.5], "slab_model": "tributary"}
    def top_drift(p):
        res = analyze(generate(p))
        _check(res)
        return max(abs(d[0]) for d in res["cases"]["WX"]["displacements"].values())
    assert top_drift({**base, "bracing": "x"}) < 0.5 * top_drift(base)


def test_api_generates_every_type():
    c = TestClient(app)
    for t in ("building", "truss2d", "warehouse", "space_truss"):
        m = c.post("/api/generate", json={"type": t}).json()
        assert m["elements"], t
    assert c.post("/api/generate", json={"type": "dome"}).status_code == 400
