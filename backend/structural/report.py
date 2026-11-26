"""PDF calculation report.

The report re-runs the linear analysis (and, when asked, buckling and the member designs) on the server from the model
it is given, so every number in it comes from this code at the time of printing; nothing is copied from the browser.
Each part is labelled INPUT (what the user or a generator defined), ASSUMED (defaults the program chose) or CALCULATED.
The report never states that the structure is safe or code-compliant.
"""
from __future__ import annotations

import base64
import contextvars
import datetime as dt
import io
from collections import Counter
from pathlib import Path

import numpy as np
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)

from .analysis import analyze
from .sections import MATERIALS, section_properties
from .report_i18n import TH, check_name_th, rebar_th, thai_date
from .serviceability import DEFAULT_LIMITS as DEFL_DEFAULTS
from .steel_design import combine_member, design_combinations

INCLUDE_DEFAULTS = {"model": True, "loads": True, "analysis": True, "members": True, "stability": False,
                    "steel": True, "rc": True, "deflection": True}
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
# language: English (built-in Helvetica) or Thai (bundled Sarabun font, shaped with HarfBuzz)
# ---------------------------------------------------------------------------------------------------------------
LANGS = ("en", "th")
FONT_DIR = Path(__file__).with_name("fonts")
_LANG = contextvars.ContextVar("report_lang", default="en")


def _th() -> bool:
    return _LANG.get() == "th"


def tr(key: str, en: str | None = None, **kw) -> str:
    """Text in the report language. ``key`` is the English text, or a short key with the English given as ``en``."""
    s = TH.get(key, en or key) if _th() else (en or key)
    return s.format(**kw) if kw else s


def _FN() -> str:
    return "Sarabun" if _th() else "Helvetica"


def _FB() -> str:
    return "Sarabun-Bold" if _th() else "Helvetica-Bold"


def _register_thai():
    """Register the Thai font once. Thai needs text shaping (tone marks over vowels), done by uharfbuzz."""
    try:
        import uharfbuzz  # noqa: F401
    except ImportError as exc:
        raise ReportError("The Thai report needs the uharfbuzz library for Thai text: run "
                          "'pip install -r backend/requirements.txt' (run.bat / run.sh do this on start).") from exc
    if "Sarabun" in pdfmetrics.getRegisteredFontNames():
        return
    pdfmetrics.registerFont(TTFont("Sarabun", str(FONT_DIR / "Sarabun-Regular.ttf")))
    pdfmetrics.registerFont(TTFont("Sarabun-Bold", str(FONT_DIR / "Sarabun-Bold.ttf")))
    pdfmetrics.registerFontFamily("Sarabun", normal="Sarabun", bold="Sarabun-Bold", italic="Sarabun", boldItalic="Sarabun-Bold")


def _rb(text) -> str:
    """Bar description in the report language."""
    return rebar_th(str(text)) if _th() else str(text)


def _cname(name: str) -> str:
    """Design check name in the report language."""
    return check_name_th(name) if _th() else name


# ---------------------------------------------------------------------------------------------------------------
# styles and small helpers
# ---------------------------------------------------------------------------------------------------------------
def _styles():
    ss = getSampleStyleSheet()
    k = 1.12 if _th() else 1.0          # Sarabun has a smaller x-height than Helvetica: print it a little larger
    kl = 1.32 if _th() else 1.0         # and Thai needs room above and below the line for vowels and tone marks
    shp = 1 if _th() else 0
    base = ParagraphStyle("base", parent=ss["Normal"], fontName=_FN(), fontSize=8.5 * k, leading=11 * kl, textColor=INK,
                          shaping=shp, splitLongWords=0 if _th() else 1)   # never split a Thai word between a letter and its mark
    return {
        "base": base,
        "small": ParagraphStyle("small", parent=base, fontSize=7.5 * k, leading=9.5 * kl),
        "muted": ParagraphStyle("muted", parent=base, fontSize=7.5 * k, leading=9.5 * kl, textColor=MUTED),
        "cell": ParagraphStyle("cell", parent=base, fontSize=7 * k, leading=8.5 * kl),
        "cellb": ParagraphStyle("cellb", parent=base, fontName=_FB(), fontSize=7 * k, leading=8.5 * kl),
        "title": ParagraphStyle("title", parent=base, fontName=_FB(), fontSize=20, leading=26, spaceAfter=4),
        "h1": ParagraphStyle("h1", parent=base, fontName=_FB(), fontSize=12.5, leading=17, spaceBefore=10,
                             spaceAfter=4, textColor=ACCENT),
        "h2": ParagraphStyle("h2", parent=base, fontName=_FB(), fontSize=9.5 * k, leading=12.5 * kl, spaceBefore=6, spaceAfter=3),
        "note": ParagraphStyle("note", parent=base, fontSize=8 * k, leading=10.5 * kl, leftIndent=8, bulletIndent=0, alignment=TA_LEFT),
    }


# The built-in PDF fonts only have the WinAnsi (Latin-1) characters: spell the others out.
_GLYPHS = {"α": "alpha", "β": "beta", "γ": "gamma", "δ": "delta", "Δ": "Delta", "ε": "eps", "λ": "lambda", "χ": "chi",
           "ρ": "rho", "φ": "phi", "ϕ": "phi", "Φ": "phi", "σ": "sigma", "τ": "tau", "Σ": "Sum ", "≥": ">=", "≤": "<=",
           "∞": "inf", "√": "sqrt", "→": "->", "⁴": "4", "⁻": "-", "₀": "0", "₁": "1", "₂": "2", "ₓ": "x", "ᵧ": "y",
           "′": "'", "−": "-", "≈": "~", "·": "·"}


def _cmap() -> dict:
    return pdfmetrics.getFont("Sarabun").face.charToGlyph


def _is_thai(s: str) -> bool:
    return any("\u0e00" <= ch <= "\u0e7f" for ch in s)


def _t(s) -> str:
    s = str(s)
    if s.isascii():
        return s
    cmap = _cmap() if _th() else None
    out = []
    for ch in s:
        if cmap is not None and ord(ch) in cmap and ch not in _GLYPHS:
            out.append(ch)
        elif ch in _GLYPHS:
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


_CELL = {}


def _cell_style(bold: bool, right: bool) -> ParagraphStyle:
    key = (_LANG.get(), bold, right)
    if key not in _CELL:
        st = _styles()
        _CELL[key] = ParagraphStyle(f"c{key}", parent=st["cellb" if bold else "cell"], alignment=2 if right else 0)
    return _CELL[key]


def _fit_header_words(header, widths):
    """Widen columns whose Thai header has a word wider than the column (Thai words cannot be split), taking the
    room from the widest column."""
    need = []
    for c, w in zip(header, widths):
        words = c.split() if isinstance(c, str) and _is_thai(c) else []
        need.append(max([pdfmetrics.stringWidth(x, _FB(), 7.5) for x in words] + [0]) + 7)
    widths = list(widths)
    extra = sum(max(0.0, n - w) for n, w in zip(need, widths))
    if extra <= 0:
        return widths
    big = max(range(len(widths)), key=lambda k: widths[k] - need[k])
    for k, n in enumerate(need):
        if k != big and n > widths[k]:
            widths[k] = n
    widths[big] = max(widths[big] - extra, need[big])
    return widths


def _table(rows, widths=None, header_rows=1, align_right_from=None, styles_extra=()):
    rows = [[_t(c) if isinstance(c, str) else c for c in row] for row in rows]
    if _th():
        widths = _fit_header_words(rows[0], widths) if header_rows and widths else widths
        # Table cells are drawn without shaping: Thai text goes into shaped paragraphs
        rows = [[Paragraph(_esc(c), _cell_style(r < header_rows, align_right_from is not None and k >= align_right_from))
                 if isinstance(c, str) and _is_thai(c) else c for k, c in enumerate(row)] for r, row in enumerate(rows)]
    fs = 7.5 if _th() else 7
    t = Table(rows, colWidths=widths, repeatRows=header_rows)
    st = [
        ("FONT", (0, 0), (-1, -1), _FN(), fs),
        ("FONT", (0, 0), (-1, header_rows - 1), _FB(), fs),
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
    return f'<font size="7" color="{TAG[kind].hexval().replace("0x", "#")}"><b>[{tr(kind)}]</b></font>'


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
                 image_png: str | None = None, stability_load: str | None = None, project: dict | None = None,
                 lang: str = "en", deflection: dict | None = None) -> bytes:
    """Return the PDF bytes. ``image_png`` is an optional base64 PNG (data URL or raw) of the 3D view.
    ``lang`` "en" or "th" (Thai headings, tables and notes; numbers and clause references unchanged).
    ``deflection``: {"limits": {...}, "wind_factor": ...} for the deflection and drift section."""
    if lang not in LANGS:
        raise ReportError(f"unknown report language {lang!r} (use 'en' or 'th')")
    if lang == "th":
        _register_thai()
    token = _LANG.set(lang)
    try:
        return _build(model, include, steel_code, rc_options, image_png, stability_load, project, deflection or {})
    finally:
        _LANG.reset(token)


def _build(model, include, steel_code, rc_options, image_png, stability_load, project, defl_opt) -> bytes:
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
    steel = rc = buck = defl = None
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
            errors.append(tr("Steel design could not run: {e}", e=exc))
    if inc["rc"] and has_conc:
        from .rc_design import rc_design
        try:
            rc = rc_design(model, rc_options or {}, results=res)
        except (ValueError, KeyError) as exc:
            errors.append(tr("RC design could not run: {e}", e=exc))
    if inc["deflection"]:
        from .serviceability import deflection_checks
        try:
            defl = deflection_checks(model, res, defl_opt.get("limits") or None, defl_opt.get("wind_factor"))
        except (ValueError, KeyError) as exc:
            errors.append(tr("Deflection check could not run: {e}", e=exc))
    if inc["stability"]:
        from .stability import buckling
        load = stability_load or (combos[0][0] if combos else (loads[0][0] if loads else None))
        try:
            buck = buckling(model, load, n_modes=4) if load else None
        except (ValueError, KeyError) as exc:
            errors.append(tr("Buckling analysis could not run for {load}: {e}", load=load, e=exc))

    # ------------------------------------------------------------------ title block
    d.p(_esc(project.get("title") or model.get("name") or tr("Structural model")), "title")
    d.p(tr("Calculation report: 3D linear analysis and member design" if (steel or rc) else "Calculation report: 3D linear analysis"), "h2")
    meta = [[tr("Project"), project.get("project") or model.get("name", "–")],
            [tr("Engineer"), project.get("engineer") or "–"],
            [tr("Date"), thai_date(now) if _th() else now.strftime("%d %B %Y, %H:%M")],
            [tr("Design standard (loads)"), tr({"EN1990": "EN 1990 (Eurocode)", "ASCE7": "ASCE 7", "TH": "Thai (DPT / EIT)"}.get(std, std))],
            [tr("Units"), tr("kN, m (forces kN, moments kN·m, displacements mm where noted)")],
            [tr("Software"), tr("Structural Analyze (open source); report generated from the model at the time of printing")]]
    d.add(_table([["", ""]] + meta, widths=[45 * mm, 125 * mm], header_rows=1,
                 styles_extra=[("BACKGROUND", (0, 0), (-1, 0), colors.white), ("LINEBELOW", (0, 0), (-1, 0), 0, colors.white),
                               ("FONT", (0, 1), (0, -1), _FB(), 7.5 if _th() else 7)]))
    d.gap(6)
    d.p(tr("SCOPE", "<b>Scope of this report.</b> Every result below was calculated by the program from the model shown, at "
           "the time of printing. Labels: {INPUT} defined by the user or by a model generator; {ASSUMED} a default or "
           "simplification chosen by the program; {CALCULATED} computed. A utilisation at or below 1.0 means the member "
           "passes the checks listed for it. This report is <b>not</b> a statement that the structure is safe or "
           "code-compliant: connections, foundations, overall stability, serviceability, detailing and the items in the "
           "notes must be checked separately by a qualified engineer.",
           INPUT=_tag("INPUT"), ASSUMED=_tag("ASSUMED"), CALCULATED=_tag("CALCULATED")), "small")
    if _th():
        d.p(tr("LANG_NOTE"), "muted")
    if image_png:
        img = _image(image_png)
        if img is not None:
            d.gap(6)
            d.add(img)
            d.p(tr("3D view of the model as shown on screen when the report was printed (illustration, not a result)."), "muted")
    for e in errors:
        d.p(f'<font color="#b91c1c">{_esc(e)}</font>', "small")

    # ------------------------------------------------------------------ model
    if inc["model"]:
        d.story.append(PageBreak())
        d.h1(tr("Model"), "INPUT")
        counts = [[tr("Nodes"), len(model["nodes"])], [tr("Members"), len(model["elements"])],
                  [tr("Slab panels"), len(model.get("slabs", []))], [tr("Wall panels"), len(model.get("walls", []))],
                  [tr("Supports"), len(model.get("supports", []))], [tr("Load cases"), len(model.get("load_cases", []))],
                  [tr("Combinations"), len(model.get("combinations", []))]]
        xyz = np.array([[n["x"], n["y"], n["z"]] for n in model["nodes"]], dtype=float)
        ext = xyz.max(0) - xyz.min(0) if len(xyz) else np.zeros(3)
        counts.append([tr("Extent X × Y × Z (m)"), f"{ext[0]:.2f} × {ext[1]:.2f} × {ext[2]:.2f}"])
        d.add(_table([[tr("Item"), tr("Value")]] + [[a, str(b)] for a, b in counts], widths=[50 * mm, 50 * mm]))
        gen = model.get("generator", {})
        if gen.get("type"):
            d.p(tr("Model source: {g} generator.", g=_esc(gen["type"])), "muted")

        d.h2(tr("Materials"), "INPUT")
        used_mats = sorted({s.get("material", "") for s in model["sections"].values()})
        rows = [[tr("Id"), tr("Name"), tr("Kind"), "E (MPa)", "fy / fck (MPa)", tr("Density (kN/m³)")]]
        for mid in used_mats:
            m = mats.get(mid, {})
            rows.append([mid, m.get("name", ""), tr(m.get("kind", "")), _f(m.get("E"), 0),
                         _f(m.get("fy", m.get("fck", m.get("fc"))), 1), _f(m.get("gamma", m.get("density")), 1)])
        d.add(_table(rows, widths=[22 * mm, 50 * mm, 20 * mm, 22 * mm, 26 * mm, 28 * mm], align_right_from=3))

        d.h2(tr("Sections"), "INPUT")
        n_use = Counter(e["section"] for e in model["elements"])
        hp = ParagraphStyle("hp", parent=st["cellb"], alignment=2)
        rows = [[tr("Id"), tr("Name"), tr("Shape"), tr("Material"), tr("Members"), "A (cm²)"]
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

        d.h2(tr("Supports"), "INPUT")
        sup = Counter(_support_kind(s) for s in model.get("supports", []))
        d.p(_esc(", ".join(f"{n} {k}" for k, n in sup.items()) or tr("No supports.")), "small")
        if model.get("notes"):
            d.h2(tr("Model notes"), "INPUT")
            d.bullets(model["notes"])

    # ------------------------------------------------------------------ loads
    if inc["loads"]:
        d.h1(tr("Loads"), "INPUT")
        d.h2(tr("Load cases"))
        n_loads = Counter(l.get("case") for l in model.get("loads", []))
        n_area = Counter(a.get("case") for s in model.get("slabs", []) for a in s.get("loads", []) if isinstance(a, dict))
        rows = [[tr("Id"), tr("Name"), tr("Type"), tr("Self-weight"), tr("Loads defined")]]
        for c in model.get("load_cases", []):
            rows.append([c["id"], Paragraph(_esc(c.get("name", "")), st["cell"]), c.get("type", ""),
                         tr("yes") if c.get("self_weight") else "", str(n_loads.get(c["id"], 0) + n_area.get(c["id"], 0))])
        d.add(_table(rows, widths=[16 * mm, 80 * mm, 22 * mm, 22 * mm, 26 * mm]))
        d.h2(tr("Load combinations"))
        rows = [[tr("Id"), tr("Name"), tr("Factors"), tr("Used for design")]]
        ids = {c for c, _ in combos}
        for c in model.get("combinations", []):
            fac = " + ".join(f"{v:g}·{k}" for k, v in c.get("factors", {}).items())
            rows.append([c["id"], Paragraph(_esc(c.get("name", "")), st["cell"]), Paragraph(_esc(fac), st["cell"]),
                         "ULS" if c["id"] in ids else tr("no (serviceability)")])
        d.add(_table(rows, widths=[16 * mm, 55 * mm, 70 * mm, 25 * mm]))
        d.p(tr("Combinations whose id or name contains sls, serv, service, characteristic or ths are treated as "
               "serviceability combinations and are not used for member design."), "muted")

    # ------------------------------------------------------------------ analysis
    if inc["analysis"]:
        d.story.append(PageBreak())
        d.h1(tr("Linear static analysis"), "CALCULATED")
        d.p(_esc(res.get("solver", {}).get("type", "")), "small")
        d.bullets(res.get("log", []), "note")
        assumed = [tr("Linear elastic material, small displacements (first-order analysis) unless P-Delta is listed below."),
                   tr("Members are straight Euler-Bernoulli beam elements; member end releases as defined.")]
        if res.get("slab_model") != "shell" and model.get("slabs"):
            assumed.append(tr("Slab area loads are distributed to the supporting beams by tributary areas; slabs are not FE-analysed."))
        d.h2(tr("Analysis assumptions"), "ASSUMED")
        d.bullets(assumed)
        if res.get("warnings"):
            d.h2(tr("Solver messages"))
            d.bullets([w.get("message", "") for w in res["warnings"]])

        d.h2(tr("Equilibrium check (sum of applied loads vs sum of reactions)"), "CALCULATED")
        rows = [[tr(h) for h in ("Load case", "Sum Fx applied", "Sum Fy applied", "Sum Fz applied", "Sum Fz reactions",
                                 "Force error", "Moment error", "Check")]]
        for c in model.get("load_cases", []):
            eq = res["cases"].get(c["id"], {}).get("equilibrium")
            if not eq:
                continue
            a, r = eq["applied"], eq["reactions"]
            rows.append([c["id"], _f(a[0]), _f(a[1]), _f(a[2]), _f(r[2]), f"{eq['force_error']:.1e}", f"{eq['moment_error']:.1e}",
                         tr("OK") if eq.get("ok") else tr("CHECK")])
        d.add(_table(rows, widths=[20 * mm, 22 * mm, 22 * mm, 22 * mm, 24 * mm, 20 * mm, 22 * mm, 14 * mm], align_right_from=1))
        d.p(tr("Errors are relative to the applied load; values near machine precision mean the solution is in equilibrium."), "muted")

        d.h2(tr("Support reactions per load case (kN, kN·m)"), "CALCULATED")
        for c in model.get("load_cases", []):
            reac = res["cases"].get(c["id"], {}).get("reactions", {})
            if not reac:
                continue
            rows = [[tr("Node"), "Fx", "Fy", "Fz", "Mx", "My", "Mz"]]
            tot = np.zeros(6)
            for nid, v in reac.items():
                rows.append([nid] + [_f(x) for x in v])
                tot += np.asarray(v, dtype=float)
            rows.append([tr("Sum")] + [_f(x) for x in tot[:3]] + ["", "", ""])
            d.add(KeepTogether([Paragraph(f"<b>{_esc(c['id'])}</b> {_esc(c.get('name', ''))}", st["small"]), Spacer(1, 2)]))
            d.add(_table(rows, widths=[22 * mm] + [24 * mm] * 6, align_right_from=1,
                         styles_extra=[("FONT", (0, -1), (-1, -1), _FB(), 7.5 if _th() else 7), ("LINEABOVE", (0, -1), (-1, -1), 0.6, INK)]))
            d.gap(4)
        if model.get("combinations"):
            d.p(tr("Reactions for a combination are the sums of the load-case reactions above multiplied by the combination "
                   "factors (linear analysis)."), "muted")

        d.h2(tr("Extreme member internal forces per load (kN, kN·m)"), "CALCULATED")
        d.p(tr("Local axes: N axial (tension positive), Vy / Vz shear, T torsion, My / Mz bending about the local y / z axes. "
               "Values are taken at the member stations (ends, intermediate points)."), "muted")
        rows = [[tr(h) for h in ("Load", "Force", "Max", "Member @ x (m)", "Min", "Member @ x (m)")]]
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
        d.h2(tr("Member force envelope over all combinations (largest absolute values, kN, kN·m)"), "CALCULATED")
        env_loads = [l for l in loads if l[0] in {c["id"] for c in model.get("combinations", [])}] or loads
        env = _member_envelope(model, res, env_loads)
        rows = [[tr("Member"), tr("Section"), "|N|", "|Vy|", "|Vz|", "|T|", "|My|", "|Mz|", tr("Governing load (|M| max)")]]
        secname = {e["id"]: e["section"] for e in model["elements"]}
        for k, (eid, r) in enumerate(env.items()):
            if k >= MAX_MEMBER_ROWS:
                break
            gov = r["My"][1] if r["My"][0] >= r["Mz"][0] else r["Mz"][1]
            rows.append([eid, secname.get(eid, "")] + [_f(r[q][0]) for q in QTY] + [gov])
        d.add(_table(rows, widths=[16 * mm, 16 * mm, 18 * mm, 17 * mm, 17 * mm, 15 * mm, 18 * mm, 18 * mm, 30 * mm], align_right_from=2,
                     styles_extra=[("ALIGN", (-1, 0), (-1, -1), "LEFT")]))
        if len(env) > MAX_MEMBER_ROWS:
            d.p(tr("Only the first {n} of {m} members are listed.", n=MAX_MEMBER_ROWS, m=len(env)), "muted")

    # ------------------------------------------------------------------ stability
    if buck:
        d.h1(tr("Elastic critical buckling"), "CALCULATED")
        d.p(tr("Load: <b>{load}</b> {name}.", load=_esc(buck["load"]), name=_esc(buck.get("load_name", ""))), "small")
        rows = [[tr("Mode"), tr("Critical load factor alpha_cr")]] + [[str(k + 1), _f(m["factor"], 3)] for k, m in enumerate(buck["modes"])]
        d.add(_table(rows, widths=[20 * mm, 45 * mm], align_right_from=1))
        if buck["modes"]:
            a = buck["modes"][0]["factor"]
            d.p(_esc(tr("BUCKLING_REF", "Lowest alpha_cr = {a}. For reference, EN 1993-1-1 5.2.1(3) allows a first-order "
                        "analysis when alpha_cr >= 10; AISC 360 Appendix 7 / Chapter C use the ratio of second-order to "
                        "first-order drift instead. The program does not decide which analysis your project needs.",
                        a=f"{a:.2f}")), "small")
        d.bullets(buck.get("notes", []))
        d.bullets([w.get("message", "") for w in buck.get("warnings", []) if w.get("level") != "info"])

    # ------------------------------------------------------------------ steel
    if steel:
        d.story.append(PageBreak())
        d.h1(tr("Steel member design: {code}", code=steel["code_name"]), "CALCULATED")
        _design_summary(d, steel)
        rows = [[tr("Member"), tr("Section"), "L (m)", "K y / z", "Lb (m)", tr("Util."), tr("Governing check"), tr("Clause"),
                 tr("Combo"), tr("Status")]]
        for m in sorted(steel["members"].values(), key=lambda m: -(m.get("util") or -1)):
            if m["status"] == "skipped":
                continue
            p = m.get("params", {})
            g = m.get("governing") or {}
            rows.append([m["id"], Paragraph(_esc(m.get("section", "")), st["cell"]), _f(p.get("L")),
                         f"{_f(p.get('Ky'))} / {_f(p.get('Kz'))}" if p else "", _f(p.get("Lb")), _f(m.get("util")),
                         Paragraph(_esc(_cname(g["name"]) if g.get("name") else m.get("reason", "")), st["cell"]),
                         Paragraph(_esc(g.get("clause", "")), st["cell"]),
                         g.get("combo", ""), _status(m["status"])])
        d.add(_table(rows, widths=[13 * mm, 34 * mm, 11 * mm, 15 * mm, 11 * mm, 11 * mm, 40 * mm, 18 * mm, 12 * mm, 17 * mm],
                     align_right_from=None, styles_extra=_status_styles(rows)))
        _detail_tables(d, steel, st)
        _design_notes(d, steel)

    # ------------------------------------------------------------------ RC
    if rc:
        d.story.append(PageBreak())
        d.h1(tr("Reinforced concrete design: {code}", code=rc["code_name"]), "CALCULATED")
        o = rc.get("options", {})
        d.p(_esc(tr("RC_OPTIONS", "Main bars {main}, stirrups / ties {tie}, clear cover {cover} cm, stirrup {stirrup}.",
                    main=o.get("main_grade", ""), tie=o.get("tie_grade", ""), cover=_f((o.get("cover") or 0) * 100, 1),
                    stirrup=o.get("stirrup", ""))) + " " + _tag("INPUT"), "small")
        _design_summary(d, rc)
        beams = [m for m in rc["members"].values() if m.get("kind") == "beam"]
        cols = [m for m in rc["members"].values() if m.get("kind") == "column"]
        if beams:
            d.h2(tr("Beams"))
            rows = [[tr(h) for h in ("Member", "Section", "Bottom", "Top", "Stirrups", "Side bars", "Util.", "Governing", "Status")]]
            for m in beams:
                rb = m.get("rebar", {})
                g = m.get("governing") or {}
                rows.append([m["id"], Paragraph(_esc(m.get("section", "")), st["cell"]), rb.get("bottom", "–"), rb.get("top", "–"),
                             Paragraph(_esc(_rb(rb.get("stirrups", "–"))), st["cell"]), Paragraph(_esc(_rb(rb.get("side", ""))), st["cell"]),
                             _f(m.get("util")), Paragraph(_esc(_cname(g["name"]) if g.get("name") else m.get("reason", "")), st["cell"]), _status(m["status"])])
            d.add(_table(rows, widths=[13 * mm, 26 * mm, 16 * mm, 16 * mm, 30 * mm, 22 * mm, 11 * mm, 31 * mm, 17 * mm],
                         styles_extra=_status_styles(rows)))
        if cols:
            d.h2(tr("Columns"))
            rows = [[tr("Member"), tr("Section"), tr("Bars"), "rho (%)", tr("Layout"), tr("Ties"), tr("Util."), tr("Governing"), tr("Status")]]
            for m in cols:
                rb = m.get("rebar", {})
                g = m.get("governing") or {}
                rows.append([m["id"], Paragraph(_esc(m.get("section", "")), st["cell"]), rb.get("bars", "–"), _f(rb.get("rho_percent")),
                             Paragraph(_esc(_rb(rb.get("layout", ""))), st["cell"]), Paragraph(_esc(_rb(rb.get("ties", "–"))), st["cell"]),
                             _f(m.get("util")), Paragraph(_esc(_cname(g["name"]) if g.get("name") else m.get("reason", "")), st["cell"]), _status(m["status"])])
            d.add(_table(rows, widths=[13 * mm, 26 * mm, 16 * mm, 11 * mm, 27 * mm, 24 * mm, 11 * mm, 37 * mm, 17 * mm],
                         styles_extra=_status_styles(rows)))
        _detail_tables(d, rc, st)
        _design_notes(d, rc)

    if defl and defl["items"]:
        d.story.append(PageBreak())
        d.h1(tr("Deflection and drift (serviceability)"), "CALCULATED")
        lim = defl["limits"]
        changed = any(lim[k] != v for k, v in DEFL_DEFAULTS.items())
        d.p(_esc(tr("DEFL_LIMITS", "Limits: floors L/{fl} live, L/{ft} total; roof members L/{rl} live or wind, L/{rt} total; "
                    "cantilevers use 2L; storey drift H/{dr}.", fl=_f(lim["floor_live"], 0), ft=_f(lim["floor_total"], 0),
                    rl=_f(lim["roof_live"], 0), rt=_f(lim["roof_total"], 0), dr=_f(defl["drift_limit"], 0)))
            + " " + _tag("INPUT" if changed else "ASSUMED"), "small")
        d.p(tr("Combinations used: {c}.", c=_esc(", ".join(f"{c['id']} ({c['name']})" for c in defl["combinations"]))), "muted")
        s = defl["summary"]
        d.add(_table([[tr(h) for h in ("Checked", "Within the limit", "Over the limit", "Max deflection / limit")],
                      [str(s["n"]), str(s["ok"]), str(s["fail"]), _f(s.get("max_util"))]],
                     widths=[30 * mm] * 4, align_right_from=0))
        kind = {"beam": "span", "cantilever": "cantilever", "truss": "truss", "drift": "storey drift"}
        rows = [[tr(h) for h in ("Item", "Members", "Type", "L or H (m)", "δ (mm)", "Allowed (mm)", "Limit", "Combo", "Ratio", "Status")]]
        shown = defl["items"][:60]
        for it in shown:
            mem = ", ".join(it["elements"][:3]) + (f" +{len(it['elements']) - 3}" if len(it["elements"]) > 3 else "")
            rows.append([it["id"], Paragraph(_esc(mem), st["cell"]), Paragraph(_esc(f"{it['role']} {tr(kind[it['kind']])}"), st["cell"]),
                         _f(it["L"]), _f(it["delta"] * 1000, 1), _f(it["allow"] * 1000, 1),
                         Paragraph(_esc(it["limit"]), st["cell"]), it["combo"], _f(it["util"]), _status(it["status"])])
        d.add(_table(rows, widths=[10 * mm, 30 * mm, 26 * mm, 14 * mm, 13 * mm, 15 * mm, 22 * mm, 14 * mm, 11 * mm, 17 * mm],
                     align_right_from=3, styles_extra=[("ALIGN", (6, 0), (7, -1), "LEFT")] + _status_styles(rows)))
        if len(defl["items"]) > len(shown):
            d.p(tr("… and {n} more.", n=len(defl["items"]) - len(shown)), "muted")
        d.h2(tr("Deflection notes and assumptions"), "ASSUMED")
        d.bullets(list(defl["notes"]))

    # ------------------------------------------------------------------ closing
    d.h1(tr("Limitations"))
    d.bullets([tr(x) for x in (
        "The analysis is linear elastic. Second-order effects are included only where a P-Delta load is listed.",
        "Member design covers only the checks listed in the tables; members marked NOT COVERED or skipped must be checked by hand.",
        ("Connections, base plates, foundations, punching shear, slabs, walls, fatigue, fire, vibration and detailing "
         "(anchorage, laps, curtailment) are not checked by this report." if defl else
         "Connections, base plates, foundations, punching shear, slabs, walls, fatigue, fire, serviceability limits "
         "(deflection, vibration) and detailing (anchorage, laps, curtailment) are not checked by this report."),
        "Default sections, effective lengths and supports chosen by a generator or by the DXF import are assumptions: "
        "replace them with the project values before relying on the results.",
        "This report does not state that the structure is safe or code-compliant.",
    )])

    buf = io.BytesIO()
    title = project.get("title") or model.get("name") or tr("Structural model")
    th = _th()
    head = _t(tr("{title}: calculation report", title=title))
    foot = tr("Structural Analyze. Results are calculated; see section labels and limitations.")

    def page(canvas, doc):
        canvas.saveState()
        w, h = doc.pagesize
        canvas.setStrokeColor(ACCENT)
        canvas.setLineWidth(0.8)
        canvas.line(15 * mm, h - 12 * mm, w - 15 * mm, h - 12 * mm)
        canvas.setFont(_FN(), 7.5 if th else 7)
        canvas.setFillColor(MUTED)
        canvas.drawString(15 * mm, h - 10.5 * mm, head, shaping=th)
        canvas.drawRightString(w - 15 * mm, h - 10.5 * mm, now.strftime("%Y-%m-%d %H:%M"))
        canvas.drawString(15 * mm, 9 * mm, foot, shaping=th)
        canvas.drawRightString(w - 15 * mm, 9 * mm, tr("Page {n}", n=doc.page), shaping=th)
        canvas.restoreState()

    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=17 * mm, bottomMargin=15 * mm,
                            title=tr("{title}: calculation report", title=title), author=project.get("engineer") or "Structural Analyze",
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
        return tr(s["type"])
    if dofs == [1] * 6:
        return tr("fixed")
    if dofs == [1, 1, 1, 0, 0, 0]:
        return tr("pinned")
    return tr("restrained") + " " + " ".join(k for k, v in zip(("ux", "uy", "uz", "rx", "ry", "rz"), dofs) if v)


def _status(s):
    return tr(STATUS.get(s, (s, MUTED))[0])


def _status_styles(rows):
    out = []
    for r, row in enumerate(rows[1:], start=1):
        for label, c in STATUS.values():
            if row[-1] == tr(label):
                out.append(("TEXTCOLOR", (-1, r), (-1, r), c))
                out.append(("FONT", (-1, r), (-1, r), _FB(), 7.5 if _th() else 7))
    return out


def _design_summary(d, r):
    s = r["summary"]
    rows = [[tr(h) for h in ("Checked", "OK", "Over 1.0", "Not covered", "Skipped", "Max utilisation")],
            [str(s.get("n_checked", s["ok"] + s["fail"])), str(s["ok"]), str(s["fail"]), str(s["not_covered"]),
             str(s.get("skipped", 0)), _f(s.get("max_util"))]]
    d.add(_table(rows, widths=[26 * mm] * 6, align_right_from=0))
    d.p(tr("Combinations used: {c}.", c=_esc(", ".join(r.get("combinations", [])))), "muted")


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
    d.h2(tr("Check details: most utilised members and members over 1.0" if any(m["status"] == "fail" for m in pick)
            else "Check details: most utilised members"))
    for m in pick:
        rows = [[tr("Check ").strip(), tr("Clause"), tr("Combo"), "x (m)", tr("Demand"), tr("Capacity"), tr("Unit"), tr("Ratio")]]
        for c in sorted(m.get("checks", []), key=lambda c: -(c.get("ratio") or 0)):
            unit = UNIT.get(c.get("unit"), c.get("unit", ""))
            dg = 3 if c.get("unit") == "ratio" else 2
            rows.append([Paragraph(_esc(_cname(c["name"])), st["cell"]), Paragraph(_esc(c.get("clause", "")), st["cell"]), c.get("combo", ""), _f(c.get("x")),
                         _f(abs(c["demand"]) if c.get("unit") != "ratio" else c["demand"], dg), _f(c["capacity"], dg), unit,
                         _f(c.get("ratio"), 3)])
        head = Paragraph(tr("MEMBER_HEAD", "<b>{id}</b> {sec}: utilisation <b>{u}</b> ({status})", id=_esc(m["id"]),
                            sec=_esc(m.get("section", "")), u=_f(m["util"], 3), status=_status(m["status"])), st["small"])
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
        d.h2(tr("Not covered ({n}): outside the implemented clauses, check by hand", n=len(nc)))
        d.bullets([f"{m['id']}: {m.get('reason', '')}" for m in nc[:40]])
        if len(nc) > 40:
            d.p(tr("… and {n} more.", n=len(nc) - 40), "muted")
    member_notes = Counter(n for m in r["members"].values() for n in m.get("notes", []) or [])
    d.h2(tr("Design notes and assumptions"), "ASSUMED")
    d.bullets(list(r.get("notes", [])) + [f"{n} " + tr("({k} members)" if k != 1 else "({k} member)", k=k)
                                          for n, k in member_notes.most_common(12)])


__all__ = ["build_report", "ReportError", "INCLUDE_DEFAULTS", "LANGS"]
