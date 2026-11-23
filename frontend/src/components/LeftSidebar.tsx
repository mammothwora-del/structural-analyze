import { useState } from "react";
import type { Section } from "../lib/types";
import { useStore } from "../store";
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

function Generator() {
  const { generate, busy } = useStore();
  const [p, setP] = useState({
    x: "6, 6, 6", y: "5, 5", h: "4, 3.5, 3.5, 3.5", colB: 400, colH: 400, mbB: 300, mbH: 600, sbB: 250, sbH: 450,
    sec: "y", slab: 180, sdl: 1.5, ll: 3.0, rll: 1.0, support: "fixed", fB: 2.0, fT: 0.6, wind: 1.0, cs: 0.08, mat: "C30/37", standard: "EN1990", qa: 250,
  });
  const u = (k: keyof typeof p) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setP({ ...p, [k]: e.target.type === "number" ? +e.target.value : e.target.value });
  const run = () => generate({
    x_spans: list(p.x), y_spans: list(p.y), story_heights: list(p.h),
    column: { shape: "rect", b: p.colB / 1000, h: p.colH / 1000, material: p.mat },
    main_beam: { shape: "rect", b: p.mbB / 1000, h: p.mbH / 1000, material: p.mat },
    secondary_beam: { shape: "rect", b: p.sbB / 1000, h: p.sbH / 1000, material: p.mat },
    secondary_beams: p.sec, slab_thickness: p.slab / 1000, sdl: p.sdl, live_load: p.ll, roof_live_load: p.rll,
    support: p.support, footing: { B: p.fB, L: p.fB, t: p.fT }, wind_pressure: p.wind, seismic_cs: p.cs, standard: p.standard, allowable_bearing: p.qa,
  });
  return (
    <div>
      <div className="panel-title mb-2">Grid & storeys</div>
      <F label="X spans (m)" hint="grid 1, 2, 3…"><input className="input" value={p.x} onChange={u("x")} /></F>
      <F label="Y spans (m)" hint="grid A, B, C…"><input className="input" value={p.y} onChange={u("y")} /></F>
      <F label="Storey heights (m)" hint="bottom → top"><input className="input" value={p.h} onChange={u("h")} /></F>
      <div className="panel-title mt-3 mb-2">Members (mm)</div>
      <F label="Material"><select className="input" value={p.mat} onChange={u("mat")}><option>C25/30</option><option>C30/37</option><option>C40/50</option></select></F>
      <div className="grid grid-cols-2 gap-x-2">
        <F label="Column b"><input className="input" type="number" value={p.colB} onChange={u("colB")} /></F>
        <F label="Column h"><input className="input" type="number" value={p.colH} onChange={u("colH")} /></F>
        <F label="Main beam b"><input className="input" type="number" value={p.mbB} onChange={u("mbB")} /></F>
        <F label="Main beam h"><input className="input" type="number" value={p.mbH} onChange={u("mbH")} /></F>
        <F label="Sec. beam b"><input className="input" type="number" value={p.sbB} onChange={u("sbB")} /></F>
        <F label="Sec. beam h"><input className="input" type="number" value={p.sbH} onChange={u("sbH")} /></F>
      </div>
      <F label="Secondary beams"><select className="input" value={p.sec} onChange={u("sec")}><option value="none">none</option><option value="y">run along Y (mid-bay)</option><option value="x">run along X (mid-bay)</option></select></F>
      <F label="Slab thickness (mm)"><input className="input" type="number" value={p.slab} onChange={u("slab")} /></F>
      <div className="panel-title mt-3 mb-2">Foundations</div>
      <div className="grid grid-cols-2 gap-x-2">
        <F label="Support"><select className="input" value={p.support} onChange={u("support")}><option value="fixed">fixed</option><option value="pinned">pinned</option></select></F>
        <F label="q allow (kN/m²)"><input className="input" type="number" value={p.qa} onChange={u("qa")} /></F>
        <F label="Footing B=L (m)"><input className="input" type="number" step={0.1} value={p.fB} onChange={u("fB")} /></F>
        <F label="Footing t (m)"><input className="input" type="number" step={0.05} value={p.fT} onChange={u("fT")} /></F>
      </div>
      <div className="panel-title mt-3 mb-2">Loads</div>
      <div className="grid grid-cols-2 gap-x-2">
        <F label="SDL (kN/m²)"><input className="input" type="number" step={0.1} value={p.sdl} onChange={u("sdl")} /></F>
        <F label="Live (kN/m²)"><input className="input" type="number" step={0.1} value={p.ll} onChange={u("ll")} /></F>
        <F label="Roof live"><input className="input" type="number" step={0.1} value={p.rll} onChange={u("rll")} /></F>
        <F label="Wind net (kN/m²)"><input className="input" type="number" step={0.1} value={p.wind} onChange={u("wind")} /></F>
        <F label="Seismic Cs"><input className="input" type="number" step={0.01} value={p.cs} onChange={u("cs")} /></F>
        <F label="Combinations"><select className="input" value={p.standard} onChange={u("standard")}><option value="EN1990">EN 1990</option><option value="ASCE7">ASCE 7 LRFD</option></select></F>
      </div>
      <div className="text-[10px] text-ink-400 leading-snug mb-2">Wind and seismic generators are simplified (uniform net pressure; ELF with user Cs) and are not code calculations. Self-weight of members and slabs is in case DL.</div>
      <button className="btn-primary w-full" disabled={busy} onClick={run}>Generate building</button>
    </div>
  );
}

function ModelTree() {
  const { model, hiddenTypes, set, maxLevel, exploded, isolated } = useStore();
  if (!model) return null;
  const levels = Math.max(0, ...model.elements.map((e) => e.level ?? 0));
  const count = (k: string) => k === "slab" ? model.slabs.length : k === "footing" ? model.supports.length :
    model.elements.filter((e) => (k === "column" ? e.type === "column" : k === "brace" ? e.type === "brace" : e.type === "beam" && (e.role === "secondary") === (k === "secondary"))).length;
  const types: [string, string, string][] = [["column", "Columns", TYPE_COLORS.column], ["main", "Main beams", TYPE_COLORS.main], ["secondary", "Secondary beams", TYPE_COLORS.secondary], ["slab", "Slabs", "#8fa3b8"], ["footing", "Footings", "#6b7a8c"]];
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
      <div className="mt-4 text-[10px] text-ink-400 leading-snug">Phase 1 editing: assign sections, delete members, add members between two nodes (shift-click two nodes in Model mode), supports and loads via the inspector. Copy/move/rotate and walls/bracing/trusses come in later phases.</div>
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
