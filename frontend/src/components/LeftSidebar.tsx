import { useState } from "react";
import type { Section } from "../lib/types";
import { useStore, useU } from "../store";
import { elementColorKey, TYPE_COLORS, TYPE_LABELS } from "../three/Members";
import { GenPreview, isRoofTruss, PicturePicker, TRUSS_TYPES, TrussTypePicker } from "./GenPreview";

const list = (s: string) => s.split(/[,\s]+/).filter(Boolean).map(Number).filter((x) => x > 0);

export function LeftSidebar() {
  const [tab, setTab] = useState<"generate" | "model" | "sections">("generate");
  return (
    <aside className="w-[270px] shrink-0 border-r border-ink-800 bg-ink-900 flex flex-col min-h-0">
      <div className="flex border-b border-ink-800">
        {(["generate", "model", "sections"] as const).map((t) => (
          <button key={t} onClick={() => setTab(t)} className={`flex-1 py-2 text-[11px] uppercase tracking-wider font-semibold ${tab === t ? "text-accent border-b-2 border-accent" : "text-ink-400 hover:text-ink-200"}`}>
            {t === "generate" ? "Generate" : t === "model" ? "Model" : "Sections"}
          </button>
        ))}
      </div>
      <div className="flex-1 overflow-y-auto p-3">
        {tab === "generate" && <Generator />}
        {tab === "model" && <ModelTree />}
        {tab === "sections" && <Sections />}
      </div>
    </aside>
  );
}

const F = ({ label, children, hint }: { label: string; children: React.ReactNode; hint?: string }) => (
  <label className="block mb-2">
    <div className="flex justify-between text-[11px] text-ink-400 mb-0.5"><span>{label}</span>{hint && <span className="text-ink-600">{hint}</span>}</div>
    {children}
  </label>
);

const OCCUPANCY: Record<string, { label: string; q: number }[]> = {
  // Thai Ministerial Regulation No. 6 (B.E. 2527) live loads, kg/m² — verify against the regulation in force.
  TH: [
    { label: "Residence / house (150 kg/m²)", q: 150 }, { label: "School, condo, hotel, hospital (200)", q: 200 },
    { label: "Office, bank (250)", q: 250 }, { label: "Commercial, assembly hall (300)", q: 300 },
    { label: "Market, dept. store, car park (400)", q: 400 }, { label: "Warehouse, factory, library (500)", q: 500 },
  ],
  EN1990: [
    { label: "Residential, cat. A (1.5 kN/m²)", q: 1.5 / 0.00980665 }, { label: "Office, cat. B (3.0)", q: 3.0 / 0.00980665 },
    { label: "Assembly, cat. C3 (5.0)", q: 5.0 / 0.00980665 }, { label: "Shopping, cat. D1 (4.0)", q: 4.0 / 0.00980665 },
  ],
  ASCE7: [
    { label: "Residential (40 psf)", q: 40 * 4.88243 }, { label: "Office (50 psf)", q: 50 * 4.88243 },
    { label: "Corridors above 1st floor (80 psf)", q: 80 * 4.88243 }, { label: "Assembly, movable seats (100 psf)", q: 100 * 4.88243 },
  ],
};
const MATS: Record<string, string[]> = { TH: ["TH-fc240", "TH-fc280", "TH-fc320", "TH-fc210", "TH-fc180"], EN1990: ["C30/37", "C25/30", "C40/50"], ASCE7: ["C30/37", "C25/30", "C40/50"] };
const KGM2 = 0.00980665; // kN/m² per kg/m²

type StructType = "building" | "truss2d" | "warehouse" | "space_truss" | "lattice_roof";
const STRUCT_LABEL: Record<StructType, string> = {
  building: "Multi-storey building (frame, slabs, walls, bracing)",
  truss2d: "Planar truss (12 types)",
  warehouse: "Steel warehouse (roof trusses or portal frame)",
  space_truss: "Space truss roof (double-layer grid)",
  lattice_roof: "Lattice roof (barrel vault, dome)",
};

function Generator() {
  const [type, setType] = useState<StructType>("building");
  return (
    <div>
      <div className="panel-title mb-2">Structure type</div>
      <select className="input mb-3" value={type} onChange={(e) => setType(e.target.value as StructType)}>
        {(Object.keys(STRUCT_LABEL) as StructType[]).map((t) => <option key={t} value={t}>{STRUCT_LABEL[t]}</option>)}
      </select>
      {type === "building" && <BuildingGen />}
      {type === "truss2d" && <TrussGen />}
      {type === "warehouse" && <WarehouseGen />}
      {type === "space_truss" && <SpaceGen />}
      {type === "lattice_roof" && <LatticeGen />}
    </div>
  );
}

const STD_OPTIONS = (
  <>
    <option value="TH">Thai — EIT 1008 / Ministerial Regulation, DPT 1301/1302</option>
    <option value="EN1990">Eurocode EN 1990</option>
    <option value="ASCE7">ASCE 7 LRFD</option>
  </>
);
const STEEL_FOR: Record<string, string> = { TH: "SS400", EN1990: "S355", ASCE7: "A992" };

/** Number input bound to an SI state value, shown in the selected unit system. */
function useSI<T extends Record<string, unknown>>(init: T) {
  const u = useU();
  const [p, setP] = useState(init);
  const num = (k: keyof T, kind: Parameters<typeof u.c>[0] | null, step?: number) => (
    <input className="input" type="number" step={step ?? "any"} value={kind ? +u.c(kind, p[k] as number).toFixed(4) : (p[k] as number)}
      onChange={(e) => setP({ ...p, [k]: kind ? u.si(kind, +e.target.value) : +e.target.value })} />
  );
  return { p, setP, num, u };
}

function GenNote({ children }: { children: React.ReactNode }) {
  return <div className="text-[10px] text-ink-400 leading-snug mb-2">{children}</div>;
}

function TrussGen() {
  const { generate, busy } = useStore();
  const { p, setP, num, u } = useSI({ truss_type: "pratt", span: 18, height: 2, panels: 6, eave_depth: 0, bottom_rise: 0, spacing: 6, sdl: 0.5, live_load: 0.5, standard: "EN1990",
    chB: 0.15, chT: 0.008, wD: 0.0889, wT: 0.005 });
  const L = u.u("length"), D = u.u("dim");
  const params = { type: "truss2d", truss_type: p.truss_type, span: p.span, height: p.height, panels: Math.round(p.panels),
    eave_depth: isRoofTruss(p.truss_type) ? p.eave_depth : 0, bottom_rise: p.bottom_rise, spacing: p.spacing, sdl: p.sdl, live_load: p.live_load, standard: p.standard,
    chord: { shape: "box", b: p.chB, h: p.chB, t: p.chT }, web: { shape: "pipe", d: p.wD, t: p.wT } };
  return (
    <div>
      <div className="text-[11px] text-ink-400 mb-1">Truss type</div>
      <TrussTypePicker value={p.truss_type} onChange={(v) => setP({ ...p, truss_type: v, height: isRoofTruss(v) && !isRoofTruss(p.truss_type) ? 3 : !isRoofTruss(v) && isRoofTruss(p.truss_type) ? 2 : p.height })} />
      <div className="text-[10px] text-ink-400 -mt-1 mb-2">{TRUSS_TYPES.find((t) => t.key === p.truss_type)?.hint}</div>
      <GenPreview params={params} view="front" height={110} />
      <F label="Standard (combinations, steel)"><select className="input" value={p.standard} onChange={(e) => setP({ ...p, standard: e.target.value })}>{STD_OPTIONS}</select></F>
      <div className="grid grid-cols-2 gap-x-2">
        <F label={`Span (${L})`}>{num("span", "length")}</F>
        <F label={isRoofTruss(p.truss_type) ? `Rise (${L})` : `Depth (${L})`}>{num("height", "length")}</F>
        {p.truss_type !== "fink" && p.truss_type !== "fan" && <F label="Panels">{num("panels", null, 1)}</F>}
        {isRoofTruss(p.truss_type) && <F label={`Depth at supports (${L})`}>{num("eave_depth", "length")}</F>}
        {p.truss_type === "scissors" && <F label={`Bottom chord rise (${L})`} hint="0 = rise/2">{num("bottom_rise", "length")}</F>}
        <F label={`Truss spacing (${L})`}>{num("spacing", "length")}</F>
        <F label={`Roof SDL (${u.u("areaLoad")})`}>{num("sdl", "areaLoad")}</F>
        <F label={`Roof live (${u.u("areaLoad")})`}>{num("live_load", "areaLoad")}</F>
        <F label={`Chord box b=h (${D})`}>{num("chB", "dim")}</F>
        <F label={`Chord wall t (${D})`}>{num("chT", "dim")}</F>
        <F label={`Web tube d (${D})`}>{num("wD", "dim")}</F>
        <F label={`Web wall t (${D})`}>{num("wT", "dim")}</F>
      </div>
      <GenNote>Pin-jointed members (axial force only under nodal loads). Roof load = q × spacing, lumped at the top-chord panel points by tributary length (assumed). Left support pinned, right roller; out-of-plane restraint assumed at every node. Steel: {STEEL_FOR[p.standard]}.</GenNote>
      <button className="btn-primary w-full" disabled={busy} onClick={() => generate(params)}>Generate truss</button>
    </div>
  );
}

function WarehouseGen() {
  const { generate, busy } = useStore();
  const { p, setP, num, u } = useSI({ roof: "pitched", spans: [20] as number[], roof_layout: "repeat", bay: 6, n_bays: 5, eave_height: 6, rise: 2, eave_depth: 1, panels: 8, support: "fixed", sdl: 0.3, live_load: 0.5,
    wind_pressure: 0.8, standard: "EN1990", roof_bracing: true, wall_bracing: true });
  const [spanText, setSpanText] = useState<Record<string, string>>({});
  const L = u.u("length"), A = u.u("areaLoad");
  const portal = p.roof === "portal";
  const multi = p.spans.length > 1;
  const canContinue = p.roof !== "fink" && p.roof !== "fan";
  const layout = multi && canContinue ? p.roof_layout : "repeat";
  const params = { type: "warehouse", ...p, roof_layout: layout, span: p.spans[0], n_spans: p.spans.length, n_bays: Math.round(p.n_bays), panels: Math.round(p.panels), eave_depth: portal ? 0 : p.eave_depth };
  const roofs = [...WAREHOUSE_ROOFS.map(([key, label, hint]) => ({ key, label, hint,
    params: { type: "warehouse", roof: key, span: 16, n_bays: 1, eave_height: 5, rise: 2.5, eave_depth: key === "portal" ? 0 : 0.8, panels: 6, roof_bracing: false, wall_bracing: false, wind_pressure: 0 } }))];
  const spanValue = spanText[u.sys] ?? p.spans.map((v) => +u.c("length", v).toFixed(3)).join(", ");
  const setSpans = (txt: string) => {
    setSpanText({ [u.sys]: txt });
    const v = list(txt).map((x) => u.si("length", x));
    if (v.length) setP({ ...p, spans: v });
  };
  const width = p.spans.reduce((a, b) => a + b, 0);
  return (
    <div>
      <div className="text-[11px] text-ink-400 mb-1">Roof structure</div>
      <PicturePicker options={roofs} value={p.roof} onChange={(v) => setP({ ...p, roof: v })} cols={4} height={30} />
      <GenPreview params={params} />
      <F label="Standard (combinations, steel)"><select className="input" value={p.standard} onChange={(e) => setP({ ...p, standard: e.target.value })}>{STD_OPTIONS}</select></F>
      <div className="grid grid-cols-2 gap-x-2">
        <div className="col-span-2">
          <F label={`Span lengths (${L})`} hint={multi ? `${p.spans.length} spans, ${+u.c("length", width).toFixed(2)} ${L}` : "e.g. 20, 15"}>
            <input className="input" value={spanValue} onChange={(e) => setSpans(e.target.value)} />
          </F>
        </div>
        {multi && (
          <div className="col-span-2 mb-2">
            <div className="text-[11px] text-ink-400 mb-0.5">Roof over the spans</div>
            <div className="flex rounded border border-ink-700 overflow-hidden text-[11px]">
              {([["repeat", portal ? "Frame per span" : "Truss per span"], ["continuous", portal ? "One rafter, middle columns" : "One truss, middle columns"]] as const).map(([k, l]) => (
                <button key={k} type="button" disabled={k === "continuous" && !canContinue} onClick={() => setP({ ...p, roof_layout: k })}
                  className={`flex-1 py-1 ${layout === k ? "bg-accent text-ink-950 font-semibold" : "text-ink-300 hover:bg-ink-800"} disabled:opacity-40 disabled:hover:bg-transparent`}>{l}</button>
              ))}
            </div>
            <div className="text-[10px] text-ink-500 mt-0.5">
              {!canContinue ? "Fink and fan trusses have a fixed panel layout: one truss per span only."
                : layout === "continuous" ? `One ${portal ? "rafter" : "truss"} over the full width, carried by a column on every inner grid line. Panel points are placed on the column lines; the rise is over the full width.`
                : `A separate ${portal ? "frame" : "truss"} on each span${p.roof === "mono" ? " (saw-tooth)" : ""}, sharing the inner columns.`}
            </div>
          </div>
        )}
        <F label={`Bay spacing (${L})`}>{num("bay", "length")}</F>
        <F label="Number of bays">{num("n_bays", null, 1)}</F>
        <F label={`Eave height (${L})`}>{num("eave_height", "length")}</F>
        <F label={`Roof rise (${L})`}>{num("rise", "length")}</F>
        {!portal && <F label={`Truss depth at eave (${L})`}>{num("eave_depth", "length")}</F>}
        {p.roof !== "fink" && p.roof !== "fan" && <F label={portal ? "Purlin spaces per span" : "Truss panels per span"}>{num("panels", null, 1)}</F>}
        <F label="Column bases"><select className="input" value={p.support} onChange={(e) => setP({ ...p, support: e.target.value })}><option value="fixed">fixed</option><option value="pinned">pinned</option></select></F>
        <F label={`Roof SDL (${A})`}>{num("sdl", "areaLoad")}</F>
        <F label={`Roof live (${A})`}>{num("live_load", "areaLoad")}</F>
        <F label={`Wind net (${A})`}>{num("wind_pressure", "areaLoad")}</F>
      </div>
      <label className="flex items-center gap-2 text-[11px] mb-1"><input type="checkbox" className="accent-sky-400" checked={p.roof_bracing} onChange={(e) => setP({ ...p, roof_bracing: e.target.checked })} />Roof bracing in end bays</label>
      <label className="flex items-center gap-2 text-[11px] mb-2"><input type="checkbox" className="accent-sky-400" checked={p.wall_bracing} onChange={(e) => setP({ ...p, wall_bracing: e.target.checked })} />Wall bracing in end bays</label>
      <GenNote>{portal ? "Portal frames: I-section rafters rigidly connected to the columns (no haunches modelled)" : "Roof trusses on steel columns, bottom-chord ties with vertical bracing in the end bays"}, simply supported purlins and eave struts. Roof sheeting spans one way to the purlins (assumed). Several spans share the internal columns, or carry one continuous roof on middle columns. Untick a bracing option to see the stability check report the mechanism. Steel: {STEEL_FOR[p.standard]}.</GenNote>
      <button className="btn-primary w-full" disabled={busy} onClick={() => generate(params)}>Generate warehouse</button>
    </div>
  );
}

const WAREHOUSE_ROOFS: [string, string, string][] = [
  ["pitched", "Pratt", "pitched Pratt roof truss"], ["howe_roof", "Howe", "pitched Howe roof truss"], ["fink", "Fink", "Fink (W) roof truss"],
  ["fan", "Fan", "fan roof truss"], ["scissors", "Scissors", "scissors truss (raised bottom chord)"], ["bowstring", "Bowstring", "curved top chord"],
  ["mono", "Mono", "mono-pitch truss (lean-to / saw-tooth when multi-span)"], ["portal", "Portal", "portal frame with I-section rafters, no truss"],
];

const LATTICE_SHAPES = [
  { key: "barrel", label: "Barrel vault", hint: "cylindrical lattice shell", params: { type: "lattice_roof", shape: "barrel", span: 24, rise: 6, length: 30, n_arc: 8, n_long: 6 }, view: "iso" as const },
  { key: "dome", label: "Dome", hint: "spherical lattice dome", params: { type: "lattice_roof", shape: "dome", diameter: 24, dome_rise: 7, n_rings: 4, n_sectors: 12 }, view: "iso" as const },
];
const LATTICE_PATTERNS: Record<string, [string, string, string][]> = {
  barrel: [["braced", "Braced", "quads with one diagonal (herringbone)"], ["cross", "Cross-braced", "quads with X diagonals"], ["ribbed", "Ribbed", "arches and longitudinals only (frame action)"]],
  dome: [["schwedler", "Schwedler", "ribs, rings and one diagonal per panel"], ["lamella", "Lamella", "rotated rings, fully triangulated"], ["ribbed", "Ribbed", "ribs and rings only (frame action)"]],
};

function LatticeGen() {
  const { generate, busy } = useStore();
  const { p, setP, num, u } = useSI({ shape: "barrel", pattern: "braced", span: 24, rise: 6, length: 36, n_arc: 12, n_long: 12, diameter: 30, dome_rise: 7.5, n_rings: 6, n_sectors: 16,
    support_height: 0, sdl: 0.3, live_load: 0.5, standard: "EN1990", d: 0.1397, t: 0.0063 });
  const L = u.u("length"), A = u.u("areaLoad"), D = u.u("dim");
  const barrel = p.shape === "barrel";
  const { d, t, ...rest } = p;
  const params = { type: "lattice_roof", ...rest, n_arc: Math.round(p.n_arc), n_long: Math.round(p.n_long), n_rings: Math.round(p.n_rings), n_sectors: Math.round(p.n_sectors),
    member: { shape: "pipe", d, t } };
  const patterns = LATTICE_PATTERNS[p.shape].map(([key, label, hint]) => ({ key, label, hint, view: "iso" as const,
    params: barrel ? { type: "lattice_roof", shape: "barrel", pattern: key, span: 24, rise: 6, length: 24, n_arc: 6, n_long: 4 }
      : { type: "lattice_roof", shape: "dome", pattern: key, diameter: 24, dome_rise: 7, n_rings: 3, n_sectors: 10 } }));
  return (
    <div>
      <PicturePicker options={LATTICE_SHAPES} value={p.shape} onChange={(v) => setP({ ...p, shape: v, pattern: LATTICE_PATTERNS[v][0][0] })} cols={2} height={44} />
      <div className="text-[11px] text-ink-400 mb-1">Pattern</div>
      <PicturePicker options={patterns} value={p.pattern} onChange={(v) => setP({ ...p, pattern: v })} cols={3} height={34} />
      <GenPreview params={params} />
      <F label="Standard (combinations, steel)"><select className="input" value={p.standard} onChange={(e) => setP({ ...p, standard: e.target.value })}>{STD_OPTIONS}</select></F>
      <div className="grid grid-cols-2 gap-x-2">
        {barrel ? <>
          <F label={`Span (${L})`}>{num("span", "length")}</F>
          <F label={`Rise (${L})`}>{num("rise", "length")}</F>
          <F label={`Length (${L})`}>{num("length", "length")}</F>
          <F label="Segments across">{num("n_arc", null, 1)}</F>
          <F label="Bays along">{num("n_long", null, 1)}</F>
        </> : <>
          <F label={`Diameter (${L})`}>{num("diameter", "length")}</F>
          <F label={`Rise (${L})`}>{num("dome_rise", "length")}</F>
          <F label="Rings">{num("n_rings", null, 1)}</F>
          <F label="Sectors">{num("n_sectors", null, 1)}</F>
        </>}
        <F label={`Support level (${L})`}>{num("support_height", "length")}</F>
        <F label={`Roof SDL (${A})`}>{num("sdl", "areaLoad")}</F>
        <F label={`Roof live (${A})`}>{num("live_load", "areaLoad")}</F>
        <F label={`Tube d (${D})`}>{num("d", "dim")}</F>
        <F label={`Tube wall t (${D})`}>{num("t", "dim")}</F>
      </div>
      <GenNote>Single-layer steel tube lattice with rigid joints, pinned along the springing line (ring beam or walls assumed rigid). Roof load lumped at the nodes by tributary plan area (assumed). Linear analysis only: buckling and snap-through, which usually govern lattice shells, are NOT checked. Steel: {STEEL_FOR[p.standard]}.</GenNote>
      <button className="btn-primary w-full" disabled={busy} onClick={() => generate(params)}>Generate {barrel ? "barrel vault" : "dome"}</button>
    </div>
  );
}

function SpaceGen() {
  const { generate, busy } = useStore();
  const { p, setP, num, u } = useSI({ nx: 8, ny: 6, module: 2, depth: 1.5, column_height: 5, supports: "perimeter", sdl: 0.5, live_load: 0.75, standard: "EN1990" });
  const L = u.u("length"), A = u.u("areaLoad");
  const params = { type: "space_truss", ...p, nx: Math.round(p.nx), ny: Math.round(p.ny) };
  return (
    <div>
      <GenPreview params={params} />
      <F label="Standard (combinations, steel)"><select className="input" value={p.standard} onChange={(e) => setP({ ...p, standard: e.target.value })}>{STD_OPTIONS}</select></F>
      <div className="grid grid-cols-2 gap-x-2">
        <F label="Modules in X">{num("nx", null, 1)}</F>
        <F label="Modules in Y">{num("ny", null, 1)}</F>
        <F label={`Module size (${L})`}>{num("module", "length")}</F>
        <F label={`Grid depth (${L})`}>{num("depth", "length")}</F>
        <F label={`Column height (${L})`} hint="0 = on supports">{num("column_height", "length")}</F>
        <F label="Supports"><select className="input" value={p.supports} onChange={(e) => setP({ ...p, supports: e.target.value })}><option value="perimeter">perimeter (every 2nd node)</option><option value="corners">4 corners</option></select></F>
        <F label={`Roof SDL (${A})`}>{num("sdl", "areaLoad")}</F>
        <F label={`Roof live (${A})`}>{num("live_load", "areaLoad")}</F>
      </div>
      <GenNote>Square-on-square double-layer grid of pin-jointed tubes. Roof load lumped at the top nodes by tributary plan area (assumed). Steel: {STEEL_FOR[p.standard]}.</GenNote>
      <button className="btn-primary w-full" disabled={busy} onClick={() => generate(params)}>Generate space truss</button>
    </div>
  );
}

function BuildingGen() {
  const { generate, busy } = useStore();
  const u = useU();
  // state is kept in SI (m, kN/m², kN/m³...) and shown in the selected unit system
  const [p, setP] = useState({
    x: [6, 6, 6], y: [5, 5], h: [4, 3.5, 3.5, 3.5], colB: 0.4, colH: 0.4, mbB: 0.3, mbH: 0.6, sbB: 0.25, sbH: 0.45,
    sec: "y", slab: 0.18, sdl: 1.5, ll: 3.0, rll: 1.0, support: "fixed", fB: 2.0, fT: 0.6, wind: 1.0, cs: 0.08, mat: "C30/37", standard: "EN1990", qa: 250,
    slabModel: "shell", mesh: 1.0, walls: "none", wallT: 0.2, bracing: "none",
  });
  const [lists, setLists] = useState<Record<string, string>>({});
  const listText = (k: "x" | "y" | "h") => lists[k + u.sys] ?? p[k].map((v) => +u.c("length", v).toFixed(3)).join(", ");
  const num = (k: keyof typeof p, kind: Parameters<typeof u.c>[0] | null, step?: number) => (
    <input className="input" type="number" step={step ?? "any"} value={kind ? +u.c(kind, p[k] as number).toFixed(4) : (p[k] as number)}
      onChange={(e) => setP({ ...p, [k]: kind ? u.si(kind, +e.target.value) : +e.target.value })} />
  );
  const setStd = (std: string) => setP({ ...p, standard: std, mat: MATS[std][0], ll: std === "TH" ? 250 * KGM2 : std === "ASCE7" ? 50 * 0.04788 : 3.0, rll: std === "TH" ? 50 * KGM2 : std === "ASCE7" ? 20 * 0.04788 : 1.0, sdl: std === "TH" ? 150 * KGM2 : 1.5 });
  const params = {
    x_spans: p.x, y_spans: p.y, story_heights: p.h,
    column: { shape: "rect", b: p.colB, h: p.colH, material: p.mat },
    main_beam: { shape: "rect", b: p.mbB, h: p.mbH, material: p.mat },
    secondary_beam: { shape: "rect", b: p.sbB, h: p.sbH, material: p.mat },
    secondary_beams: p.sec, slab_thickness: p.slab, sdl: p.sdl, live_load: p.ll, roof_live_load: p.rll,
    support: p.support, footing: { B: p.fB, L: p.fB, t: p.fT }, wind_pressure: p.wind, seismic_cs: p.cs, standard: p.standard, allowable_bearing: p.qa,
    slab_model: p.slabModel, mesh_size: p.mesh, walls: p.walls, wall_thickness: p.wallT, bracing: p.bracing,
  };
  const run = () => generate(params);
  const listInput = (k: "x" | "y" | "h") => (
    <input className="input" value={listText(k)} onChange={(e) => {
      setLists({ ...lists, [k + u.sys]: e.target.value });
      const v = list(e.target.value).map((x) => u.si("length", x));
      if (v.length) setP({ ...p, [k]: v });
    }} />
  );
  const L = u.u("length"), D = u.u("dim"), A = u.u("areaLoad");
  return (
    <div>
      <GenPreview params={params} />
      <div className="panel-title mb-2">Design standard</div>
      <F label="Standard (combinations, presets)">
        <select className="input" value={p.standard} onChange={(e) => setStd(e.target.value)}>
          <option value="TH">Thai — EIT 1008 / Ministerial Regulation, DPT 1301/1302</option>
          <option value="EN1990">Eurocode EN 1990</option>
          <option value="ASCE7">ASCE 7 LRFD</option>
        </select>
      </F>
      <div className="panel-title mt-3 mb-2">Grid & storeys</div>
      <F label={`X spans (${L})`} hint="grid 1, 2, 3…">{listInput("x")}</F>
      <F label={`Y spans (${L})`} hint="grid A, B, C…">{listInput("y")}</F>
      <F label={`Storey heights (${L})`} hint="bottom → top">{listInput("h")}</F>
      <div className="panel-title mt-3 mb-2">Members ({D})</div>
      <F label="Material"><select className="input" value={p.mat} onChange={(e) => setP({ ...p, mat: e.target.value })}>{[...MATS[p.standard], ...Object.values(MATS).flat().filter((m) => !MATS[p.standard].includes(m))].filter((m, i, a) => a.indexOf(m) === i).map((m) => <option key={m} value={m}>{m}</option>)}</select></F>
      <div className="grid grid-cols-2 gap-x-2">
        <F label="Column b">{num("colB", "dim")}</F>
        <F label="Column h">{num("colH", "dim")}</F>
        <F label="Main beam b">{num("mbB", "dim")}</F>
        <F label="Main beam h">{num("mbH", "dim")}</F>
        <F label="Sec. beam b">{num("sbB", "dim")}</F>
        <F label="Sec. beam h">{num("sbH", "dim")}</F>
      </div>
      <F label="Secondary beams"><select className="input" value={p.sec} onChange={(e) => setP({ ...p, sec: e.target.value })}><option value="none">none</option><option value="y">run along Y (mid-bay)</option><option value="x">run along X (mid-bay)</option></select></F>
      <F label={`Slab thickness (${D})`}>{num("slab", "dim")}</F>
      <F label="Slab analysis">
        <select className="input" value={p.slabModel} onChange={(e) => setP({ ...p, slabModel: e.target.value })}>
          <option value="shell">Shell FEM (plate + membrane) — calculated</option>
          <option value="tributary">Tributary areas (45°) — assumed</option>
        </select>
      </F>
      <F label="Shear walls (shell FEM)">
        <select className="input" value={p.walls} onChange={(e) => setP({ ...p, walls: e.target.value })}>
          <option value="none">none</option>
          <option value="x">outer frames, parallel to X (middle bay)</option>
          <option value="xy">outer frames, X and Y (middle bays)</option>
        </select>
      </F>
      {p.walls !== "none" && <F label={`Wall thickness (${D})`}>{num("wallT", "dim")}</F>}
      <F label="Steel bracing (end bays of outer frames)">
        <select className="input" value={p.bracing} onChange={(e) => setP({ ...p, bracing: e.target.value })}>
          <option value="none">none</option><option value="x">X-bracing</option><option value="diagonal">single diagonal</option>
        </select>
      </F>
      {(p.slabModel === "shell" || p.walls !== "none") && <F label={`Shell mesh size (${L})`} hint="smaller = more accurate, slower">{num("mesh", "length")}</F>}
      <div className="panel-title mt-3 mb-2">Foundations</div>
      <div className="grid grid-cols-2 gap-x-2">
        <F label="Support"><select className="input" value={p.support} onChange={(e) => setP({ ...p, support: e.target.value })}><option value="fixed">fixed</option><option value="pinned">pinned</option></select></F>
        <F label={`q allow (${u.u("soil")})`}>{num("qa", "soil")}</F>
        <F label={`Footing B=L (${L})`}>{num("fB", "length")}</F>
        <F label={`Footing t (${L})`}>{num("fT", "length")}</F>
      </div>
      <div className="panel-title mt-3 mb-2">Loads ({A})</div>
      <F label="Occupancy preset (live load)">
        <select className="input" value="" onChange={(e) => e.target.value && setP({ ...p, ll: +e.target.value * KGM2 })}>
          <option value="">Choose…</option>
          {OCCUPANCY[p.standard].map((o) => <option key={o.label} value={o.q}>{o.label}</option>)}
        </select>
      </F>
      <div className="grid grid-cols-2 gap-x-2">
        <F label="SDL">{num("sdl", "areaLoad")}</F>
        <F label="Live">{num("ll", "areaLoad")}</F>
        <F label="Roof live">{num("rll", "areaLoad")}</F>
        <F label="Wind net">{num("wind", "areaLoad")}</F>
        <F label="Seismic Cs">{num("cs", null, 0.01)}</F>
      </div>
      <div className="text-[10px] text-ink-400 leading-snug mb-2">
        {p.standard === "TH" ? "Thai presets: load factors per EIT 1008-38 strength design (1.4D+1.7L …), seismic combos in DPT 1301/1302 style, live loads per Ministerial Regulation No. 6. Verify against the editions in force. " : ""}
        Wind and seismic generators are simplified (uniform net pressure; ELF with user Cs) — not a DPT 1311 / DPT 1301 / code calculation. Self-weight is in case DL.
      </div>
      <button className="btn-primary w-full" disabled={busy} onClick={run}>Generate building</button>
    </div>
  );
}

function ModelTree() {
  const { model, hiddenTypes, set, maxLevel, exploded, isolated } = useStore();
  if (!model) return null;
  const levels = Math.max(0, ...model.elements.map((e) => e.level ?? 0));
  const count = (k: string) => k === "slab" ? model.slabs.length : k === "wall" ? (model.walls?.length ?? 0) : k === "footing" ? model.supports.filter((s) => !s.lateral).length :
    model.elements.filter((e) => elementColorKey(e) === k).length;
  const all: [string, string, string][] = [
    ...Object.keys(TYPE_COLORS).map((k) => [k, TYPE_LABELS[k], TYPE_COLORS[k]] as [string, string, string]),
    ["slab", "Slabs", "#8fa3b8"], ["wall", "Walls", "#a7b4c2"], ["footing", "Supports & footings", "#6b7a8c"]];
  const types = all.filter(([k]) => count(k) > 0);
  return (
    <div>
      <div className="panel-title mb-2">Structural components</div>
      {types.map(([k, label, c]) => (
        <label key={k} className="flex items-center gap-2 py-1 cursor-pointer">
          <input type="checkbox" checked={!hiddenTypes[k]} onChange={() => set({ hiddenTypes: { ...hiddenTypes, [k]: !hiddenTypes[k] } })} className="accent-sky-400" />
          <span className="w-3 h-3 rounded-sm" style={{ background: c }} />
          <span className="flex-1">{label}</span>
          <span className="num text-ink-400">{count(k)}</span>
        </label>
      ))}
      <div className="panel-title mt-4 mb-1">Section cut (show up to level)</div>
      <input type="range" min={1} max={levels} value={maxLevel ?? levels} onChange={(e) => set({ maxLevel: +e.target.value >= levels ? null : +e.target.value })} className="w-full accent-sky-400" />
      <div className="text-ink-400 text-[11px]">{maxLevel === null ? "All levels" : `Levels 1–${maxLevel}`}</div>
      <div className="panel-title mt-4 mb-1">Exploded view</div>
      <input type="range" min={0} max={6} step={0.25} value={exploded} onChange={(e) => set({ exploded: +e.target.value })} className="w-full accent-sky-400" />
      <div className="text-ink-400 text-[11px]">{exploded ? `+${exploded} m per level` : "Off"}</div>
      {isolated && <button className="btn mt-3 w-full" onClick={() => set({ isolated: null })}>Show all ({isolated.length} isolated)</button>}
      <div className="panel-title mt-4 mb-1">Model summary</div>
      <div className="text-[11px] text-ink-300 space-y-0.5">
        <div>Nodes: <span className="num">{model.nodes.length}</span></div>
        <div>Frame members: <span className="num">{model.elements.length}</span></div>
        <div>Slab panels: <span className="num">{model.slabs.length}</span></div>
        <div>Supports: <span className="num">{model.supports.length}</span></div>
        <div>Load cases: <span className="num">{model.load_cases.length}</span>, combinations: <span className="num">{model.combinations.length}</span></div>
      </div>
      {model.notes?.length ? (<>
        <div className="panel-title mt-4 mb-1">Model assumptions</div>
        <ul className="text-[10px] text-amber-200/80 leading-snug list-disc pl-4 space-y-0.5">{model.notes.map((n) => <li key={n}>{n}</li>)}</ul>
      </>) : null}
      <AddNode />
      <div className="mt-4 text-[10px] text-ink-400 leading-snug">Editing: add nodes here; add a member by shift-clicking two nodes in Model mode; set end releases (pin / truss), sections, supports and loads in the right panel. Slabs and shear walls are analysed with shell elements.</div>
    </div>
  );
}

function AddNode() {
  const { model, editModel, set } = useStore();
  const u = useU();
  const [c, setC] = useState({ x: 0, y: 0, z: 0 });
  if (!model) return null;
  const add = () => {
    let k = model.nodes.length + 1;
    while (model.nodes.some((n) => n.id === `N${k}`)) k++;
    const id = `N${k}`;
    const lv = model.grid?.levels ?? [];
    const level = lv.reduce((best, l, i) => (Math.abs(l.z - c.z) < Math.abs(lv[best].z - c.z) ? i : best), 0);
    editModel((m) => { m.nodes.push({ id, x: c.x, y: c.y, z: c.z, level }); });
    set({ selection: { kind: "node", id }, mode: "model" });
  };
  return (
    <div>
      <div className="panel-title mt-4 mb-1">Add node ({u.u("length")})</div>
      <div className="grid grid-cols-3 gap-1">
        {(["x", "y", "z"] as const).map((k) => (
          <input key={k} className="input" type="number" step="any" title={k} placeholder={k} value={+u.c("length", c[k]).toFixed(4)}
            onChange={(e) => setC({ ...c, [k]: u.si("length", +e.target.value) })} />
        ))}
      </div>
      <button className="btn mt-1 w-full" onClick={add}>Add node</button>
    </div>
  );
}

function Sections() {
  const { model, editModel } = useStore();
  const [n, setN] = useState({ id: "", shape: "rect", b: 300, h: 500, bf: 200, tf: 15, tw: 9, d: 114.3, t: 6, material: "C30/37" });
  if (!model) return null;
  return (
    <div>
      <div className="panel-title mb-2">Materials</div>
      {Object.entries(model.materials).map(([k, m]) => (
        <div key={k} className="flex justify-between text-[11px] py-0.5 border-b border-ink-800"><span>{m.name}</span><span className="num text-ink-400">E {m.E / 1000} GPa · γ {m.density}</span></div>
      ))}
      <div className="panel-title mt-4 mb-2">Sections</div>
      {Object.entries(model.sections).map(([k, s]) => (
        <div key={k} className="flex justify-between text-[11px] py-0.5 border-b border-ink-800">
          <span><b className="text-ink-200">{k}</b> {s.name}</span>
          <span className="text-ink-400">{model.elements.filter((e) => e.section === k).length} used</span>
        </div>
      ))}
      <div className="panel-title mt-4 mb-2">New section</div>
      <div className="grid grid-cols-2 gap-1">
        <input className="input" placeholder="id e.g. B2" value={n.id} onChange={(e) => setN({ ...n, id: e.target.value })} />
        <select className="input" value={n.shape} onChange={(e) => setN({ ...n, shape: e.target.value, material: e.target.value === "rect" ? "C30/37" : "S355" })}><option value="rect">Rectangle</option><option value="I">I-section</option><option value="pipe">Tube (CHS)</option><option value="box">Box (RHS/SHS)</option></select>
        {n.shape === "pipe" ? (<>
          <input className="input" type="number" title="d (mm)" value={n.d} onChange={(e) => setN({ ...n, d: +e.target.value })} />
          <input className="input" type="number" title="t (mm)" value={n.t} onChange={(e) => setN({ ...n, t: +e.target.value })} />
        </>) : n.shape === "box" ? (<>
          <input className="input" type="number" title="b (mm)" value={n.b} onChange={(e) => setN({ ...n, b: +e.target.value })} />
          <input className="input" type="number" title="h (mm)" value={n.h} onChange={(e) => setN({ ...n, h: +e.target.value })} />
          <input className="input col-span-2" type="number" title="t (mm)" value={n.t} onChange={(e) => setN({ ...n, t: +e.target.value })} />
        </>) : n.shape === "rect" ? (<>
          <input className="input" type="number" title="b (mm)" value={n.b} onChange={(e) => setN({ ...n, b: +e.target.value })} />
          <input className="input" type="number" title="h (mm)" value={n.h} onChange={(e) => setN({ ...n, h: +e.target.value })} />
        </>) : (<>
          <input className="input" type="number" title="h (mm)" value={n.h} onChange={(e) => setN({ ...n, h: +e.target.value })} />
          <input className="input" type="number" title="bf (mm)" value={n.bf} onChange={(e) => setN({ ...n, bf: +e.target.value })} />
          <input className="input" type="number" title="tf (mm)" value={n.tf} onChange={(e) => setN({ ...n, tf: +e.target.value })} />
          <input className="input" type="number" title="tw (mm)" value={n.tw} onChange={(e) => setN({ ...n, tw: +e.target.value })} />
        </>)}
        <select className="input col-span-2" value={n.material} onChange={(e) => setN({ ...n, material: e.target.value })}>{Object.keys(model.materials).map((m) => <option key={m}>{m}</option>)}</select>
      </div>
      <button className="btn mt-2 w-full" disabled={!n.id || !!model.sections[n.id]} onClick={() => editModel((m) => {
        const s: Section = n.shape === "rect" ? { shape: "rect", b: n.b / 1000, h: n.h / 1000, material: n.material, name: `${n.b}x${n.h} ${n.material}` }
          : n.shape === "pipe" ? { shape: "pipe", d: n.d / 1000, t: n.t / 1000, material: n.material, name: `CHS ${n.d}x${n.t} ${n.material}` }
          : n.shape === "box" ? { shape: "box", b: n.b / 1000, h: n.h / 1000, t: n.t / 1000, material: n.material, name: `RHS ${n.h}x${n.b}x${n.t} ${n.material}` }
          : { shape: "I", h: n.h / 1000, bf: n.bf / 1000, tf: n.tf / 1000, tw: n.tw / 1000, material: n.material, name: `I ${n.h}x${n.bf} ${n.material}` };
        m.sections[n.id] = s;
      })}>Add section</button>
      <div className="text-[10px] text-ink-400 mt-2">Select members (shift-click) and assign the section in the right panel.</div>
    </div>
  );
}
