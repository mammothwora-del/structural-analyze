"""High-level analysis driver: model dict -> complete results for all load cases."""
from __future__ import annotations

import time

import numpy as np

from .slabs import expand_area_loads
from .solver import FrameModel, ModelError

ROUND = 6  # significant digits kept in the JSON output


def _r(v):
    if isinstance(v, float):
        return float(f"{v:.{ROUND}g}")
    if isinstance(v, list):
        return [_r(x) for x in v]
    if isinstance(v, dict):
        return {k: _r(x) for k, x in v.items()}
    return v


def analyze(model: dict, n_stations: int = 11) -> dict:
    t0 = time.perf_counter()
    log = []
    analysis_model, tributary, warnings = expand_area_loads(model)
    log.append(f"Slab panels: {len(tributary)}; area loads converted to beam line loads by tributary areas "
               f"(Phase 1 approximation, slabs are not FE-analysed).")
    fm = FrameModel(analysis_model)
    warnings += fm.warnings
    log.append(f"Assembled {len(fm.elements)} frame elements, {len(fm.active_nodes)} nodes, "
               f"{fm.ndof} DOF ({int(fm.restrained.sum())} restrained), nnz(K) = {fm.K.nnz}.")
    log.append(f"Sparse LU factorisation done ({'regularised - MECHANISM' if fm.regularized else 'OK'}).")
    fm.prepare_stations([c["id"] for c in analysis_model.get("load_cases", [])])
    cases = {}
    for c in analysis_model.get("load_cases", []):
        r = fm.solve_case(c["id"], n_stations)
        eq = r["equilibrium"]
        log.append(f"Case {c['id']}: sum applied Fz = {eq['applied'][2]:.3f} kN, sum reactions Fz = "
                   f"{eq['reactions'][2]:.3f} kN, force error {eq['force_error']:.2e} kN, moment error "
                   f"{eq['moment_error']:.2e} kNm -> {'EQUILIBRIUM OK' if eq['ok'] else 'EQUILIBRIUM FAILED'}")
        for w in r["warnings"]:
            w = {**w, "case": c["id"]}
            warnings.append(w)
        cases[c["id"]] = r
    # Member loads (as applied to each element) for inspection / load visualisation
    member_loads = {}
    for ld in analysis_model.get("loads", []):
        if ld["kind"] in ("dist", "point"):
            member_loads.setdefault(ld["element"], []).append(ld)
    dt = time.perf_counter() - t0
    log.append(f"Analysis completed in {dt * 1000:.0f} ms.")
    return _r({
        "ok": not any(w["level"] == "error" for w in warnings),
        "warnings": warnings,
        "log": log,
        "elements": fm.element_info(),
        "unstable_dofs": sorted(set(fm.unstable_dofs)),
        "tributary": tributary,
        "member_loads": member_loads,
        "nodal_loads": [l for l in analysis_model.get("loads", []) if l["kind"] == "nodal"],
        "cases": cases,
        "solver": {"type": "3D linear static, Euler-Bernoulli frame, 6 DOF/node, sparse LU (SuperLU)",
                   "ndof": fm.ndof, "nnz": int(fm.K.nnz), "time_ms": dt * 1000},
    })


__all__ = ["analyze", "ModelError"]
