"""DXF import: parsing, units, node merging, T-junction splitting, member typing, and the model analyses."""
import pytest

from structural.analysis import analyze
from structural.dxf_import import DXFError, import_dxf, parse_dxf


def dxf(entities: str, insunits: int | None = 4) -> str:
    head = "0\nSECTION\n2\nHEADER\n" + (f"9\n$INSUNITS\n70\n{insunits}\n" if insunits is not None else "") + "0\nENDSEC\n"
    return head + "0\nSECTION\n2\nENTITIES\n" + entities + "0\nENDSEC\n0\nEOF\n"


def line(layer, p0, p1):
    return (f"0\nLINE\n8\n{layer}\n10\n{p0[0]}\n20\n{p0[1]}\n30\n{p0[2]}\n"
            f"11\n{p1[0]}\n21\n{p1[1]}\n31\n{p1[2]}\n")


PORTAL = (line("S-COLUMN", (0, 0, 0), (0, 0, 4000))
          + line("S-COLUMN", (6000, 0, 4000), (6000, 0, 0))          # drawn top to bottom
          + line("S-BEAM", (0, 0, 4000.002), (6000, 0, 4000)))       # 2 micro-mm off: merged


def test_portal_in_mm():
    m = import_dxf(dxf(PORTAL))
    assert len(m["nodes"]) == 4
    assert {e["type"] for e in m["elements"]} == {"column", "beam"}
    zs = sorted(n["z"] for n in m["nodes"])
    assert zs == pytest.approx([0, 0, 4, 4])
    assert len(m["supports"]) == 2
    nodes = {n["id"]: n for n in m["nodes"]}
    for e in m["elements"]:
        if e["type"] == "column":                          # columns always run bottom to top
            assert nodes[e["i"]]["z"] < nodes[e["j"]]["z"]
    r = analyze(m)
    assert r["ok"]
    # self-weight goes down to the two supports
    assert sum(v[2] for v in r["cases"]["DL"]["reactions"].values()) > 0


def test_t_junction_split_and_crossings():
    ents = (line("COL", (0, 0, 0), (0, 0, 6))
            + line("COL", (8, 0, 0), (8, 0, 6))
            + line("BEAM", (0, 0, 6), (8, 0, 6))
            + line("BEAM", (0, 0, 3), (8, 0, 3))                 # ends on both columns at mid-height: splits them
            + line("BRACING", (0, 0, 0), (8, 0, 6))              # crosses the mid beam at (4, 0, 3)
            + line("BRACING", (8, 0, 0), (4, 0, 6))              # ends at the middle of the roof beam: splits it
            + line("BEAM", (2, -1, 4.5), (2, 1, 4.5)))           # passes 2 m away from every member: stays apart
    # crossings kept apart
    m = import_dxf(dxf(ents, insunits=6), {"connect_crossings": False})
    types = [e["type"] for e in m["elements"]]
    assert (types.count("column"), types.count("beam"), types.count("brace")) == (4, 4, 2)
    assert len(m["nodes"]) == 9                                # 2 base, 2 mid, 3 roof, 2 for the loose beam
    braces = [e for e in m["elements"] if e["type"] == "brace"]
    assert all(e["releases"]["i"][4] == 1 and e["releases"]["j"][4] == 1 for e in braces)
    # crossings connected (default): brace 1 x mid beam (4, 0, 3), brace 2 x mid beam (6, 0, 3), brace 1 x brace 2 (16/3, 0, 4)
    m = import_dxf(dxf(ents, insunits=6))
    types = [e["type"] for e in m["elements"]]
    assert (types.count("column"), types.count("beam"), types.count("brace")) == (4, 6, 6)
    xyz = {(round(n["x"], 3), round(n["z"], 3)) for n in m["nodes"]}
    assert {(4, 3), (6, 3), (5.333, 4)} <= xyz
    assert any("cross in 3D" in n for n in m["notes"])
    # braces are pinned only at the ends of the drawn line and continuous through the crossings
    nodes = {n["id"]: n for n in m["nodes"]}
    for e in m["elements"]:
        if e["type"] != "brace":
            continue
        for end in ("i", "j"):
            p = nodes[e[end]]
            drawn_end = (p["x"], p["z"]) in {(0, 0), (8, 0), (8, 6), (4, 6)}
            assert (e.get("releases", {}).get(end, [0] * 6)[4] == 1) == drawn_end
    loose = [n for n in m["notes"] if "not connected to any supported part" in n]
    assert len(loose) == 1 and loose[0].startswith("1 member")
    m["elements"] = [e for e in m["elements"] if nodes[e["i"]]["y"] == 0]     # delete the loose beam, then analyse
    r = analyze(m)
    assert r["ok"] and not r.get("unstable_dofs")


def test_lwpolyline_and_direction_typing_in_metres():
    poly = ("0\nLWPOLYLINE\n8\n0\n90\n4\n70\n0\n38\n0\n"
            "10\n0\n20\n0\n10\n0\n20\n0\n")                    # degenerate, merged away
    frame = ("0\nPOLYLINE\n8\nFRAME\n66\n1\n70\n0\n"
             "0\nVERTEX\n8\nFRAME\n10\n0\n20\n0\n30\n0\n"
             "0\nVERTEX\n8\nFRAME\n10\n0\n20\n0\n30\n3\n"
             "0\nVERTEX\n8\nFRAME\n10\n5\n20\n0\n30\n4\n"
             "0\nVERTEX\n8\nFRAME\n10\n10\n20\n0\n30\n3\n"
             "0\nVERTEX\n8\nFRAME\n10\n10\n20\n0\n30\n0\n"
             "0\nSEQEND\n8\nFRAME\n")
    m = import_dxf(dxf(poly + frame), {"units": "m", "support": "pinned", "material": "concrete", "standard": "TH"})
    types = sorted(e["type"] for e in m["elements"])
    assert types == ["brace", "brace", "column", "column"]   # rafters at 11.3 deg read as inclined
    assert all(s["type"] == "pinned" for s in m["supports"])
    assert all(s["material"] == "TH-fc240" for s in m["sections"].values())
    assert m["settings"]["standard"] == "TH"
    analyze(m)


def test_units_from_header_and_override():
    seg = line("COL", (0, 0, 0), (0, 0, 120)) + line("BEAM", (0, 0, 120), (100, 0, 120))
    assert max(n["z"] for n in import_dxf(dxf(seg, insunits=5))["nodes"]) == pytest.approx(1.2)    # cm
    assert max(n["z"] for n in import_dxf(dxf(seg, insunits=1))["nodes"]) == pytest.approx(3.048)  # in
    assert max(n["z"] for n in import_dxf(dxf(seg, insunits=None))["nodes"]) == pytest.approx(0.12)  # default mm
    assert max(n["z"] for n in import_dxf(dxf(seg), {"units": "m"})["nodes"]) == pytest.approx(120)


def test_ignored_entities_and_blocks_reported():
    ents = PORTAL + "0\nCIRCLE\n8\n0\n10\n0\n20\n0\n30\n0\n40\n5\n0\nTEXT\n8\n0\n1\nhello\n"
    blocks = "0\nSECTION\n2\nBLOCKS\n0\nBLOCK\n8\n0\n" + line("X", (0, 0, 0), (1, 1, 1)) + "0\nENDBLK\n0\nENDSEC\n"
    text = dxf(ents).replace("0\nSECTION\n2\nENTITIES", blocks + "0\nSECTION\n2\nENTITIES")
    segs, header = parse_dxf(text)
    assert len(segs) == 3
    assert header["ignored"] == {"CIRCLE": 1, "TEXT": 1}
    m = import_dxf(text)
    assert any("Ignored entities" in n for n in m["notes"])
    assert any("block" in n for n in m["notes"])


@pytest.mark.parametrize("text, msg", [
    ("", "empty"),
    ("AC1015\x00\x01binary junk\nmore\n", "ASCII"),
    (dxf("0\nCIRCLE\n8\n0\n10\n0\n20\n0\n30\n0\n40\n5\n"), "no LINE"),
    (dxf(line("0", (0, 0, 0), (5000, 0, 0)) + line("0", (5000, 0, 0), (5000, 4000, 0))), "flat in Z"),
    (dxf(line("0", (0, 0, 0), (0.001, 0, 0))), "shorter than"),
])
def test_errors(text, msg):
    with pytest.raises(DXFError, match=msg):
        import_dxf(text)
