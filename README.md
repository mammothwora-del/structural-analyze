# Structural Analyze — 3D Structural Analysis & Load Path Visualization

A browser-based 3D structural engineering tool: build a multi-storey frame, apply loads, click **ANALYZE**, then switch to **Load Path** mode to watch the computed forces travel from slabs and beams through columns into the footings and soil.

Every result shown is computed by a real 3D finite element solver (frame elements for beams and columns, shell elements for slabs and walls). Anything that is an assumption (for example the optional slab-to-beam tributary distribution) is labelled as such in the interface and in [docs/conventions.md](docs/conventions.md).

## How to run (step by step)

### 1. Install the prerequisites (one time)
- **Python 3.10 or newer**: https://www.python.org/downloads/ — on Windows tick **"Add python.exe to PATH"** in the installer.
- **Node.js 18 or newer (LTS)**: https://nodejs.org/
- **Git** (optional, to clone): https://git-scm.com/downloads

Check in a terminal (Windows: *Command Prompt* or *PowerShell*; Mac: *Terminal*):
```
python --version      (Mac/Linux: python3 --version)
node --version
```

### 2. Get the code
Either download the ZIP from GitHub (green **Code** button → **Download ZIP**, then unzip), or:
```
git clone https://github.com/mammothwora-del/structural-analyze.git
cd structural-analyze
```

### 3. Start the app
- **Windows:** double-click `run.bat` (or run `run.bat` in a terminal opened in the folder).
- **Mac/Linux:** `./run.sh`

The first run downloads packages and takes a few minutes. When you see
`Uvicorn running on http://127.0.0.1:8000`, open **http://localhost:8000** in Chrome, Edge or Firefox.
Keep the terminal window open while you use the app; press `Ctrl+C` to stop it.

### Manual commands (if the script doesn't work)
```
python -m pip install -r backend/requirements.txt
cd frontend
npm install
npx vite build
cd ../backend
python -m uvicorn structural.api:app --port 8000
```

### 4. Use it
1. A sample 4-storey building is generated automatically (change it in the **Building** tab on the left, then **Generate building**).
2. Click **ANALYZE** (top right) or press F5. The status turns **SOLVED**.
3. The view switches to **Load Path**. Pick a case or combination in the **Load** dropdown (e.g. `ULS2`).
4. Click a member to inspect it, then **Trace down** / **Trace up**. Keys 1–7 switch modes; **Dashboard** is at the top.

### Troubleshooting
- `python` not found on Windows: reinstall Python with "Add to PATH" ticked, or use `py` instead of `python`.
- Red dot at the top right / "Solver backend not reachable": the terminal running the server was closed or failed — re-run the script and read the error.
- Port 8000 busy: change `--port 8000` to e.g. `--port 8010` and open that address.

### Development (hot reload)
```
cd backend && pip install -r requirements.txt && uvicorn structural.api:app --reload --port 8000
cd frontend && npm install && npm run dev      # http://localhost:5173 (proxies /api to :8000)
```

Run the solver tests: `cd backend && python -m pytest -q`

## What Phase 1 contains

**Modelling**
- Parametric building generator: grid spans in X/Y, storey heights, RC columns, main beams, optional secondary beams, slab panels, isolated footings with fixed or pinned supports.
- Material library (concrete C25/30–C40/50, steel S275/S355/A992), rectangular / I / circular / general sections with computed A, Iy, Iz, J.
- Edit: assign sections (single or multi-select), delete members, add a member between two nodes, change supports, undo. Save/open the model as JSON.
- Viewport: orbit, pan, zoom, perspective/orthographic, Iso/Top/Front/Right views, section cut by level, exploded view, hide/show component types, isolate, fullscreen.

**Loads**
- Load cases: DL (self-weight of members and slabs), SDL, LL, wind (simplified net facade pressure) and seismic (equivalent lateral force with a user coefficient).
- Area loads on slabs, line loads and point loads on members, nodal forces.
- Combinations: EN 1990 or ASCE 7 LRFD presets, fully editable; evaluated by exact linear superposition.
- Load visualisation with 3D arrows and magnitude labels, animated.

**Analysis engine** (`backend/structural/solver.py`)
- 3D linear static analysis, Euler–Bernoulli space-frame element, 6 DOF per node, sparse assembly and sparse LU (SuperLU).
- Consistent nodal loads for piecewise-linear distributed and concentrated member loads.
- Element end forces, N/Vy/Vz/T/My/Mz along every member, deflected shape by curvature integration, extreme-fibre stresses.
- Global equilibrium check of applied loads vs. reactions (forces and moments) for every case and combination.
- Stability diagnostics: no supports, parts not connected to a support, DOFs without stiffness, mechanisms (singular stiffness), high residual, unrealistically large displacements.

**Verification** (`backend/tests/`): 27 Phase 1 tests against closed-form textbook results, including cantilever tip load (both axes), axial and torsion, simply supported and fixed–fixed UDL, triangular load, midspan point load, two-span continuous beam, portal frame vs. an independent slope-deflection solution, rigid-beam portal sway, L-shaped cantilever with bending + torsion, rotation invariance of an inclined member, mesh independence, self-weight, slab tributary area conservation, node force balance on a full building, and instability detection.

**Results modes**
- Load Path: members coloured by the load they carry along the path direction; animated particles move the way the load actually travels (sign of the internal force), split at zero-shear points; slab tributary arrows; support reactions. Click any member to see incoming/outgoing loads, and trace the path down to the footings or up to the sources.
- Stress (|σ| / user limit), Deformation (scaled deformed shape with |u| contours), Internal Forces (N, Vy, Vz, T, My, Mz diagrams), Foundation Reactions (reaction arrows, rigid-footing soil pressure, q/q_allow).
- Element inspector, engineering dashboard (load totals, structural weight, reactions, extremes, critical members, storey load accumulation, equilibrium status), analysis log, warnings, reaction and member result tables, CSV / PNG / JSON export.

## Phase 2

- **Shell FEM for slabs and walls** (`backend/structural/shell.py`, `mesh.py`): flat 4-node MITC4 shell (membrane +
  Mindlin plate). Slabs are meshed and connected to the beams along their whole length, so the slab-to-beam load
  transfer is calculated (the 45° tributary method stays available as an option, labelled ASSUMED).
- **Shear walls** in the generator (outer frames, X or X and Y), meshed with the same shells, fixed or pinned at the base.
- Slab and wall contours: σv, m_x, m_y, m_xy, n_x, n_y, n_xy, v_x, v_y; slab/wall deflection on the deformed shape;
  **deformation animation**; slab and wall **load flux arrows** in Load Path mode; slab/wall inspector with the load
  delivered to each beam.
- **Units**: SI (kN, m), Metric MKS as used in Thai practice (tf, kg/m², ksc) and Imperial (kip, ft, psf, ksi).
- **Thai standard presets**: EIT 1008-38 load combinations (1.4D+1.7L, 0.75(1.4D+1.7L+1.7W), 0.9D+1.3W),
  DPT 1301/1302-61 seismic combinations, Thai concrete fc′ 180–320 ksc (Ec = 15100√fc′), SS400/SM520 steel,
  Ministerial Regulation No. 6 live loads by occupancy. Presets are editable and must be verified for the project.
- Verification: 13 more tests, including simply supported and clamped square plates against Timoshenko's
  coefficients (w = 0.00406 qa⁴/D and 0.00126 qa⁴/D, m = 0.0479 qa²), convergence, a distorted mesh, a membrane patch
  test, a rotated plate, a shell cantilever, node balance with shells, shell vs tributary column loads, and walls
  attracting lateral load.

## Phase 3: trusses and more complex structures

- **Member end releases** (`backend/structural/solver.py`): any rotational DOF at either end can be released
  (pinned ends, truss members). Implemented by static condensation of the element stiffness and fixed-end forces,
  with recovery of the released rotations so that the deflected shape between nodes stays exact.
- **Truss members** (`truss: true` or type `truss`): moments released at both ends, axial force only under nodal
  loads. Rotations at joints where every member is pinned are fixed automatically and reported as INFO; real
  mechanisms (a truss panel without a diagonal, a roof without bracing) are still reported as errors.
- **Hollow sections**: circular tubes (CHS: d, t) and rectangular/square boxes (RHS/SHS: b, h, t; Bredt torsion).
- **New generators** (left panel, *Structure type*):
  - Planar truss: Pratt, Howe, Warren or pitched (gable, Pratt-pattern web), any span, depth and panel count.
  - Steel warehouse: pitched Pratt roof trusses on steel columns, simply supported purlins, eave struts,
    bottom-chord ties, roof and wall X-bracing in the end bays (switch the bracing off to see the stability check
    report the mechanism).
  - Space truss roof: square-on-square double-layer grid on tube columns (or pinned supports).
  - Buildings: steel X or single-diagonal bracing in the end bays of the outer frames.
- **Modelling tools**: end-release editor in the inspector (Rigid / Pin i / Pin j / Pin both / Truss, also for a
  multi-selection), *Add node* by coordinates in the Model tab, tube and box sections in the Sections tab, hinge
  symbols at released ends, truss chord/web/purlin colours, and the model's assumptions listed in the Model tab.
- Verification: 17 more tests (57 in total): a Pratt truss against the method of joints and virtual-work deflection,
  pinned-pinned and fixed-pinned beams (qL²/8, 5qL⁴/384EI, reactions 5qL/8 and 3qL/8), a truss mechanism, hollow
  section properties, the top chord force wL²/(8h) of the generated truss, equilibrium of every generator, and
  bracing reducing drift.

## More truss and roof types

- **12 planar truss types**:
  - Parallel chords: Pratt, Howe, Warren, Warren with verticals, K-truss.
  - Roof trusses: pitched Pratt, pitched Howe, Fink (W), fan, scissors, mono-pitch, bowstring.
- **Steel warehouse roof options**: any of the roof trusses or a **portal frame** (I-section rafters rigid to the columns).
  - **Multi-span**: several spans share the internal column lines. Mono-pitch spans give a saw-tooth roof.
- **Lattice roofs** (new *Lattice roof* type):
  - Single-layer tube **barrel vault**: braced, cross-braced or ribbed.
  - Spherical **dome**: Schwedler, lamella or ribbed.
  - Joints are rigid and the roof is pinned along the springing line.
  - The app warns that buckling and snap-through are not checked.
- **Generate panel**: picture buttons for every truss, warehouse roof, vault and dome pattern, plus a live preview.
- **Verification**:
  - Member forces of every truss type, with and without depth at the supports, are compared against an independent
    2D bar solver.
  - Fink truss checked by hand calculation.
  - Warren bottom chord force = M/h.
  - Load totals and stability of every warehouse roof and multi-span layout.
  - Equal base reactions in the domes (rotational symmetry).
  - 102 tests in total.

## Stability: buckling and P-Delta

Open the **Stability** mode (key `8`, or *Analyze → Stability*), pick a load case or combination in the top bar, then:

- **Buckling**: elastic critical load factors α<sub>cr</sub> and animated mode shapes.
  - Linear eigenvalue buckling: (K + α K<sub>G</sub>) φ = 0, with the axial forces from a linear analysis of the chosen load.
  - Every member is split into 2 to 8 segments (default 4), so single members can buckle between their joints.
  - α<sub>cr</sub> below 10 is flagged (EN 1993-1-1 §5.2.1 then asks for second-order analysis).
- **P-Delta**: second-order analysis of the chosen load, iterating (K + K<sub>G</sub>(N)) u = F until the axial
  forces converge.
  - Shows the linear vs second-order maximum displacement and the amplification.
  - The result is added to the Load list as `PD:<load>`, so forces, deformation, stress, reactions and tables can
    all show the second-order values.
  - A load above the buckling load is refused (the tangent stiffness is no longer positive definite).
- **Verification** (`tests/test_stability.py`, 22 tests):
  - Euler columns (cantilever, pinned, fixed-pinned, fixed-guided) within 0.1 to 0.2 %, including convergence from above.
  - Pin-ended truss column, sway portal with a rigid beam (K = 2).
  - P-Delta cantilever against the exact beam-column formula within 0.01 %; base moment = HL + PΔ.
  - Every generator runs both analyses. 124 tests in total.
- Limits: elastic, perfect geometry (no imperfections, residual stresses or yielding). Slabs and walls add
  stiffness but no geometric stiffness, so plate buckling is not included. These results are not a design check.

## Steel member design

Open **Steel Design** (key `9`, or *Analyze → Steel member design*), choose the code and press *Check steel members*.
Every steel member is checked for all ultimate combinations of the model (service combinations are skipped).
Members are coloured by utilisation; click one for every check with its clause, demand, capacity, governing
combination and location, and to set its design values (K about each axis, unbraced length for LTB, Cb / C1).

- **AISC 360-16 (LRFD)**: tension D2 (gross yielding); compression E3 / E4 (flexural and torsional buckling) with
  slender elements by E7; flexure F2, F3, F6 (I), F7 (box, incl. slender flanges), F8 (round HSS), F11 (solid);
  shear G2, G4, G5, G6; torsion of HSS H3; interaction H1-1 at every station. Cb from the moment diagram.
- **EN 1993-1-1**: section class (Table 5.2) at every station; class 4 by the effective area of EN 1993-1-5 4.4;
  tension, compression, bending, shear with the 6.2.8 reduction, bending + axial 6.2.9; flexural and torsional
  buckling 6.3.1 (curves from Table 6.2); lateral-torsional buckling 6.3.2.2 (M_cr with C1 from the moment diagram);
  member interaction 6.3.3 with the Annex B factors. gamma_M0 = gamma_M1 = 1.0 (recommended values).
- **Thai EIT**: the AISC 360-16 LRFD equations with TIS steel grades (SS400, SM520) and the model's Thai combinations.
  The app says so; confirm against the EIT steel standard edition in force.
- A member outside the implemented clauses (for example a class 4 tube, a slender I-section web in AISC, steel above
  S460) is shown as **not covered**, with the reason, instead of being given a number.
- Not checked: connections and net-section rupture, web crippling under point loads, torsion of open sections,
  seismic detailing, and second-order effects (use the Stability mode). Default K = 1.0 (braced member) is labelled
  as an assumption on every member.
- **Verification** (`tests/test_steel_design.py`, 22 tests): EN 1993 buckling curve values at unit slenderness
  (0.6656 / 0.5970 / 0.5399 / 0.4671); hand calculations of a braced compact beam (plastic moment, web shear), an
  unbraced beam in the inelastic and elastic LTB ranges with Cb = 1.136 for uniform load, a pinned column (AISC E3,
  EN 1993 curve b), a tension member, a class 4 box with its effective area. 146 tests in total.

## RC beam and column design (Thai EIT 1008-38)

In **Design** mode (key `9`), the *RC (Thai EIT)* tab designs the reinforcement of every rectangular concrete beam and
column for all ultimate combinations (pick the main bar grade SD30/SD40/SD50, stirrup grade and cover). EIT 1008-38
follows ACI 318-95 strength design; the equations use kgf, cm and ksc as in Thai practice.

- **Beams**: bottom and top bars for the largest positive and negative moments (rho_min, 4/3 rule, rho <= 0.75 rho_b,
  bars fitted in one or two layers with clear spacing >= db and 2.5 cm); stirrups for the largest shear (Vc = 0.53
  sqrt(fc') bw d, spacing limits d/2 or d/4, minimum Av); torsion above the threshold with closed stirrups, longitudinal
  Al (top, bottom and side bars) and the section-size check (11-18).
- **Columns** (tied): bars around the perimeter (1 % to 8 %), P-M interaction about both axes by strain compatibility,
  phi from 0.70 to 0.90, 0.80 P0 cap, biaxial bending by the linear load contour (conservative), nonsway slenderness
  magnification with k = 1.0 assumed, ties (16 db, 48 tie diameters, least dimension) and shear with axial load.
- Click a member to see the bars drawn in its section, the stirrups / ties and every check with its clause.
- Not designed: deflection and cracking, anchorage / laps / curtailment, beam-column joints, seismic detailing,
  slabs, walls, footings, circular or spiral columns. If the combinations are not the Thai ones, the app says so.
- **Verification** (`tests/test_rc_design.py`, 9 tests): beta1 and rho_b (0.0262 for fc' 240 ksc, SD40), the
  singly reinforced section, a strain-compatibility point worked by hand, the column axial limit and phi, the
  moment magnifier, and a simply supported beam (bars, stirrup spacing, phi Vn) worked by hand. 155 tests in total.

## Reports, project files and DXF import

- **Project files** (*File → Save project*, `Ctrl+S`): a `.sproj` file holds the model and your settings (display units,
  steel code, RC bar grades and cover, report engineer / project). Results are not stored: run the analysis again after
  *File → Open project*, which also opens a plain model `.json`.
- **DXF import** (*File → Import DXF wireframe*): reads LINE, LWPOLYLINE and POLYLINE entities of an ASCII DXF drawn in
  3D (or as an X-Z elevation) with Z up. Units from the file header or chosen by you; end points closer than the merge
  tolerance become one node; a member is split where another member ends on it, and (optionally) where two members
  truly intersect in 3D. Layer names with COL / BEAM / BRAC / TRUSS set the member type, otherwise the direction does.
  Sections, supports (at the lowest nodes) and the self-weight load case are **defaults** and are labelled as such:
  replace them with the project values. Blocks, arcs, text and binary DXF / DWG are not imported, and the import says
  what it skipped. Members not connected to a supported part are listed.
- **PDF calculation report** (*Export → PDF calculation report*): the server re-runs the analysis and the chosen
  designs from the current model and writes a PDF: model data, loads and combinations, solver log, equilibrium check,
  reactions, extreme internal forces per load, a member force envelope, optional elastic buckling factors, steel and
  RC design tables with the check details of the most utilised members, the notes and the limitations. Every section is
  labelled INPUT, ASSUMED or CALCULATED, and the report says that it is not a statement that the structure is safe.
  A picture of the 3D view can be added (marked as an illustration).
- **Verification**: `tests/test_dxf_import.py` (units, merging, T-junctions, 3D crossings, brace releases, errors) and
  `tests/test_report.py` (the utilisations and reactions printed match the calculation, the API endpoints). 170 tests.

## Not yet included (planned)
- Tension-only bracing, rigid diaphragms, spring supports, openings in walls and slabs.
- Copy/move/rotate tools, snapping, IFC import, OBJ/GLTF export, database storage.

## Layout

```
backend/structural/   solver.py (FEM) · shell.py (MITC4 shell) · mesh.py (slab/wall meshing) · slabs.py (tributary) · generator.py · analysis.py · api.py
                      stability.py · steel_design.py · rc_design.py · dxf_import.py · report.py (PDF)
backend/tests/        benchmark + integration tests
frontend/src/         React + TypeScript + React Three Fiber
  lib/loadpath.ts     load path from element forces (flows, transfers, tracing)
  three/              merged member mesh, particles, diagrams, overlays
  components/         toolbar, sidebars, inspector, legend, dashboard
docs/conventions.md   units, axes, sign conventions, calculated vs. assumed
```

This is an analysis and visualisation tool. It does not verify that a structure is safe or code-compliant.
