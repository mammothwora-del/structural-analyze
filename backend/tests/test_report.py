"""PDF calculation report and the import / report API endpoints."""
import base64
import io
import struct
import zlib

import pytest
from fastapi.testclient import TestClient

from structural.analysis import analyze
from structural.api import app
from structural.generator import generate
from structural.report import _f, _t, build_report
from structural.steel_design import steel_design
from structural.structures import generate_truss2d, generate_warehouse

pypdf = pytest.importorskip("pypdf")


def text_of(pdf: bytes) -> str:
    return "\n".join(p.extract_text() for p in pypdf.PdfReader(io.BytesIO(pdf)).pages)


def tiny_png(w=4, h=3) -> str:
    raw = b"".join(b"\x00" + b"\x30\x80\xc0" * w for _ in range(h))

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
    return "data:image/png;base64," + base64.b64encode(png).decode()


@pytest.fixture(scope="module")
def warehouse():
    return generate_warehouse()


def test_steel_report_contents_match_the_calculation(warehouse):
    pdf = build_report(warehouse, {"stability": True}, image_png=tiny_png())
    assert pdf.startswith(b"%PDF")
    txt = text_of(pdf)
    for s in ("Calculation report", "[INPUT]", "[ASSUMED]", "[CALCULATED]", "Equilibrium check", "Support reactions",
              "Extreme member internal forces", "Member force envelope", "Elastic critical buckling", "alpha_cr",
              "Steel member design", "Check details", "Limitations", "3D view of the model"):
        assert s in txt, s
    # the governing utilisation printed is the one the design module calculates
    s = steel_design(warehouse)
    assert f"{s['summary']['max_util']:.2f}" in txt
    worst = max((m for m in s["members"].values() if m.get("util") is not None), key=lambda m: m["util"])
    assert f"{worst['util']:.3f}" in txt
    # the sum of the dead-load reactions printed equals the analysed one
    r = analyze(warehouse)
    fz = sum(v[2] for v in r["cases"]["DL"]["reactions"].values())
    assert f"{fz:.2f}" in txt
    # never a claim of safety or compliance
    low = txt.lower().replace("\n", " ")
    assert "not a statement that the structure is safe" in low
    assert "structure is safe." not in low.replace("not a statement that the structure is safe", "")


def test_rc_report_and_options():
    m = generate({"standard": "TH"})
    pdf = build_report(m, {"members": False, "steel": False}, rc_options={"main_grade": "SD50", "cover": 0.05},
                       project={"title": "Test building", "engineer": "A. Engineer"})
    txt = text_of(pdf)
    assert "Reinforced concrete design" in txt and "Beams" in txt and "Columns" in txt
    assert "SD50" in txt and "5.0 cm" in txt
    assert "Test building" in txt and "A. Engineer" in txt
    assert "Member force envelope" not in txt
    assert "Steel member design" not in txt


def test_report_without_design_and_bad_image():
    m = generate_truss2d()
    pdf = build_report(m, {"steel": False, "rc": False}, image_png="data:image/png;base64,bm90IGFuIGltYWdl")
    txt = text_of(pdf)
    assert "Linear static analysis" in txt and "3D view" not in txt


def test_text_helpers():
    assert _t("αcr ≥ 10, ΣFz, φMn, kN·m, 25 m²") == "alphacr >= 10, Sum Fz, phiMn, kN·m, 25 m²"
    _t("漢字").encode("cp1252")
    assert _f(4.1e-17) == "0.00" and _f(-1e-9) == "0.00" and _f(1234.567) == "1234.57" and _f(2.5e7) == "2.5e+07"
    assert _f(None) == "–" and _f(float("inf")) == "∞"


def test_api_report_and_dxf():
    c = TestClient(app)
    m = c.post("/api/generate", json={"type": "truss2d"}).json()
    r = c.post("/api/report", json={"model": m, "include": {"steel": True}})
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF") and "attachment" in r.headers["content-disposition"]
    assert c.post("/api/report", json={"model": {**m, "supports": []}}).status_code == 422
    assert c.post("/api/report", json={}).status_code == 400

    dxf = ("0\nSECTION\n2\nENTITIES\n"
           "0\nLINE\n8\nCOL\n10\n0\n20\n0\n30\n0\n11\n0\n21\n0\n31\n3000\n"
           "0\nLINE\n8\nBEAM\n10\n0\n20\n0\n30\n3000\n11\n5000\n21\n0\n31\n3000\n"
           "0\nLINE\n8\nCOL\n10\n5000\n20\n0\n30\n0\n11\n5000\n21\n0\n31\n3000\n0\nENDSEC\n0\nEOF\n")
    r = c.post("/api/import/dxf", json={"dxf": dxf, "options": {"material": "concrete", "standard": "TH"}})
    assert r.status_code == 200
    model = r.json()
    assert len(model["elements"]) == 3 and model["settings"]["standard"] == "TH"
    assert c.post("/api/analyze", json=model).status_code == 200
    bad = c.post("/api/import/dxf", json={"dxf": "garbage\x00\nfile\n"})
    assert bad.status_code == 400 and "DXF" in bad.json()["detail"]
    assert c.post("/api/import/dxf", json={}).status_code == 400
