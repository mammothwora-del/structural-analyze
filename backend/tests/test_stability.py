"""Linear (eigenvalue) buckling and P-Delta, checked against closed-form results.

Euler: Pcr = pi^2 EI / (K L)^2.  P-Delta cantilever with a tip load H and axial load P (exact beam-column):
delta = H (tan(aL) - aL) / (P a), a = sqrt(P / EI).
"""
import math

import numpy as np
import pytest

from structural.generator import generate
from structural.solver import ModelError
from structural.sections import MATERIALS, section_properties
from structural.solver import FrameModel  # noqa: E402
from structural.stability import assemble_kg, buckling, kg_unit, pdelta, subdivide

PIPE = {"shape": "pipe", "d": 0.1143, "t": 0.006, "material": "S355"}
E = MATERIALS["S355"]["E"] * 1000.0   # MPa -> kN/m2
I = section_properties(PIPE).Iy
L = 5.0

TOP = {"free": [0, 0, 0, 0, 0, 0], "pinned": [1, 1, 0, 0, 0, 0], "guided": [1, 1, 0, 1, 1, 1]}
K_EFF = {"free": 2.0, "pinned": 0.699, "guided": 0.5}


def column(top="free", base=(1, 1, 1, 1, 1, 1), P=100.0, H=0.0, truss=False):
    return {"name": "col", "settings": {"standard": "EN1990"}, "materials": {}, "sections": {"S": PIPE},
            "nodes": [{"id": "A", "x": 0, "y": 0, "z": 0}, {"id": "B", "x": 0, "y": 0, "z": L}],
            "elements": [{"id": "C", "type": "column", "i": "A", "j": "B", "section": "S", **({"truss": True} if truss else {})}],
            "supports": [{"node": "A", "dofs": list(base)}] + ([{"node": "B", "dofs": TOP[top]}] if top != "free" else []),
            "load_cases": [{"id": "P", "name": "P", "type": "dead"}],
            "loads": [{"case": "P", "kind": "nodal", "node": "B", "values": [H, 0, -P, 0, 0, 0]}],
            "combinations": [{"id": "C1", "name": "1.5 P", "factors": {"P": 1.5}}], "slabs": []}


def euler(K):
    return math.pi ** 2 * E * I / (K * L) ** 2


@pytest.mark.parametrize("top", ["free", "pinned", "guided"])
def test_euler_columns(top):
    r = buckling(column(top), "P", n_modes=2, n_seg=8)
    assert r["modes"][0]["factor"] * 100.0 == pytest.approx(euler(K_EFF[top]), rel=2e-3 if top == "pinned" else 1e-3)
    pts = r["modes"][0]["members"]["C"]   # [x, y, z, ux, uy, uz] from the base to the top
    assert len(pts) == 9 and pts[0][:3] == [0, 0, 0] and pts[-1][:3] == [0, 0, L]
    assert max(math.hypot(*p[3:]) for p in pts) == pytest.approx(1.0)


def test_pinned_pinned_column_converges_with_segments():
    base = (1, 1, 1, 0, 0, 1)
    ratio = [buckling(column("pinned", base), "P", n_modes=1, n_seg=s)["modes"][0]["factor"] * 100 / euler(1.0) for s in (1, 2, 4)]
    assert ratio[0] > ratio[1] > ratio[2] > 1.0   # the cubic element over-estimates and converges from above
    assert ratio[2] == pytest.approx(1.0, abs=1e-3)


def test_pin_ended_truss_column():
    r = buckling(column("pinned", truss=True), "P", n_modes=1, n_seg=4)
    assert r["modes"][0]["factor"] * 100 == pytest.approx(euler(1.0), rel=1e-3)


def test_combination_scales_the_load_factor():
    a = buckling(column("free"), "P", n_modes=1)["modes"][0]["factor"]
    b = buckling(column("free"), "C1", n_modes=1)["modes"][0]["factor"]
    assert b == pytest.approx(a / 1.5, rel=1e-9)


def test_tension_gives_no_modes():
    r = buckling(column("free", P=-100.0), "P")
    assert r["modes"] == []
    assert any("tension" in n for n in r["notes"])


def test_sway_portal_with_rigid_beam():
    # pinned bases, rigid beam, equal loads on both column tops: sway mode, each column K = 2
    h, b = 4.0, 6.0
    m = {"name": "portal", "settings": {"standard": "EN1990"}, "materials": {},
         "sections": {"S": PIPE, "R": {"shape": "rect", "b": 1.0, "h": 2.0, "material": "S355"}},
         "nodes": [{"id": "A", "x": 0, "y": 0, "z": 0}, {"id": "B", "x": 0, "y": 0, "z": h},
                   {"id": "C", "x": b, "y": 0, "z": h}, {"id": "D", "x": b, "y": 0, "z": 0}],
         "elements": [{"id": "c1", "type": "column", "i": "A", "j": "B", "section": "S"},
                      {"id": "bm", "type": "beam", "i": "B", "j": "C", "section": "R"},
                      {"id": "c2", "type": "column", "i": "D", "j": "C", "section": "S"}],
         "supports": [{"node": n, "dofs": [1, 1, 1, 0, 0, 0]} for n in ("A", "D")]
                     + [{"node": n, "dofs": [0, 1, 0, 1, 0, 1]} for n in ("B", "C")],   # planar frame
         "load_cases": [{"id": "P", "name": "P", "type": "dead"}],
         "loads": [{"case": "P", "kind": "nodal", "node": n, "values": [0, 0, -1.0, 0, 0, 0]} for n in ("B", "C")],
         "combinations": [], "slabs": []}
    r = buckling(m, "P", n_modes=1, n_seg=8)
    assert r["modes"][0]["factor"] == pytest.approx(math.pi ** 2 * E * I / (2 * h) ** 2, rel=2e-3)
    ux = [r["modes"][0]["nodes"][n][0] for n in ("B", "C")]
    assert ux[0] == pytest.approx(ux[1], rel=1e-3) and abs(ux[0]) == pytest.approx(1.0)   # sway, normalised


@pytest.mark.parametrize("ratio", [0.1, 0.3, 0.6])
def test_pdelta_cantilever_matches_exact_beam_column(ratio):
    P, H = ratio * euler(2.0), 1.0
    r = pdelta(column("free", P=P, H=H), "P", n_seg=4)
    assert r["converged"]
    a = math.sqrt(P / (E * I))
    d_exact = H * (math.tan(a * L) - a * L) / (P * a)
    d = r["result"]["displacements"]["B"][0]
    assert d == pytest.approx(d_exact, rel=1e-4)
    base = r["result"]["elements"]["C"]
    M0 = max(abs(base["My"][0]), abs(base["Mz"][0]))
    assert M0 == pytest.approx(H * L + P * d, rel=1e-3)   # second-order base moment
    assert r["amplification"] > 1.0


def test_pdelta_above_buckling_load_is_refused():
    with pytest.raises(ModelError):
        pdelta(column("free", P=1.2 * euler(2.0), H=1.0), "P", n_seg=4)


def test_unknown_load_is_refused():
    with pytest.raises(ModelError):
        buckling(column(), "nope")


def test_geometric_stiffness_is_symmetric_and_matches_textbook():
    G = kg_unit(L, 0.01, 1e-5, 1e-5)
    assert np.allclose(G, G.T, atol=1e-10)
    # classic consistent geometric stiffness, bending in the x-z plane (DOFs uz, ry at both ends): N/(30L) [...]
    ref = np.array([[36, -3 * L, -36, -3 * L], [-3 * L, 4 * L * L, 3 * L, -L * L],
                    [-36, 3 * L, 36, 3 * L], [-3 * L, -L * L, 3 * L, 4 * L * L]]) / (30 * L)
    d = [2, 4, 8, 10]
    assert np.allclose(G[np.ix_(d, d)], ref, rtol=1e-4, atol=1e-6)

    fe, _ = subdivide(generate({"type": "truss2d", "truss_type": "pratt"}), 2)
    fm = FrameModel(fe)
    Kg = assemble_kg(fm, np.linspace(-5, 5, len(fm.elements))).toarray()
    assert np.allclose(Kg, Kg.T, atol=1e-9)


GENERATORS = [{"type": "truss2d", "truss_type": t} for t in ("pratt", "fink", "bowstring")] + [
    {"type": "warehouse", "roof": "pitched", "n_bays": 2},
    {"type": "warehouse", "roof": "portal", "n_bays": 2},
    {"type": "space_truss"},
    {"type": "lattice_roof", "shape": "dome", "pattern": "schwedler"},
    {"type": "building", "x_spans": [6, 6], "y_spans": [5], "story_heights": [3.5, 3.2]},
]


@pytest.mark.parametrize("params", GENERATORS, ids=lambda p: "-".join(str(v) for v in p.values()))
def test_every_generator_runs_buckling_and_pdelta(params):
    m = generate(params)
    load = next((c["id"] for c in m.get("combinations", [])), m["load_cases"][0]["id"])
    b = buckling(m, load, n_modes=2, n_seg=2)
    assert b["modes"], b["notes"]
    lam = b["modes"][0]["factor"]
    assert lam > 0
    assert set(b["modes"][0]["members"]) <= {e["id"] for e in m["elements"]}
    if lam > 1.05:
        p = pdelta(m, load)
        assert p["converged"]
        assert p["amplification"] > 0.9   # can be below 1 where tension members stiffen the structure
        assert set(p["result"]["elements"]) >= {e["id"] for e in m["elements"]}
