"""PDF calculation report.

The report re-runs the linear analysis (and, when asked, buckling and the member designs) on the server from the model
it is given, so every number in it comes from this code at the time of printing; nothing is copied from the browser.
Each part is labelled INPUT (what the user or a generator defined), ASSUMED (defaults the program chose) or CALCULATED.
The report never states that the structure is safe or code-compliant.
"""
from __future__ import annotations

import base64
import datetime as dt
import io
from collections import Counter

import numpy as np
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)

from .analysis import analyze
from .sections import MATERIALS, section_properties
from .steel_design import combine_member, design_combinations

INCLUDE_DEFAULTS = {"model": True, "loads": True, "analysis": True, "members": True, "stability": False,
                    "steel": True, "rc": True}
QTY = ("N", "Vy", "Vz", "T", "My", "Mz")
QTY_UNIT = {"N": "kN", "Vy": "kN", "Vz": "kN", "T": "kN·m", "My": "kN·m", "Mz": "kN·m"}
UNIT = {"force": "kN", "moment": "kN·m", "ratio": ""}
MAX_MEMBER_ROWS = 400

ACCENT = colors.HexColor("#0e7490")
INK = colors.HexColor("#1f2937")
MUTED = colors.HexColor("#6b7280")
GRID = colors.HexColor("#d1d5db")
ZEBRA = colors.HexColor("#f3f4f6")
TAG = {"INPUT": colors.HexColor("#475569"), "ASSUMED": colors.HexColor("#b45309"), "CALCULATED": colors.HexColor("#047857")}
STATUS = {"ok": ("OK", colors.HexColor("#047857")), "fail": ("OVER 1.0", colors.HexColor("#b91c1c")),
          "not_covered": ("NOT COVERED", colors.HexColor("#b45309")), "skipped": ("skipped", MUTED)}


class ReportError(ValueError):
    pass


# ---------------------------------------------------------------------------------------------------------------
# styles and small helpers
# ---------------------------------------------------------------------------------------------------------------
def _styles():
    ss = getSampleStyleSheet()
    base = ParagraphStyle("base", parent=ss["Normal"], fontName="Helvetica", fontSize=8.5, leading=11, textColor=INK)
    return {
        "base": base,
        "small": ParagraphStyle("small", parent=base, fontSize=7.5, leading=9.5),
        "muted": ParagraphStyle("muted", parent=base, fontSize=7.5, leading=9.5, textColor=MUTED),
        "cell": ParagraphStyle("cell", parent=base, fontSize=7, leading=8.5),
        "title": ParagraphStyle("title", parent=base, fontName="Helvetica-Bold", fontSize=20, leading=24, spaceAfter=4),
        "h1": ParagraphStyle("h1", parent=base, fontName="Helvetica-Bold", fontSize=12.5, leading=16, spaceBefore=10,
                             spaceAfter=4, textColor=ACCENT),
        "h2": ParagraphStyle("h2", parent=base, fontName="Helvetica-Bold", fontSize=9.5, leading=12, spaceBefore=6, spaceAfter=3),
        "note": ParagraphStyle("note", parent=base, fontSize=8, leading=10.5, leftIndent=8, bulletIndent=0, alignment=TA_LEFT),
    }


# The built-in PDF fonts only have the WinAnsi (Latin-1) characters: spell the others out.
_GLYPHS = {"α": "alpha", "β": "beta", "γ": "gamma", "δ": "delta", "Δ": "Delta", "ε": "eps", "λ": "lambda", "χ": "chi",
           "ρ": "rho", "φ": "phi", "ϕ": "phi", "Φ": "phi", "σ": "sigma", "τ": "tau", "Σ": "Sum ", "≥": ">=", "≤": "<=",
           "∞": "inf", "√": "sqrt", "→": "->", "⁴": "4", "⁻": "-", "₀": "0", "₁": "1", "₂": "2", "ₓ": "x", "ᵧ": "y",
           "′": "'", "−": "-", "≈": "~", "·": "·"}


def _t(s) -> str:
    s = str(s)
    if s.isascii():
        return s
    out = []
    for ch in s:
        if ch in _GLYPHS:
            out.append(_GLYPHS[ch])
        else:
            try:
                ch.encode("cp1252")
                out.append(ch)
            except UnicodeEncodeError:
                out.append("?")
    return "".join(out)


def _esc(s) -> str:
    return _t(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _f(v, dg=2) -> str:
    if v is None:
        return "–"
    try:
        v = float(v)
    except (TypeError, ValueError):
        return _esc(v)
    if not np.isfinite(v):
        return "∞" if v > 0 else "–"
    if abs(v) >= 1e6:
        return f"{v:.3g}"
    if abs(v) < 0.5 * 10 ** (-dg):
        v = 0.0                                          # round-off noise such as 1e-17 prints as 0
    return f"{v:.{dg}f}"


def _table(rows, widths=None, header_rows=1, align_right_from=None, styles_extra=()):
    rows = [[_t(c) if isinstance(c, str) else c for c in row] for row in rows]
    t = Table(rows, colWidths=widths, repeatRows=header_rows)
    st = [
        ("FONT", (0, 0), (-1, -1), "Helvetica", 7),
        ("FONT", (0, 0), (-1, header_rows - 1), "Helvetica-Bold", 7),
        ("TEXTCOLOR", (0, 0), (-1, -1), INK),
        ("BACKGROUND", (0, 0), (-1, header_rows - 1), colors.HexColor("#e5e7eb")),
        ("LINEBELOW", (0, header_rows - 1), (-1, header_rows - 1), 0.6, INK),
        ("LINEBELOW", (0, header_rows), (-1, -1), 0.25, GRID),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 1.6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.6),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
    ]
    for r in range(header_rows, len(rows)):
        if (r - header_rows) % 2 == 1:
            st.append(("BACKGROUND", (0, r), (-1, r), ZEBRA))
    if align_right_from is not None:
        st.append(("ALIGN", (align_right_from, 0), (-1, -1), "RIGHT"))
    t.setStyle(TableStyle(st + list(styles_extra)))
    return t


def _tag(kind: str) -> str:
    return f'<font size="7" color="{TAG[kind].hexval().replace("0x", "#")}"><b>[{kind}]</b></font>'


class _Doc:
    """Collects flowables and numbers the sections."""

    def __init__(self, st):
        self.st, self.story, self.n = st, [], 0

    def h1(self, text, tag=None):
        self.n += 1
        self.story.append(Paragraph(f"{self.n}. {_esc(text)} {_tag(tag) if tag else ''}", self.st["h1"]))

    def h2(self, text, tag=None):
        self.story.append(Paragraph(f"{_esc(text)} {_tag(tag) if tag else ''}", self.st["h2"]))

    def p(self, text, style="base"):
        self.story.append(Paragraph(_t(text), self.st[style]))

    def bullets(self, items, style="note"):
        for it in items:
            self.story.append(Paragraph(_esc(it), self.st[style], bulletText="•"))

    def add(self, *flow):
        self.story.extend(flow)

    def gap(self, h=4):
        self.story.append(Spacer(1, h))


# ---------------------------------------------------------------------------------------------------------------
# calculations used by the report (linear combinations of the calculated load-case results)
# ---------------------------------------------------------------------------------------------------------------
def _loads(model) -> list[tuple[str, str, dict]]:
    """Every load case (factor 1) and every combination, in model order."""
    out = [(c["id"], c.get("name", ""), {c["id"]: 1.0}) for c in model.get("load_cases", [])]
    case_ids = {c["id"] for c in model.get("load_cases", [])}
    out += [(c["id"], c.get("name", ""), {k: float(v) for k, v in c.get("factors", {}).items() if k in case_ids})
            for c in model.get("combinations", [])]
    return out


def _member_extremes(model, res, factors):
    """Largest positive and negative value of each internal force over all members for one load."""
    best = {q: {"max": (-np.inf, None, None), "min": (np.inf, None, None)} for q in QTY}
    for e in model["elements"]:
        f = combine_member(res["cases"], e["id"], factors)
        if f is None:
            continue
        for q in QTY:
            arr = np.asarray(getattr(f, q), dtype=float)
            k = int(arr.argmax())
            if arr[k] > best[q]["max"][0]:
                best[q]["max"] = (float(arr[k]), e["id"], float(f.x[k]))
            k = int(arr.argmin())
            if arr[k] < best[q]["min"][0]:
                best[q]["min"] = (float(arr[k]), e["id"], float(f.x[k]))
    return best


def _member_envelope(model, res, loads):
    """Per member: largest absolute value of each internal force over the given loads, with the load id."""
    out = {}
    for e in model["elements"]:
        row = {}
        for lid, _, fac in loads:
            f = combine_member(res["cases"], e["id"], fac)
            if f is None:
                continue
            for q in QTY:
                v = float(np.abs(getattr(f, q)).max())
                if q not in row or v > row[q][0]:
                    row[q] = (v, lid)
        if row:
            out[e["id"]] = row
    return out


# ---------------------------------------------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------------------------------------------
def build_report(model: dict, include: dict | None = None, steel_code: str | None = None, rc_options: dict | None = None,
                 image_png: str | None = None, stability_load: str | None = None, project: dict | None = None) -> bytes:
    """Return the PDF bytes. ``image_png`` is an optional base64 PNG (data URL or raw) of the 3D view."""
    inc = {**INCLUDE_DEFAULTS, **(include or {})}
    project = project or {}
    st = _styles()
    d = _Doc(st)
    res = analyze(model)
    if not res.get("ok", True):
        raise ReportError("the analysis did not run: " + "; ".join(w.get("message", "") for w in res.get("warnings", [])))
    std = model.get("settings", {}).get("standard", "EN1990")
    mats = {**MATERIALS, **model.get("materials", {})}
    now = dt.datetime.now()
    loads = _loads(model)
    combos, _ = design_combinations(model)
    steel = rc = buck = None
    errors = []
    has_steel = any(mats.get(model["sections"].get(e["section"], {}).get("material", ""), {}).get("kind") == "steel"
                    for e in model["elements"])
    has_conc = any(mats.get(model["sections"].get(e["section"], {}).get("material", ""), {}).get("kind") == "concrete"
                   for e in model["elements"])
    if inc["steel"] and has_steel:
        from .steel_design import steel_design
        try:
            steel = steel_design(model, steel_code or None, results=res)
        except (ValueError, KeyError) as exc:
            errors.append(f"Steel design could not run: {exc}")
    if inc["rc"] and has_conc:
        from .rc_design import rc_design
        try:
            rc = rc_design(model, rc_options or {}, results=res)
        except (ValueError, KeyError) as exc:
            errors.append(f"RC design could not run: {exc}")
    if inc["stability"]:
        from .stability import buckling
        load = stability_load or (combos[0][0] if combos else (loads[0][0] if loads else None))
        try:
            buck = buckling(model, load, n_modes=4) if load else None
        except (ValueError, KeyError) as exc:
            errors.append(f"Buckling analysis could not run for {load}: {exc}")

    # ------------------------------------------------------------------ title block
    d.p(_esc(project.get("title") or model.get("name") or "Structural model"), "title")
    d.p("Calculation report: 3D linear analysis" + (" and member design" if (steel or rc) else ""), "h2")
    meta = [["Project", _esc(project.get("project") or model.get("name", "–"))],
            ["Engineer", _esc(project.get("engineer") or "–")],
            ["Date", now.strftime("%d %B %Y, %H:%M")],
            ["Design standard (loads)", {"EN1990": "EN 1990 (Eurocode)", "ASCE7": "ASCE 7", "TH": "Thai (DPT / EIT)"}.get(std, std)],
            ["Units", "kN, m (forces kN, moments kN·m, displacements mm where noted)"],
            ["Software", "Structural Analyze (open source); report generated from the model at the time of printing"]]
    d.add(_table([["", ""]] + meta, widths=[45 * mm, 125 * mm], header_rows=1,
                 styles_extra=[("BACKGROUND", (0, 0), (-1, 0), colors.white), ("LINEBELOW", (0, 0), (-1, 0), 0, colors.white),
                               ("FONT", (0, 1), (0, -1), "Helvetica-Bold", 7)]))
    d.gap(6)
    d.p("<b>Scope of this report.</b> Every result below was calculated by the program from the model shown, at the time of "
        "printing. Labels: " + _tag("INPUT") + " defined by the user or by a model generator; " + _tag("ASSUMED") +
        " a default or simplification chosen by the program; " + _tag("CALCULATED") + " computed. "
        "A utilisation at or below 1.0 means the member passes the checks listed for it. This report is <b>not</b> a "
        "statement that the structure is safe or code-compliant: connections, foundations, overall stability, "
        "serviceability, detailing and the items in the notes must be checked separately by a qualified engineer.", "small")
    if image_png:
        img = _image(image_png)
        if img is not None:
            d.gap(6)
            d.add(img)
            d.p("3D view of the model as shown on screen when the report was printed (illustration, not a result).", "muted")
    for e in errors:
        d.p(f'<font color="#b91c1c">{_esc(e)}</font>', "small")

    # ------------------------------------------------------------------ model
    if inc["model"]:
        d.story.append(PageBreak())
        d.h1("Model", "INPUT")
        counts = [["Nodes", len(model["nodes"])], ["Members", len(model["elements"])],
                  ["Slab panels", len(model.get("slabs", []))], ["Wall panels", len(model.get("walls", []))],
                  ["Supports", len(model.get("supports", []))], ["Load cases", len(model.get("load_cases", []))],
                  ["Combinations", len(model.get("combinations", []))]]
        xyz = np.array([[n["x"], n["y"], n["z"]] for n in model["nodes"]], dtype=float)
        ext = xyz.max(0) - xyz.min(0) if len(xyz) else np.zeros(3)
        counts.append(["Extent X × Y × Z (m)", f"{ext[0]:.2f} × {ext[1]:.2f} × {ext[2]:.2f}"])
        d.add(_table([["Item", "Value"]] + [[a, str(b)] for a, b in counts], widths=[50 * mm, 50 * mm]))
        gen = model.get("generator", {})
        if gen.get("type"):
            d.p(f"Model source: {_esc(gen['type'])} generator.", "muted")

        d.h2("Materials", "INPUT")
        used_mats = sorted({s.get("material", "") for s in model["sections"].values()})
        rows = [["Id", "Name", "Kind", "E (MPa)", "fy / fck (MPa)", "Density (kN/m³)"]]
        for mid in used_mats:
            m = mats.get(mid, {})
            rows.append([mid, _esc(m.get("name", "")), m.get("kind", ""), _f(m.get("E"), 0),
                         _f(m.get("fy", m.get("fck", m.get("fc"))), 1), _f(m.get("gamma", m.get("density")), 1)])
        d.add(_table(rows, widths=[22 * mm, 50 * mm, 20 * mm, 22 * mm, 26 * mm, 28 * mm], align_right_from=3))

        d.h2("Sections", "INPUT")
        n_use = Counter(e["section"] for e in model["elements"])
        hp = ParagraphStyle("hp", parent=st["cell"], fontName="Helvetica-Bold", alignment=2)
        rows = [["Id", "Name", "Shape", "Material", "Members", "A (cm²)"]
                + [Paragraph(f"{q} (cm<super>4</super>)", hp) for q in ("Iy", "Iz", "J")]]
        for sid, s in model["sections"].items():
            try:
                pr = section_properties(s)
                A, Iy, Iz, J = pr.A * 1e4, pr.Iy * 1e8, pr.Iz * 1e8, pr.J * 1e8
            except (KeyError, ValueError):
                A = Iy = Iz = J = None
            rows.append([sid, Paragraph(_esc(s.get("name", "")), st["cell"]), s.get("shape", "rect"), s.get("material", ""),
                         str(n_use.get(sid, 0)), _f(A, 1), _f(Iy, 0), _f(Iz, 0), _f(J, 0)])
        d.add(_table(rows, widths=[14 * mm, 52 * mm, 13 * mm, 18 * mm, 14 * mm, 15 * mm, 16 * mm, 16 * mm, 14 * mm], align_right_from=4))

        d.h2("Supports", "INPUT")
        sup = Counter(_support_kind(s) for s in model.get("supports", []))
        d.p(", ".join(f"{n} {k}" for k, n in sup.items()) or "No supports.", "small")
        if model.get("notes"):
            d.h2("Model notes", "INPUT")
            d.bullets(model["notes"])

    # ------------------------------------------------------------------ loads
    if inc["loads"]:
        d.h1("Loads", "INPUT")
        d.h2("Load cases")
        n_loads = Counter(l.get("case") for l in model.get("loads", []))
        n_area = Counter(a.get("case") for s in model.get("slabs", []) for a in s.get("loads", []) if isinstance(a, dict))
        rows = [["Id", "Name", "Type", "Self-weight", "Loads defined"]]
        for c in model.get("load_cases", []):
            rows.append([c["id"], Paragraph(_esc(c.get("name", "")), st["cell"]), c.get("type", ""),
                         "yes" if c.get("self_weight") else "", str(n_loads.get(c["id"], 0) + n_area.get(c["id"], 0))])
        d.add(_table(rows, widths=[16 * mm, 80 * mm, 22 * mm, 22 * mm, 26 * mm]))
        d.h2("Load combinations")
        rows = [["Id", "Name", "Factors", "Used for design"]]
        ids = {c for c, _ in combos}
        for c in model.get("combinations", []):
            fac = " + ".join(f"{v:g}·{k}" for k, v in c.get("factors", {}).items())
            rows.append([c["id"], Paragraph(_esc(c.get("name", "")), st["cell"]), Paragraph(_esc(fac), st["cell"]),
                         "ULS" if c["id"] in ids else "no (serviceability)"])
        d.add(_table(rows, widths=[16 * mm, 55 * mm, 70 * mm, 25 * mm]))
        d.p("Combinations whose id or name contains sls, serv, service, characteristic or ths are treated as "
            "serviceability combinations and are not used for member design.", "muted")

    # ------------------------------------------------------------------ analysis
    if inc["analysis"]:
        d.story.append(PageBreak())
        d.h1("Linear static analysis", "CALCULATED")
        d.p(_esc(res.get("solver", {}).get("type", "")), "small")
        d.bullets(res.get("log", []), "note")
        assumed = ["Linear elastic material, small displacements (first-order analysis) unless P-Delta is listed below.",
                   "Members are straight Euler-Bernoulli beam elements; member end releases as defined."]
        if res.get("slab_model") != "shell" and model.get("slabs"):
            assumed.append("Slab area loads are distributed to the supporting beams by tributary areas; slabs are not FE-analysed.")
        d.h2("Analysis assumptions", "ASSUMED")
        d.bullets(assumed)
        if res.get("warnings"):
            d.h2("Solver messages")
            d.bullets([w.get("message", "") for w in res["warnings"]])

        d.h2("Equilibrium check (sum of applied loads vs sum of reactions)", "CALCULATED")
        rows = [["Load case", "Sum Fx applied", "Sum Fy applied", "Sum Fz applied", "Sum Fz reactions", "Force error", "Moment error", "Check"]]
        for c in model.get("load_cases", []):
            eq = res["cases"].get(c["id"], {}).get("equilibrium")
            if not eq:
                continue
            a, r = eq["applied"], eq["reactions"]
            rows.append([c["id"], _f(a[0]), _f(a[1]), _f(a[2]), _f(r[2]), f"{eq['force_error']:.1e}", f"{eq['moment_error']:.1e}",
                         "OK" if eq.get("ok") else "CHECK"])
        d.add(_table(rows, widths=[20 * mm, 22 * mm, 22 * mm, 22 * mm, 24 * mm, 20 * mm, 22 * mm, 14 * mm], align_right_from=1))
        d.p("Errors are relative to the applied load; values near machine precision mean the solution is in equilibrium.", "muted")

        d.h2("Support reactions per load case (kN, kN·m)", "CALCULATED")
        for c in model.get("load_cases", []):
            reac = res["cases"].get(c["id"], {}).get("reactions", {})
            if not reac:
                continue
            rows = [["Node", "Fx", "Fy", "Fz", "Mx", "My", "Mz"]]
            tot = np.zeros(6)
            for nid, v in reac.items():
                rows.append([nid] + [_f(x) for x in v])
                tot += np.asarray(v, dtype=float)
            rows.append(["Sum"] + [_f(x) for x in tot[:3]] + ["", "", ""])
            d.add(KeepTogether([Paragraph(f"<b>{_esc(c['id'])}</b> {_esc(c.get('name', ''))}", st["small"]), Spacer(1, 2)]))
            d.add(_table(rows, widths=[22 * mm] + [24 * mm] * 6, align_right_from=1,
                         styles_extra=[("FONT", (0, -1), (-1, -1), "Helvetica-Bold", 7), ("LINEABOVE", (0, -1), (-1, -1), 0.6, INK)]))
            d.gap(4)
        if model.get("combinations"):
            d.p("Reactions for a combination are the sums of the load-case reactions above multiplied by the combination "
                "factors (linear analysis).", "muted")

        d.h2("Extreme member internal forces per load (kN, kN·m)", "CALCULATED")
        d.p("Local axes: N axial (tension positive), Vy / Vz shear, T torsion, My / Mz bending about the local y / z axes. "
            "Values are taken at the member stations (ends, intermediate points).", "muted")
        rows = [["Load", "Force", "Max", "Member @ x (m)", "Min", "Member @ x (m)"]]
        for lid, _, fac in loads:
            ex = _member_extremes(model, res, fac)
            for k, q in enumerate(QTY):
                mx, mn = ex[q]["max"], ex[q]["min"]
                rows.append([lid if k == 0 else "", f"{q} ({QTY_UNIT[q]})", _f(mx[0]), f"{mx[1]} @ {mx[2]:.2f}" if mx[1] else "–",
                             _f(mn[0]), f"{mn[1]} @ {mn[2]:.2f}" if mn[1] else "–"])
        d.add(_table(rows, widths=[20 * mm, 22 * mm, 24 * mm, 34 * mm, 24 * mm, 34 * mm], align_right_from=2,
                     styles_extra=[("ALIGN", (0, 0), (1, -1), "LEFT")]
                     + [("LINEABOVE", (0, r), (-1, r), 0.6, INK) for r in range(1, len(rows), len(QTY))]))

    if inc["members"]:
        d.h2("Member force envelope over all combinations (largest absolute values, kN, kN·m)", "CALCULATED")
        env_loads = [l for l in loads if l[0] in {c["id"] for c in model.get("combinations", [])}] or loads
        env = _member_envelope(model, res, env_loads)
        rows = [["Member", "Section", "|N|", "|Vy|", "|Vz|", "|T|", "|My|", "|Mz|", "Governing load (|M| max)"]]
        secname = {e["id"]: e["section"] for e in model["elements"]}
        for k, (eid, r) in enumerate(env.items()):
            if k >= MAX_MEMBER_ROWS:
                break
            gov = r["My"][1] if r["My"][0] >= r["Mz"][0] else r["Mz"][1]
            rows.append([eid, secname.get(eid, "")] + [_f(r[q][0]) for q in QTY] + [gov])
        d.add(_table(rows, widths=[16 * mm, 16 * mm, 18 * mm, 17 * mm, 17 * mm, 15 * mm, 18 * mm, 18 * mm, 30 * mm], align_right_from=2,
                     styles_extra=[("ALIGN", (-1, 0), (-1, -1), "LEFT")]))
        if len(env) > MAX_MEMBER_ROWS:
            d.p(f"Only the first {MAX_MEMBER_ROWS} of {len(env)} members are listed.", "muted")

    # ------------------------------------------------------------------ stability
    if buck:
        d.h1("Elastic critical buckling", "CALCULATED")
        d.p(f"Load: <b>{_esc(buck['load'])}</b> {_esc(buck.get('load_name', ''))}.", "small")
        rows = [["Mode", "Critical load factor alpha_cr"]] + [[str(k + 1), _f(m["factor"], 3)] for k, m in enumerate(buck["modes"])]
        d.add(_table(rows, widths=[20 * mm, 45 * mm], align_right_from=1))
        if buck["modes"]:
            a = buck["modes"][0]["factor"]
            d.p(f"Lowest alpha_cr = {a:.2f}. For reference, EN 1993-1-1 5.2.1(3) allows a first-order analysis when alpha_cr >= 10; "
                "AISC 360 Appendix 7 / Chapter C use the ratio of second-order to first-order drift instead. The program does "
                "not decide which analysis your project needs.", "small")
        d.bullets(buck.get("notes", []))
        d.bullets([w.get("message", "") for w in buck.get("warnings", []) if w.get("level") != "info"])

    # ------------------------------------------------------------------ steel
    if steel:
        d.story.append(PageBreak())
        d.h1(f"Steel member design: {steel['code_name']}", "CALCULATED")
        _design_summary(d, steel)
        rows = [["Member", "Section", "L (m)", "K y / z", "Lb (m)", "Util.", "Governing check", "Clause", "Combo", "Status"]]
        for m in sorted(steel["members"].values(), key=lambda m: -(m.get("util") or -1)):
            if m["status"] == "skipped":
                continue
            p = m.get("params", {})
            g = m.get("governing") or {}
            rows.append([m["id"], Paragraph(_esc(m.get("section", "")), st["cell"]), _f(p.get("L")),
                         f"{_f(p.get('Ky'))} / {_f(p.get('Kz'))}" if p else "", _f(p.get("Lb")), _f(m.get("util")),
                         Paragraph(_esc(g.get("name", m.get("reason", ""))), st["cell"]), _esc(g.get("clause", "")),
                         g.get("combo", ""), _status(m["status"])])
        d.add(_table(rows, widths=[13 * mm, 34 * mm, 11 * mm, 15 * mm, 11 * mm, 11 * mm, 40 * mm, 18 * mm, 12 * mm, 17 * mm],
                     align_right_from=None, styles_extra=_status_styles(rows)))
        _detail_tables(d, steel, st)
        _design_notes(d, steel)

    # ------------------------------------------------------------------ RC
    if rc:
        d.story.append(PageBreak())
        d.h1(f"Reinforced concrete design: {rc['code_name']}", "CALCULATED")
        o = rc.get("options", {})
        d.p(f"Main bars {_esc(o.get('main_grade', ''))}, stirrups / ties {_esc(o.get('tie_grade', ''))}, clear cover "
            f"{_f((o.get('cover') or 0) * 100, 1)} cm, stirrup {_esc(o.get('stirrup', ''))}. " + _tag("INPUT"), "small")
        _design_summary(d, rc)
        beams = [m for m in rc["members"].values() if m.get("kind") == "beam"]
        cols = [m for m in rc["members"].values() if m.get("kind") == "column"]
        if beams:
            d.h2("Beams")
            rows = [["Member", "Section", "Bottom", "Top", "Stirrups", "Side bars", "Util.", "Governing", "Status"]]
            for m in beams:
                rb = m.get("rebar", {})
                g = m.get("governing") or {}
                rows.append([m["id"], Paragraph(_esc(m.get("section", "")), st["cell"]), rb.get("bottom", "–"), rb.get("top", "–"),
                             Paragraph(_esc(rb.get("stirrups", "–")), st["cell"]), Paragraph(_esc(rb.get("side", "")), st["cell"]),
                             _f(m.get("util")), Paragraph(_esc(g.get("name", m.get("reason", ""))), st["cell"]), _status(m["status"])])
            d.add(_table(rows, widths=[13 * mm, 26 * mm, 16 * mm, 16 * mm, 30 * mm, 22 * mm, 11 * mm, 31 * mm, 17 * mm],
                         styles_extra=_status_styles(rows)))
        if cols:
            d.h2("Columns")
            rows = [["Member", "Section", "Bars", "rho (%)", "Layout", "Ties", "Util.", "Governing", "Status"]]
            for m in cols:
                rb = m.get("rebar", {})
                g = m.get("governing") or {}
                rows.append([m["id"], Paragraph(_esc(m.get("section", "")), st["cell"]), rb.get("bars", "–"), _f(rb.get("rho_percent")),
                             Paragraph(_esc(rb.get("layout", "")), st["cell"]), Paragraph(_esc(rb.get("ties", "–")), st["cell"]),
                             _f(m.get("util")), Paragraph(_esc(g.get("name", m.get("reason", ""))), st["cell"]), _status(m["status"])])
            d.add(_table(rows, widths=[13 * mm, 26 * mm, 16 * mm, 11 * mm, 27 * mm, 24 * mm, 11 * mm, 37 * mm, 17 * mm],
                         styles_extra=_status_styles(rows)))
        _detail_tables(d, rc, st)
        _design_notes(d, rc)

    # ------------------------------------------------------------------ closing
    d.h1("Limitations")
    d.bullets([
        "The analysis is linear elastic. Second-order effects are included only where a P-Delta load is listed.",
        "Member design covers only the checks listed in the tables; members marked NOT COVERED or skipped must be checked by hand.",
        "Connections, base plates, foundations, punching shear, slabs, walls, fatigue, fire, serviceability limits "
        "(deflection, vibration) and detailing (anchorage, laps, curtailment) are not checked by this report.",
        "Default sections, effective lengths and supports chosen by a generator or by the DXF import are assumptions: "
        "replace them with the project values before relying on the results.",
        "This report does not state that the structure is safe or code-compliant.",
    ])

    buf = io.BytesIO()
    title = project.get("title") or model.get("name") or "Structural model"

    def page(canvas, doc):
        canvas.saveState()
        w, h = doc.pagesize
        canvas.setStrokeColor(ACCENT)
        canvas.setLineWidth(0.8)
        canvas.line(15 * mm, h - 12 * mm, w - 15 * mm, h - 12 * mm)
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(MUTED)
        canvas.drawString(15 * mm, h - 10.5 * mm, f"{title}: calculation report")
        canvas.drawRightString(w - 15 * mm, h - 10.5 * mm, now.strftime("%Y-%m-%d %H:%M"))
        canvas.drawString(15 * mm, 9 * mm, "Structural Analyze. Results are calculated; see section labels and limitations.")
        canvas.drawRightString(w - 15 * mm, 9 * mm, f"Page {doc.page}")
        canvas.restoreState()

    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=17 * mm, bottomMargin=15 * mm,
                            title=f"{title}: calculation report", author=project.get("engineer") or "Structural Analyze",
                            subject="Structural calculation report", creator="Structural Analyze")
    doc.build(d.story, onFirstPage=page, onLaterPages=page)
    return buf.getvalue()


def _image(data: str):
    try:
        raw = base64.b64decode(data.split(",", 1)[1] if data.startswith("data:") else data, validate=False)
        if not raw.startswith(b"\x89PNG") and not raw.startswith(b"\xff\xd8"):
            return None
        img = Image(io.BytesIO(raw))
        w, h = img.imageWidth, img.imageHeight
        maxw, maxh = 180 * mm, 120 * mm
        s = min(maxw / w, maxh / h)
        img.drawWidth, img.drawHeight = w * s, h * s
        return img
    except Exception:       # a bad screenshot never stops the report
        return None


def _support_kind(s):
    from .solver import SUPPORT_TYPES
    dofs = list(map(int, s.get("dofs") or SUPPORT_TYPES.get(s.get("type", "fixed"), [1] * 6)))
    if s.get("type") and not s.get("dofs"):
        return s["type"]
    if dofs == [1] * 6:
        return "fixed"
    if dofs == [1, 1, 1, 0, 0, 0]:
        return "pinned"
    return "restrained " + " ".join(k for k, v in zip(("ux", "uy", "uz", "rx", "ry", "rz"), dofs) if v)


def _status(s):
    return STATUS.get(s, (s, MUTED))[0]


def _status_styles(rows):
    out = []
    for r, row in enumerate(rows[1:], start=1):
        for label, c in STATUS.values():
            if row[-1] == label:
                out.append(("TEXTCOLOR", (-1, r), (-1, r), c))
                out.append(("FONT", (-1, r), (-1, r), "Helvetica-Bold", 7))
    return out


def _design_summary(d, r):
    s = r["summary"]
    rows = [["Checked", "OK", "Over 1.0", "Not covered", "Skipped", "Max utilisation"],
            [str(s.get("n_checked", s["ok"] + s["fail"])), str(s["ok"]), str(s["fail"]), str(s["not_covered"]),
             str(s.get("skipped", 0)), _f(s.get("max_util"))]]
    d.add(_table(rows, widths=[26 * mm] * 6, align_right_from=0))
    d.p(f"Combinations used: {_esc(', '.join(r.get('combinations', [])))}.", "muted")


def _detail_tables(d, r, st, n=6):
    """All checks of the most utilised members and of every member over 1.0 (up to 12)."""
    ms = [m for m in r["members"].values() if m.get("util") is not None]
    ms.sort(key=lambda m: -m["util"])
    pick = [m for m in ms if m["status"] == "fail"][:12]
    for m in ms[:n]:
        if m not in pick:
            pick.append(m)
    if not pick:
        return
    d.h2("Check details: most utilised members" + (" and members over 1.0" if any(m["status"] == "fail" for m in pick) else ""))
    for m in pick:
        rows = [["Check", "Clause", "Combo", "x (m)", "Demand", "Capacity", "Unit", "Ratio"]]
        for c in sorted(m.get("checks", []), key=lambda c: -(c.get("ratio") or 0)):
            unit = UNIT.get(c.get("unit"), c.get("unit", ""))
            dg = 3 if c.get("unit") == "ratio" else 2
            rows.append([Paragraph(_esc(c["name"]), st["cell"]), _esc(c.get("clause", "")), c.get("combo", ""), _f(c.get("x")),
                         _f(abs(c["demand"]) if c.get("unit") != "ratio" else c["demand"], dg), _f(c["capacity"], dg), unit,
                         _f(c.get("ratio"), 3)])
        head = Paragraph(f"<b>{_esc(m['id'])}</b> {_esc(m.get('section', ''))}: utilisation <b>{_f(m['util'], 3)}</b> "
                         f"({_status(m['status'])})", st["small"])
        tab = _table(rows, widths=[52 * mm, 26 * mm, 14 * mm, 12 * mm, 20 * mm, 20 * mm, 12 * mm, 14 * mm], align_right_from=3,
                     styles_extra=[("ALIGN", (6, 0), (6, -1), "LEFT")]
                     + [("TEXTCOLOR", (-1, k), (-1, k), STATUS["fail"][1]) for k, row in enumerate(rows[1:], 1)
                        if _num(row[-1]) > 1.0])
        d.add(KeepTogether([head, Spacer(1, 2), tab]))
        if m.get("notes"):
            d.bullets(m["notes"], "muted")
        d.gap(5)


def _num(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return 0.0


def _design_notes(d, r):
    nc = [m for m in r["members"].values() if m["status"] == "not_covered"]
    if nc:
        d.h2(f"Not covered ({len(nc)}): outside the implemented clauses, check by hand")
        d.bullets([f"{m['id']}: {m.get('reason', '')}" for m in nc[:40]])
        if len(nc) > 40:
            d.p(f"… and {len(nc) - 40} more.", "muted")
    member_notes = Counter(n for m in r["members"].values() for n in m.get("notes", []) or [])
    d.h2("Design notes and assumptions", "ASSUMED")
    d.bullets(list(r.get("notes", [])) + [f"{n} ({k} member{'s' if k != 1 else ''})" for n, k in member_notes.most_common(12)])


__all__ = ["build_report", "ReportError", "INCLUDE_DEFAULTS"]
