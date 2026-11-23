# Units and sign conventions

## Units
Internal (solver and saved model files): kN, m, rad. Material input: E in MPa, density in kN/m³.
The **Units** selector only changes display and input:
* SI: kN, kN·m, MPa, kN/m², kN/m, m, mm.
* Metric (MKS, Thai practice): tf, tf·m, ksc (kgf/cm²), kg/m², t/m², kg/m; 1 tf = 9.80665 kN.
* Imperial: kip, kip·ft, ksi, psf, ksf, kip/ft, ft, in.

## Global axes
Z is vertical (up). Gravity acts in −Z. Grid lines 1, 2, 3… are along X, A, B, C… along Y.

## Element local axes (`solver.local_axes`)
* local x: from node i to node j.
* Non-vertical members: local z lies in the vertical plane and points up; local y = z × x.
* Vertical members: local z = global +X, local y = z × x.
* Section width b is along local y, depth h along local z.
* Iy (major) is about local y (bending in the x–z plane); Iz (minor) about local z.

## Element end forces
`end_i`, `end_j` = [Fx, Fy, Fz, Mx, My, Mz] in local axes: the force/moment the **node exerts on the member**.

## Internal forces (diagrams)
Forces on the cut face of the i-side part (exerted by the j-side part):
* N > 0 tension.
* Sagging of a horizontal beam under gravity gives My < 0 (diagram drawn on the tension side).
* Obtained by statics of the free body [0, x] using end_i and the member loads — exact for the applied load shapes.

## Deflected shape
Integrated from end i: u' = N/EA, θz' = Mz/EIz, v' = θz, θy' = My/EIy, w' = −θy.
The integrated values at end j are checked against the FE nodal solution (`end_check`).

## Load path quantities (`frontend/src/lib/loadpath.ts`)
* d: load-path direction (default gravity −Z when vertical load exists, otherwise the applied resultant).
* flow(x) = −(Rᵀ[N, Vy, Vz]) · d — force along d carried across the section; positive = toward end j.
* t_end = −(Rᵀ f_end) · d — positive: member delivers load to its node; negative: node delivers load into member.
* Member equilibrium: t_i + t_j = load applied directly on the member (exact).
* Node equilibrium: Σt + P·d + S·d + R·d = 0 (exact), S = force from slab/wall shells on the node.
* Slab/wall load flux (shell FEM): φ = −(d_x [n_x, n_xy] + d_y [n_xy, n_y] + d_z [v_x, v_y]) in panel axes, i.e. the
  traction on a cut projected on d, in kN/m. For a horizontal slab under gravity φ = (v_x, v_y).
* Trace up/down uses proportional sharing at nodes/members — an attribution convention (labelled in the UI).

## Shell elements (slabs and walls, Phase 2)
* Flat 4-node shell (`backend/structural/shell.py`): bilinear membrane + Reissner–Mindlin plate with MITC4 transverse
  shear (no shear locking), 2×2 Gauss, κ = 5/6. Drilling rotation: weak rigid-body-consistent penalty (γ = 10⁻³ G).
* Panel axes: z = normal (right-hand rule on the corner order; up for generated slabs), x = global X projected on the
  panel (global Y if the panel is perpendicular to X), y = z × x.
* Resultants per unit width: n_x, n_y, n_xy (tension +), m_x, m_y, m_xy (**+ = tension at the −z face**, i.e. sagging
  of a slab), v_x, v_y (force in +z on a face with outward normal +x / +y).
* Surface stresses: σ = n/t ± 6m/t²; σv = von Mises, max of top and bottom. Elastic, uncracked, no design check.
* Mesh (`backend/structural/mesh.py`): axis-aligned panels share global mesh lines (conforming mesh). Beams and
  columns are split at mesh nodes on them and reported back under their own ids. Slab/wall nodal results are
  averaged per panel.
* Slabs are modelled in the plane of the beam centrelines (no offset, no T-beam action). Wall base nodes get the
  wall's base support.

## What is calculated vs. assumed
| Item | Status |
|---|---|
| Frame displacements, reactions, end forces, N/V/M/T diagrams | Calculated (FEM, verified by tests) |
| Elastic extreme-fibre stress N/A ± My/Sy ± Mz/Sz | Calculated |
| Slab bending, membrane forces, deflection; shear walls | Calculated (shell FEM, verified by plate benchmarks) |
| Slab → beam load distribution | Slab analysis = Shell FEM: **calculated**. Slab analysis = Tributary: **assumed** 45° tributary areas |
| Footing soil pressure | **Assumed** rigid footing, linear full-contact pressure |
| Wind / seismic loads | **Simplified** generators (net pressure / ELF with user Cs), not code calculations |
| Load combinations (Thai, EN 1990, ASCE 7) | Presets of the factors only; editable; verify against the edition in force |
| Thai live loads (Ministerial Regulation 6) | Presets for convenience; verify for the project |
| Stress ratio | vs. user-defined limit, **not** a design check |
| Design utilisation | Not implemented — no safety/compliance claim |
