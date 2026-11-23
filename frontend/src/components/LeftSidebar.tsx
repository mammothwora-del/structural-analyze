import { useState } from "react";
import type { Section } from "../lib/types";
import { useStore, useU } from "../store";
import { TYPE_COLORS } from "../three/Members";

const list = (s: string) => s.split(/[,\s]+/).filter(Boolean).map(Number).filter((x) => x > 0);

export function LeftSidebar() {
  const [tab, setTab] = useState<"generate" | "model" | "sections">("generate");
  return (
    <aside className="w-[270px] shrink-0 border-r border-ink-800 bg-ink-900 flex flex-col min-h-0">
      <div className="flex border-b border-ink-800">
        {(["generate", "model", "sections"] as const).map((t) => (
          <button key={t} onClick={() => setTab(t)} className={`flex-1 py-2 text-[11px] uppercase tracking-wider font-semibold ${tab === t ? "text-accent border-b-2 border-accent" : "text-ink-400 hover:text-ink-200"}`}>
            {t === "generate" ? "Building" : t === "model" ? "Model" : "Sections"}
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

function Generator() {
  const { generate, busy } = useStore();
  const u = useU();
  // state is kept in SI (m, kN/m², kN/m³...) and shown in the selected unit system
  const [p, setP] = useState({
    x: [6, 6, 6], y: [5, 5], h: [4, 3.5, 3.5, 3.5], colB: 0.4, colH: 0.4, mbB: 0.3, mbH: 0.6, sbB: 0.25, sbH: 0.45,
    sec: "y", slab: 0.18, sdl: 1.5, ll: 3.0, rll: 1.0, support: "fixed", fB: 2.0, fT: 0.6, wind: 1.0, cs: 0.08, mat: "C30/37", standard: "EN1990", qa: 250,
    slabModel: "shell", mesh: 1.0, walls: "none", wallT: 0.2,
  });
  const [lists, setLists] = useState<Record<string, string>>({});
  const listText = (k: "x" | "y" | "h") => lists[k + u.sys] ?? p[k].map((v) => +u.c("length", v).toFixed(3)).join(", ");
  const num = (k: keyof typeof p, kind: Parameters<typeof u.c>[0] | null, step?: number) => (
    <input className="input" type="number" step={step ?? "any"} value={kind ? +u.c(kind, p[k] as number).toFixed(4) : (p[k] as number)}
      onChange={(e) => setP({ ...p, [k]: kind ? u.si(kind, +e.target.value) : +e.target.value })} />
  );
  const setStd = (std: string) => setP({ ...p, standard: std, mat: MATS[std][0], ll: std === "TH" ? 250 * KGM2 : std === "ASCE7" ? 50 * 0.04788 : 3.0, rll: std === "TH" ? 50 * KGM2 : std === "ASCE7" ? 20 * 0.04788 : 1.0, sdl: std === "TH" ? 150 * KGM2 : 1.5 });
  const run = () => generate({
    x_spans: p.x, y_spans: p.y, story_heights: p.h,
    column: { shape: "rect", b: p.colB, h: p.colH, material: p.mat },
    main_beam: { shape: "rect", b: p.mbB, h: p.mbH, material: p.mat },
    secondary_beam: { shape: "rect", b: p.sbB, h: p.sbH, material: p.mat },
    secondary_beams: p.sec, slab_thickness: p.slab, sdl: p.sdl, live_load: p.ll, roof_live_load: p.rll,
    support: p.support, footing: { B: p.fB, L: p.fB, t: p.fT }, wind_pressure: p.wind, seismic_cs: p.cs, standard: p.standard, allowable_bearing: p.qa,
    slab_model: p.slabModel, mesh_size: p.mesh, walls: p.walls, wall_thickness: p.wallT,
  });
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
  const count = (k: string) => k === "slab" ? model.slabs.length : k === "wall" ? (model.walls?.length ?? 0) : k === "footing" ? model.supports.length :
    model.elements.filter((e) => (k === "column" ? e.type === "column" : k === "brace" ? e.type === "brace" : e.type === "beam" && (e.role === "secondary") === (k === "secondary"))).length;
  const types: [string, string, string][] = [["column", "Columns", TYPE_COLORS.column], ["main", "Main beams", TYPE_COLORS.main], ["secondary", "Secondary beams", TYPE_COLORS.secondary], ["slab", "Slabs", "#8fa3b8"], ["wall", "Walls", "#a7b4c2"], ["footing", "Footings", "#6b7a8c"]];
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
      <div className="mt-4 text-[10px] text-ink-400 leading-snug">Phase 1 editing: assign sections, delete members, add members between two nodes (shift-click two nodes in Model mode), supports and loads via the inspector. Slabs and shear walls are analysed with shell elements (Phase 2). Copy/move/rotate and bracing/trusses come in later phases.</div>
    </div>
  );
}

function Sections() {
  const { model, editModel } = useStore();
  const [n, setN] = useState({ id: "", shape: "rect", b: 300, h: 500, bf: 200, tf: 15, tw: 9, material: "C30/37" });
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
        <select className="input" value={n.shape} onChange={(e) => setN({ ...n, shape: e.target.value, material: e.target.value === "I" ? "S355" : "C30/37" })}><option value="rect">Rectangle</option><option value="I">I-section</option></select>
        {n.shape === "rect" ? (<>
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
          : { shape: "I", h: n.h / 1000, bf: n.bf / 1000, tf: n.tf / 1000, tw: n.tw / 1000, material: n.material, name: `I ${n.h}x${n.bf} ${n.material}` };
        m.sections[n.id] = s;
      })}>Add section</button>
      <div className="text-[10px] text-ink-400 mt-2">Select members (shift-click) and assign the section in the right panel.</div>
    </div>
  );
}
