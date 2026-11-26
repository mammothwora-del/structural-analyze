"""Bill of quantities: steel mass and concrete volume of the members, with optional unit prices.

Quantities are CALCULATED from the model: member length = distance between its end nodes (centre-line, no deduction
or extension at connections) and the section of the member. Mass per metre: the supplier table's kg/m for a standard
size taken unchanged from the catalogue (steel_catalog.py), otherwise area × density of the material
(density / g). Concrete: area × length, in m³ (reinforcement is not included).

An allowance (%) for connections, plates, bolts and waste is added on top when given; it is the user's figure (none by
default). Unit prices are the user's figures; no price is assumed, so the cost columns stay empty without them.
Slabs, walls, foundations, sheeting, painting and erection are not included.
"""
from __future__ import annotations

import io

import numpy as np

from .sections import MATERIALS, section_properties
from .steel_catalog import CATALOG

G = 9.80665
_BY_NAME = {e["name"]: e for e in CATALOG}
DIM_KEYS = ("shape", "h", "b", "t", "d", "bf", "tf", "tw", "c")
SHAPE_FAMILY = {"I": "H / I", "channel": "C", "angle": "L", "lipchannel": "LC", "box": "SHS / RHS", "pipe": "CHS",
                "rect": "Solid rectangle", "circle": "Solid round"}


def _family(sec: dict) -> str:
    cat = _BY_NAME.get(sec.get("catalog") or "")
    if cat and _same_dims(sec, cat):
        return cat["family"]
    return SHAPE_FAMILY.get(sec.get("shape", ""), sec.get("shape", "other"))


def _same_dims(sec: dict, cat: dict) -> bool:
    return all(abs(float(sec.get(k) or 0) - float(cat.get(k) or 0)) < 1e-9 if k != "shape" else sec.get(k) == cat.get(k)
               for k in DIM_KEYS if k in cat or k in sec)


def _describe(sec: dict) -> str:
    if sec.get("name"):
        return str(sec["name"])
    s = sec.get("shape", "")
    mm = lambda v: f"{float(v) * 1000:g}"  # noqa: E731
    if s == "rect":
        return f"Rect {mm(sec['b'])}x{mm(sec['h'])}"
    if s == "circle":
        return f"Round {mm(sec['d'])}"
    if s == "pipe":
        return f"Pipe {mm(sec['d'])}x{mm(sec['t'])}"
    if s == "box":
        return f"Box {mm(sec['h'])}x{mm(sec['b'])}x{mm(sec['t'])}"
    if s == "I":
        return f"I {mm(sec['h'])}x{mm(sec['bf'])}x{mm(sec['tw'])}x{mm(sec['tf'])}"
    return s or "section"


def quantities(model: dict, options: dict | None = None) -> dict:
    """options: {"allowance": % (0), "currency": "THB", "prices": {family or "steel": price per kg},
    "concrete_price": price per m³}"""
    o = {"allowance": 0.0, "currency": "THB", "prices": {}, "concrete_price": None, **(options or {})}
    allow = float(o.get("allowance") or 0.0)
    if not 0.0 <= allow <= 100.0:
        raise ValueError("The allowance must be between 0 and 100 %")
    prices = {k: float(v) for k, v in (o.get("prices") or {}).items() if v not in (None, "")}
    if any(v < 0 for v in prices.values()):
        raise ValueError("Prices cannot be negative")
    cprice = None if o.get("concrete_price") in (None, "") else float(o["concrete_price"])
    mats = {**MATERIALS, **model.get("materials", {})}
    xyz = {n["id"]: np.array([n["x"], n["y"], n["z"]], dtype=float) for n in model["nodes"]}
    groups: dict[str, dict] = {}
    members = []
    for e in model["elements"]:
        sid = e["section"]
        sec = model["sections"].get(sid)
        if sec is None:
            raise ValueError(f"Member {e['id']} uses section '{sid}', which is not defined")
        mat = mats.get(sec.get("material", ""), {})
        L = float(np.linalg.norm(xyz[e["j"]] - xyz[e["i"]]))
        g = groups.get(sid)
        if g is None:
            sp = section_properties(sec)
            kind = mat.get("kind", "other")
            cat = _BY_NAME.get(sec.get("catalog") or "")
            if kind == "steel" and cat and _same_dims(sec, cat) and cat.get("mass"):
                kgm, src = float(cat["mass"]), "table" if cat.get("source") == "table" else "nominal"
            else:
                kgm, src = sp.A * float(mat.get("density", 0.0)) / G * 1000.0, "A x density"
            g = groups[sid] = {"section": sid, "description": _describe(sec), "family": _family(sec) if kind == "steel" else "Concrete",
                               "material": sec.get("material", ""), "kind": kind, "A": sp.A, "kg_per_m": kgm, "mass_source": src,
                               "n": 0, "length": 0.0, "types": {}}
        g["n"] += 1
        g["length"] += L
        role = e.get("role") or e["type"]
        g["types"][role] = g["types"].get(role, 0.0) + L
        members.append({"id": e["id"], "type": e["type"], "role": role, "section": sid, "length": L})

    rows, by_type = [], {}
    for sid, g in groups.items():
        row = {k: v for k, v in g.items() if k != "types"}
        row["roles"] = sorted(g["types"])
        if g["kind"] == "steel":
            row["mass"] = g["kg_per_m"] * g["length"]
            row["mass_total"] = row["mass"] * (1 + allow / 100.0)
            price = prices.get(g["family"], prices.get("steel"))
            row["unit_price"] = price
            row["cost"] = row["mass_total"] * price if price is not None else None
            for role, L in g["types"].items():
                t = by_type.setdefault(role, {"role": role, "length": 0.0, "mass": 0.0})
                t["length"] += L
                t["mass"] += g["kg_per_m"] * L
        elif g["kind"] == "concrete":
            row["volume"] = g["A"] * g["length"]
            row["unit_price"] = cprice
            row["cost"] = row["volume"] * cprice if cprice is not None else None
        else:
            row["cost"] = None
        rows.append(row)
    rows.sort(key=lambda r: (r["kind"] != "steel", r["family"], -(r.get("mass") or r.get("volume") or 0)))
    for m in members:
        g = groups[m["section"]]
        m["mass"] = g["kg_per_m"] * m["length"] if g["kind"] == "steel" else None
    steel = [r for r in rows if r["kind"] == "steel"]
    conc = [r for r in rows if r["kind"] == "concrete"]
    fam: dict[str, dict] = {}
    for r in steel:
        f = fam.setdefault(r["family"], {"family": r["family"], "mass": 0.0, "mass_total": 0.0, "length": 0.0, "cost": 0.0, "priced": True})
        f["mass"] += r["mass"]
        f["mass_total"] += r["mass_total"]
        f["length"] += r["length"]
        if r["cost"] is None:
            f["priced"] = False
        else:
            f["cost"] += r["cost"]
    for f in fam.values():
        if not f["priced"]:
            f["cost"] = None
    costs = [r["cost"] for r in rows if r.get("cost") is not None]
    unpriced = [r["section"] for r in rows if r["kind"] in ("steel", "concrete") and r.get("cost") is None]
    totals = {"steel_mass": sum(r["mass"] for r in steel), "steel_mass_total": sum(r["mass_total"] for r in steel),
              "steel_length": sum(r["length"] for r in steel), "concrete_volume": sum(r["volume"] for r in conc),
              "cost": sum(costs) if costs else None, "complete": not unpriced}
    notes = [
        "Lengths are centre-line lengths between nodes (no deduction or extension at connections).",
        "Steel mass per metre: the supplier table (kg/m) for standard sizes; otherwise area x density. Concrete: area x "
        "length (reinforcement, formwork not included).",
        (f"Allowance for connections, plates, bolts and waste: {allow:g} % (entered by the user)." if allow
         else "No allowance added for connections, plates, bolts and waste (enter one if needed)."),
        "Not included: slabs, walls, foundations, roof and wall sheeting, girts not in the model, painting, galvanising, "
        "transport and erection.",
    ]
    if prices or cprice is not None:
        notes.append(f"Unit prices ({o['currency']}) are the user's figures." +
                     (f" Sections without a price: {', '.join(unpriced)}." if unpriced else ""))
    else:
        notes.append("No unit prices entered: quantities only.")
    return {"currency": o["currency"], "allowance": allow, "prices": prices, "concrete_price": cprice, "rows": rows,
            "families": sorted(fam.values(), key=lambda f: -f["mass"]),
            "by_type": sorted(by_type.values(), key=lambda t: -t["mass"]), "members": members, "totals": totals, "notes": notes}


def boq_xlsx(model: dict, options: dict | None = None) -> bytes:
    """Excel workbook with live formulas: mass = length x kg/m, total = mass x (1 + allowance), cost = total x price."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    q = quantities(model, options)
    wb = Workbook()
    ws = wb.active
    ws.title = "BOQ"
    bold = Font(bold=True)
    head_fill = PatternFill("solid", fgColor="DDE7F0")
    ws["A1"] = f"Bill of quantities: {model.get('name') or 'model'}"
    ws["A1"].font = Font(bold=True, size=13)
    ws["A2"] = "Allowance (%)"
    ws["B2"] = q["allowance"]
    ws["C2"] = "Currency"
    ws["D2"] = q["currency"]
    ws["A2"].font = ws["C2"].font = bold
    hdr = ["Section", "Description", "Family", "Material", "Members", "Length (m)", "kg/m", "kg/m from",
           "Net mass (kg)", "Mass with allowance (kg)", f"Price per kg ({q['currency']})", f"Cost ({q['currency']})"]
    r0 = 4
    for c, h in enumerate(hdr, 1):
        cell = ws.cell(r0, c, h)
        cell.font = bold
        cell.fill = head_fill
        cell.alignment = Alignment(wrap_text=True, vertical="top")
    r = r0
    steel_rows = [x for x in q["rows"] if x["kind"] == "steel"]
    for x in steel_rows:
        r += 1
        ws.cell(r, 1, x["section"])
        ws.cell(r, 2, x["description"])
        ws.cell(r, 3, x["family"])
        ws.cell(r, 4, x["material"])
        ws.cell(r, 5, x["n"])
        ws.cell(r, 6, round(x["length"], 3))
        ws.cell(r, 7, round(x["kg_per_m"], 3))
        ws.cell(r, 8, x["mass_source"])
        ws.cell(r, 9, f"=F{r}*G{r}")
        ws.cell(r, 10, f"=I{r}*(1+$B$2/100)")
        if x["unit_price"] is not None:
            ws.cell(r, 11, x["unit_price"])
        ws.cell(r, 12, f'=IF(K{r}="","",J{r}*K{r})')
    first, last = r0 + 1, r
    r += 1
    ws.cell(r, 1, "Total steel").font = bold
    if steel_rows:
        for col in (6, 9, 10, 12):
            L = get_column_letter(col)
            ws.cell(r, col, f"=SUM({L}{first}:{L}{last})").font = bold
    total_row = r
    conc = [x for x in q["rows"] if x["kind"] == "concrete"]
    if conc:
        r += 2
        for c, h in enumerate(["Section", "Description", "", "Material", "Members", "Length (m)", "Area (m²)", "",
                               "Volume (m³)", "", f"Price per m³ ({q['currency']})", f"Cost ({q['currency']})"], 1):
            cell = ws.cell(r, c, h)
            cell.font = bold
            cell.fill = head_fill
        c0 = r + 1
        for x in conc:
            r += 1
            ws.cell(r, 1, x["section"])
            ws.cell(r, 2, x["description"])
            ws.cell(r, 4, x["material"])
            ws.cell(r, 5, x["n"])
            ws.cell(r, 6, round(x["length"], 3))
            ws.cell(r, 7, round(x["A"], 6))
            ws.cell(r, 9, f"=F{r}*G{r}")
            if x["unit_price"] is not None:
                ws.cell(r, 11, x["unit_price"])
            ws.cell(r, 12, f'=IF(K{r}="","",I{r}*K{r})')
        r += 1
        ws.cell(r, 1, "Total concrete").font = bold
        ws.cell(r, 9, f"=SUM(I{c0}:I{r - 1})").font = bold
        ws.cell(r, 12, f"=SUM(L{c0}:L{r - 1})").font = bold
    r += 2
    ws.cell(r, 1, "Notes").font = bold
    for n in q["notes"]:
        r += 1
        ws.cell(r, 1, n)
    for col, w in zip("ABCDEFGHIJKL", (10, 26, 11, 10, 9, 11, 9, 11, 13, 14, 13, 14)):
        ws.column_dimensions[col].width = w
    for row in ws.iter_rows(min_row=first, max_row=total_row):
        for cell in row[5:]:
            if cell.column in (6, 7):
                cell.number_format = "0.00"
            elif cell.column >= 9:
                cell.number_format = "#,##0.0"
    ws.freeze_panes = ws.cell(r0 + 1, 1)

    wt = wb.create_sheet("By member type")
    for c, h in enumerate(["Member type / role", "Length (m)", "Net mass (kg)"], 1):
        wt.cell(1, c, h).font = bold
    for k, t in enumerate(q["by_type"], 2):
        wt.cell(k, 1, t["role"])
        wt.cell(k, 2, round(t["length"], 3))
        wt.cell(k, 3, round(t["mass"], 1))
    wt.column_dimensions["A"].width = 22
    wm = wb.create_sheet("Members")
    for c, h in enumerate(["Member", "Type", "Role", "Section", "Length (m)", "Net mass (kg)"], 1):
        wm.cell(1, c, h).font = bold
    for k, m in enumerate(q["members"], 2):
        wm.cell(k, 1, m["id"])
        wm.cell(k, 2, m["type"])
        wm.cell(k, 3, m["role"])
        wm.cell(k, 4, m["section"])
        wm.cell(k, 5, round(m["length"], 4))
        if m["mass"] is not None:
            wm.cell(k, 6, round(m["mass"], 2))
    wm.freeze_panes = "A2"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


__all__ = ["quantities", "boq_xlsx"]
