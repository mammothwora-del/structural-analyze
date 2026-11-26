"""Standard section tables and the suggested-sizes routine."""
import pytest
from fastapi.testclient import TestClient

from structural.api import app
from structural.generator import generate
from structural.sections import section_properties
from structural.steel_catalog import CATALOG, FAMILIES, as_section, family
from structural.steel_design import steel_design
from structural.steel_sizing import suggest_sections
from structural.structures import generate_truss2d, generate_warehouse


def test_catalog_entries_are_valid_and_sorted():
    names = [e["name"] for e in CATALOG]
    assert len(names) == len(set(names))
    for f in FAMILIES:
        es = family(f)
        assert len(es) >= 10
        assert [e["A"] for e in es] == sorted(e["A"] for e in es)
        for e in es:
            assert section_properties(as_section(e, "SS400")).A == pytest.approx(e["A"])
    h400 = next(e for e in CATALOG if e["name"] == "H 400x200x8x13")
    # the supplier's area with root radii (84.12 cm2); from the nominal plates alone it would be 8.192e-3 m2
    assert h400["source"] == "table" and h400["A"] == pytest.approx(8.412e-3, rel=1e-9)
    nominal = next(e for e in CATALOG if e["source"] == "nominal" and e["family"] == "H")
    assert section_properties(nominal).A == pytest.approx(nominal["A"])
    with pytest.raises(ValueError):
        family("W")


@pytest.fixture(scope="module")
def warehouse():
    return generate_warehouse({"roof": "mono", "n_spans": 2, "roof_layout": "continuous", "n_bays": 3, "standard": "TH"})


@pytest.fixture(scope="module")
def suggested(warehouse):
    return suggest_sections(warehouse)


def test_suggested_sizes_pass_and_are_reported_from_a_fresh_check(warehouse, suggested):
    r = suggested
    assert r["converged"] and r["code"] == "EIT"
    assert r["design"]["summary"]["fail"] == 0
    assert r["design"]["summary"]["max_util"] <= 1.0
    catalog = {e["name"] for e in CATALOG}
    for sid, sec in r["sections"].items():
        assert sec["catalog"] in catalog and sec["material"] == "SS400"
    # same shape family as before unless asked otherwise
    assert r["sections"]["COL"]["shape"] == "I" and r["sections"]["WEB"]["shape"] == "pipe"
    # the reported design is exactly a normal check of the model with those sections
    again = steel_design({**warehouse, "sections": r["sections"]})
    assert again["summary"]["max_util"] == pytest.approx(r["design"]["summary"]["max_util"])
    rows = {g["section"]: g for g in r["groups"]}
    assert set(rows) == {"COL", "CHO", "WEB", "PUR", "BRA"}
    assert all(g["max_util"] <= 1.0 for g in rows.values())


def test_each_suggested_size_is_the_lightest_that_passes(warehouse, suggested):
    """One size lighter in the same family fails somewhere in the group (with the forces of the final model)."""
    from structural.steel_catalog import as_section
    secs = suggested["sections"]
    for sid in ("COL", "WEB"):
        fam = family("H" if sid == "COL" else "CHS")
        k = next(i for i, e in enumerate(fam) if e["name"] == secs[sid]["catalog"])
        if k == 0:
            continue
        lighter = {**secs, sid: as_section(fam[k - 1], "SS400")}
        d = steel_design({**warehouse, "sections": lighter})
        worst = max(d["members"][e["id"]]["util"] for e in warehouse["elements"] if e["section"] == sid)
        assert worst > 1.0 - 0.05   # forces shift a little with the lighter size; it is at or over the limit


def test_lock_family_change_and_target(warehouse):
    r = suggest_sections(warehouse, target=0.8, groups={"COL": "SHS", "PUR": "lock"})
    assert r["sections"]["COL"]["shape"] == "box" and r["sections"]["COL"]["catalog"].startswith("SHS")
    assert r["sections"]["PUR"] == warehouse["sections"]["PUR"]
    rows = {g["section"]: g for g in r["groups"]}
    assert rows["PUR"]["locked"] and not rows["PUR"]["changed"]
    for sid in ("COL", "CHO", "WEB", "BRA"):
        assert rows[sid]["max_util"] <= 0.8 + 1e-6 or not r["converged"]
    with pytest.raises(ValueError, match="target"):
        suggest_sections(warehouse, target=1.5)
    with pytest.raises(ValueError, match="family"):
        suggest_sections(warehouse, groups={"COL": "W"})


def test_no_steel_group_is_an_error_and_heavy_loads_are_reported():
    with pytest.raises(ValueError, match="No steel section group"):
        suggest_sections(generate({}))     # reinforced concrete building
    m = generate_truss2d({"span": 18.0, "sdl": 400.0})
    r = suggest_sections(m, groups={"WEB": "CHS", "CHO": "CHS"})
    assert any(g["largest_too_small"] for g in r["groups"])
    assert any("largest standard size" in n for n in r["notes"])


def test_api(warehouse):
    c = TestClient(app)
    cat = c.get("/api/sections/catalog").json()
    assert set(cat["families"]) == {"H", "I", "C", "L", "LC", "SHS", "RHS", "CHS"} and len(cat["sections"]) == len(CATALOG)
    m = generate_truss2d()
    r = c.post("/api/design/steel/suggest", json={"model": m, "target": 0.9})
    assert r.status_code == 200
    body = r.json()
    assert body["target"] == 0.9 and body["design"]["summary"]["fail"] == 0
    assert c.post("/api/design/steel/suggest", json={"model": m, "target": 2}).status_code == 400
    assert c.post("/api/design/steel/suggest", json={}).status_code == 400


def test_slenderness_limit(warehouse, suggested):
    """With the limit on (default) every member meets KL/r <= 200 / L/r <= 300; without it sizes can only get lighter."""
    import numpy as np
    from structural.analysis import analyze
    from structural.steel_design import design_combinations, member_forces, member_params
    from structural.steel_sizing import slenderness
    m = {**warehouse, "sections": suggested["sections"]}
    res = analyze(m)
    combos, _ = design_combinations(m)
    xyz = {n["id"]: np.array([n["x"], n["y"], n["z"]]) for n in m["nodes"]}
    for e in m["elements"]:
        p = member_params(e, float(np.linalg.norm(xyz[e["j"]] - xyz[e["i"]])))
        kl_r, lim = slenderness(m["sections"][e["section"]], p, member_forces(res, combos, e["id"]))
        assert kl_r <= lim + 1e-9, (e["id"], kl_r, lim)
    free = suggest_sections(warehouse, limit_slenderness=False)
    for g_on, g_off in zip(suggested["groups"], free["groups"]):
        assert (g_off["mass_after"] or 0) <= (g_on["mass_after"] or 0) + 1e-6
    assert any("KL/r <= 200" in n for n in suggested["notes"])
