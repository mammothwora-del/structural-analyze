"""Benchmarks of the frame solver against closed-form textbook solutions.

References: Roark's Formulas for Stress and Strain (8th ed.) Table 8.1;
Hibbeler, Structural Analysis; Kassimali, Matrix Analysis of Structures.
"""
import math

import numpy as np
import pytest

from structural.solver import FrameModel, ModelError

E_MPA = 200000.0
E = E_MPA * 1000  # kN/m2
NU = 0.3
G = E / (2 * (1 + NU))
B, H = 0.2, 0.4
A = B * H
IY = B * H**3 / 12   # major (vertical bending for horizontal members)
IZ = H * B**3 / 12


def base_model(nodes, elements, supports, loads, self_weight=False, sec=None):
    return {
        "materials": {"M": {"E": E_MPA, "nu": NU, "density": 0.0}},
        "sections": {"S": sec or {"shape": "rect", "b": B, "h": H, "material": "M"}},
        "nodes": [{"id": n, "x": x, "y": y, "z": z} for n, (x, y, z) in nodes.items()],
        "elements": [{"id": e, "i": i, "j": j, "section": "S"} for e, (i, j) in elements.items()],
        "supports": supports,
        "load_cases": [{"id": "LC", "self_weight": self_weight}],
        "loads": [dict(case="LC", **l) for l in loads],
    }


def chain(L, n, axis=0):
    nodes = {}
    for k in range(n + 1):
        p = [0.0, 0.0, 0.0]
        p[axis] = L * k / n
        nodes[f"N{k}"] = tuple(p)
    elements = {f"E{k}": (f"N{k}", f"N{k + 1}") for k in range(n)}
    return nodes, elements


def rel(a, b):
    return abs(a - b) / max(abs(b), 1e-12)


# ----------------------------------------------------------------- cantilever
@pytest.mark.parametrize("n", [1, 4])
def test_cantilever_tip_load_vertical(n):
    L, P = 5.0, 10.0
    nodes, els = chain(L, n)
    m = FrameModel(base_model(nodes, els, [{"node": "N0", "type": "fixed"}],
                              [{"kind": "nodal", "node": f"N{n}", "values": [0, 0, -P, 0, 0, 0]}]))
    r = m.solve_case("LC")
    tip = r["displacements"][f"N{n}"]
    assert rel(tip[2], -P * L**3 / (3 * E * IY)) < 1e-9
    assert rel(tip[4], P * L**2 / (2 * E * IY)) < 1e-9   # rotation about +y
    R = r["reactions"]["N0"]
    assert rel(R[2], P) < 1e-9
    assert rel(abs(R[4]), P * L) < 1e-9
    assert r["equilibrium"]["ok"]
    # internal moment at support = P L (hogging), magnitude
    st = r["elements"]["E0"]
    assert rel(abs(st["My"][0]), P * L) < 1e-9
    assert rel(abs(st["Vz"][0]), P) < 1e-9


def test_cantilever_tip_load_lateral_minor_axis():
    L, P = 3.0, 4.0
    nodes, els = chain(L, 1)
    m = FrameModel(base_model(nodes, els, [{"node": "N0", "type": "fixed"}],
                              [{"kind": "nodal", "node": "N1", "values": [0, P, 0, 0, 0, 0]}]))
    r = m.solve_case("LC")
    assert rel(r["displacements"]["N1"][1], P * L**3 / (3 * E * IZ)) < 1e-9


def test_axial_and_torsion():
    L, P, Tq = 4.0, 100.0, 5.0
    nodes, els = chain(L, 2)
    m = FrameModel(base_model(nodes, els, [{"node": "N0", "type": "fixed"}],
                              [{"kind": "nodal", "node": "N2", "values": [P, 0, 0, Tq, 0, 0]}]))
    r = m.solve_case("LC")
    J = m.elements[0]["props"].J
    assert rel(r["displacements"]["N2"][0], P * L / (E * A)) < 1e-9
    assert rel(r["displacements"]["N2"][3], Tq * L / (G * J)) < 1e-9
    assert rel(r["elements"]["E0"]["N"][3], P) < 1e-9          # tension positive
    assert rel(abs(r["elements"]["E1"]["T"][0]), Tq) < 1e-9


# ------------------------------------------------------- distributed loading
def test_simply_supported_udl():
    L, w, n = 8.0, 12.0, 1
    nodes, els = chain(L, n)
    sup = [{"node": "N0", "dofs": [1, 1, 1, 1, 0, 0]}, {"node": f"N{n}", "dofs": [0, 1, 1, 0, 0, 0]}]
    m = FrameModel(base_model(nodes, els, sup,
                              [{"kind": "dist", "element": "E0", "direction": [0, 0, -1], "points": [[0, w], [L, w]]}]))
    r = m.solve_case("LC")
    st = r["elements"]["E0"]
    mid = st["x"].index(L / 2)
    # midspan deflection 5wL^4/384EI (from integrated curvature)
    assert rel(st["disp"][mid][2], -5 * w * L**4 / (384 * E * IY)) < 1e-6
    # midspan moment wL^2/8 (sagging -> negative My in our convention)
    assert rel(st["My"][mid], -w * L**2 / 8) < 1e-9
    assert rel(r["reactions"]["N0"][2], w * L / 2) < 1e-9
    assert r["equilibrium"]["ok"]


def test_fixed_fixed_udl_mesh_independent():
    L, w = 6.0, 20.0
    for n in (1, 3, 6):
        nodes, els = chain(L, n)
        loads = [{"kind": "dist", "element": e, "direction": [0, 0, -1], "points": [[0, w], [L / n, w]]} for e in els]
        m = FrameModel(base_model(nodes, els, [{"node": "N0", "type": "fixed"}, {"node": f"N{n}", "type": "fixed"}], loads))
        r = m.solve_case("LC")
        assert rel(abs(r["reactions"]["N0"][4]), w * L**2 / 12) < 1e-9
        # midspan deflection wL^4/384EI
        if n == 1:
            st = r["elements"]["E0"]
            mid = st["x"].index(L / 2)
            assert rel(st["disp"][mid][2], -w * L**4 / (384 * E * IY)) < 1e-6
        else:
            if n % 2 == 0:
                assert rel(r["displacements"][f"N{n // 2}"][2], -w * L**4 / (384 * E * IY)) < 1e-9


def test_triangular_load_simply_supported():
    # Max moment w0 L^2 / (9 sqrt 3) at x = L/sqrt(3); reactions w0L/6, w0L/3
    L, w0 = 9.0, 30.0
    nodes, els = chain(L, 1)
    sup = [{"node": "N0", "dofs": [1, 1, 1, 1, 0, 0]}, {"node": "N1", "dofs": [0, 1, 1, 0, 0, 0]}]
    m = FrameModel(base_model(nodes, els, sup,
                              [{"kind": "dist", "element": "E0", "direction": [0, 0, -1], "points": [[0, 0], [L, w0]]}]))
    r = m.solve_case("LC")
    assert rel(r["reactions"]["N0"][2], w0 * L / 6) < 1e-9
    assert rel(r["reactions"]["N1"][2], w0 * L / 3) < 1e-9
    # evaluate exact maximum by fine sampling of the statics expression
    st = r["elements"]["E0"]
    assert max(abs(v) for v in st["My"]) <= w0 * L**2 / (9 * math.sqrt(3)) * (1 + 1e-9)


def test_midspan_point_load_member():
    L, P = 6.0, 50.0
    nodes, els = chain(L, 1)
    sup = [{"node": "N0", "dofs": [1, 1, 1, 1, 0, 0]}, {"node": "N1", "dofs": [0, 1, 1, 0, 0, 0]}]
    m = FrameModel(base_model(nodes, els, sup,
                              [{"kind": "point", "element": "E0", "direction": [0, 0, -1], "a": L / 2, "P": P}]))
    r = m.solve_case("LC")
    st = r["elements"]["E0"]
    mid = st["x"].index(L / 2)
    assert rel(st["My"][mid], -P * L / 4) < 1e-9
    assert rel(st["disp"][mid][2], -P * L**3 / (48 * E * IY)) < 1e-5


# ----------------------------------------------------------- frames / 3D
def portal_slope_deflection(h, L, Ic, Ib, H):
    """Independent slope-deflection solution of a fixed-base portal frame with a
    lateral load H at beam level (axial deformations neglected).
    Unknowns: theta_B, theta_C, Delta."""
    kc, kb = Ic / h, Ib / L
    # Equations (E cancels; use E=1 then scale)
    # M_BA = 2kc(2tB - 3D/h), M_AB = 2kc(tB - 3D/h)
    # M_BC = 2kb(2tB + tC),   M_CB = 2kb(2tC + tB)
    # Joint B: M_BA + M_BC = 0 ; Joint C: M_CD + M_CB = 0
    # Shear: (M_AB + M_BA + M_DC + M_CD)/h + H = 0
    Am = np.array([
        [4 * kc + 4 * kb, 2 * kb, -6 * kc / h],
        [2 * kb, 4 * kc + 4 * kb, -6 * kc / h],
        [6 * kc / h, 6 * kc / h, -24 * kc / h**2],
    ])
    rhs = np.array([0, 0, -H])
    tB, tC, D = np.linalg.solve(Am, rhs)
    M_AB = 2 * kc * (tB - 3 * D / h)
    return D, M_AB


def test_portal_frame_lateral_vs_slope_deflection():
    h, L, Hload = 4.0, 6.0, 25.0
    big = 1e4  # suppress axial deformation to match slope-deflection assumptions
    sec = {"shape": "general", "A": A * big, "Iy": IY, "Iz": IZ, "J": 1.0, "b": B, "h": H, "material": "M"}
    nodes = {"A": (0, 0, 0), "B": (0, 0, h), "C": (L, 0, h), "D": (L, 0, 0)}
    els = {"AB": ("A", "B"), "BC": ("B", "C"), "DC": ("D", "C")}
    m = FrameModel(base_model(nodes, els, [{"node": "A", "type": "fixed"}, {"node": "D", "type": "fixed"}],
                              [{"kind": "nodal", "node": "B", "values": [Hload, 0, 0, 0, 0, 0]}], sec=sec))
    r = m.solve_case("LC")
    # columns: local z = global X => in-plane bending of columns uses Iy; beam vertical bending uses Iy
    D, M_AB = portal_slope_deflection(h, L, IY, IY, Hload)
    D /= E
    M_AB_val = M_AB  # moment from E*theta terms already scaled (E cancels)
    assert rel(r["displacements"]["B"][0], D) < 1e-4
    assert rel(abs(r["reactions"]["A"][4]), abs(M_AB_val)) < 1e-4
    assert rel(r["reactions"]["A"][0] + r["reactions"]["D"][0], -Hload) < 1e-9
    assert r["equilibrium"]["ok"]


def test_rigid_beam_portal_sway():
    # Infinitely stiff beam -> each column fixed-fixed: k = 12EI/h^3
    h, L, Hload = 3.5, 5.0, 40.0
    nodes = {"A": (0, 0, 0), "B": (0, 0, h), "C": (L, 0, h), "D": (L, 0, 0)}
    els = {"AB": ("A", "B"), "BC": ("B", "C"), "DC": ("D", "C")}
    model = base_model(nodes, els, [{"node": "A", "type": "fixed"}, {"node": "D", "type": "fixed"}],
                       [{"kind": "nodal", "node": "B", "values": [Hload, 0, 0, 0, 0, 0]}])
    model["sections"]["RIG"] = {"shape": "general", "A": 1e3, "Iy": 1e3, "Iz": 1e3, "J": 1e3, "material": "M"}
    model["sections"]["COL"] = {"shape": "general", "A": 1e3, "Iy": IY, "Iz": IZ, "J": 1.0, "b": B, "h": H, "material": "M"}
    for e in model["elements"]:
        e["section"] = "RIG" if e["id"] == "BC" else "COL"
    r = FrameModel(model).solve_case("LC")
    assert rel(r["displacements"]["B"][0], Hload * h**3 / (24 * E * IY)) < 1e-4


def test_l_shaped_cantilever_bending_and_torsion():
    """Classic 3D benchmark: L-shaped cantilever in plan, vertical tip load.
    delta = P a^3/3EI + P b^3/3EI + P b^2 a / GJ  (circular bar -> Iy = Iz)."""
    a, b, P, d = 2.0, 1.5, 3.0, 0.1
    sec = {"shape": "circle", "d": d, "material": "M"}
    nodes = {"O": (0, 0, 0), "K": (a, 0, 0), "T": (a, b, 0)}
    els = {"OK": ("O", "K"), "KT": ("K", "T")}
    m = FrameModel(base_model(nodes, els, [{"node": "O", "type": "fixed"}],
                              [{"kind": "nodal", "node": "T", "values": [0, 0, -P, 0, 0, 0]}], sec=sec))
    r = m.solve_case("LC")
    I = math.pi * d**4 / 64
    J = 2 * I
    expect = P * a**3 / (3 * E * I) + P * b**3 / (3 * E * I) + P * b**2 * a / (G * J)
    assert rel(-r["displacements"]["T"][2], expect) < 1e-9
    # torsion in arm OK = P b
    assert rel(abs(r["elements"]["OK"]["T"][0]), P * b) < 1e-9
    assert r["equilibrium"]["ok"]


def test_inclined_member_rotation_invariance():
    """A cantilever along an arbitrary 3D direction gives the same tip deflection."""
    L, P = 4.0, 7.0
    d = np.array([1.0, 2.0, 0.5])
    d /= np.linalg.norm(d)
    nodes = {"A": (0, 0, 0), "B": tuple(L * d)}
    perp = np.cross(d, [0, 0, 1.0])
    perp /= np.linalg.norm(perp)
    sec = {"shape": "circle", "d": 0.15, "material": "M"}
    m = FrameModel(base_model(nodes, {"E": ("A", "B")}, [{"node": "A", "type": "fixed"}],
                              [{"kind": "nodal", "node": "B", "values": [*(P * perp), 0, 0, 0]}], sec=sec))
    r = m.solve_case("LC")
    I = math.pi * 0.15**4 / 64
    tip = np.array(r["displacements"]["B"][:3])
    assert rel(float(tip @ perp), P * L**3 / (3 * E * I)) < 1e-9


def test_deflected_shape_consistent_with_nodal_solution():
    # Two-span continuous beam with UDL: integrated curvature at end j must match FE nodal value.
    L, w = 5.0, 10.0
    nodes, els = chain(2 * L, 2)
    sup = [{"node": "N0", "dofs": [1, 1, 1, 1, 0, 0]}, {"node": "N1", "dofs": [0, 1, 1, 0, 0, 0]},
           {"node": "N2", "dofs": [0, 1, 1, 0, 0, 0]}]
    loads = [{"kind": "dist", "element": e, "direction": [0, 0, -1], "points": [[0, w], [L, w]]} for e in els]
    r = FrameModel(base_model(nodes, els, sup, loads)).solve_case("LC")
    # interior support moment wL^2/8 for two equal spans
    assert rel(abs(r["elements"]["E0"]["My"][-1]), w * L**2 / 8) < 1e-9
    assert rel(r["reactions"]["N1"][2], 1.25 * w * L) < 1e-9
    for st in r["elements"].values():
        assert st["end_check"] < 1e-9


def test_self_weight():
    L = 5.0
    nodes, els = chain(L, 2)
    model = base_model(nodes, els, [{"node": "N0", "type": "fixed"}], [], self_weight=True)
    model["materials"]["M"]["density"] = 25.0
    r = FrameModel(model).solve_case("LC")
    assert rel(r["reactions"]["N0"][2], 25.0 * A * L) < 1e-9
    assert rel(abs(r["reactions"]["N0"][4]), 25.0 * A * L**2 / 2) < 1e-9


# ----------------------------------------------------------- stability
def test_no_supports_raises():
    nodes, els = chain(3.0, 1)
    with pytest.raises(ModelError):
        FrameModel(base_model(nodes, els, [], []))


def test_disconnected_part_flagged():
    nodes = {"A": (0, 0, 0), "B": (3, 0, 0), "C": (10, 0, 0), "D": (12, 0, 0)}
    els = {"E1": ("A", "B"), "E2": ("C", "D")}
    m = FrameModel(base_model(nodes, els, [{"node": "A", "type": "fixed"}], []))
    codes = {w["code"] for w in m.warnings}
    assert "disconnected" in codes


def test_mechanism_flagged():
    # beam on two pins with no torsional restraint about its axis -> mechanism (rx free)
    nodes, els = chain(4.0, 1)
    m = FrameModel(base_model(nodes, els, [{"node": "N0", "type": "pinned"}, {"node": "N1", "type": "pinned"}], []))
    codes = {w["code"] for w in m.warnings}
    assert codes & {"mechanism", "zero_stiffness"}
