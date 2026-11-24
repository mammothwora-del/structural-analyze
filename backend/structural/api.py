"""FastAPI application exposing the generator and the solver."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
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


# Serve the built frontend (frontend/dist) when present.
_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if _dist.exists():
    app.mount("/assets", StaticFiles(directory=_dist / "assets"), name="assets")

    @app.get("/")
    def index():
        return FileResponse(_dist / "index.html")
