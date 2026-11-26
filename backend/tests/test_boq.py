"""Bill of quantities (boq.py)."""
import io

import numpy as np
import pytest
from fastapi.testclient import TestClient

from structural.api import app
from structural.boq import boq_xlsx, quantities
from structural.generator import generate
from structural.sections import section_properties
from structural.steel_catalog import CATALOG, as_section
from structural.structures import generate_warehouse


def lengths(m, sid):
    xyz = {n["id"]: np.array([n["x"], n["y"], n["z"]]) for n in m["nodes"]}
    return sum(np.linalg.norm(xyz[e["j"]] - xyz[e["i"]]) for e in m["elements"] if e["section"] == sid)


def test_steel_mass_from_area_and_from_the_supplier_table():
    m = generate_warehouse({"roof": "portal", "standard": "TH"})
    h = next(e for e in CATALOG if e["name"] == "H 200x200x8x12")
    m["sections"]["COL"] = as_section(h, "SS400")
    q = quantities(m)
    rows = {r["section"]: r for r in q["rows"]}
    col = rows["COL"]
    assert col["mass_source"] == "table" and col["kg_per_m"] == pytest.approx(h["mass"])
    assert col["length"] == pytest.approx(lengths(m, "COL")) and col["n"] == 12
    assert col["mass"] == pytest.approx(h["mass"] * lengths(m, "COL"))
    pur = rows["PUR"]                                      # own dimensions: A x 77 kN/m3 / g
    A = section_properties(m["sections"]["PUR"]).A
    assert pur["mass_source"] == "A x density" and pur["kg_per_m"] == pytest.approx(A * 77.0 / 9.80665 * 1000)
    assert q["totals"]["steel_mass"] == pytest.approx(sum(r["mass"] for r in q["rows"]))
    assert q["totals"]["cost"] is None and not q["totals"]["complete"]
    assert sum(t["mass"] for t in q["by_type"]) == pytest.approx(q["totals"]["steel_mass"])
    assert sum(mm["length"] for mm in q["members"]) == pytest.approx(q["totals"]["steel_length"])


def test_allowance_prices_and_concrete():
    m = generate_warehouse({"roof": "portal", "standard": "TH"})
    q = quantities(m, {"allowance": 10, "prices": {"steel": 30, "CHS": 40}, "currency": "THB"})
    for r in q["rows"]:
        assert r["mass_total"] == pytest.approx(r["mass"] * 1.1)
        assert r["cost"] == pytest.approx(r["mass_total"] * (40 if r["family"] == "CHS" else 30))
    assert q["totals"]["complete"] and q["totals"]["cost"] == pytest.approx(sum(r["cost"] for r in q["rows"]))
    b = generate({"n_levels": 2})
    qb = quantities(b, {"concrete_price": 3000})
    for r in qb["rows"]:
        assert r["kind"] == "concrete" and r["volume"] == pytest.approx(r["A"] * r["length"])
        assert r["cost"] == pytest.approx(r["volume"] * 3000)
    with pytest.raises(ValueError):
        quantities(m, {"allowance": 150})
    with pytest.raises(ValueError):
        quantities(m, {"prices": {"steel": -1}})


def test_excel_has_formulas_and_matches():
    import openpyxl
    m = generate_warehouse({"roof": "pitched", "standard": "TH"})
    opts = {"allowance": 5, "prices": {"steel": 32}}
    wb = openpyxl.load_workbook(io.BytesIO(boq_xlsx(m, opts)))
    ws = wb["BOQ"]
    assert ws["B2"].value == 5
    q = quantities(m, opts)
    r = 5
    for row in [x for x in q["rows"] if x["kind"] == "steel"]:
        assert ws.cell(r, 1).value == row["section"]
        assert ws.cell(r, 9).value == f"=F{r}*G{r}" and ws.cell(r, 12).value.startswith("=IF(")
        assert ws.cell(r, 6).value * ws.cell(r, 7).value == pytest.approx(row["mass"], rel=1e-3)
        r += 1
    assert set(wb.sheetnames) == {"BOQ", "By member type", "Members"}
    assert wb["Members"].max_row == len(m["elements"]) + 1


def test_api_and_report():
    import pypdf

    from structural.report import build_report
    m = generate_warehouse({"roof": "portal", "standard": "TH"})
    with TestClient(app) as c:
        out = c.post("/api/boq", json={"model": m, "options": {"prices": {"steel": 30}}}).json()
        assert out["totals"]["cost"] > 0
        x = c.post("/api/boq/xlsx", json={"model": m})
        assert x.status_code == 200 and x.content[:2] == b"PK" and "BOQ.xlsx" in x.headers["content-disposition"]
        assert c.post("/api/boq", json={"model": m, "options": {"allowance": -5}}).status_code == 400
    pdf = build_report(m, {"steel": False, "rc": False, "deflection": False, "members": False}, boq={"prices": {"steel": 30}})
    txt = "".join(p.extract_text() for p in pypdf.PdfReader(io.BytesIO(pdf)).pages)
    q = quantities(m, {"prices": {"steel": 30}})
    assert "Quantities and cost" in txt and f"{q['totals']['steel_mass']:.0f}" in txt.replace(",", "")
