"""More truss types, warehouse roof options (incl. portal frame and multi-span) and lattice roofs.

The truss member forces from the 3D frame solver (with condensed end releases) are checked against an
independent 2D pin-jointed bar solver written here from scratch.
"""
import math

import numpy as np
import pytest

from structural.analysis import analyze
from structural.generator import generate
from structural.structures import TRUSS_TYPES, WAREHOUSE_ROOFS, truss_geometry


def _check(res):
    assert res["ok"], [w for w in res["warnings"] if w["level"] == "error"]
    for c in res["cases"].values():
        assert c["equilibrium"]["ok"]


def bar_forces_2d(P, M, supports, loads, EA=1.0):
    """Axial forces of a 2D pin-jointed truss by the direct stiffness method (independent of the 3D solver)."""
    names = list(P)
    idx = {n: k for k, n in enumerate(names)}
    K = np.zeros((2 * len(names), 2 * len(names)))
    geo = []
    for a, b, _ in M:
        (xa, za), (xb, zb) = P[a], P[b]
        L = math.hypot(xb - xa, zb - za)
        c, s = (xb - xa) / L, (zb - za) / L
        d = [2 * idx[a], 2 * idx[a] + 1, 2 * idx[b], 2 * idx[b] + 1]
        v = np.array([-c, -s, c, s])
        K[np.ix_(d, d)] += EA / L * np.outer(v, v)
        geo.append((d, v, L))
    F = np.zeros(2 * len(names))
    for n, fz in loads.items():
        F[2 * idx[n] + 1] += fz
    fixed = set()
    for n, (fx, fz) in supports.items():
        if fx:
            fixed.add(2 * idx[n])
        if fz:
            fixed.add(2 * idx[n] + 1)
    free = [k for k in range(len(F)) if k not in fixed]
    u = np.zeros(len(F))
    u[free] = np.linalg.solve(K[np.ix_(free, free)], F[free])
    return [EA / L * v @ u[d] for d, v, L in geo]


@pytest.mark.parametrize("kind", TRUSS_TYPES)
@pytest.mark.parametrize("eave", [0.0, 0.8])
def test_every_truss_type_matches_an_independent_bar_solver(kind, eave):
    flat = kind in ("pratt", "howe", "warren", "warren_v", "k")
    span, h, panels, spacing, q = 18.0, 2.0 if flat else 3.0, 6, 5.0, 1.0
    p = {"type": "truss2d", "truss_type": kind, "span": span, "height": h, "panels": panels, "eave_depth": eave,
         "spacing": spacing, "sdl": q}
    m = generate(p)
    res = analyze(m)
    _check(res)
    r = res["cases"]["SDL"]
    assert sum(v[2] for v in r["reactions"].values()) == pytest.approx(q * spacing * span, rel=1e-6)

    P, M, roof, (left, right) = truss_geometry(kind, span, h, panels, eave)
    xs = [P[n][0] for n in roof]
    trib = [((xs[k] - xs[k - 1]) / 2 if k else 0) + ((xs[k + 1] - xs[k]) / 2 if k < len(xs) - 1 else 0) for k in range(len(xs))]
    loads = {n: -q * spacing * w for n, w in zip(roof, trib)}
    N_ref = bar_forces_2d(P, M, {left: (1, 1), right: (0, 1)}, loads)

    node_of = {(round(n["x"], 6), round(n["z"], 6)): n["id"] for n in m["nodes"]}
    el_of = {frozenset((e["i"], e["j"])): e["id"] for e in m["elements"]}
    scale = max(abs(v) for v in N_ref)
    for (a, b, _), ref in zip(M, N_ref):
        ia, ib = (node_of[(round(P[x][0], 6), round(P[x][1], 6))] for x in (a, b))
        eid = el_of[frozenset((ia, ib))]
        assert r["elements"][eid]["N"][0] == pytest.approx(ref, abs=max(1e-6 * scale, 6e-4)), (kind, a, b)   # results are rounded to 0.001 kN
        st = r["elements"][eid]
        assert max(abs(v) for v in st["My"] + st["Mz"]) < 1e-6 * scale   # pin-ended, nodal loads: no bending


def test_warren_with_verticals_bottom_chord_is_midspan_moment_over_depth():
    L, h, w = 18.0, 2.0, 5.0
    m = generate({"type": "truss2d", "truss_type": "warren_v", "span": L, "height": h, "panels": 6, "spacing": 5.0, "sdl": 1.0})
    r = analyze(m)["cases"]["SDL"]
    xz = {n["id"]: (n["x"], n["z"]) for n in m["nodes"]}
    # panel 2-3 has its diagonal into the top node at midspan, so a cut there gives N_bottom = M(L/2) / h
    eid = next(e["id"] for e in m["elements"] if e["role"] == "chord" and xz[e["i"]][1] == 0 == xz[e["j"]][1]
               and sorted((xz[e["i"]][0], xz[e["j"]][0])) == [6.0, 9.0])
    assert r["elements"][eid]["N"][0] == pytest.approx(w * L ** 2 / 8 / h, rel=1e-6)


def test_fink_truss_hand_calculation():
    # Fink truss, span 12 m, rise 3 m, unit loads at T1, T2, T3: by symmetry R = 1.5,
    # joint B0: top chord force = -R / sin(alpha), bottom chord = R / tan(alpha), alpha = atan(3 / 6)
    P, M, roof, sup = truss_geometry("fink", 12.0, 3.0, 4)
    N = dict(zip([(a, b) for a, b, _ in M], bar_forces_2d(P, M, {"B0": (1, 1), "B3": (0, 1)}, {"T1": -1, "T2": -1, "T3": -1})))
    alpha = math.atan(3 / 6)
    assert N[("B0", "T1")] == pytest.approx(-1.5 / math.sin(alpha))
    assert N[("B0", "B1")] == pytest.approx(1.5 / math.tan(alpha))


@pytest.mark.parametrize("roof", WAREHOUSE_ROOFS)
def test_warehouse_roof_types_are_stable(roof):
    res = analyze(generate({"type": "warehouse", "roof": roof, "span": 20.0, "bay": 6.0, "n_bays": 3, "live_load": 0.5}))
    _check(res)
    assert sum(v[2] for v in res["cases"]["LL"]["reactions"].values()) == pytest.approx(0.5 * 20 * 18, rel=1e-5)


@pytest.mark.parametrize("roof", ["pitched", "mono", "portal"])
def test_multi_span_warehouse(roof):
    m = generate({"type": "warehouse", "roof": roof, "span": 15.0, "n_spans": 3, "bay": 6.0, "n_bays": 3, "live_load": 0.5})
    res = analyze(m)
    _check(res)
    assert sum(v[2] for v in res["cases"]["LL"]["reactions"].values()) == pytest.approx(0.5 * 45 * 18, rel=1e-5)
    assert len(m["supports"]) == 4 * 4   # 4 column lines x 4 frames
    pairs = [frozenset((e["i"], e["j"])) for e in m["elements"]]
    assert len(pairs) == len(set(pairs))   # no duplicated members on the shared column lines


def test_portal_frame_has_moment_at_the_knee():
    m = generate({"type": "warehouse", "roof": "portal", "n_bays": 2, "live_load": 1.0, "support": "pinned"})
    r = analyze(m)["cases"]["LL"]
    cols = [e["id"] for e in m["elements"] if e["type"] == "column"]
    assert max(max(abs(v) for v in r["elements"][c]["My"] + r["elements"][c]["Mz"]) for c in cols) > 1.0


@pytest.mark.parametrize("shape,pattern", [("barrel", "braced"), ("barrel", "cross"), ("barrel", "ribbed"),
                                           ("dome", "schwedler"), ("dome", "lamella"), ("dome", "ribbed")])
def test_lattice_roofs(shape, pattern):
    m = generate({"type": "lattice_roof", "shape": shape, "pattern": pattern, "sdl": 1.0})
    res = analyze(m)
    _check(res)
    rz = [v[2] for v in res["cases"]["SDL"]["reactions"].values()]
    plan = 24 * 36 if shape == "barrel" else math.pi * 15 ** 2
    assert sum(rz) == pytest.approx(plan, rel=1e-5)
    if shape == "dome":   # rotational symmetry: every base support takes the same vertical load
        assert min(rz) == pytest.approx(max(rz), rel=1e-6)


def test_unknown_types_are_rejected():
    with pytest.raises(ValueError):
        generate({"type": "truss2d", "truss_type": "banana"})
    with pytest.raises(ValueError):
        generate({"type": "warehouse", "roof": "banana"})
    with pytest.raises(ValueError):
        generate({"type": "lattice_roof", "shape": "banana"})


@pytest.mark.parametrize("roof", ["pitched", "howe_roof", "scissors", "bowstring", "mono", "portal"])
def test_roof_continuous_over_a_middle_column_with_unequal_spans(roof):
    m = generate({"type": "warehouse", "roof": roof, "spans": [12.0, 8.0], "roof_layout": "continuous", "bay": 6.0,
                  "n_bays": 3, "live_load": 0.5})
    res = analyze(m)
    _check(res)
    assert sum(v[2] for v in res["cases"]["LL"]["reactions"].values()) == pytest.approx(0.5 * 20 * 18, rel=1e-5)
    assert [g["pos"] for g in m["grid"]["x"]] == [0.0, 12.0, 20.0]
    assert len(m["supports"]) == 3 * 4
    pairs = [frozenset((e["i"], e["j"])) for e in m["elements"]]
    assert len(pairs) == len(set(pairs))
    nodes = {n["id"]: n for n in m["nodes"]}
    mid = [e for e in m["elements"] if e["type"] == "column" and abs(nodes[e["i"]]["x"] - 12) < 1e-9]
    assert len(mid) == 4   # one column per frame, from the base to the underside of the roof member
    roof_z = min(nodes[e["i"]]["z"] for e in m["elements"] if e["type"] != "column" and abs(nodes[e["i"]]["x"] - 12) < 1e-9
                 and nodes[e["i"]]["z"] > 1)
    assert all(nodes[e["j"]]["z"] == pytest.approx(roof_z) for e in mid)
    assert any("continuous over 2 spans (12 + 8 m)" in n for n in m["notes"])


def test_continuous_roof_sends_more_load_to_the_middle_column():
    """Two equal spans continuous over the middle column: the middle line takes more than either end line
    (5/8 of the total for a uniform continuous beam on rigid supports), against 1/2 with one truss per span."""
    def share(layout):
        m = generate({"type": "warehouse", "roof": "mono", "n_spans": 2, "roof_layout": layout, "n_bays": 3,
                      "live_load": 0.5, "sdl": 0, "wind_pressure": 0})
        nodes = {n["id"]: n for n in m["nodes"]}
        r = analyze(m)["cases"]["LL"]["reactions"]
        return sum(v[2] for k, v in r.items() if nodes[k]["x"] == 20.0) / sum(v[2] for v in r.values())
    repeat, continuous = share("repeat"), share("continuous")
    assert repeat == pytest.approx(0.5, abs=0.04)   # purlin tributary widths at the sawtooth step make it not exactly 1/2
    assert continuous > repeat + 0.04 and continuous < 0.66


def test_truss_geometry_breaks_land_on_bottom_chord_nodes():
    P, M, roof, (left, right) = truss_geometry("mono", 20.0, 2.0, 16, 1.0, breaks=[12.0])
    xs = sorted(x for k, (x, z) in P.items() if k.startswith("B"))
    assert 12.0 in xs and xs[0] == 0 and xs[-1] == 20
    assert max(b - a for a, b in zip(xs, xs[1:])) <= 20 / 16 * 1.5
    assert P[roof[-1]][1] == pytest.approx(3.0)   # mono top chord still rises the full rise over the whole width
    # symmetric roofs also get a ridge node, even when it is not on a span boundary
    P, *_ = truss_geometry("pitched", 20.0, 2.0, 8, 0.5, breaks=[12.0])
    assert max(z for _, z in P.values()) == pytest.approx(2.5)
    with pytest.raises(ValueError):
        truss_geometry("fink", 20.0, 2.0, 8, breaks=[12.0])


def test_span_list_input():
    m = generate({"type": "warehouse", "roof": "pitched", "spans": "15, 10, 15", "n_bays": 2})
    assert [g["pos"] for g in m["grid"]["x"]] == [0.0, 15.0, 25.0, 40.0]
    assert m["generator"]["spans"] == [15.0, 10.0, 15.0] and m["generator"]["n_spans"] == 3
    assert m["name"].startswith("Warehouse 40 ×")
    _check(analyze(m))
    with pytest.raises(ValueError, match="greater than zero"):
        generate({"type": "warehouse", "spans": [12, 0]})
    with pytest.raises(ValueError, match="fink"):
        generate({"type": "warehouse", "roof": "fink", "spans": [12, 8], "roof_layout": "continuous"})
    with pytest.raises(ValueError, match="layout"):
        generate({"type": "warehouse", "roof_layout": "banana"})
