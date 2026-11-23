# Structural Analyze — 3D Structural Analysis & Load Path Visualization

A browser-based 3D structural engineering tool: build a multi-storey frame, apply loads, click **ANALYZE**, then switch to **Load Path** mode to watch the computed forces travel from slabs and beams through columns into the footings and soil.

Every result shown is computed by a real 3D frame finite element solver. Anything that is an assumption (for example the slab-to-beam tributary distribution in Phase 1) is labelled as such in the interface and in [docs/conventions.md](docs/conventions.md).

## Quick start

Requirements: Python 3.10+, Node 18+.

```bash
./run.sh            # installs deps, builds the frontend, serves everything at http://localhost:8000
```

Development (hot reload):

```bash
cd backend && pip install -r requirements.txt && uvicorn structural.api:app --reload --port 8000
cd frontend && npm install && npm run dev      # http://localhost:5173 (proxies /api to :8000)
```

Run the solver tests:

```bash
cd backend && python -m pytest -q
```

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

**Verification** (`backend/tests/`): 27 tests against closed-form textbook results, including cantilever tip load (both axes), axial and torsion, simply supported and fixed–fixed UDL, triangular load, midspan point load, two-span continuous beam, portal frame vs. an independent slope-deflection solution, rigid-beam portal sway, L-shaped cantilever with bending + torsion, rotation invariance of an inclined member, mesh independence, self-weight, slab tributary area conservation, node force balance on a full building, and instability detection.

**Results modes**
- Load Path: members coloured by the load they carry along the path direction; animated particles move the way the load actually travels (sign of the internal force), split at zero-shear points; slab tributary arrows; support reactions. Click any member to see incoming/outgoing loads, and trace the path down to the footings or up to the sources.
- Stress (|σ| / user limit), Deformation (scaled deformed shape with |u| contours), Internal Forces (N, Vy, Vz, T, My, Mz diagrams), Foundation Reactions (reaction arrows, rigid-footing soil pressure, q/q_allow).
- Element inspector, engineering dashboard (load totals, structural weight, reactions, extremes, critical members, storey load accumulation, equilibrium status), analysis log, warnings, reaction and member result tables, CSV / PNG / JSON export.

## Not in Phase 1 (planned)

- Shell/plate FEM for slabs and walls (replacing the tributary assumption), stress contours on slabs.
- Walls, bracing, trusses, purlins, member end releases, rigid diaphragms, spring supports.
- Copy/move/rotate tools, snapping, DXF/IFC import, OBJ/GLTF export, PDF reports.
- Buckling, design code checks (no utilisation ratios or compliance claims are made), database storage.

## Layout

```
backend/structural/   solver.py (FEM) · slabs.py (tributary) · generator.py · analysis.py · api.py (FastAPI)
backend/tests/        benchmark + integration tests
frontend/src/         React + TypeScript + React Three Fiber
  lib/loadpath.ts     load path from element forces (flows, transfers, tracing)
  three/              merged member mesh, particles, diagrams, overlays
  components/         toolbar, sidebars, inspector, legend, dashboard
docs/conventions.md   units, axes, sign conventions, calculated vs. assumed
```

This is an analysis and visualisation tool. It does not verify that a structure is safe or code-compliant.
