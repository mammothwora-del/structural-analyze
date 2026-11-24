"""Phase 3 benchmarks: truss members and member end releases against hand statics."""
import math

import numpy as np
import pytest

from structural.sections import section_properties
from structural.solver import FrameModel

MAT = {"ST": {"E": 200000.0, "nu": 0.3, "density": 0.0}}
SEC = {"T": {"shape": "pipe", "d": 0.1, "t": 0.005, "material": "ST"},
       "B": {"shape": "I", "h": 0.3, "bf": 0.15, "tf": 0.01, "tw": 0.006, "material": "ST"}}


def mid_N(res, eid):
    st = res["elements"][eid]
    return st["N"][len(st["N"]) // 2]


def pratt_model():
    a, h, P = 3.0, 3.0, 10.0
    nodes = [{"id": f"B{k}", "x": a * k, "y": 0.0, "z": 0.0} for k in range(5)]
    nodes += [{"id": f"T{k}", "x": a * k, "y": 0.0, "z": h} for k in (1, 2, 3)]
    bars = [("B0", "B1"), ("B1", "B2"), ("B2", "B3"), ("B3", "B4"), ("T1", "T2"), ("T2", "T3"),
            ("B0", "T1"), ("B4", "T3"), ("B1", "T1"), ("B2", "T2"), ("B3", "T3"), ("T1", "B2"), ("T3", "B2")]
    elements = [{"id": f"{i}{j}", "i": i, "j": j, "section": "T", "type": "truss"} for i, j in bars]
    # planar truss: restrain out-of-plane translation everywhere
    supports = [{"node": n["id"], "dofs": [0, 1, 0, 0, 0, 0]} for n in nodes if n["id"] not in ("B0", "B4")]
    supports += [{"node": "B0", "dofs": [1, 1, 1, 0, 0, 0]}, {"node": "B4", "dofs": [0, 1, 1, 0, 0, 0]}]
    loads = [{"case": "P", "kind": "nodal", "node": f"B{k}", "values": [0, 0, -P, 0, 0, 0]} for k in (1, 2, 3)]
    return {"materials": MAT, "sections": SEC, "nodes": nodes, "elements": elements, "supports": supports,
            "load_cases": [{"id": "P"}], "loads": loads}


def test_pratt_truss_matches_method_of_joints():
    fm = FrameModel(pratt_model())
    res = fm.solve_case("P")
    expected = {"B0T1": -15 * math.sqrt(2), "B0B1": 15.0, "B1T1": 10.0, "B1B2": 15.0, "T1B2": 5 * math.sqrt(2),
                "T1T2": -20.0, "B2T2": 0.0, "B2B3": 15.0, "T3B2": 5 * math.sqrt(2), "B4T3": -15 * math.sqrt(2)}
    for eid, N in expected.items():
        assert mid_N(res, eid) == pytest.approx(N, abs=1e-6), eid
    # pure axial members: no bending, no shear
    for st in res["elements"].values():
        for c in ("Vy", "Vz", "T", "My", "Mz"):
            assert max(abs(v) for v in st[c]) < 1e-6
    assert res["equilibrium"]["ok"]
    assert res["reactions"]["B0"][2] == pytest.approx(15.0) and res["reactions"]["B4"][2] == pytest.approx(15.0)
    # pin joint rotations are reported as info, not as errors
    codes = {w["code"]: w["level"] for w in fm.warnings}
    assert codes.get("pin_joint_rotations") == "info" and "zero_stiffness" not in codes and "mechanism" not in codes


def test_truss_deflection_by_virtual_work():
    """Midspan deflection of the Pratt truss = sum N n L / (E A) (unit-load method, independent of the FEM)."""
    data = pratt_model()
    res = FrameModel(data).solve_case("P")
    data_u = pratt_model()
    data_u["loads"] = [{"case": "P", "kind": "nodal", "node": "B2", "values": [0, 0, -1.0, 0, 0, 0]}]
    res_u = FrameModel(data_u).solve_case("P")
    EA = 200000e3 * section_properties(SEC["T"]).A
    xyz = {n["id"]: np.array([n["x"], n["y"], n["z"]]) for n in data["nodes"]}
    delta = sum(mid_N(res, e["id"]) * mid_N(res_u, e["id"]) * np.linalg.norm(xyz[e["j"]] - xyz[e["i"]]) / EA
                for e in data["elements"])
    assert -res["displacements"]["B2"][2] == pytest.approx(delta, rel=1e-9)


def beam_with_releases(release_i, release_j, n_el=1):
    L, q = 6.0, 12.0
    nodes = [{"id": "A", "x": 0, "y": 0, "z": 0}, {"id": "B", "x": L, "y": 0, "z": 0}]
    el = {"id": "E", "i": "A", "j": "B", "section": "B",
          "releases": {"i": [0, 0, 0, 0, 1, 1] if release_i else [0] * 6, "j": [0, 0, 0, 0, 1, 1] if release_j else [0] * 6}}
    data = {"materials": MAT, "sections": SEC, "nodes": nodes, "elements": [el],
            "supports": [{"node": "A", "type": "fixed"}, {"node": "B", "type": "fixed"}],
            "load_cases": [{"id": "Q"}],
            "loads": [{"case": "Q", "kind": "dist", "element": "E", "direction": [0, 0, -1], "points": [[0, q], [L, q]]}]}
    return data, L, q


def test_pinned_both_ends_gives_simply_supported_beam():
    data, L, q = beam_with_releases(True, True)
    res = FrameModel(data).solve_case("Q")
    st = res["elements"]["E"]
    EI = 200000e3 * section_properties(SEC["B"]).Iy
    k = st["x"].index(min(st["x"], key=lambda x: abs(x - L / 2)))
    assert abs(st["My"][k]) == pytest.approx(q * L**2 / 8, rel=1e-9)
    assert abs(st["My"][0]) < 1e-9 and abs(st["My"][-1]) < 1e-9
    assert -st["disp"][k][2] == pytest.approx(5 * q * L**4 / (384 * EI), rel=1e-6)
    # supports take no moment through the hinges; vertical reactions qL/2
    assert res["reactions"]["A"][2] == pytest.approx(q * L / 2) and abs(res["reactions"]["A"][4]) < 1e-9
    assert st["end_check"] < 1e-9


def test_fixed_pinned_beam():
    data, L, q = beam_with_releases(False, True)
    res = FrameModel(data).solve_case("Q")
    st = res["elements"]["E"]
    EI = 200000e3 * section_properties(SEC["B"]).Iy
    assert abs(st["My"][0]) == pytest.approx(q * L**2 / 8, rel=1e-9)       # fixed-end moment
    assert abs(st["My"][-1]) < 1e-9
    assert res["reactions"]["A"][2] == pytest.approx(5 * q * L / 8) and res["reactions"]["B"][2] == pytest.approx(3 * q * L / 8)
    k = st["x"].index(min(st["x"], key=lambda x: abs(x - L / 2)))
    assert -st["disp"][k][2] == pytest.approx(q * L**4 / (192 * EI), rel=1e-6)


def test_truss_without_diagonal_is_a_mechanism():
    nodes = [{"id": "A", "x": 0, "y": 0, "z": 0}, {"id": "B", "x": 4, "y": 0, "z": 0},
             {"id": "C", "x": 4, "y": 0, "z": 3}, {"id": "D", "x": 0, "y": 0, "z": 3}]
    els = [{"id": f"E{k}", "i": i, "j": j, "section": "T", "truss": True} for k, (i, j) in enumerate([("A", "D"), ("D", "C"), ("C", "B")])]
    sup = [{"node": "A", "dofs": [1, 1, 1, 0, 0, 0]}, {"node": "B", "dofs": [1, 1, 1, 0, 0, 0]},
           {"node": "C", "dofs": [0, 1, 0, 0, 0, 0]}, {"node": "D", "dofs": [0, 1, 0, 0, 0, 0]}]
    data = {"materials": MAT, "sections": SEC, "nodes": nodes, "elements": els, "supports": sup,
            "load_cases": [{"id": "H"}], "loads": [{"case": "H", "kind": "nodal", "node": "D", "values": [5, 0, 0, 0, 0, 0]}]}
    fm = FrameModel(data)
    assert any(w["code"] == "mechanism" and w["level"] == "error" for w in fm.warnings)
    # adding the diagonal makes it stable
    data["elements"].append({"id": "DIAG", "i": "A", "j": "C", "section": "T", "truss": True})
    fm = FrameModel(data)
    assert not any(w["level"] == "error" for w in fm.warnings)
    res = fm.solve_case("H")
    assert mid_N(res, "DIAG") == pytest.approx(5 * 5 / 4, rel=1e-9)   # H / cos(theta), theta = atan(3/4)


def test_hollow_section_properties():
    p = section_properties({"shape": "pipe", "d": 0.2, "t": 0.01})
    assert p.A == pytest.approx(math.pi * (0.2**2 - 0.18**2) / 4)
    assert p.Iy == pytest.approx(math.pi * (0.2**4 - 0.18**4) / 64)
    b = section_properties({"shape": "box", "b": 0.1, "h": 0.2, "t": 0.01})
    assert b.A == pytest.approx(0.1 * 0.2 - 0.08 * 0.18)
    assert b.Iy == pytest.approx((0.1 * 0.2**3 - 0.08 * 0.18**3) / 12)
    assert b.Iz < b.Iy
