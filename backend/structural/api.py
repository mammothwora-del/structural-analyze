"""FastAPI application exposing the generator and the solver."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from .analysis import _r, analyze
from .generator import DEFAULTS, generate as generate_structure
from .structures import LATTICE_DEFAULTS, SPACE_DEFAULTS, TRUSS_DEFAULTS, WAREHOUSE_DEFAULTS
from .sections import MATERIALS, section_properties
from .solver import ModelError

app = FastAPI(title="Structural Analyze API", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/defaults")
def defaults():
    return {"generator": DEFAULTS, "truss2d": TRUSS_DEFAULTS, "warehouse": WAREHOUSE_DEFAULTS,
            "space_truss": SPACE_DEFAULTS, "lattice_roof": LATTICE_DEFAULTS, "materials": MATERIALS}


@app.post("/api/generate")
def generate(params: dict | None = None):
    try:
        return generate_structure(params or {})
    except (KeyError, ValueError, IndexError) as exc:
        raise HTTPException(400, f"Invalid generator parameters: {exc}") from exc


@app.post("/api/section-properties")
def section_props(section: dict):
    try:
        return section_properties(section).as_dict()
    except (KeyError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/analyze")
def run_analysis(model: dict):
    try:
        return analyze(model)
    except ModelError as exc:
        raise HTTPException(422, str(exc)) from exc
    except (KeyError, ValueError, IndexError, TypeError) as exc:
        raise HTTPException(400, f"Invalid model: {exc!r}") from exc


@app.post("/api/stability")
def run_stability(req: dict):
    """{"model": {...}, "load": case or combination id, "kind": "buckling" | "pdelta", "n_modes": 4, "n_seg": 4}"""
    from .analysis import _r
    from .stability import buckling, pdelta
    try:
        model, load = req["model"], req["load"]
        if req.get("kind", "buckling") == "pdelta":
            return pdelta(model, load, n_seg=int(req.get("n_seg", 2)))
        return _r(buckling(model, load, n_modes=int(req.get("n_modes", 4)), n_seg=int(req.get("n_seg", 4))))
    except ModelError as exc:
        raise HTTPException(422, str(exc)) from exc
    except (KeyError, ValueError, IndexError, TypeError) as exc:
        raise HTTPException(400, f"Invalid request: {exc!r}") from exc


@app.post("/api/design/steel")
def run_steel_design(req: dict):
    """{"model": {...}, "code": "AISC360" | "EC3" | "EIT" (default from the model's standard)}"""
    from .steel_design import steel_design
    try:
        return _r(steel_design(req["model"], req.get("code") or None))
    except ModelError as exc:
        raise HTTPException(422, str(exc)) from exc
    except (KeyError, ValueError, IndexError, TypeError) as exc:
        raise HTTPException(400, f"Invalid request: {exc!r}") from exc


@app.post("/api/design/steel/suggest")
def run_steel_suggest(req: dict):
    """{"model": {...}, "code": ..., "target": 1.0, "groups": {"COL": "keep" | "lock" | "H" | "SHS" | "RHS" | "CHS"},
    "limit_slenderness": true, "check_deflection": false, "limits": {...}, "wind_factor": null}"""
    from .steel_sizing import suggest_sections
    try:
        return _r(suggest_sections(req["model"], req.get("code") or None, float(req.get("target") or 1.0), req.get("groups") or {},
                                   limit_slenderness=bool(req.get("limit_slenderness", True)),
                                   check_deflection=bool(req.get("check_deflection", False)),
                                   deflection_limits=req.get("limits") or None,
                                   wind_factor=_opt_float(req.get("wind_factor"))))
    except ModelError as exc:
        raise HTTPException(422, str(exc)) from exc
    except (KeyError, ValueError, IndexError, TypeError) as exc:
        raise HTTPException(400, f"Invalid request: {exc}") from exc


def _opt_float(v):
    return None if v in (None, "") else float(v)


@app.post("/api/design/deflection")
def run_deflection(req: dict):
    """{"model": {...}, "limits": {"floor_live": 360, "floor_total": 240, "roof_live": 240, "roof_total": 180,
    "drift_multi": 400, "drift_single": 200}, "wind_factor": 1.0}  (limits as L/n; all optional)"""
    from .serviceability import deflection_checks
    try:
        return _r(deflection_checks(req["model"], None, req.get("limits") or None, _opt_float(req.get("wind_factor"))))
    except ModelError as exc:
        raise HTTPException(422, str(exc)) from exc
    except (KeyError, ValueError, IndexError, TypeError) as exc:
        raise HTTPException(400, f"Invalid request: {exc}") from exc


@app.post("/api/loads/wind")
def run_wind(req: dict):
    """{"model": {...}, "params": {"zone": "1"|"2"|"3"|"4A"|"4B", "importance": "low"|"normal"|"high"|"very_high",
    "exposure": "A"|"B", "internal": "1"|"2"|"3", "use_tf": true, "ridge": "auto"|"x"|"y", "roof_slope": null,
    "all_corners": false, "replace": true}} -> {"model", "summary"} (DPT 1311-50 low-rise method)"""
    from .wind import generate_wind
    try:
        return _r(generate_wind(req["model"], req.get("params") or {}))
    except (KeyError, ValueError, IndexError, TypeError) as exc:
        raise HTTPException(400, f"Wind loads could not be generated: {exc}") from exc


@app.post("/api/boq")
def run_boq(req: dict):
    """{"model": {...}, "options": {"allowance": 0, "currency": "THB", "prices": {"steel" | family: price per kg},
    "concrete_price": price per m3}} -> quantities by section, family and member type"""
    from .boq import quantities
    try:
        return _r(quantities(req["model"], req.get("options") or {}))
    except (KeyError, ValueError, IndexError, TypeError) as exc:
        raise HTTPException(400, f"Quantities could not be calculated: {exc}") from exc


@app.post("/api/boq/xlsx")
def run_boq_xlsx(req: dict):
    """Same request as /api/boq; returns an Excel workbook with live formulas."""
    from .boq import boq_xlsx
    try:
        data = boq_xlsx(req["model"], req.get("options") or {})
    except (KeyError, ValueError, IndexError, TypeError) as exc:
        raise HTTPException(400, f"Quantities could not be calculated: {exc}") from exc
    name = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in (req["model"].get("name") or "model"))[:60]
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{name}-BOQ.xlsx"'})


@app.get("/api/sections/catalog")
def section_catalog():
    """Standard steel section sizes (nominal dimensions in m, area in m², mass in kg/m)."""
    from .steel_catalog import CATALOG, FAMILIES
    return {"families": FAMILIES, "sections": CATALOG}


@app.post("/api/design/rc")
def run_rc_design(req: dict):
    """{"model": {...}, "options": {"main_grade": "SD40", "tie_grade": "SR24", "cover": 0.04, ...}}"""
    from .rc_design import GRADES, rc_design
    try:
        opt = req.get("options") or {}
        for k in ("main_grade", "tie_grade"):
            if k in opt and opt[k] not in GRADES:
                raise ValueError(f"unknown rebar grade {opt[k]!r}")
        return _r(rc_design(req["model"], opt))
    except ModelError as exc:
        raise HTTPException(422, str(exc)) from exc
    except (KeyError, ValueError, IndexError, TypeError) as exc:
        raise HTTPException(400, f"Invalid request: {exc!r}") from exc


@app.post("/api/import/dxf")
def import_dxf_file(req: dict):
    """{"dxf": text of an ASCII DXF file, "options": {"units": "auto", "material": "steel", "support": "fixed", ...}}"""
    from .dxf_import import DXFError, import_dxf
    text = req.get("dxf")
    if not isinstance(text, str):
        raise HTTPException(400, "Send the DXF file as text in the field 'dxf'")
    if len(text) > 50_000_000:
        raise HTTPException(413, "DXF file larger than 50 MB")
    try:
        return import_dxf(text, req.get("options") or {})
    except DXFError as exc:
        raise HTTPException(400, f"Could not import the DXF file: {exc}") from exc
    except (KeyError, ValueError, IndexError, TypeError) as exc:
        raise HTTPException(400, f"Could not import the DXF file: {exc!r}") from exc


@app.post("/api/report")
def make_report(req: dict):
    """{"model": {...}, "include": {...}, "steel_code": "", "rc_options": {...}, "image": base64 PNG, "project": {...},
     "lang": "en" | "th"}

    Re-runs the analysis and the designs on the server and returns a PDF."""
    from .report import ReportError, build_report
    try:
        pdf = build_report(req["model"], req.get("include"), req.get("steel_code") or None, req.get("rc_options"),
                           req.get("image"), req.get("stability_load") or None, req.get("project"),
                           lang=req.get("lang") or "en", deflection=req.get("deflection") or None,
                           boq=req.get("boq") or None)
    except (ModelError, ReportError) as exc:
        raise HTTPException(422, str(exc)) from exc
    except (KeyError, ValueError, IndexError, TypeError) as exc:
        raise HTTPException(400, f"Invalid request: {exc!r}") from exc
    name = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in (req["model"].get("name") or "model"))[:60]
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{name}-report{"-th" if req.get("lang") == "th" else ""}.pdf"'})


# Serve the built frontend (frontend/dist) when present.
_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if _dist.exists():
    app.mount("/assets", StaticFiles(directory=_dist / "assets"), name="assets")

    @app.get("/")
    def index():
        return FileResponse(_dist / "index.html")
