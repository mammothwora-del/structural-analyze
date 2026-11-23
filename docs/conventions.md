# Units and sign conventions

## Units
Internal: kN, m, rad. Displayed: kN, kN/m, kN/m², kN·m, MPa, mm.
Material input: E in MPa, density in kN/m³. Section input: metres (UI: mm).

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
* Node equilibrium: Σt + P·d + R·d = 0 (exact).
* Trace up/down uses proportional sharing at nodes/members — an attribution convention (labelled in the UI).

## What is calculated vs. assumed (Phase 1)
| Item | Status |
|---|---|
| Frame displacements, reactions, end forces, N/V/M/T diagrams | Calculated (FEM, verified by tests) |
| Elastic extreme-fibre stress N/A ± My/Sy ± Mz/Sz | Calculated |
| Slab → beam load distribution | **Assumed**: 45° tributary areas (no slab FEM yet) |
| Footing soil pressure | **Assumed** rigid footing, linear full-contact pressure |
| Wind / seismic loads | **Simplified** generators (net pressure / ELF with user Cs), not code calculations |
| Stress ratio | vs. user-defined limit, **not** a design check |
| Design utilisation | Not implemented — no safety/compliance claim |
