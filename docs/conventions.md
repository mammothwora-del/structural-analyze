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

## End releases and trusses (Phase 3)
* `element.releases = {"i": [ux,uy,uz,rx,ry,rz], "j": [...]}` in **local** element axes, 1 = released. Only
  rotations can be released (translations raise a model error). Torsion released at both ends is kept at end i.
* `truss: true` (or `type: "truss"`) = releases i `[0,0,0,0,1,1]`, j `[0,0,0,1,1,1]`.
* Element stiffness and fixed-end forces are condensed: K* = Kcc − Krcᵀ Krr⁻¹ Krc, P* = Pc − Krcᵀ Krr⁻¹ Pr; the
  released end rotations are recovered after the solve for the deflected shape.
* A load on a truss member (e.g. self-weight) still bends it between its ends as a simply supported beam; the
  member stays pin-ended. Joint rotations with zero stiffness (all connected members pinned) are fixed and reported.
* Generated roof loads: planar and space trusses lump q × tributary length/area at the top nodes; the warehouse
  spreads q × purlin spacing as line loads on the purlins (sheeting spanning one way). All three are **assumed**.
* Bracing is linear elastic in tension and compression. No tension-only behaviour.
* Warehouse spans: `spans` (a list, or text such as "20, 15") replaces `span` × `n_spans`. With
  `roof_layout: "continuous"` one roof truss or rafter spans the full width. Its panel points include every inner
  column line, and the ridge for symmetric roofs. Each stretch between them gets equal panels, close to (mean span) /
  panels. Inner columns stop at the bottom chord, and the post above them stays a truss web. The truss is
  continuous over those columns, so the bottom chord next to them is in compression under gravity. That force
  comes out of the analysis and is not assumed. `roof_layout: "repeat"` (the default) keeps one roof per span.

## Buckling and P-Delta (`structural/stability.py`)
* Geometric stiffness of a frame member with axial force N (tension positive):
  K<sub>G</sub> = N ∫ (N<sub>v</sub>'ᵀN<sub>v</sub>' + N<sub>w</sub>'ᵀN<sub>w</sub>') dx with the cubic Hermite shape functions of the
  elastic element, plus N (I<sub>y</sub> + I<sub>z</sub>) / (A L) on the twist DOFs. Released ends are condensed with the same
  transformation as the elastic stiffness.
* Members are subdivided (buckling: 4 segments by default, P-Delta: 2). End releases stay at the member ends.
  Pin-ended members keep a small internal spring on the twist of the interior nodes (a pin-ended rod's twist carries no load).
* Buckling: (−K<sub>G</sub>) φ = μ K φ, α<sub>cr</sub> = 1/μ for the largest μ. Mode shapes are normalised to a maximum
  translation of 1 (dimensionless; the display scale is arbitrary).
* P-Delta: N from the previous iteration, until max |ΔN| / max |N| < 1e-5. The number of negative pivots of
  K + K<sub>G</sub> (Sylvester's law of inertia) detects a load above the lowest buckling load.
* P-Delta results are for one load case or combination: second-order results do not superpose.
* Shells (slabs, walls) contribute elastic stiffness only.

## What is calculated vs. assumed
| Item | Status |
|---|---|
| Frame displacements, reactions, end forces, N/V/M/T diagrams | Calculated (FEM, verified by tests) |
| Elastic extreme-fibre stress N/A ± My/Sy ± Mz/Sz | Calculated |
| Slab bending, membrane forces, deflection; shear walls | Calculated (shell FEM, verified by plate benchmarks) |
| Slab → beam load distribution | Slab analysis = Shell FEM: **calculated**. Slab analysis = Tributary: **assumed** 45° tributary areas |
| Truss member forces, pinned-end members | Calculated (FEM with condensed end releases, verified against method of joints) |
| Roof load to truss nodes / purlins | **Assumed** tributary lumping (trusses) or one-way sheeting (warehouse) |
| Out-of-plane restraint of planar trusses | **Assumed** lateral restraint at every node (purlins/bracing not modelled) |
| Portal frame knees and ridge | **Assumed** rigid, no haunches modelled |
| Lattice roofs (vault, dome) | Linear FEM with rigid joints; linear buckling available in Stability mode; **snap-through / imperfection sensitivity NOT checked** |
| Lattice roof supports | **Assumed** pinned along the springing line (rigid ring beam / walls) |
| Bracing behaviour | Linear, tension and compression; **no** tension-only |
| Elastic critical load factors α<sub>cr</sub>, buckling modes | Calculated (eigenvalue buckling of the perfect elastic structure; verified against Euler) |
| P-Delta (second-order) displacements and forces | Calculated (geometric stiffness iteration; verified against the exact beam-column solution) |
| Imperfections, residual stresses, yielding, plate/shell buckling | **Not** included in the stability analysis |
| Footing soil pressure | **Assumed** rigid footing, linear full-contact pressure |
| Wind / seismic loads | **Simplified** generators (net pressure / ELF with user Cs), not code calculations |
| Load combinations (Thai, EN 1990, ASCE 7) | Presets of the factors only; editable; verify against the edition in force |
| Thai live loads (Ministerial Regulation 6) | Presets for convenience; verify for the project |
| Stress ratio | vs. user-defined limit, **not** a design check |
| Steel member utilisation (AISC 360-16 LRFD, EN 1993-1-1, Thai EIT via AISC) | Calculated for the listed clauses only (verified against hand calculations); members outside them are reported **not covered** |
| Effective length factors K, unbraced length, Cb / C1 | **Assumed** K = 1.0 and unbraced length = member length unless set per member; Cb / C1 from the moment diagram |
| Hollow-section buckling curve (EN 1993) | **Assumed** cold-formed (curve c) unless the section says `fab: "hot"` |
| Connections, net section, web crippling, open-section torsion, seismic detailing | **Not** checked |
| RC beam and column reinforcement (EIT 1008-38 / ACI 318-95) | Calculated for the listed clauses (verified against hand calculations); members outside them reported **not covered** |
| RC column slenderness | **Assumed** nonsway (braced), k = 1.0, Lu = member length |
| RC deflection, cracking, anchorage, joints, seismic detailing, slabs, walls, footings | **Not** designed |
| Deflection of beam spans, cantilevers and planar trusses; storey drift | Calculated (linear, gross sections; verified against 5wL⁴/384EI, PL³/3EI) |
| Deflection and drift limits (L/360, L/240, L/180, H/400, H/200) and the wind factor for deflection | **Assumed** defaults, editable |
| Seismic drift, vibration, ponding, long-term concrete deflection | **Not** checked |

## Steel design (`structural/steel_design.py`)
* Design forces: linear superposition of the load-case results for each ultimate combination (combinations whose id
  or name contains SLS, SERV, service or characteristic are skipped). First-order forces.
* Axes: y = major (My, Vz), z = minor (Mz, Vy). Compression N < 0.
* Section properties for design ignore fillet and corner radii, except sizes from the supplier tables
  (`steel_tables.py`): those use the table's A, I and S; Z = Z_dims · S_table / S_dims; J, Cw and the shear centre from
  the dimensions. Flat widths of hollow sections are b − 3t.
* Channel (`shape: channel`, h, b, tw, tf): y = major axis (the axis of symmetry), z = minor; Sz is the smaller
  modulus (to the flange tips). Shear centre e = 3b'²tf / (6b'tf + h'tw) from the web centre-line, Cw =
  tf b'³ h'² / 12 · (3b'tf + 2h'tw) / (6b'tf + h'tw) with centre-line b' = b − tw/2, h' = h − tf.
* Equal angle (`shape: angle`, b, t): principal axes. y = u (major, along the axis of symmetry through the heel),
  z = v (minor). Su = Iu / (b/√2) (leg tips); Sv = Iv / max(√2·c, (b + t)/√2 − √2·c). The shear centre is at the
  heel: x0 = √2 (c − t/2). Set the member roll so that local y is the u axis.
* Channels and angles are singly symmetric about the major axis, so flexural-torsional buckling (AISC E4-3) couples
  torsion with major-axis buckling.
* Lip channel (`shape: lipchannel`, h, b, c, t): properties from the table (or square-cornered plates); no design
  rules (not covered).
* EN 1993 class: the worst class over all stations and combinations, ignoring actions below 1 % of the resistance.
* Member checks use the largest moments along the member with C_m from Table B.3 (linear moment: 0.6 + 0.4ψ ≥ 0.4;
  span moment governing: 1.0, conservative). Cross-section checks are made at every station.

## Suggested steel sizes (`structural/steel_sizing.py`)
* A group is a section id. Every member of the group gets the same size, and the group's worst member governs.
* Candidates are standard sizes of the chosen family, lightest first, from `steel_catalog.py`. "Same shape" means:
  I to H + I-beam, channel to C, angle to L, box to SHS + RHS, pipe to CHS (lip channels are never picked). The first candidate passes when every member of the group meets the target
  utilisation with the current forces and, if asked, KL/r ≤ 200 (members ever in compression) or L/r ≤ 300 (members
  only in tension).
* Repeat: analyse, size every group, until no group changes (at most 6 passes). A group that returns to a size it had
  in an earlier pass only moves to heavier sizes from then on (it keeps its current size while that still passes). The final model is then analysed and
  checked by `steel_design()`. Only that result is reported, as **calculated**.
* A group where even the largest size fails keeps the largest size and is flagged.
* With `check_deflection`, every pass also runs `deflection_checks()`. A span or storey with ratio r > 1 sets, for each
  section in it, a minimum of r × the current Iy or Iz (the axis of the deflection) or A (trusses). Candidates below it
  are skipped. The final deflection check of the final model is reported.

## Deflection and drift (`structural/serviceability.py`)
* Beam span: chain of `type: beam` elements (roles rib, ring, arch, longitudinal, diagonal, lattice excluded) with the
  same role, turning less than 35° at each node; stops at a vertical support (one that restrains uz; lateral
  restraints do not count), at a node with a column or truss member, or at a branch. Deflection at every result
  station = displacement − linear interpolation of the end displacements (cantilever: − root displacement), component
  perpendicular to the chord. Axis "y" (bending about local y, Iy) when the local-z component dominates.
* Truss: connected `type: truss` elements; planar when the plan offset from the principal line is ≤ max(5 % of the
  length, 0.3 m). Vertical deflection relative to the bracketing supports, limit on that support-to-support span.
* Drift: collinear column stacks (within 10°), split at the highest node of each level. Horizontal relative
  displacement / height. Multi-storey (any column with level ≥ 2): drift_multi, otherwise drift_single.
* Limits: "total" combinations use the total limit; "live" the live limit; "wind" the live limit for roof members only
  (roles purlin, eave, rafter, girt, roof beam, and trusses). Drift uses every serviceability combination.

## Project files, DXF import and PDF report

- `.sproj` = `{"format": "structural-analyze-project", "version": 1, "saved_at", "model", "settings"}`. Results are
  never saved, so an opened project is always recalculated by the current solver. A newer file version is refused.
- DXF (`structural/dxf_import.py`): coordinates scaled to m (`$INSUNITS` 1 in, 2 ft, 4 mm, 5 cm, 6 m; mm when absent).
  Nodes merged on a grid of the tolerance (default 5 mm). Split at end nodes lying on a member and, unless
  `connect_crossings` is false, at true 3D intersections (closest distance <= tolerance inside both lines). Columns are
  oriented bottom to top. Braces are pinned (ry, rz released; rx at end i) only at the ends of the drawn line and stay
  continuous through crossings, so an X-brace crossing node is stable. ASSUMED: default sections per type and material,
  supports at the lowest level, load case DL with self-weight, the standard's default combinations.
- PDF (`structural/report.py`, reportlab): everything is recomputed on the server from the model sent; the screenshot
  is the only thing taken from the browser. Labels: INPUT (model data), ASSUMED (defaults and simplifications),
  CALCULATED (analysis and design results). Greek letters are spelled out (alpha_cr, rho, phi): the fonts lack them.
  `lang="th"`: text from `structural/report_i18n.py` (missing keys fall back to English), Sarabun font, shaped with
  uharfbuzz (refused with a clear message if it is not installed). Thai words cannot be split inside a word, so table
  columns are widened to the longest Thai header word.
  Forces in kN, moments in kN·m; combination results are linear sums of the load-case results.
