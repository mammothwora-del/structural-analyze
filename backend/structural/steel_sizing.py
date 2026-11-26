"""Suggest steel sections: the lightest standard size of each section group that passes the steel checks.

Every member that uses a section id is one group (all columns "COL", all chords "CHO", ...). For each group the
lightest size of the chosen family is taken whose utilisation is at most the target for every member of the group,
with the internal forces of the current analysis. A group that comes back to a size it had before (a lighter, stiffer
size attracts more force) only moves up from then on, so the passes settle. Changing sizes changes the stiffness and the self-weight and so
the forces, so the model is analysed again and the sizing repeated until no group changes (or max_iter). The
final model is then analysed and checked once more from scratch: the utilisations reported are those of that final
check, not of the sizing passes.
"""
from __future__ import annotations

import copy
import math

import numpy as np

from .analysis import analyze
from .sections import MATERIALS, section_properties
from .steel_catalog import ANALYSIS_ONLY, FAMILIES, SHAPE_FAMILIES, as_section, family
from .serviceability import deflection_checks
from .steel_design import (NotCovered, check_member, design_combinations, member_forces, member_params, resolve_code,
                           steel_design)


def slenderness(sec: dict, p, forces) -> tuple[float, float]:
    """(KL/r of the member, the limit): 200 if it is ever in compression, else 300 (AISC 360-16 E2 and D1 user notes)."""
    sp = section_properties(sec)
    ry, rz = math.sqrt(sp.Iy / sp.A), math.sqrt(sp.Iz / sp.A)
    kl_r = max(p.Ky * p.L / ry, p.Kz * p.L / rz)
    comp = any(float(np.min(f.N)) < -1e-6 for _, f in forces)
    return kl_r, 200.0 if comp else 300.0


def _util(sec, mat, p, forces, code):
    try:
        r = check_member(sec, mat, p, forces, code)
    except NotCovered:
        return None
    return max((c["ratio"] for c in r["checks"]), default=0.0)


def suggest_sections(model: dict, code: str | None = None, target: float = 1.0, groups: dict | None = None,
                     max_iter: int = 6, limit_slenderness: bool = True, check_deflection: bool = False,
                     deflection_limits: dict | None = None, wind_factor: float | None = None) -> dict:
    """groups: {section_id: "keep" | "lock" | a family: "H", "I", "C", "L", "SHS", "RHS", "CHS"} (default "keep":
    the families of the same shape).

    limit_slenderness: also require KL/r <= 200 for members in compression and L/r <= 300 for members only in
    tension. These are the AISC 360-16 recommendations (user notes to E2 and D1), not a strength check.

    check_deflection: also meet the deflection and drift limits of serviceability.deflection_checks. In each pass, a
    span over its limit asks every section in it for a stiffness of at least (current stiffness x utilisation): the
    moment of inertia about the bending axis for beams and drift, the area for truss members. That scaling is
    approximate (other members share the stiffness), so the passes repeat with a fresh analysis and the final check is
    a full deflection check of the final sizes.
    """
    code = resolve_code(model, code)
    target = float(target)
    if not 0.3 <= target <= 1.0:
        raise ValueError("The target utilisation must be between 0.3 and 1.0")
    groups = groups or {}
    m = copy.deepcopy(model)
    mats = {**MATERIALS, **m.get("materials", {})}
    xyz = {n["id"]: np.array([n["x"], n["y"], n["z"]], dtype=float) for n in m["nodes"]}
    by_sec: dict[str, list[dict]] = {}
    for e in m["elements"]:
        by_sec.setdefault(e["section"], []).append(e)
    original = {k: copy.deepcopy(v) for k, v in m["sections"].items()}

    plan, notes = {}, []
    for sid, elems in by_sec.items():
        sec = m["sections"].get(sid, {})
        mat = mats.get(sec.get("material", ""), {})
        if mat.get("kind") != "steel":
            continue
        choice = groups.get(sid, "keep")
        if choice == "lock":
            plan[sid] = None
            continue
        fams = SHAPE_FAMILIES.get(sec.get("shape"), ()) if choice == "keep" else (choice,)
        if choice != "keep" and choice not in FAMILIES:
            raise ValueError(f"Unknown section family '{choice}' for section {sid}")
        if choice in ANALYSIS_ONLY:
            raise ValueError(f"{FAMILIES[choice]} have no design checks here, so they cannot be suggested (section {sid})")
        if not fams:
            notes.append(f"{sid}: shape '{sec.get('shape')}' has no design-checked standard sizes here, so it was left "
                         "as it is. Pick a family (H, I, C, L, SHS, RHS or CHS) to size it.")
            plan[sid] = None
            continue
        cands = sorted((c for f in fams for c in family(f)), key=lambda c: c["A"])
        plan[sid] = {"cands": cands, "material": sec.get("material"), "families": list(fams),
                     "params": [(e, member_params(e, float(np.linalg.norm(xyz[e["j"]] - xyz[e["i"]])))) for e in elems]}
    if not any(plan.values()):
        raise ValueError("No steel section group to size (all locked, not steel, or not a sizable shape)")

    combos, _ = design_combinations(m)
    history, converged, short = [], False, set()
    seen = {sid: [m["sections"][sid].get("catalog")] for sid in plan}
    upward: set[str] = set()
    for it in range(max_iter):
        res = analyze(m)
        if not res.get("ok", True):
            raise ValueError("The analysis failed, so the sections cannot be sized: " + "; ".join(
                w["message"] for w in res.get("warnings", []) if w.get("level") == "error")[:300])
        changes, short = [], set()
        need = _stiffness_needs(m, res, deflection_limits, wind_factor) if check_deflection else {}
        for sid, pl in plan.items():
            if not pl:
                continue
            mat = mats[pl["material"]]
            jobs = [(p, member_forces(res, combos, e["id"])) for e, p in pl["params"]]
            jobs = [j for j in jobs if j[1]]
            if not jobs:
                continue
            cur = m["sections"][sid]
            # worst members first, so a size that is too small is rejected after one or two checks
            cur_u = [(_util(cur, mat, p, f, code), (p, f)) for p, f in jobs]
            cur_u.sort(key=lambda x: -(x[0] or 0.0))
            jobs = [j for _, j in cur_u]
            pick = None
            for c in pl["cands"]:
                sec = as_section(c, pl["material"])
                if not _stiff_enough(sec, need.get(sid)):
                    continue
                if limit_slenderness and any((r := slenderness(sec, p, f))[0] > r[1] for p, f in jobs):
                    continue
                if all((u := _util(sec, mat, p, f, code)) is not None and u <= target + 1e-9 for p, f in jobs):
                    pick = sec
                    break
            if pick is None:
                pick = as_section(pl["cands"][-1], pl["material"])
                short.add(sid)
            # A lighter but stiffer size can attract more force and fail, then the heavier one is picked again, and so
            # on. Once a group returns to a size it had before, it only moves to heavier sizes: the current size is
            # kept while it still passes.
            if pick.get("catalog") in seen[sid][:-1]:
                upward.add(sid)
            if sid in upward and cur.get("catalog") and section_properties(pick).A < section_properties(cur).A \
                    and all(u is not None and u <= target + 1e-9 for u, _ in cur_u) and _stiff_enough(cur, need.get(sid)) \
                    and not (limit_slenderness and any((r := slenderness(cur, p, f))[0] > r[1] for p, f in jobs)):
                pick = cur
            seen[sid].append(pick.get("catalog"))
            if pick.get("catalog") != cur.get("catalog") or any(cur.get(k) != pick.get(k) for k in ("shape", "h", "b", "t", "d", "bf", "tf", "tw", "c")):
                changes.append((sid, cur.get("name", sid), pick["name"]))
                m["sections"][sid] = pick
        history.append({"iteration": it + 1, "changes": [{"section": s, "from": a, "to": b} for s, a, b in changes]})
        if not changes:
            converged = True
            break

    final = steel_design(m, code)
    defl = deflection_checks(m, None, deflection_limits, wind_factor) if check_deflection else None
    rows = []
    for sid, pl in plan.items():
        members = [final["members"][e["id"]] for e in by_sec[sid] if e["id"] in final["members"]]
        utils = [x["util"] for x in members if x.get("util") is not None]
        before = original[sid]
        after = m["sections"][sid]
        mass = lambda s: _mass(s, by_sec[sid], xyz)  # noqa: E731
        rows.append({"section": sid, "locked": pl is None, "families": pl["families"] if pl else [],
                     "from": before.get("name", sid), "to": after.get("name", sid), "changed": before != after,
                     "n_members": len(by_sec[sid]), "max_util": max(utils) if utils else None,
                     "n_fail": sum(1 for x in members if x.get("status") == "fail"),
                     "mass_before": mass(before), "mass_after": mass(after),
                     "largest_too_small": sid in short,
                     "defl_util": _group_defl(defl, by_sec[sid]) if defl else None})
    if short:
        notes.append("Even the largest standard size does not pass in: " + ", ".join(sorted(short))
                     + ". Use another family, split the group into several sections, or change the structure.")
    if not converged:
        notes.append(f"Sizes still changed in the last of {max_iter} passes (the forces depend on the sizes). "
                     "The final check below is still a full analysis and check of the sizes shown.")
    if limit_slenderness:
        notes.append("Slenderness limited to KL/r <= 200 for members in compression and L/r <= 300 for members only in "
                     "tension (AISC 360-16 user notes to E2 and D1), with the K factors and lengths set on the members.")
    if defl:
        bad = [i for i in defl["items"] if i["status"] == "fail"]
        notes.append("Deflection and drift limits were included in the sizing. Final check: "
                     + (f"{len(bad)} of {len(defl['items'])} spans or storeys still over the limit (see Deflection)."
                        if bad else f"all {len(defl['items'])} spans and storeys within the limits."))
        notes.append("Sizing for drift raises the column stiffness only. Where beams or bracing carry most of the sway, "
                     "change those by hand.")
    notes += [
        "Suggested sizes are the lightest standard size per group that passes the implemented checks at the target "
        "utilisation. Groups are the model's section ids: every member of a group gets the same size.",
        "Not checked: connections, " + ("" if check_deflection else "deflection limits, ") + "vibration, fire, fatigue, and anything listed in the steel "
        "design notes. Review the sizes before using them.",
    ]
    return {"code": final["code"], "code_name": final["code_name"], "target": target, "converged": converged,
            "limit_slenderness": limit_slenderness, "check_deflection": check_deflection, "deflection": defl,
            "iterations": len(history), "history": history, "groups": rows, "sections": m["sections"],
            "design": final, "notes": notes}


def _stiffness_needs(m: dict, res: dict, limits, wind_factor) -> dict:
    """{section id: {"Iy"|"Iz"|"A": required value}} from the spans that are over their deflection limit."""
    d = deflection_checks(m, res, limits, wind_factor)
    els = {e["id"]: e for e in m["elements"]}
    need: dict[str, dict] = {}
    for it in d["items"]:
        if it["util"] <= 1.0 + 1e-9:
            continue
        key = "A" if it["kind"] == "truss" else ("Iy" if it["axis"] == "y" else "Iz")
        for eid in it["elements"]:
            sid = els[eid]["section"]
            try:
                cur = getattr(section_properties(m["sections"][sid]), key)
            except (KeyError, ValueError):
                continue
            n = need.setdefault(sid, {})
            n[key] = max(n.get(key, 0.0), cur * it["util"])
    return need


def _stiff_enough(sec: dict, need: dict | None) -> bool:
    if not need:
        return True
    sp = section_properties(sec)
    return all(getattr(sp, k) >= v * (1 - 1e-9) for k, v in need.items())


def _group_defl(defl: dict, elems: list[dict]) -> float | None:
    u = [defl["members"][e["id"]]["util"] for e in elems if e["id"] in defl["members"]]
    return max(u) if u else None


def _mass(sec: dict, elems: list[dict], xyz: dict) -> float | None:
    from .sections import section_properties
    try:
        A = section_properties(sec).A
    except (KeyError, ValueError):
        return None
    L = sum(float(np.linalg.norm(xyz[e["j"]] - xyz[e["i"]])) for e in elems)
    return A * L * 7850.0


__all__ = ["suggest_sections"]
