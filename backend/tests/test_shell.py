"""Shell element benchmarks against classical plate theory (Timoshenko & Woinowsky-Krieger)
and membrane patch tests. All plates: square a x a, nu = 0.3, uniform load q downward."""
import numpy as np
import pytest

from structural.shell import ShellElement
from structural.solver import FrameModel

E_MPA = 30000.0


def plate_model(n, a=4.0, t=0.02, q=10.0, edge="ss", nu=0.3, distort=0.0):
    xs = np.linspace(0, a, n + 1)
    nodes, nid = [], {}
    rng = np.random.default_rng(1)
    for j in range(n + 1):
        for i in range(n + 1):
            x, y = xs[i], xs[j]
            if distort and 0 < i < n and 0 < j < n:
                x += distort * a / n * rng.uniform(-1, 1)
                y += distort * a / n * rng.uniform(-1, 1)
            nid[(i, j)] = f"P{i}_{j}"
            nodes.append({"id": nid[(i, j)], "x": x, "y": y, "z": 0.0})
    shells = []
    for j in range(n):
        for i in range(n):
            shells.append({"id": f"Q{i}_{j}", "nodes": [nid[(i, j)], nid[(i + 1, j)], nid[(i + 1, j + 1)], nid[(i, j + 1)]],
                           "t": t, "material": "M", "group": "plate"})
    supports = []
    for (i, j), n_ in nid.items():
        edge_node = i in (0, n) or j in (0, n)
        if edge_node:
            dofs = [1, 1, 1, 0, 0, 1] if edge == "ss" else [1, 1, 1, 1, 1, 1]
        else:
            dofs = [1, 1, 0, 0, 0, 1]   # in-plane and drilling are irrelevant for a flat plate
        supports.append({"node": n_, "dofs": dofs})
    return {
        "materials": {"M": {"E": E_MPA, "nu": nu, "density": 0.0}},
        "sections": {}, "nodes": nodes, "elements": [], "shells": shells, "supports": supports,
        "load_cases": [{"id": "Q"}],
        "loads": [{"case": "Q", "kind": "pressure", "group": "plate", "q": q}],
    }, nid


def centre_values(res, nid, n, shells):
    c = nid[(n // 2, n // 2)]
    w = res["displacements"][c][2]
    vals = []
    for s in shells:
        if c in s["nodes"]:
            vals.append(res["shells"][s["id"]]["n"][s["nodes"].index(c)])
    return w, np.mean(vals, axis=0)


@pytest.mark.parametrize("edge,alpha_w,beta_m", [("ss", 0.00406, 0.0479), ("cl", 0.00126, 0.0231)])
def test_square_plate_uniform_load(edge, alpha_w, beta_m):
    n, a, t, q, nu = 16, 4.0, 0.02, 10.0, 0.3
    data, nid = plate_model(n, a, t, q, edge)
    fm = FrameModel(data)
    res = fm.solve_case("Q")
    D = E_MPA * 1000 * t**3 / (12 * (1 - nu**2))
    w, r = centre_values(res, nid, n, data["shells"])
    assert w < 0  # deflects downward
    assert -w / (q * a**4 / D) == pytest.approx(alpha_w, rel=0.03)
    # sagging moment positive (bottom fibre in tension), Mx = My by symmetry
    assert r[3] / (q * a**2) == pytest.approx(beta_m, rel=0.04)
    assert r[4] == pytest.approx(r[3], rel=1e-6)
    eq = res["equilibrium"]
    assert eq["ok"]
    assert eq["applied"][2] == pytest.approx(-q * a * a, rel=1e-9)
    assert sum(v[2] for v in res["reactions"].values()) == pytest.approx(q * a * a, rel=1e-9)


def test_plate_convergence_and_distorted_mesh():
    """Thin simply supported plate: converges with refinement; tolerant to a distorted mesh (no shear locking)."""
    nu, a, t, q = 0.3, 4.0, 0.01, 10.0
    D = E_MPA * 1000 * t**3 / (12 * (1 - nu**2))
    errs = []
    for n in (4, 8, 16):
        data, nid = plate_model(n, a, t, q, "ss")
        w, _ = centre_values(FrameModel(data).solve_case("Q"), nid, n, data["shells"])
        errs.append(abs(-w / (q * a**4 / D) - 0.00406) / 0.00406)
    assert errs[-1] < 0.01
    data, nid = plate_model(16, a, t, q, "ss", distort=0.2)
    w, _ = centre_values(FrameModel(data).solve_case("Q"), nid, 16, data["shells"])
    assert -w / (q * a**4 / D) == pytest.approx(0.00406, rel=0.03)


def test_membrane_patch_uniform_tension():
    """Irregular 4-element patch under uniform edge tension: constant Nx = p everywhere."""
    pts = {"A": (0, 0), "B": (2, 0), "C": (2, 2), "D": (0, 2), "E": (0.7, 0.8),
           "M1": (1.1, 0), "M2": (2, 0.9), "M3": (1.0, 2), "M4": (0, 1.2)}
    nodes = [{"id": k, "x": x, "y": y, "z": 0.0} for k, (x, y) in pts.items()]
    shells = [
        {"id": "S1", "nodes": ["A", "M1", "E", "M4"], "t": 0.1, "material": "M"},
        {"id": "S2", "nodes": ["M1", "B", "M2", "E"], "t": 0.1, "material": "M"},
        {"id": "S3", "nodes": ["E", "M2", "C", "M3"], "t": 0.1, "material": "M"},
        {"id": "S4", "nodes": ["M4", "E", "M3", "D"], "t": 0.1, "material": "M"},
    ]
    p = 50.0  # kN/m
    # consistent loads on right edge x = 2 (B, M2, C): segment lengths 0.9 and 1.1
    loads = [{"case": "T", "kind": "nodal", "node": "B", "values": [p * 0.45, 0, 0, 0, 0, 0]},
             {"case": "T", "kind": "nodal", "node": "M2", "values": [p * 1.0, 0, 0, 0, 0, 0]},
             {"case": "T", "kind": "nodal", "node": "C", "values": [p * 0.55, 0, 0, 0, 0, 0]}]
    supports = [{"node": "A", "dofs": [1, 1, 1, 1, 1, 1]}]
    supports += [{"node": n, "dofs": [1, 0, 1, 1, 1, 1]} for n in ("M4", "D")]
    supports += [{"node": n, "dofs": [0, 0, 1, 1, 1, 1]} for n in ("M1", "B", "E", "M2", "C", "M3")]
    data = {"materials": {"M": {"E": 200000.0, "nu": 0.3}}, "sections": {}, "nodes": nodes, "elements": [],
            "shells": shells, "supports": supports, "load_cases": [{"id": "T"}], "loads": loads}
    res = FrameModel(data).solve_case("T")
    for s in shells:
        for r in [res["shells"][s["id"]]["c"], *res["shells"][s["id"]]["n"]]:
            assert r[0] == pytest.approx(p, rel=1e-6)
            assert abs(r[1]) < 1e-6 * p and abs(r[2]) < 1e-6 * p
    # exact displacement u = p/(E t) x
    E = 200000.0 * 1000
    assert res["displacements"]["C"][0] == pytest.approx(p / (E * 0.1) * 2.0, rel=1e-6)


def test_rotated_plate_invariance():
    """The same simply supported plate built in a vertical plane gives the same deflection."""
    n, a, t, q = 8, 4.0, 0.02, 10.0
    data, nid = plate_model(n, a, t, q, "ss")
    w_flat = FrameModel(data).solve_case("Q")["displacements"][nid[(n // 2, n // 2)]][2]
    # rotate about the x axis by 90 deg: (x, y, z) -> (x, -z, y); the plate now lies in the XZ plane
    for nd in data["nodes"]:
        nd["x"], nd["y"], nd["z"] = nd["x"], -nd["z"], nd["y"]
    # out-of-plane translation is now uy, drilling is ry
    sup = []
    for (i, j), nn in nid.items():
        if i in (0, n) or j in (0, n):
            sup.append({"node": nn, "dofs": [1, 1, 1, 0, 1, 0]})
        else:
            sup.append({"node": nn, "dofs": [1, 0, 1, 0, 1, 0]})
    data["supports"] = sup
    data["loads"] = [{"case": "Q", "kind": "pressure", "group": "plate", "q": q, "direction": [0, -1, 0]}]
    res = FrameModel(data).solve_case("Q")
    w_rot = res["displacements"][nid[(n // 2, n // 2)]][1]
    assert w_rot == pytest.approx(w_flat, rel=1e-6)
    assert res["equilibrium"]["ok"]


def test_shell_frame_coupling_cantilever_slab_strip():
    """A shell strip modelled as a cantilever (clamped at one end, tip line load) vs beam theory, nu = 0."""
    L, b, t, P = 3.0, 0.5, 0.1, 2.0
    n = 12
    nodes, shells = [], []
    for i in range(n + 1):
        for j, y in enumerate((0.0, b)):
            nodes.append({"id": f"N{i}_{j}", "x": L * i / n, "y": y, "z": 0.0})
    for i in range(n):
        shells.append({"id": f"S{i}", "nodes": [f"N{i}_0", f"N{i + 1}_0", f"N{i + 1}_1", f"N{i}_1"], "t": t, "material": "M"})
    supports = [{"node": f"N0_{j}", "dofs": [1] * 6} for j in (0, 1)]
    loads = [{"case": "P", "kind": "nodal", "node": f"N{n}_{j}", "values": [0, 0, -P / 2, 0, 0, 0]} for j in (0, 1)]
    data = {"materials": {"M": {"E": 30000.0, "nu": 0.0}}, "sections": {}, "nodes": nodes, "elements": [],
            "shells": shells, "supports": supports, "load_cases": [{"id": "P"}], "loads": loads}
    res = FrameModel(data).solve_case("P")
    E = 30000.0e3
    I = b * t**3 / 12
    G = E / 2
    w_exact = P * L**3 / (3 * E * I) + P * L / (5 / 6 * G * b * t)
    assert -res["displacements"][f"N{n}_0"][2] == pytest.approx(w_exact, rel=0.01)
    # root moment per unit width = P L / b, hogging (top tension) -> negative in the sagging-positive convention
    r = res["shells"]["S0"]
    m_root = np.mean([r["n"][0][3], r["n"][3][3]])
    assert m_root == pytest.approx(-P * L / b, rel=0.1)
    # shell nodal forces balance the support reactions
    sf = res["shell_node_force"]
    for j in (0, 1):
        assert np.allclose(np.array(sf[f"N0_{j}"]) + np.array(res["reactions"][f"N0_{j}"][:3]), 0, atol=1e-8)
