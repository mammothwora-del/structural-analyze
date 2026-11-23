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

## Not yet included (planned)

- Bracing, trusses, purlins, member end releases, rigid diaphragms, spring supports, openings in walls and slabs.
- Copy/move/rotate tools, snapping, DXF/IFC import, OBJ/GLTF export, PDF reports.
- Buckling, design code checks (no utilisation ratios or compliance claims are made), database storage.

## Layout

```
backend/structural/   solver.py (FEM) · shell.py (MITC4 shell) · mesh.py (slab/wall meshing) · slabs.py (tributary) · generator.py · analysis.py · api.py
backend/tests/        benchmark + integration tests
frontend/src/         React + TypeScript + React Three Fiber
  lib/loadpath.ts     load path from element forces (flows, transfers, tracing)
  three/              merged member mesh, particles, diagrams, overlays
  components/         toolbar, sidebars, inspector, legend, dashboard
docs/conventions.md   units, axes, sign conventions, calculated vs. assumed
```

This is an analysis and visualisation tool. It does not verify that a structure is safe or code-compliant.
